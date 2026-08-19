"""确定性分诊与编排器快路径（批 7 自 planner.py 切出；ADR-0002 控制流统一）。

分诊只认客观状态事实，零语料：advance（外层循环接管）仅由客观事实触发；
其余一律 handoff（受界模型循环）——歧义宁可交模型也不猜意图；
交接后由阶段前置闸（platform.stage_precondition）与步间回收保底。
进出结果全记 tracer.record_control_flow + [ControlFlow] 日志（控制流决策永不无据可查）。
"""
from typing import Any, Callable, Dict, Optional

from loguru import logger

from src.video_agent.core import pipeline_orchestrator as _po
from src.video_agent.core import prompt_gates
from src.video_agent.core.tracer import AgentTracer
from src.video_agent.skill_runtime.registry import script_required_active
from src.video_agent.state.models import CAT_AUDIO_ITEMS, CAT_KEY_ELEMENTS, CAT_SHOTS


def is_adhoc_edit(state: Dict[str, Any], user_message: Any) -> bool:
    """ad-hoc 特征（客观事实）：消息命中既有资产名 → 交接模型循环。
    （语料动词已删：标题命中即足以判定，不猜措辞。）"""
    if not isinstance(user_message, str) or not user_message.strip():
        return False
    titles = [
        str(g.get("title") or "").strip()
        for cat in (CAT_KEY_ELEMENTS, CAT_SHOTS, CAT_AUDIO_ITEMS)
        for g in (state.get(cat) or []) if isinstance(g, dict)
    ]
    return any(t and len(t) >= 2 and t in user_message for t in titles)


def is_question(user_message: Any) -> bool:
    """提问客观特征（标点/疑问词）：自由提问不错抓进流程推进。"""
    msg = str(user_message or "").strip()
    return (
        "？" in msg or "?" in msg
        or msg.startswith(("什么", "怎么", "为什么", "哪", "吗"))
    )


def triage_control(state: Dict[str, Any], user_message: Any, skill: str) -> str:
    """确定性分诊：返回 advance | handoff，零语料。

    advance（外层循环接管）仅由客观事实触发：
    - 一条龙豁免生效，或存在待确认暂停（回应即续进；改指示命中资产名
      时经 adhoc 交接，提问经 question 交接）；
    - 系统建议按钮的机械续进文案（suggested_actions 的 continue 值）；
    - 管线未启动且（原料就位 或 原料闸启用）→ 开局（编排器直跑首个
      确定性阶段或机械回提醒卡）。
    其余一律 handoff（受界模型循环）。
    """
    msg = str(user_message or "").strip()
    inter = state.get("interaction") or {}
    if inter.get("auto_continue"):
        return "advance"
    if inter.get("awaiting_confirmation"):
        if is_adhoc_edit(state, msg) or is_question(msg):
            return "handoff"
        return "advance"
    if msg == "继续完成":  # suggested_actions continue 按钮机械文案
        return "advance"
    if not msg or is_adhoc_edit(state, msg) or is_question(msg):
        return "handoff"
    started = bool((state.get("analysis") or {}).get("summary"))
    if not started:
        if state.get("uploadedDocs"):
            return "advance"
        try:
            if script_required_active(skill):
                return "advance"  # 编排器机械回提醒卡/上传回执
        except Exception:
            pass
    return "handoff"


async def run_orchestrator_path(
    state_manager: Any,
    skill: str,
    user_message: Any,
    response_factory: Callable[..., Any],
    issue_pause: Callable[[Any], None],
) -> Optional[Any]:
    """编排器快路径；返回 None = 创作型阶段交接模型循环。

    response_factory 以 callable 注入（PlannerResponse 类，同 assemble_response
    惯例，避免与 planner 循环导入）；issue_pause 为暂停签发登记委托。
    进出结果全记控制流事件（可观测性）。
    """
    outcome = await _po.orchestrate_turn(state_manager, skill, user_message)
    _kind = outcome.kind if outcome is not None else "handoff"
    logger.info("[ControlFlow] orchestrator outcome={}", _kind)
    try:
        AgentTracer.get_instance().record_control_flow(
            "stage_batch" if outcome is not None else "handoff",
            _kind, skill or "")
    except Exception:
        pass
    if outcome is None:
        return None
    if outcome.kind == "script_pending":
        resp = response_factory(
            text=outcome.message, confirmation=outcome.message,
            confirmation_options=outcome.options or [], steps=1)
        issue_pause(resp)
        return resp
    if outcome.kind == "script_ack":
        return response_factory(text=outcome.message, steps=1)
    if outcome.kind == "spec_pending":
        msg, opts = prompt_gates.spec_collect_card(state_manager.state_dict)
        resp = response_factory(
            text="", confirmation=msg, confirmation_options=opts, steps=1)
        issue_pause(resp)
        return resp
    if outcome.kind == "paused":
        inter = state_manager.state_dict.setdefault("interaction", {})
        inter["awaiting_confirmation"] = True
        inter["confirmation_message"] = outcome.message
        state_manager.save_debounced()
        resp = response_factory(
            text=outcome.message, confirmation=outcome.message,
            confirmation_options=outcome.options or [], steps=1)
        issue_pause(resp)
        return resp
    return response_factory(text=outcome.message or "", steps=1)
