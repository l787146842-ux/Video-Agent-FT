"""闸预检协作臂壳。

模型永远唯一行动主体。2026-08-31 用户裁决：原料闸/规格闸机械兜底卡
退役（Flova 对齐：流程顺序与原料收集归 skill 散文 + 模型自觉），
本模块恒交接模型循环；保留委托壳（planner 委托）。
进出结果全记 tracer.record_control_flow + [ControlFlow] 日志。
"""
from typing import Any, Callable, Optional

from loguru import logger

from src.video_agent.core import stage_probes as _po
from src.video_agent.core import live_metrics
from src.video_agent.core.tracer import AgentTracer


async def run_gate_precheck(
    state_manager: Any,
    skill: str,
    user_message: Any,
    response_factory: Callable[..., Any],
) -> Optional[Any]:
    """轮始闸预检壳：恒返回 None = 交接模型循环（模型持主动权）。"""
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
    return None
