"""统一闸机管线（宪法 §2.0：Guardrails are Execution Logic； 恢复接线）。

FC 轨（core/fc_tool_runner.py）与文本轨（web/action_executor.py）共用
同一份规则源（core/prompt_gates.py）与本模块的执行组合：

    input guard → tool input guard → tool execute → tool output guard → output guard → audit

本模块是「提示词写入」判定的唯一组合实现；两轨只注入参数，不各自写判定。
verdict 结构化（GateVerdict），回喂模型与展示用户用同一源；
每条判定经 tracer.record_gate 入审计（/api/agent/gates 可见）。

语义基线（/，用户第一）：
- 流程闸（元素概念图前置/故事板待确认窗口）只警告不拦人；
- 结构闸（字数/语言/时长/字幕/音频/镜头语言）strict 模式拒收重写；
- 用户坚持（gate_override 作用域覆盖）时硬伤降为警告放行。
"""
from loguru import logger
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src.video_agent.core import prompt_gates
from src.video_agent.core.tracer import AgentTracer


@dataclass
class GateVerdict:
    """一次闸机判定的结构化结果。"""

    rule_id: str
    layer: str  # platform | skill | session
    ok: bool
    message: str = ""

    def to_dict(self) -> Dict[str, Any]:
        meta = prompt_gates.GATE_RULES.get(self.rule_id)
        return {
            "rule_id": self.rule_id,
            "layer": self.layer,
            "description": meta.description if meta else "",
            "ok": self.ok,
            "message": self.message,
        }


@dataclass
class GateCheckOutcome:
    """提示词写入闸机的组合结果（双轨共用）。

    ok=False 时 reject_message 必须回喂模型（拒收重写，自愈闭环）；
    warnings 随回复/时间线展示；verdicts 入审计。
    """

    ok: bool = True
    reject_message: str = ""
    hard_errors: List[str] = field(default_factory=list)  # 结构校验硬伤明细（日志/升级指引用）
    warnings: List[str] = field(default_factory=list)
    verdicts: List[GateVerdict] = field(default_factory=list)
    overridden: bool = False              # 用户坚持放行过任一闸
    element_image_override_hit: bool = False  # 元素概念图前置被用户覆盖（文本轨落盘声明用）


def audit_verdicts(
    verdicts: List[GateVerdict],
    skill_name: str = "",
    action: str = "",
    draft_id: str = "",
    overridden: bool = False,
) -> None:
    """把 verdict 列表写入审计（tracer.record_gate）；失败不阻断主链路。"""
    try:
        tracer = AgentTracer.get_instance()
        for v in verdicts:
            tracer.record_gate(
                rule_id=v.rule_id,
                layer=v.layer,
                ok=v.ok,
                skill_name=skill_name,
                action=action,
                draft_id=draft_id,
                overridden=overridden,
                message=v.message,
            )
    except Exception as _e:
        logger.debug("[guard_pipeline] 忽略异常: {}", _e)


def evaluate_prompt_write(
    prompt: str,
    kind: str,
    state: Dict[str, Any],
    *,
    gate_rules: Optional[Dict[str, Any]] = None,
    gate_override: Any = False,
    gate_enabled: bool = True,
    element_image_missing: bool = False,
    mode: Optional[str] = None,
) -> GateCheckOutcome:
    """提示词写入统一判定（决策 D + 结构条款 + 流程闸组合；§2.0 唯一组合实现）。

    参数（两轨只注入，不各自组装判定）：
    - gate_rules: Skill manifest 解析出的可配置规则（parse_gate_rules 结果）；
    - gate_override: 用户坚持作用域（False/"all"/"element_image"…）；
    - element_image_missing: 元素概念图前置是否不满足（FC 轨按全量元素判定、
      文本轨按 sceneRefs 引用感知判定，各自算好传入，判定组合仍在本处）。

    返回 GateCheckOutcome；ok=False 时调用方必须拒绝写入并回喂 reject_message。
    """
    out = GateCheckOutcome()
    mode = mode or prompt_gates.gate_mode()
    if not gate_enabled or kind not in ("shot", "keyElement") or not str(prompt or "").strip():
        out.verdicts.append(GateVerdict("platform.prompt_write", "platform", True))
        return out
    if mode == "off":
        out.verdicts.append(GateVerdict("platform.prompt_write", "platform", True))
        return out

    # 流程闸：元素概念图前置（只警告不拦人， 语义；用户坚持时降为提示）
    if kind == "shot" and mode == "strict" and element_image_missing:
        if prompt_gates.override_covers(gate_override, prompt_gates.GATE_ELEMENT_IMAGE):
            out.warnings.append(
                "用户坚持跳过元素概念图前置（仅警告）：" + prompt_gates.SHOT_SEQUENCE_GATE_ERROR
            )
            out.overridden = True
            out.element_image_override_hit = True
        else:
            out.warnings.append(prompt_gates.SHOT_SEQUENCE_GATE_ERROR)
        out.verdicts.append(GateVerdict(
            "skill.flow.element_image", "skill", True,
            prompt_gates.SHOT_SEQUENCE_GATE_ERROR,
        ))

    # 结构闸：写入即校验（拒收重写，自愈闭环）
    ok, hard, _soft = prompt_gates.validate_prompt_write(
        str(prompt), kind, state, rules=gate_rules,
    )
    if ok:
        out.verdicts.append(GateVerdict("skill.prompt_structure", "skill", True))
        return out
    if prompt_gates.override_covers(gate_override, prompt_gates.GATE_STRUCTURE):
        # 决策 D：用户坚持 → 放行，硬伤降为警告
        out.hard_errors = list(hard)
        lines = "\n".join(f"- {e}" for e in hard)
        out.warnings.append(
            f"用户坚持写入，提示词结构校验未通过（本条仅为警告）：\n{lines}"
        )
        out.overridden = True
        out.verdicts.append(GateVerdict(
            "skill.prompt_structure", "skill", True,
            prompt_gates.format_gate_errors(hard),
        ))
        return out
    if mode != "strict":
        out.verdicts.append(GateVerdict("skill.prompt_structure", "skill", True))
        return out
    out.ok = False
    out.hard_errors = list(hard)
    out.reject_message = prompt_gates.format_gate_errors(hard)
    out.verdicts.append(GateVerdict(
        "skill.prompt_structure", "skill", False, out.reject_message,
    ))
    return out


def evaluate_gen_confirm(
    drafts: List[Dict[str, Any]],
    *,
    active: bool,
    override: Any = False,
    action: str = "",
) -> "tuple[Optional[str], List[str]]":
    """生成确认闸统一判定（双轨收敛一期：platform.gen_confirm 唯一实现）。

    drafts：目标草稿（已含提示词者由调用方筛好）；active：Skill 激活且 strict；
    override：用户坚持作用域。返回 (硬拒原因, warnings)，双轨语义逐字节一致：
    - override 命中 → 不拒，附豁免警告；
    - 未激活/空目标 → 不拒（空目标交工具自身报「未找到」）；
    - 全部已确认 → 不拒；
    - 存在未确认 → 硬拒（模型跳确认非用户意志），拒因用 BLOCKED 文案。
    判定经 tracer.record_gate 入审计（前端 chips 同源）。
    """
    warns: List[str] = []
    if override in ("all", True):
        w = "用户坚持跳过生成确认闸（仅警告），照常生成"
        warns.append(w)
        audit_verdicts([GateVerdict("platform.gen_confirm", "platform", True, w)],
                       action=action, overridden=True)
        return None, warns
    if not active or not drafts:
        return None, warns
    if prompt_gates.drafts_confirmed({}, drafts):
        audit_verdicts([GateVerdict("platform.gen_confirm", "platform", True)], action=action)
        return None, warns
    msg = "生成确认闸拦截：" + prompt_gates.GENERATION_CONFIRM_GATE_BLOCKED
    warns.append(msg)
    audit_verdicts([GateVerdict("platform.gen_confirm", "platform", False, msg)], action=action)
    return msg, warns


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
    """统一提示词写入判定（单 verdict 便捷出口；组合实现见 evaluate_prompt_write）。

    - ok=False：调用方必须拒绝写入并把 message 回喂模型（自愈闭环）；
    - ok=True 且 message 非空：写入放行，message 作为警告随结果展示；
    - user_override=True（决策 D：用户坚持）：硬伤降为警告照常放行。
    流程闸（元素图/待确认窗口）按  语义只警告不拦人。
    """
    out = evaluate_prompt_write(
        prompt, kind, state,
        gate_rules=gate_rules,
        gate_override="all" if user_override else False,
        gate_enabled=gate_enabled,
        element_image_missing=(
            kind == "shot" and prompt_gates.element_images_missing(state)
        ),
        mode=mode,
    )
    if not out.ok:
        return GateVerdict("skill.prompt_structure", "skill", False, out.reject_message)
    # 放行：返回结构闸 verdict（用户坚持时携带降级警告文案，层归属保持 skill）
    warn = out.warnings[0] if out.warnings else ""
    return GateVerdict("skill.prompt_structure", "skill", True, warn)
