"""
Studio Actions 解析器 — 从 actions.py 抽离。

职责：从 Agent 回复文本中提取 / 解析 / 修复 studio-actions JSON 块。
纯函数实现，无状态依赖，可独立测试。
"""
from loguru import logger
import json
import re
from typing import Any, Dict, List, Optional


# ---------- 正则模式 ----------

_ACTION_BLOCK_PATTERNS = [
    re.compile(r"```(?:studio-actions|studio_action|studioActions)\s*([\s\S]*?)```", re.IGNORECASE),
    re.compile(r"<studio-actions>([\s\S]*?)</studio-actions>", re.IGNORECASE),
]

_ACTION_BLOCK_DETECT = re.compile(
    r"```(?:studio-actions|studio_action|studioActions)|<studio-actions>", re.IGNORECASE
)

_STRIP_PATTERNS = [
    re.compile(r"```(?:studio-actions|studio_action|studioActions)\s*[\s\S]*?```", re.IGNORECASE),
    re.compile(r"<studio-actions>[\s\S]*?</studio-actions>", re.IGNORECASE),
]

# 包装格式探测（9999 事故）：模型把确认写进 ```json 围栏或裸 JSON 的
# {"studio-actions": [...]} 包装对象里，标准围栏匹配不到
_WRAPPER_KEY_RE = re.compile(r"\"studio-actions\"\s*:")
_JSON_FENCE_RE = re.compile(r"```(?:json|javascript)\s*([\s\S]*?)```", re.IGNORECASE)

# 退化流程信号探测（7777 事故第五/六代变体）：模型不写 studio-actions 围栏，
# 直接在正文写 ①普通 ```json 围栏 [{"action": "request_confirmation", ...}]；
# ②裸 JSON {"status": "done", "tool": "confirm", "message": ...}。
# 识别口径：action/name/type/tool 任一键值命中流程信号别名即算。
_SIGNAL_KEYS = ("action", "name", "type", "tool")
_SIGNAL_ALIASES = (
    "request_confirmation", "confirm", "confirmation", "pause",
    "workflow_pause", "continue",
)
# 裸 JSON 锚点键（name/type 太泛不作裸锚，防误伤正文里的普通 JSON）
_BARE_SIGNAL_KEY_RE = re.compile(r"\"(?:action|tool|status)\"\s*:")


# ---------- 公开 API ----------

def strip_action_blocks(text: str) -> str:
    """移除 studio-actions 块，返回纯可见文本（含包装格式，9999 事故；
    含退化流程信号 JSON，7777 事故）"""
    for pat in _STRIP_PATTERNS:
        text = pat.sub("", text)
    text = _strip_wrapper_blocks(text)
    # 退化信号块（json 围栏/裸 JSON）：倒序剥离不影响前面的区间坐标
    for s, e, _ in reversed(extract_degraded_signal_blocks(text)):
        text = text[:s] + text[e:]
    return text.strip()


def has_action_block(reply: str) -> bool:
    """回复中是否存在 studio-actions 块（无论能否解析成功，含包装格式与退化信号）"""
    return (
        bool(_ACTION_BLOCK_DETECT.search(reply))
        or bool(_WRAPPER_KEY_RE.search(reply))
        or bool(extract_degraded_signal_blocks(reply))
    )


def _find_wrapper_span(text: str, key_match_start: int) -> Optional[tuple]:
    """从包装键位置向前找最近的 '{'，用括号深度扫描出完整对象区间。"""
    start = text.rfind("{", 0, key_match_start)
    if start == -1:
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "{[":
            depth += 1
        elif ch in "]}":
            depth -= 1
            if depth == 0:
                return start, i + 1
    return None


def _strip_wrapper_blocks(text: str) -> str:
    """剥离 {"studio-actions": [...]} 包装对象（含包裹它的 json 围栏）。"""
    while True:
        m = _WRAPPER_KEY_RE.search(text)
        if not m:
            return text
        span = _find_wrapper_span(text, m.start())
        if not span:
            return text
        s, e = span
        # 若包装对象被 ```json/``` 围栏包裹，连同围栏一起剥离
        pre = text[:s]
        fence_open = None
        for fm in _JSON_FENCE_RE.finditer(text):
            if fm.start() < s <= fm.end():
                fence_open = fm
                break
        if fence_open is not None:
            s, e = fence_open.start(), fence_open.end()
        text = (pre[:s] if fence_open is None else text[:s]) + text[e:]


def parse_actions_from_reply(reply: str) -> List[Dict[str, Any]]:
    """从 Agent 回复文本中提取 studio-actions JSON 块并解析为操作列表"""
    actions: List[Dict[str, Any]] = []
    for pattern in _ACTION_BLOCK_PATTERNS:
        for match in pattern.finditer(reply):
            parsed = parse_json_tolerant(match.group(1))
            if parsed:
                actions.extend(normalize_actions(parsed))
    # 包装格式兜底（9999 事故）：{"studio-actions": [...]} 无论裸 JSON 还是
    # json 围栏内，都按包装对象解析
    if not actions and _WRAPPER_KEY_RE.search(reply):
        for m in _WRAPPER_KEY_RE.finditer(reply):
            span = _find_wrapper_span(reply, m.start())
            if not span:
                continue
            parsed = parse_json_tolerant(reply[span[0]:span[1]])
            if parsed:
                actions.extend(normalize_actions(parsed))
            break
    # 退化信号兜底（7777 事故）：普通 json 围栏/裸 JSON 里直接写确认/暂停信号，
    # 无 studio-actions 标签也识别出来，避免 JSON 原文漏给用户
    if not actions:
        for _, _, parsed in extract_degraded_signal_blocks(reply):
            actions.extend(normalize_actions(parsed))
    return [a for a in actions if isinstance(a, dict)]


# ---------- 退化流程信号探测（7777 事故） ----------

def _is_signal_obj(obj: Any) -> bool:
    """单个 dict 是否为流程信号（确认/暂停/继续）"""
    if not isinstance(obj, dict):
        return False
    for key in _SIGNAL_KEYS:
        val = obj.get(key)
        if isinstance(val, str) and val.strip().lower() in _SIGNAL_ALIASES:
            return True
    return False


def _parsed_is_signal(parsed: Any) -> bool:
    """解析结果是否含流程信号（dict 本体 / 列表 / actions 包装）"""
    if _is_signal_obj(parsed):
        return True
    if isinstance(parsed, list):
        return any(_is_signal_obj(x) for x in parsed)
    if isinstance(parsed, dict):
        for key in ("actions", "studio-actions"):
            sub = parsed.get(key)
            if isinstance(sub, list) and any(_is_signal_obj(x) for x in sub):
                return True
    return False


def extract_degraded_signal_blocks(reply: str) -> List[tuple]:
    """扫描回复中的退化流程信号 JSON 块，返回 [(start, end, parsed)] 按起点升序。

    覆盖两类：①```json/javascript 围栏内容解析后含信号；②正文裸 JSON 对象
    （以 action/tool/status 键为锚点，括号深度扫描取完整区间）。与已命中
    区间重叠的锚点跳过，防重复剥离。
    """
    blocks: List[tuple] = []
    for fm in _JSON_FENCE_RE.finditer(reply):
        parsed = parse_json_tolerant(fm.group(1))
        if parsed is not None and _parsed_is_signal(parsed):
            blocks.append((fm.start(), fm.end(), parsed))
    for km in _BARE_SIGNAL_KEY_RE.finditer(reply):
        if any(s <= km.start() < e for s, e, _ in blocks):
            continue
        span = _find_wrapper_span(reply, km.start())
        if not span:
            continue
        s, e = span
        if any(s < e2 and s2 < e for s2, e2, _ in blocks):
            continue
        parsed = parse_json_tolerant(reply[s:e])
        if parsed is not None and _parsed_is_signal(parsed):
            blocks.append((s, e, parsed))
    blocks.sort(key=lambda b: b[0])
    return blocks


# ---------- JSON 容错解析 ----------

def parse_json_tolerant(raw: str) -> Any:
    """容错 JSON 解析：先直接解析，失败后尝试轻量修复"""
    text = raw.strip()
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError) as _e:
        logger.debug("[action_parser] 忽略异常: {}", _e)
    repaired = repair_json(text)
    if repaired != text:
        try:
            return json.loads(repaired)
        except (json.JSONDecodeError, ValueError) as _e:
            logger.debug("[action_parser] 忽略异常: {}", _e)
    return None


def repair_json(text: str) -> str:
    """轻量 JSON 修复：去尾逗号、单引号转双引号、补全截断括号。不引入外部依赖。"""
    s = text
    # 1. 单引号 → 双引号（仅当不存在双引号键时启发式替换）
    if "'" in s and '"' not in s:
        s = s.replace("'", '"')
    # 2. 去除尾逗号（,] 或 ,}）
    s = re.sub(r",\s*([\]\}])", r"\1", s)
    # 3. 补全截断的括号（LLM 被 max_tokens 截断时常见）
    open_braces = s.count("{") - s.count("}")
    open_brackets = s.count("[") - s.count("]")
    if open_braces > 0 or open_brackets > 0:
        # 移除末尾不完整的键值对
        s = re.sub(r',?\s*"[^"]*"\s*:\s*"[^"]*$', '', s)
        s = re.sub(r',?\s*"[^"]*"\s*:\s*[^,\]\}]*$', '', s)
        # 重新计算并补全
        open_braces = s.count("{") - s.count("}")
        open_brackets = s.count("[") - s.count("]")
        s += "]" * max(open_brackets, 0) + "}" * max(open_braces, 0)
    return s


def normalize_actions(parsed: Any) -> List[Dict]:
    """将解析结果统一为 action dict 列表（兼容包装格式与 name 键变体）"""
    if isinstance(parsed, dict) and isinstance(parsed.get("studio-actions"), list):
        # 包装格式：{"studio-actions": [...]}（9999 事故）
        return [_normalize_action_item(a) for a in parsed["studio-actions"]]
    if isinstance(parsed, list):
        return [_normalize_action_item(a) for a in parsed]
    if isinstance(parsed, dict):
        if isinstance(parsed.get("actions"), list):
            return [_normalize_action_item(a) for a in parsed["actions"]]
        # 单对象兜底（7777 事故：{"status":..., "tool": "confirm"} 无 action 键，
        # 归一后能补出 action 才返回，避免把普通对象误当动作）
        item = _normalize_action_item(parsed)
        if isinstance(item, dict) and item.get("action"):
            return [item]
    return []


def _normalize_action_item(a: Any) -> Any:
    """单条 action 归一：缺 action 键时用 name/type/tool 兜底（笨模型变体，
    9999 事故：模型写 {"name": "request_confirmation", ...}；
    7777 事故：模型写 {"status": "done", "tool": "confirm", ...}）。"""
    return normalize_action_aliases(a)


def normalize_action_aliases(a: Any) -> Any:
    """单条 action 的键级别名归一（9999 现场：弱模型把 add_draft 写成
    type/groupId/payload 驼峰 schema，group_id/draft 缺失导致整批被
    「拒绝盲建」拒收）。只在正典字段缺失时补，不覆盖已有值；幂等。"""
    if not isinstance(a, dict):
        return a
    out = dict(a)
    if not out.get("action"):
        alt = out.get("name") or out.get("type") or out.get("tool")
        if isinstance(alt, str) and alt.strip():
            out["action"] = alt.strip()
    if not out.get("group_id") and isinstance(out.get("groupId"), str) and out["groupId"].strip():
        out["group_id"] = out["groupId"].strip()
    if not out.get("draft_id") and isinstance(out.get("draftId"), str) and out["draftId"].strip():
        out["draft_id"] = out["draftId"].strip()
    payload = out.get("payload")
    if isinstance(payload, dict) and payload:
        act = str(out.get("action") or "")
        if act in ("update_draft", "patch_draft", "update_current_draft", "set_prompt"):
            if not isinstance(out.get("patch"), dict):
                out["patch"] = payload
        elif not isinstance(out.get("draft"), dict):
            out["draft"] = payload
    return out


# ---------- 流式增量提取（边写边填） ----------

class StreamingActionExtractor:
    """studio-actions 块的流式增量提取器。

    喂入被 StreamActionSuppressor 抑制的动作块内容（不含围栏），
    用括号深度 + 字符串状态机检测顶层 JSON 对象闭合，
    每闭合一个立即解析返回——支持模型边生成、系统边执行，
    草稿卡片逐张填充，而不是等全部写完一次性弹出。
    解析失败的片段静默丢弃（流尾由 parse_actions_from_reply 全量兜底）。
    """

    def __init__(self) -> None:
        self._buf = ""
        self._obj_start = -1
        self._depth = 0
        self._in_str = False
        self._esc = False

    def feed(self, chunk: str) -> List[Dict[str, Any]]:
        """追加增量内容，返回本次新闭合的 action dict 列表"""
        out: List[Dict[str, Any]] = []
        for ch in chunk:
            if self._obj_start == -1:
                if ch == "{":
                    self._obj_start = len(self._buf)
                    self._depth = 1
                    self._in_str = False
                    self._esc = False
                # 数组括号/逗号/空白跳过（对象内嵌套数组在深度计数内处理）
                self._buf += ch
                continue
            self._buf += ch
            if self._in_str:
                if self._esc:
                    self._esc = False
                elif ch == "\\":
                    self._esc = True
                elif ch == '"':
                    self._in_str = False
                continue
            if ch == '"':
                self._in_str = True
            elif ch in "{[":
                self._depth += 1
            elif ch in "}]":
                self._depth -= 1
                if self._depth == 0:
                    raw = self._buf[self._obj_start:]
                    self._obj_start = -1
                    self._in_str = False
                    self._esc = False
                    parsed = parse_json_tolerant(raw)
                    for a in normalize_actions(parsed):
                        if isinstance(a, dict):
                            out.append(a)
        return out
