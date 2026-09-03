# -*- coding: utf-8 -*-
"""循环内语义压缩（第 5 批，Q6/Q7 裁决 2026-09-01）。

truncate_messages 的轮组截断是有损删除；本模块在截断**之前**对最旧轮组
做摘要替换（复用 planner/compaction.md 模板，与入口层会话 compaction
同模板同哲学）：丢正文留摘要+句柄，消灭有损截断的主触发源。

触发与边界：
- 触发：消息估算总量 >= 0.8 × 预算才压（短对话零损失，同惰性压缩哲学）；
- 目标：保护窗口（最近 keep_recent 条）外最旧的一个轮组，整组原子替换
  （轮组边界复用 token_budget._is_real_user_msg，FC 配对不劈半）；
- 单条孤立真实用户消息不压（用户原话逐字保留，Codex 交接备忘原则）；
- 摘要按轮组内容指纹缓存（多步循环每步不重复烧摘要调用）；
- 失败静默回落（压缩是优化不是前置条件），调用方继续走既有截断链。
"""
import hashlib
from typing import Any, Dict, List

from loguru import logger

from src.video_agent.config import settings
from src.video_agent.core.token_budget import (
    _is_real_user_msg,
    estimate_messages_tokens,
)
from src.video_agent.core.tracer import AgentTracer
from src.video_agent.utils.prompts import load_prompt_section

# 触发比例：消息总量达预算的该比例才启动循环内压缩
COMPACT_TRIGGER_RATIO = 0.8
# 采样进摘要模板的对话字符上限（摘要调用自身也要省）
_MAX_DIALOG_CHARS = 8000
# 指纹缓存上限（防遥测式自膨胀；新条目挤掉最旧）
_CACHE_MAX = 64
_COMPACT_CACHE: Dict[str, str] = {}

# 摘要替换消息的前缀文案：外置 shared/degradation.md::ROUND_SUMMARY_PREFIX
#（单一事实源）；模块加载期读取一次保前缀字节稳定，分节缺失时仅
# logger.warning + 最小功能性占位（M-2 同口径，不内联逐字兜底）
_SUMMARY_PREFIX = load_prompt_section("shared/degradation.md", "ROUND_SUMMARY_PREFIX")
if not _SUMMARY_PREFIX:
    logger.warning(
        "[round_compact] prompts/shared/degradation.md::ROUND_SUMMARY_PREFIX "
        "分节缺失，使用最小占位")
    _SUMMARY_PREFIX = "（系统）早期轮次已压缩为摘要："


def _record_event(kind: str, detail: str) -> None:
    try:
        AgentTracer.get_instance().record_context_event(kind, detail)
    except Exception as e:
        logger.debug(f"[RoundCompact] 事件记录失败（忽略）: {e}")


def _group_end(messages: List[Dict[str, Any]], start: int, protect_start: int) -> int:
    """轮组终点：start（真实用户消息）到下一条真实用户消息（不含）或保护起点。"""
    end = start + 1
    while end < protect_start and not _is_real_user_msg(messages[end]):
        end += 1
    return end


def _sample_dialog(group: List[Dict[str, Any]]) -> str:
    """轮组采样文本（role 标注 + 截断上限），供摘要模板消费。"""
    parts: List[str] = []
    total = 0
    for m in group:
        content = m.get("content", "")
        if isinstance(content, list):
            content = " ".join(
                str(p.get("text", "")) for p in content
                if isinstance(p, dict) and p.get("type") == "text"
            )
        text = str(content).strip()
        if not text:
            continue
        line = f"{m.get('role', 'user')}: {text}"
        if total + len(line) > _MAX_DIALOG_CHARS:
            break
        parts.append(line)
        total += len(line)
    return "\n".join(parts)


async def compact_oldest_round(
    messages: List[Dict[str, Any]],
    adapter: Any,
    max_tokens: int,
    keep_recent: int = 4,
) -> bool:
    """预算逼近时把保护窗外最旧轮组摘要替换为单条合成消息（原地修改）。

    返回 True = 本轮发生过压缩。任何失败路径返回 False 且 messages 不变。
    """
    if not messages or adapter is None:
        return False
    total = estimate_messages_tokens(messages)
    if total < int(max_tokens * COMPACT_TRIGGER_RATIO):
        return False
    protect_start = len(messages) - min(keep_recent, len(messages) - 1)
    # 最旧轮组从索引 0 起；索引 0 非真实用户消息（如合成摘要头）则顺移到首个真实用户
    start = 0
    while start < protect_start and not _is_real_user_msg(messages[start]):
        start += 1
    if start >= protect_start:
        return False
    end = _group_end(messages, start, protect_start)
    # 孤立单条真实用户消息不压（用户原话逐字保留）
    if end - start < 2:
        return False
    group = messages[start:end]
    dialog = _sample_dialog(group)
    if not dialog:
        return False
    fp = hashlib.md5(dialog.encode("utf-8")).hexdigest()
    summary = _COMPACT_CACHE.get(fp)
    if not summary:
        tpl = load_prompt_section("planner/compaction.md", "TEMPLATE")
        prompt = tpl.replace("{{dialog}}", dialog) if tpl else (
            "请把以下对话压缩为不超过 300 字的摘要，保留决策与约束：\n" + dialog)
        try:
            resp = await adapter.chat(
                [
                    {"role": "system", "content": "你是会话摘要助手。"},
                    {"role": "user", "content": prompt},
                ],
                timeout=settings.llm_timeout,
            )
            summary = (getattr(resp, "content", "") or "").strip()
        except Exception as e:
            logger.warning(f"[RoundCompact] 循环内摘要失败，回落截断链: {e}")
            return False
        if not summary:
            return False
        _COMPACT_CACHE[fp] = summary
        if len(_COMPACT_CACHE) > _CACHE_MAX:
            _COMPACT_CACHE.pop(next(iter(_COMPACT_CACHE)))
    messages[start:end] = [{"role": "user", "content": _SUMMARY_PREFIX + summary}]
    new_total = estimate_messages_tokens(messages)
    logger.info(
        f"[RoundCompact] 循环内语义压缩：轮组 {end - start} 条 -> 摘要 1 条，"
        f"{total} -> {new_total} tokens（预算 {max_tokens}）")
    _record_event(
        "compact",
        f"循环内轮组摘要 {total}->{new_total} tokens（{end - start} 条->1 条）",
    )
    return True
