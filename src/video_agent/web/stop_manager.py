"""停止/在途登记小模块（端到端中断协议）。

职责（不变式：任何中断都有痕迹、都有出口）：
- 停止阶段措辞与痕迹文案（与前端 locale 同一口径，持久化供刷新后恢复）
- 在途外部生成任务快照 re-export（第一版不撤销，仅登记 + 文案告知）
- stopped 终态事件构造（Cancel 守门/补发/透传富化三处共用）
- 停止痕迹消息持久化（有文本正文 + meta / 无文本轻量气泡，同轮 turn_id）
"""
from typing import Any, Dict, List

from src.video_agent.core.sse_events import SSE_STOPPED
from src.video_agent.web.task_manager import snapshot_inflight_generations

__all__ = [
    "stopped_event",
    "stopped_note",
    "persist_stop_trace",
    "snapshot_inflight_generations",
    "CONTINUE_LAST_TASK_SUGGESTION",
    "retry_suggestion_if_user",
]

# 「继续刚才的任务」建议动作（与前端 locale rp.msg.continueLastTask 同口径）：
# kind=retry=点击走既有机械重发，失效走 suggestedTargetIndex 既有机制；
# 随停止/错误消息落盘，刷新后历史装载即可重建
CONTINUE_LAST_TASK_SUGGESTION: List[Dict[str, str]] = [
    {"kind": "retry", "label": "继续刚才的任务", "value": ""},
]


def retry_suggestion_if_user(svc) -> List[Dict[str, str]] | None:
    """存在用户消息（可机械重发）时才给继续建议（与前端挂载条件同语义）。

    返回新拷贝，避免多处落盘共享同一可变列表。
    """
    if any(m.get("sender") == "user" for m in svc.get_chat_messages()):
        return [dict(a) for a in CONTINUE_LAST_TASK_SUGGESTION]
    return None

# 停止阶段 → 痕迹文案（与前端 locale 同一口径，后端持久化供刷新后恢复）
_STOP_PHASE_TEXT = {
    "thinking": "已在思考阶段停止（未产生内容）",
    "tool_executing": "已在工具执行阶段停止",
    "streaming": "已在输出阶段停止",
}


def stopped_note(phase: str, inflight_count: int = 0) -> str:
    """停止痕迹文案：阶段措辞 + 在途外部生成任务提醒（如有）"""
    note = _STOP_PHASE_TEXT.get(phase) or _STOP_PHASE_TEXT["thinking"]
    if inflight_count > 0:
        note += f"（注意：{inflight_count} 项外部生成任务仍在供应商侧继续，本次停止不会撤销）"
    return note


def stopped_event(phase: str = "thinking", inflight: List[Dict[str, Any]] | None = None) -> Dict[str, Any]:
    """构造 stopped 终态事件并富化在途登记（web 层职责：core 不感知注册表）。

    两处共用：_run_agent_task 的 CancelledError 守门补发，
    以及 _real_stream 对 agent_loop 检查点事件的透传富化（setdefault 不覆盖
    上游已带字段）。第一版不做真实撤销/补偿，仅登记 + 文案告知。
    """
    ev: Dict[str, Any] = {"type": SSE_STOPPED, "phase": phase}
    ev["inflight"] = inflight if inflight is not None else snapshot_inflight_generations()
    return ev


async def persist_stop_trace(
    svc, final_text: str, stop_phase: str, model: str,
    turn_id: str, use_studio_context: bool,
) -> None:
    """落停止痕迹消息供刷新后恢复（stopped 即终态，调用方不再发 done）。

    有文本：正文落盘 + meta 标停止阶段；无文本：轻量系统气泡
    （与前端 cancelStream 无文本路径同构）；均属同一停止轮，带同轮 turn_id。
    """
    if not use_studio_context:
        return
    inflight = snapshot_inflight_generations()
    note = stopped_note(stop_phase, len(inflight))
    async with svc.lock:
        if final_text:
            svc.add_chat_message(
                "agent", final_text, model_name=model or "",
                meta=f"⏹ {note}",
                turn_id=turn_id,
                suggested_actions=retry_suggestion_if_user(svc),
            )
        else:
            svc.add_chat_message(
                "agent", f"⏹ {note}", turn_id=turn_id,
                suggested_actions=retry_suggestion_if_user(svc),
            )
