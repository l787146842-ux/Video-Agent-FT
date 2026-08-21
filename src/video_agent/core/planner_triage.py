"""闸预检协作臂（Rule2 v6：workflow_runtime 的闸节点，装配兜底卡）。

正向设计（宪法 v6 Rule2，ADR-0003）：白名单确定性阶段由 runtime 直跑；
本模块只在轮始装配两类机械兜底卡（原料闸提醒/规格向导），**永不执行
阶段、永不抢先对话**；创作型阶段交接模型循环，越阶由闸机在工具调用点否决。
进出结果全记 tracer.record_control_flow + [ControlFlow] 日志（可观测性）。
"""
from typing import Any, Callable, Optional

from loguru import logger

from src.video_agent.core import pipeline_orchestrator as _po
from src.video_agent.core import live_metrics
from src.video_agent.core import prompt_gates
from src.video_agent.core import pause_composer
from src.video_agent.core.tracer import AgentTracer


async def run_gate_precheck(
    state_manager: Any,
    skill: str,
    user_message: Any,
    response_factory: Callable[..., Any],
    issue_pause: Callable[[Any], None],
) -> Optional[Any]:
    """轮始闸预检；返回 None = 交接模型循环（模型持主动权）。

    response_factory 以 callable 注入（PlannerResponse 类，同 assemble_response
    惯例，避免与 planner 循环导入）；issue_pause 为暂停签发登记委托。
    仅装配原料闸/规格闸兜底卡；其余一律 None。
    """
    outcome = await _po.gate_precheck(state_manager, skill, user_message)
    _kind = outcome.kind if outcome is not None else "handoff"
    logger.info("[ControlFlow] gate_precheck outcome={}", _kind)
    try:
        AgentTracer.get_instance().record_control_flow(
            "gate_card" if outcome is not None else "handoff",
            _kind, skill or "")
    except Exception:
        # 控制流审计登记失败不阻断（降级遥测可见）
        live_metrics.record_degradation("planner_triage.control_flow_log")
    if outcome is None:
        return None
    if outcome.kind == "script_pending":
        # 三通道（Rule2 v6）：引导词归正文，卡=一句问句，kind=remind
        card = pause_composer.compose_remind_card(
            "剧本尚未收到，请选择原料提供方式。", outcome.options or [])
        resp = response_factory(
            text=outcome.message, confirmation=card["message"],
            confirmation_options=card["options"], steps=1)
        resp.pause_kind = card["kind"]
        issue_pause(resp)
        return resp
    if outcome.kind == "script_ack":
        return response_factory(text=outcome.message, steps=1)
    if outcome.kind == "spec_pending":
        lead, opts = prompt_gates.spec_collect_card(state_manager.state_dict)
        card = pause_composer.compose_collect_card(lead, opts)
        resp = response_factory(
            text=lead,  # 引导词归正文通道（正常完成禁空正文）
            confirmation="请逐项选定规格维度后发送（点选或自定义输入）。",
            confirmation_options=card["options"], steps=1)
        resp.pause_kind = card["kind"]
        issue_pause(resp)
        return resp
    return None
