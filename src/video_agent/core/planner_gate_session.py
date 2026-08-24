"""闸机豁免消费域（自 planner.py 切出；handle_message 瘦身）。

会话层一次性豁免（gate_overrides，§2.4）的消费与作用域判定：
唯一权威入口 = 前端「本次放行」按钮随消息登记 interaction.gate_overrides，
单次消费即清除、留痕入 trace（C5：正则猜自然语言豁免入口已退役，
「坚持/听我的/直接写」类话术不再降级闸门，误伤面归零）。
返回作用域（False = 无豁免）；消费失败不阻断对话（本轮无豁免放行）。
"""
from typing import Any

from loguru import logger

from src.video_agent.core import live_metrics, prompt_gates
from src.video_agent.core.tracer import AgentTracer


def consume_gate_overrides(state_manager: Any, user_message: Any) -> Any:
    """消费本轮一次性豁免并返回作用域（False/"all"/"element_image"）。

    显式枚举判定：scope=all 或 platform.* 前缀 → ALL；其余 → ELEMENT_IMAGE。
    全程留痕（§2.4）：实际消费 scope 入 trace；消费失败本轮视为无豁免。
    """
    gate_override_scope: Any = False
    try:
        interaction = state_manager.state_dict.get("interaction") or {}
        taken = [r for r in (interaction.get("gate_overrides") or []) if r]
        if taken:
            interaction["gate_overrides"] = []
            state_manager.save()
            gate_override_scope = (
                prompt_gates.GATE_OVERRIDE_SCOPE_ALL
                if any(str(r) == prompt_gates.GATE_OVERRIDE_SCOPE_ALL
                       or str(r).startswith("platform.") for r in taken)
                else prompt_gates.GATE_OVERRIDE_SCOPE_ELEMENT_IMAGE
            )
            logger.info(f"[GateOverride] 消费 {len(taken)} 条一次性豁免，作用域={gate_override_scope}")
            AgentTracer.get_instance().record_gate(
                # override 留痕经统一归一出口（P5；正式 ID 归一为恒等，语义不变）
                prompt_gates.normalize_rule_id("platform.gate_override"), "session", True,
                overridden=True, message=f"一次性放行生效，作用域={gate_override_scope}",
                scope=str(gate_override_scope),
            )
    except Exception as _e:
        # 承重接线遥测：豁免消费断线不再只进日志，降级端点可见
        live_metrics.record_degradation("planner_gate_session.consume_gate_overrides")
        logger.warning("[GateOverride] 豁免消费失败（本次放行可能未生效，本轮视为无豁免）: {}", _e)
    return gate_override_scope
