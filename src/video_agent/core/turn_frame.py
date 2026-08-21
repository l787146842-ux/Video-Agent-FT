# -*- coding: utf-8 -*-
"""轮帧公共域（批4 turn_frame 抽公共）。

节点内模型循环（agent_loop step1）的前奏时间线登记：只登记真实
发生的 system 准备动作，前奏不冒充工具操作。
一切机械动作进转录一等条目（运行态/持久化同条目）。
（历史 runtime 机械直跑消费方已随 ADR-0004 退役，现唯一消费方 = agent_loop。）
"""
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from src.video_agent.core.sse_events import SSE_TOOL_FINISHED, SSE_TOOL_STARTED


async def emit_prelude_events(
    prelude_notes: Optional[List[Tuple[str, str]]],
    record_action: Callable[..., Any],
    emit: Callable[[Dict[str, Any]], Awaitable[None]],
) -> None:
    """前奏时间线（live 事件 + trace 条目同构登记）。

    只登记真实发生的 system 准备动作（加载 Skill 流程基线等）；
    读取/存档由对应工具真实发生时记录，前奏不冒充工具操作。
    """
    for pi, (pname, psummary) in enumerate(prelude_notes or []):
        record_action(str(pname), str(psummary), 0.0, True)
        pid = f"pre-{pi}"
        await emit({"type": SSE_TOOL_STARTED, "id": pid,
                    "name": str(pname), "summary": str(psummary)})
        await emit({"type": SSE_TOOL_FINISHED, "id": pid, "ok": True,
                    "elapsed_ms": 0.0, "result_summary": str(psummary)})


__all__ = ["emit_prelude_events"]
