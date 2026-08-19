"""
Studio Actions 解析器 — 从 actions.py 抽离。

职责（单轨化后，ADR-0001）：仅保留 JSON 容错解析与动作归一
纯函数（mock 演示通道与回归测试使用）。生产动作通道唯一 = FC 工具调用。

已随双轨退役删除：strip_action_blocks / has_action_block（防泄漏清洗，
文本块通道不复存在）、退化流程信号探测（extract_degraded_signal_blocks，
）、StreamingActionExtractor 流式增量提取（边写边填）。
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

# 包装格式探测：{"studio-actions": [...]} 包装对象（解析兜底保留）
_WRAPPER_KEY_RE = re.compile(r"\"studio-actions\"\s*:")


# ---------- 公开 API ----------

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


def parse_actions_from_reply(reply: str) -> List[Dict[str, Any]]:
    """从回复文本中提取 studio-actions JSON 块并解析为操作列表。

     后仅 mock 演示通道与回归测试使用；生产动作通道唯一 = FC 工具。
    """
    actions: List[Dict[str, Any]] = []
    for pattern in _ACTION_BLOCK_PATTERNS:
        for match in pattern.finditer(reply):
            parsed = parse_json_tolerant(match.group(1))
            if parsed:
                actions.extend(normalize_actions(parsed))
    # 包装格式兜底：{"studio-actions": [...]} 无论裸 JSON 还是
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
    return [a for a in actions if isinstance(a, dict)]


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
        # 包装格式：{"studio-actions": [...]}
        return [_normalize_action_item(a) for a in parsed["studio-actions"]]
    if isinstance(parsed, list):
        return [_normalize_action_item(a) for a in parsed]
    if isinstance(parsed, dict):
        if isinstance(parsed.get("actions"), list):
            return [_normalize_action_item(a) for a in parsed["actions"]]
        # 单对象兜底：归一后能补出 action 才返回，避免把普通对象误当动作
        item = _normalize_action_item(parsed)
        if isinstance(item, dict) and item.get("action"):
            return [item]
    return []


def _normalize_action_item(a: Any) -> Any:
    """单条 action 归一：缺 action 键时用 name/type/tool 兜底（变体）。"""
    return normalize_action_aliases(a)


def normalize_action_aliases(a: Any) -> Any:
    """单条 action 的键级别名归一（现场：弱模型把 add_draft 写成
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
