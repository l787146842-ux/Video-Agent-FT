"""统一闸机管线（宪法 §2.0：Guardrails are Execution Logic）。

FC 轨（core/fc_tool_runner.py）与文本轨（web/action_executor.py）共用
同一份规则源（core/prompt_gates.py）与本模块的执行组合：

    input guard → tool input guard → tool execute → tool output guard → output guard → audit

本模块是「提示词写入」判定的唯一组合实现；两轨只注入参数，不各自写判定。
verdict 结构化（GateVerdict），回喂模型与展示用户用同一源。
"""
from dataclasses import dataclass
from typing import Any, Dict, Optional

from src.video_agent.core import prompt_gates


@dataclass
class GateVerdict:
    """一次闸机判定的结构化结果。"""

    rule_id: str
    layer: str  # platform | skill | session
    ok: bool
    message: str = ""


def prompt_write_verdict(
    prompt: str,
    kind: str,
    state: Dict[str, Any],
    *,
    gate_rules: Optional[Dict[str, Any]] = None,
    user_override: bool = False,
    gate_enabled: bool = True,
    mode: Optional[str] = None,
) -> GateVerdict:
    """统一提示词写入判定（决策 D + 结构条款 + 时序闸）。

    - ok=False：调用方必须拒绝写入并把 message 回喂模型（自愈闭环）；
    - ok=True 且 message 非空：写入放行，message 作为警告随结果展示；
    - user_override=True（决策 D：用户坚持）：硬伤降为警告照常放行。
    """
    mode = mode or prompt_gates.gate_mode()
    if not gate_enabled or kind not in ("shot", "keyElement") or not str(prompt or "").strip():
        return GateVerdict("platform.prompt_write", "platform", True)
    if mode == "off":
        return GateVerdict("platform.prompt_write", "platform", True)
    # 平台硬边界：元素图像未就绪严禁写分镜提示词
    if kind == "shot" and mode == "strict" and prompt_gates.element_images_missing(state):
        return GateVerdict(
            "platform.shot_sequence", "platform", False,
            prompt_gates.SHOT_SEQUENCE_GATE_ERROR,
        )
    # 平台硬边界：故事板结构待用户确认（审阅窗口）
    if mode == "strict" and prompt_gates.storyboard_pending(state):
        return GateVerdict(
            "platform.storyboard_pending", "platform", False,
            prompt_gates.STORYBOARD_PENDING_GATE_ERROR,
        )
    ok, hard, soft = prompt_gates.validate_prompt_write(
        str(prompt), kind, state, rules=gate_rules,
    )
    if ok:
        return GateVerdict("skill.prompt_structure", "skill", True)
    if user_override:
        # 决策 D：用户坚持 → 放行，硬伤降为警告
        return GateVerdict(
            "skill.prompt_structure", "skill", True,
            prompt_gates.format_gate_errors(hard),
        )
    if mode != "strict":
        return GateVerdict("skill.prompt_structure", "skill", True)
    return GateVerdict(
        "skill.prompt_structure", "skill", False,
        prompt_gates.format_gate_errors(hard),
    )
