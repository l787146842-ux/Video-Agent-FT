"""
对话摘要：LLM 压缩对话为长期记忆条目；LLM 不可用时降级截取。

Prompt 外置（Rule6）：prompts/memory/summarize.md
"""
from typing import Awaitable, Callable, Optional

from loguru import logger

from src.video_agent.utils.prompts import render_prompt

# 降级截取长度
_FALLBACK_USER_CHARS = 60
_FALLBACK_REPLY_CHARS = 80
_SUMMARY_MAX_CHARS = 200


def _to_text(content) -> str:
    """多模态 content（list parts）→ 纯文本"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for p in content:
            if isinstance(p, dict) and p.get("type") == "text":
                parts.append(str(p.get("text", "")))
        return " ".join(parts)
    return str(content or "")


def fallback_summary(user_message: str, agent_reply: str) -> str:
    """无 LLM 时的降级摘要：截取首尾关键句"""
    user = _to_text(user_message).strip().replace("\n", " ")[:_FALLBACK_USER_CHARS]
    reply = _to_text(agent_reply).strip().replace("\n", " ")[:_FALLBACK_REPLY_CHARS]
    if not user and not reply:
        return ""
    return f"用户要求：{user}；Agent 回复要点：{reply}"


async def summarize_dialog(
    user_message: str,
    agent_reply: str,
    summarize_fn: Optional[Callable[[str], Awaitable[str]]] = None,
) -> str:
    """
    生成单条记忆文本。
    summarize_fn: 可选 async callable(prompt) -> str（由 Planner 用当前 adapter 包装）
    """
    user_text = _to_text(user_message)
    reply_text = _to_text(agent_reply)
    if not user_text.strip() and not reply_text.strip():
        return ""

    if summarize_fn is None:
        return fallback_summary(user_text, reply_text)

    prompt = render_prompt(
        "memory/summarize.md",
        user_message=user_text[:2000],
        agent_reply=reply_text[:3000],
    )
    if not prompt:
        return fallback_summary(user_text, reply_text)

    try:
        text = (await summarize_fn(prompt)).strip()
        if not text:
            return fallback_summary(user_text, reply_text)
        return text[:_SUMMARY_MAX_CHARS]
    except Exception as e:
        logger.warning(f"[Memory] LLM 摘要失败，降级截取: {e}")
        return fallback_summary(user_text, reply_text)
