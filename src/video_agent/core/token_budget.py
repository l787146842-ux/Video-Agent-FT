"""
Token 预算管理 — 估算 token 并自动截断历史消息。

估算规则：
- 优先使用 tiktoken（可选依赖，OpenAI 系精确估算）
- 未安装时回退启发式：中文 ~1.5 字/token，英文 ~4 字符/token

在 Planner 构建 messages 时：若估算超限（模型上下文窗口 * token_budget_ratio），
自动截断历史消息（保留最近 N 条 + 首条 system）；首条 system 自身超预算时，
可通过 system_degrader 降级重建（第二道保险丝）。
"""
import re
from typing import Any, Callable, Dict, List, Optional

from loguru import logger

from src.video_agent.config import settings

# tiktoken 为可选依赖：装了走精确估算，没装回退启发式（功能不中断）
try:
    import tiktoken

    _ENC = tiktoken.get_encoding("cl100k_base")
except Exception:  # ImportError 或离线环境下 encoding 数据不可用
    _ENC = None

# 模型名关键字 → 上下文窗口（token）。只收录确定值；未命中回落全局 CONTEXT_WINDOW_SIZE。
# 新模型接入时按供应商文档扩充本表即可。
_MODEL_CONTEXT_WINDOWS = {
    "gemini-3": 1_000_000,
    "gemini-2": 1_000_000,
    "gemini-1.5": 1_000_000,
    "gpt-4.1": 1_000_000,
    "gpt-4o": 128_000,
    "gpt-4-turbo": 128_000,
    "deepseek": 64_000,
    "qwen": 128_000,
    "claude": 200_000,
}


def context_window_for_model(model: str) -> int:
    """按模型名查上下文窗口；未收录的模型回落 settings.context_window_size。"""
    m = (model or "").lower()
    for key, window in _MODEL_CONTEXT_WINDOWS.items():
        if key in m:
            return window
    return settings.context_window_size


def estimate_tokens(text: str) -> int:
    """
    估算 token 数量。
    tiktoken 可用时精确估算（cl100k_base，对中文同样有效）；
    否则启发式：中文字符按 1.5 字/token，其他按 4 字符/token。
    """
    if not text:
        return 0
    if _ENC is not None:
        return len(_ENC.encode(text)) + 1
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
    system_degrader: Optional[Callable[[str], str]] = None,
) -> List[Dict[str, Any]]:
    """
    截断消息列表以适应 token 预算。

    策略：
    - 保留首条消息（通常是 system prompt）
    - 保留最近 keep_recent 条消息
    - 从中间开始删除最早的消息，直到估算 token 数 <= max_tokens
    - 保险丝：删无可删仍超预算且首条为 system 时，调用 system_degrader
      降级重建 system 段（如状态 JSON 只留组标题/计数），避免超限请求发出

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

    # 第二道保险丝：历史已删到保护边界仍超预算 → 首条 system 自身过大
    # （状态 JSON 大 + Skill 全文注入的场景），用降级器重建 system 段
    if total > max_tokens and result and result[0].get("role") == "system" and system_degrader is not None:
        degraded = system_degrader(result[0].get("content") or "")
        if degraded and degraded != result[0].get("content"):
            result[0] = {**result[0], "content": degraded}
            new_total = estimate_messages_tokens(result)
            logger.warning(
                f"[TokenBudget] system 段超预算，已降级重建: {total} -> {new_total} tokens "
                f"(预算 {max_tokens})"
            )
            total = new_total
    if total > max_tokens:
        logger.warning(
            f"[TokenBudget] 截断后仍超预算: {total} > {max_tokens} tokens，"
            f"请求可能被供应商拒绝（请考虑缩短 Skill 全文或清理草稿）"
        )
    return result
