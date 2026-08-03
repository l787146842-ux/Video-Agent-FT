"""
Studio Actions 解析器 — 从 actions.py 抽离。

职责：从 Agent 回复文本中提取 / 解析 / 修复 studio-actions JSON 块。
纯函数实现，无状态依赖，可独立测试。
"""
import json
import re
from typing import Any, Dict, List


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


# ---------- 公开 API ----------

def strip_action_blocks(text: str) -> str:
    """移除 studio-actions 块，返回纯可见文本"""
    for pat in _STRIP_PATTERNS:
        text = pat.sub("", text)
    return text.strip()


def has_action_block(reply: str) -> bool:
    """回复中是否存在 studio-actions 块（无论能否解析成功）"""
    return bool(_ACTION_BLOCK_DETECT.search(reply))


def parse_actions_from_reply(reply: str) -> List[Dict[str, Any]]:
    """从 Agent 回复文本中提取 studio-actions JSON 块并解析为操作列表"""
    actions: List[Dict[str, Any]] = []
    for pattern in _ACTION_BLOCK_PATTERNS:
        for match in pattern.finditer(reply):
            parsed = parse_json_tolerant(match.group(1))
            if parsed:
                actions.extend(normalize_actions(parsed))
    return [a for a in actions if isinstance(a, dict)]


# ---------- JSON 容错解析 ----------

def parse_json_tolerant(raw: str) -> Any:
    """容错 JSON 解析：先直接解析，失败后尝试轻量修复"""
    text = raw.strip()
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        pass
    repaired = repair_json(text)
    if repaired != text:
        try:
            return json.loads(repaired)
        except (json.JSONDecodeError, ValueError):
            pass
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
    """将解析结果统一为 action dict 列表"""
    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict):
        if isinstance(parsed.get("actions"), list):
            return parsed["actions"]
        if parsed.get("action"):
            return [parsed]
    return []
