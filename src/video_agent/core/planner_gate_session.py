"""闸机豁免消费域（批 7 自 planner.py 切出；handle_message 瘦身）。

会话层一次性豁免（gate_overrides，§2.4）的消费与作用域判定：
按钮路径（随消息登记 interaction.gate_overrides，单次消费即清除、留痕入 trace）
优先；无显式豁免时回落正则意图识别兜底（按钮化全覆盖前的过渡）。
返回作用域（False = 无豁免）；消费失败不阻断对话（回落兜底）。
"""
from typing import Any

from loguru import logger

from src.video_agent.core import prompt_gates
from src.video_agent.core.tracer import AgentTracer


def consume_gate_overrides(state_manager: Any, user_message: Any) -> Any:
    """消费本轮一次性豁免并返回作用域（False/"all"/"element_image"）。

    显式枚举判定：scope=all 或 platform.* 前缀 → ALL；其余 → ELEMENT_IMAGE。
    全程留痕（§2.4）：实际消费 scope 入 trace；消费失败回落意图识别兜底。
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
                "platform.gate_override", "session", True,
                overridden=True, message=f"一次性放行生效，作用域={gate_override_scope}",
                scope=str(gate_override_scope),
            )
    except Exception as _e:
        logger.warning("[GateOverride] 豁免消费失败（本次放行可能未生效，回落意图识别兜底）: {}", _e)
    if not gate_override_scope and isinstance(user_message, str):
        gate_override_scope = prompt_gates.user_insists_override(user_message) or False
    return gate_override_scope
