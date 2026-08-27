"""闸预检协作臂。

模型永远唯一行动主体：
workflow_runtime 降级为账本 + 裁判数据层，永不发起行动；本模块只在轮始
装配两类机械兜底卡（原料闸提醒/规格向导，系统派生引导卡非行动发起），
**永不执行阶段、永不抢先对话**；其余一律交接模型循环（模型持主动权），
越阶由阶段前置闸在工具调用点否决（顺序保障 = 刹车不是方向盘）。
进出结果全记 tracer.record_control_flow + [ControlFlow] 日志（可观测性）。

提醒类兜底卡不占暂停槽（批 B）：提醒文案经正文通道上下文注入（下一轮经
history 模型可见），候选项降级为 quick-actions 快捷动作芯片（随 done
payload suggested_actions 下发；点击 = 一次普通用户消息，既有意图判定/
向导消费机械受理，不新增暂停语义）。
"""
from typing import Any, Callable, Dict, List, Optional

from loguru import logger

from src.video_agent.core import stage_probes as _po
from src.video_agent.core import live_metrics
from src.video_agent.core import prompt_gates
from src.video_agent.core.tracer import AgentTracer


def _quick_action_chips(options: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """提醒卡选项 → quick-actions 芯片（不占暂停槽，批 B）。

    kind=next：前端渲染显式 label 并直发 value；契约 = value 与 label
    同值的人类可读文本（suggested-guard 护栏），下一轮用户消息到达时由既有
    意图判定（豁免/上传回执）或规格向导消费机械受理，不携带暂停语义。
    """
    chips: List[Dict[str, str]] = []
    for opt in options or []:
        if not isinstance(opt, dict):
            continue
        label = str(opt.get("label") or "").strip()
        if not label:
            continue
        chips.append({"kind": "next", "label": label, "value": label})
    return chips


async def run_gate_precheck(
    state_manager: Any,
    skill: str,
    user_message: Any,
    response_factory: Callable[..., Any],
) -> Optional[Any]:
    """轮始闸预检；返回 None = 交接模型循环（模型持主动权）。

    response_factory 以 callable 注入（PlannerResponse 类，同 assemble_response
    惯例，避免与 planner 循环导入）。
    仅装配原料闸/规格闸兜底卡；提醒类不登记 active_pause、不签发 pause_id
    （系统提醒不占暂停槽）；重试引导只入账数据后交接；其余一律 None。
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
        # 提醒文案归正文通道（下一轮经 history 进模型上下文，模型可见）；
        # 选项 = quick-actions 芯片（点击发普通用户消息，不占暂停槽）
        return response_factory(
            text=outcome.message,
            suggested_actions=_quick_action_chips(outcome.options or []),
            steps=1)
    if outcome.kind == "script_ack":
        return response_factory(text=outcome.message, steps=1)
    if outcome.kind == "spec_pending":
        lead, opts = prompt_gates.spec_collect_card(state_manager.state_dict)
        # 引导词归正文通道（正常完成禁空正文）；维度候选项降为芯片，
        # 逐行「维度：值」文本由 _consume_spec_wizard 机械解析落盘；
        # 不选的维度仍由模型按剧本拟定后给用户过目（既有向导语义不变）
        return response_factory(
            text=f"{lead}\n请逐项选定规格维度后发送（点选或自定义输入）。",
            suggested_actions=_quick_action_chips(opts),
            steps=1)
    return None
