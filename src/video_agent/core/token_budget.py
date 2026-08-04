"""
Token 预算管理 — 基于字符数估算 token 并自动截断历史消息。

估算规则：
- 中文 ~1.5 字/token
- 英文 ~4 字符/token
- 混合取加权平均

在 Planner 构建 messages 时：若估算超限（context_window_size * token_budget_ratio），
自动截断历史消息（保留最近 N 条 + 首条 system）。
"""
import re
from typing import Any, Dict, List

from loguru import logger


def estimate_tokens(text: str) -> int:
    """
    基于字符数估算 token 数量。
    中文字符按 1.5 字/token，其他按 4 字符/token。
    """
    if not text:
        return 0
    # 统计中文字符数
    cjk_count = len(re.findall(r'[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]', text))
    other_count = len(text) - cjk_count
    # 中文 1.5 字/token，英文 4 字符/token
    return int(cjk_count / 1.5 + other_count / 4) + 1


def estimate_messages_tokens(messages: List[Dict[str, Any]]) -> int:
    """估算消息列表的总 token 数"""
    total = 0
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            total += estimate_tokens(content)
        elif isinstance(content, list):
            # 多模态 content parts
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    total += estimate_tokens(part.get("text", ""))
        # 每条消息的 role/metadata 开销约 4 token
        total += 4
    return total


def truncate_messages(
    messages: List[Dict[str, Any]],
    max_tokens: int,
    keep_recent: int = 4,
) -> List[Dict[str, Any]]:
    """
    截断消息列表以适应 token 预算。

    策略：
    - 保留首条消息（通常是 system prompt）
    - 保留最近 keep_recent 条消息
    - 从中间开始删除最早的消息，直到估算 token 数 <= max_tokens

    返回截断后的消息列表（不修改原列表）。
    实现注：每条消息的 token 只估算一次，删除时用增量减法维护总量，
    避免旧版 while 循环里每删一条都全量重估的 O(n²) 开销。
    """
    if not messages:
        return messages

    per_msg_tokens = [estimate_messages_tokens([m]) for m in messages]
    current_tokens = sum(per_msg_tokens)
    if current_tokens <= max_tokens:
        return messages

    # 需要截断
    result = list(messages)
    token_list = list(per_msg_tokens)
    total = current_tokens
    # 保护边界：首条 + 最近 keep_recent 条
    min_keep = 1 + min(keep_recent, len(result) - 1)

    while total > max_tokens and len(result) > min_keep:
        # 删除第 2 条（索引 1），即最早的非保护消息
        removed = result.pop(1)
        total -= token_list.pop(1)
        preview = str(removed.get("content", ""))[:40]
        logger.debug(f"[TokenBudget] 截断历史消息: {preview}...")

    if current_tokens > max_tokens:
        logger.info(
            f"[TokenBudget] 消息截断: {current_tokens} -> {total} tokens "
            f"({len(messages)} -> {len(result)} 条)"
        )
    return result
