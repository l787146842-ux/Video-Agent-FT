"""执行器进度上报（M6）：长任务批次 x/y 与预计剩余时间实时推给前端状态栏。

用 contextvar 绑定当前任务的事件通道：FC 轨（fc_tool_runner 工具调用处）与
文本轨（agent_loop 执行 executor 动作处）在调用执行器前 bind_progress_emitter，
执行器内部在批次边界调用 emit_progress("...")；未绑定时静默无操作
（单测/CLI/无前端场景不受影响）。
"""
import contextvars
import uuid
from typing import Any, Awaitable, Callable, Dict, Optional

from src.video_agent.core.sse_events import (
    SSE_ACTIONS_APPLIED,
    SSE_STATUS,
    SSE_TOOL_FINISHED,
    SSE_TOOL_STARTED,
)

ProgressEmitter = Callable[[Dict[str, Any]], Awaitable[None]]

_progress_var: contextvars.ContextVar[Optional[ProgressEmitter]] = contextvars.ContextVar(
    "skill_progress_emitter", default=None
)


def bind_progress_emitter(on_event: Optional[ProgressEmitter]):
    """绑定进度事件通道，返回解绑 token；on_event 为 None 时绑定空占位。"""
    async def _emit(event: Dict[str, Any]) -> None:
        if on_event is not None:
            await on_event(event)

    return _progress_var.set(_emit)


def unbind_progress_emitter(token) -> None:
    """解绑进度事件通道（与 bind_progress_emitter 成对使用）。"""
    _progress_var.reset(token)


async def emit_progress(text: str) -> None:
    """推送一条进度状态文案（未绑定/空文案静默忽略，异常不阻断执行器）。"""
    emitter = _progress_var.get()
    if emitter is None or not text:
        return
    try:
        await emitter({"type": SSE_STATUS, "text": text})
    except Exception:
        pass


async def emit_timeline_note(
    summary: str, *, name: str = "executor_substep", ok: bool = True, elapsed_ms: float = 0.0,
) -> None:
    """执行器子步骤过程明细（Q2：模型的一切操作都要进时间线）。

    双通道记录：持久化 trace（刷新后仍在）+ 实时时间线事件（推理中可见）。
    未绑定事件通道时仅记 trace（单测/CLI 场景不受影响）。
    """
    if not summary:
        return
    try:
        from src.video_agent.core.tracer import AgentTracer
        # 814G2：子步骤缓冲挂到父工具条目之后（持久化顺序 = live 顺序）
        AgentTracer.get_instance().record_subaction(
            name=name, summary=summary, elapsed_ms=elapsed_ms, ok=ok,
        )
    except Exception:
        pass
    emitter = _progress_var.get()
    if emitter is None:
        return
    try:
        nid = f"sub-{uuid.uuid4().hex[:8]}"
        await emitter({"type": SSE_TOOL_STARTED, "id": nid, "name": name, "summary": summary})
        await emitter({
            "type": SSE_TOOL_FINISHED, "id": nid, "ok": ok,
            "elapsed_ms": round(elapsed_ms, 1), "result_summary": summary,
        })
    except Exception:
        pass


async def emit_state_refresh(count: int = 1) -> None:
    """状态快照即时下发（Q3 首拆即显）：执行器批次落盘后立即通知前端
    刷新故事板，不等整个工具调用结束。chat_service 收到 actions_applied
    会附上全量快照，前端左栏卡片当场亮出来。"""
    emitter = _progress_var.get()
    if emitter is None:
        return
    try:
        await emitter({"type": SSE_ACTIONS_APPLIED, "count": max(1, count)})
    except Exception:
        pass


def format_eta(seconds: float) -> str:
    """预计剩余时间的人类可读文案"""
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"约 {seconds} 秒"
    minutes, rest = divmod(seconds, 60)
    return f"约 {minutes} 分钟" if not rest else f"约 {minutes} 分 {rest} 秒"
