"""统一闸机管线（宪法 §2.0：Guardrails are Execution Logic）。

动作通道单轨 = FC：判定经 fc_tool_runner 闸机链执行，
规则源唯一 = core/prompt_gates.py，执行组合唯一 = 本模块：

    input guard → tool input guard → tool execute → tool output guard → output guard → audit

本模块是「提示词写入」判定的唯一组合实现；调用方只注入参数，不各自写判定。
verdict 结构化（GateVerdict），回喂模型与展示用户用同一源；
每条判定经 tracer.record_gate 入审计（/api/agent/gates 可见）。
遥测旁路：audit_verdicts 同步轻量 append 一行到
GATE_TRIGGER_COUNTS（data/gate_trigger_counts.jsonl），
使「连续 N 轮零触发降档」可计算（scripts/audit_gate_triggers.py 汇总）；
旁路只记不改判定，任何异常吞掉不影响主链路。

语义基线（用户第一）：
- 流程闸（故事板待确认窗口）只警告不拦人；
- 结构闸（字数/语言/时长/字幕/音频/镜头语言）strict 模式拒收重写；
- 用户坚持（gate_override 作用域覆盖）时硬伤降为警告放行。
"""
import json
import threading
import time
from datetime import datetime, timezone

from loguru import logger
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src.video_agent.config import normalize_exec_pref, settings
from src.video_agent.core import prompt_gates
from src.video_agent.core.tracer import AgentTracer
from src.video_agent.utils.paths import DATA_DIR

# 遥测旁路落盘路径（与 agent_traces.jsonl 同层同口径，被 data/* 忽略不入库）
GATE_TRIGGER_COUNTS = DATA_DIR / "gate_trigger_counts.jsonl"
# 遥测 append 并发保护：单进程部署下锁即足；多进程部署需另议文件锁
_TRIGGER_COUNTS_LOCK = threading.Lock()


@dataclass
class GateVerdict:
    """一次闸机判定的结构化结果。"""

    rule_id: str
    layer: str  # platform | skill | session
    ok: bool
    message: str = ""

    def __post_init__(self) -> None:
        # 签发即归一：历史别名 rule_id 经此统一为注册表正式条目，
        # 下游 to_dict/audit_verdicts/trace 留痕全部同口径
        self.rule_id = prompt_gates.normalize_rule_id(self.rule_id)

    def to_dict(self) -> Dict[str, Any]:
        # rule_id 已归一；再经 normalize 一次仅为防御直改字段的外围写入
        rid = prompt_gates.normalize_rule_id(self.rule_id)
        meta = prompt_gates.GATE_RULES.get(rid)
        return {
            "rule_id": rid,
            "layer": self.layer,
            "description": meta.description if meta else "",
            "ok": self.ok,
            "message": self.message,
        }


@dataclass
class GateCheckOutcome:
    """提示词写入闸机的组合结果。

    ok=False 时 reject_message 必须回喂模型（拒收重写，自愈闭环）；
    warnings 随回复/时间线展示；verdicts 入审计。
    """

    ok: bool = True
    reject_message: str = ""
    hard_errors: List[str] = field(default_factory=list)  # 结构校验硬伤明细（日志/升级指引用）
    warnings: List[str] = field(default_factory=list)
    verdicts: List[GateVerdict] = field(default_factory=list)
    overridden: bool = False              # 用户坚持放行过任一闸


def _append_trigger_counts(
    verdicts: List[GateVerdict],
    skill_name: str = "",
    action: str = "",
    overridden: bool = False,
) -> None:
    """遥测旁路：每条判定 append 一行 JSON 到 GATE_TRIGGER_COUNTS。

    轻量只增不改判定；任何异常吞掉仅 logger.debug，绝不影响主链路。
    字段：ts（ISO UTC）/ rule_id（归一）/ ok（True=放行 False=拦截）/
    skill（在场才有值）/ layer / action / overridden。
    """
    try:
        GATE_TRIGGER_COUNTS.parent.mkdir(parents=True, exist_ok=True)
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with _TRIGGER_COUNTS_LOCK, open(GATE_TRIGGER_COUNTS, "a", encoding="utf-8") as f:
            for v in verdicts:
                rec = {
                    "ts": now,
                    "epoch": time.time(),
                    "rule_id": prompt_gates.normalize_rule_id(v.rule_id),
                    "ok": bool(v.ok),
                    "skill": str(skill_name or ""),
                    "layer": v.layer,
                    "action": str(action or ""),
                    "overridden": bool(overridden),
                }
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception as _e:
        logger.debug("[guard_pipeline] 遥测落盘忽略异常: {}", _e)


def audit_verdicts(
    verdicts: List[GateVerdict],
    skill_name: str = "",
    action: str = "",
    draft_id: str = "",
    overridden: bool = False,
) -> None:
    """把 verdict 列表写入审计（tracer.record_gate）；失败不阻断主链路。

    同步走遥测旁路 _append_trigger_counts 落盘触发计数：
    与 tracer 各自独立 try/except，一侧失败不影响另一侧。
    """
    _append_trigger_counts(verdicts, skill_name, action, overridden)
    try:
        tracer = AgentTracer.get_instance()
        for v in verdicts:
            tracer.record_gate(
                rule_id=prompt_gates.normalize_rule_id(v.rule_id),
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
    gate_override: Any = False,
    gate_enabled: bool = True,
    mode: Optional[str] = None,
) -> GateCheckOutcome:
    """提示词写入统一判定（决策 D + 结构条款组合；§2.0 唯一组合实现）。

    参数（两轨只注入，不各自组装判定）：
    - gate_override: 用户坚持作用域（False/"all"…）。

    返回 GateCheckOutcome；ok=False 时调用方必须拒绝写入并回喂 reject_message。
    （C1a 裁决 2026-08-31：技能级闸层删除，结构校验为平台固定地板，
    verdict 统一签发 platform.prompt_write。）
    """
    out = GateCheckOutcome()
    mode = mode or prompt_gates.gate_mode()
    if not gate_enabled or kind not in ("shot", "keyElement") or not str(prompt or "").strip():
        out.verdicts.append(GateVerdict("platform.prompt_write", "platform", True))
        return out
    if mode == "off":
        out.verdicts.append(GateVerdict("platform.prompt_write", "platform", True))
        return out

    # 结构闸：写入即校验（拒收重写，自愈闭环）
    ok, hard, _soft = prompt_gates.validate_prompt_write(
        str(prompt), kind, state,
    )
    if ok:
        out.verdicts.append(GateVerdict("platform.prompt_write", "platform", True))
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
            "platform.prompt_write", "platform", True,
            prompt_gates.format_gate_errors(hard),
        ))
        return out
    if mode != "strict":
        out.verdicts.append(GateVerdict("platform.prompt_write", "platform", True))
        return out
    out.ok = False
    out.hard_errors = list(hard)
    out.reject_message = prompt_gates.format_gate_errors(hard)
    out.verdicts.append(GateVerdict(
        "platform.prompt_write", "platform", False, out.reject_message,
    ))
    return out


def _exec_pref() -> str:
    """当前执行偏好（白名单口径，脏值回落默认档；枚举与清洗口归 config 单一事实源）。"""
    return normalize_exec_pref(settings.execution_preference)


def evaluate_gen_confirm(
    drafts: List[Dict[str, Any]],
    *,
    active: bool,
    override: Any = False,
    action: str = "",
) -> "tuple[Optional[str], List[str]]":
    """生成确认闸统一判定（platform.gen_confirm 唯一实现）。

    drafts：目标草稿（已含提示词者由调用方筛好）；active：Skill 激活且 strict；
    override：用户坚持作用域。返回 (硬拒原因, warnings)，双轨语义逐字节一致：
    - 执行偏好前置分支（2026-08-30 裁决）：generate_directly 恒放行，
      auto_decide 且活跃 Skill 指导在场放行（系统代发同意，均留痕）；
      默认档 confirm_before_gen 不命中，行为与现状逐字节一致；
    - override 命中 → 不拒，附豁免警告；
    - 未激活/空目标 → 不拒（空目标交工具自身报「未找到」）；
    - 全部已确认 → 不拒；
    - 存在未确认 → 硬拒（模型跳确认非用户意志），拒因用 BLOCKED 文案。
    判定经 tracer.record_gate 入审计（前端 chips 同源）。
    """
    warns: List[str] = []
    pref = _exec_pref()
    if pref == "generate_directly":
        w = "执行偏好「直接生成」：免确认直接生成（系统代发同意，留痕）"
        warns.append(w)
        audit_verdicts([GateVerdict("platform.gen_confirm", "platform", True, w)],
                       action=action, overridden=True)
        return None, warns
    if pref == "auto_decide" and active:
        w = "执行偏好「自动决定」：活跃 Skill 指导在场，本次生成免逐次确认（系统代发同意，留痕）"
        warns.append(w)
        audit_verdicts([GateVerdict("platform.gen_confirm", "platform", True, w)],
                       action=action, overridden=True)
        return None, warns
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


def evaluate_tool_risk(
    name: str,
    *,
    override: Any = False,
    costly: bool = False,
    skill_active: bool = False,
) -> "tuple[Optional[str], List[str]]":
    """工具风险分级确认闸（宪法 §2.7：high 必须平台闸机 + 用户确认）。

    适用范围 = 审批分级生效档 approval_tier=confirm 的工具（数据驱动：
    high→confirm、未注册→confirm，deny-by-default）；image_generate 批量轨
    由 gen_confirm 闸专属覆盖，不重复设闸（single 轨不在覆盖内，回本闸默认拦）。
    确认回携机制与 gen_confirm 同源（§2.4）：
    - 用户「本次放行」（gate_overrides 单次消费）= 一次性同意；
    - 无同意 → 硬拒（Context ≠ Consent，禁止静默放行），
      拒因回喂模型，由其暂停向用户发起确认邀请。
    执行偏好前置分支（2026-08-30 裁决，仅对花钱生成工具放宽）：
    costly=True 时 generate_directly 恒放行、auto_decide 且活跃 Skill 指导在场
    （skill_active）放行，均系统代发同意并留痕；未声明花钱（含未注册/
    非花钱高危）者不命中本分支，兜底拦截语义零改动。
    （C1a 裁决 2026-08-31：flow_directive 一条龙作为同意的 Context≠Consent
    执行机制删除——上下文/模型解读不再构成同意。）
    判定经 audit_verdicts 入审计（rule_id = platform.tool_risk）。
    返回 (硬拒原因, warnings)。
    """
    warns: List[str] = []
    if override in (True, "all") or prompt_gates.override_covers(override, "tool_risk"):
        w = f"用户坚持放行高风险工具确认闸（仅警告，单次生效留痕）：{name}"
        warns.append(w)
        audit_verdicts([GateVerdict("platform.tool_risk", "platform", True, w)],
                       action=name, overridden=True)
        return None, warns
    if costly:
        pref = _exec_pref()
        if pref == "generate_directly":
            w = f"执行偏好「直接生成」：花钱工具 {name} 免确认直接执行（系统代发同意，留痕）"
            warns.append(w)
            audit_verdicts([GateVerdict("platform.tool_risk", "platform", True, w)],
                           action=name, overridden=True)
            return None, warns
        if pref == "auto_decide" and skill_active:
            w = (f"执行偏好「自动决定」：活跃 Skill 指导在场，花钱工具 {name} "
                 "免逐次确认（系统代发同意，留痕）")
            warns.append(w)
            audit_verdicts([GateVerdict("platform.tool_risk", "platform", True, w)],
                           action=name, overridden=True)
            return None, warns
    msg = prompt_gates.TOOL_RISK_BLOCKED_MSG.replace("{{name}}", name)
    warns.append(msg)
    audit_verdicts([GateVerdict("platform.tool_risk", "platform", False, msg)],
                   action=name)
    return msg, warns


def prompt_write_verdict(
    prompt: str,
    kind: str,
    state: Dict[str, Any],
    *,
    user_override: bool = False,
    gate_enabled: bool = True,
    mode: Optional[str] = None,
) -> GateVerdict:
    """统一提示词写入判定（单 verdict 便捷出口；组合实现见 evaluate_prompt_write）。

    - ok=False：调用方必须拒绝写入并把 message 回喂模型（自愈闭环）；
    - ok=True 且 message 非空：写入放行，message 作为警告随结果展示；
    - user_override=True（决策 D：用户坚持）：硬伤降为警告照常放行。
    """
    out = evaluate_prompt_write(
        prompt, kind, state,
        gate_override="all" if user_override else False,
        gate_enabled=gate_enabled,
        mode=mode,
    )
    if not out.ok:
        return GateVerdict("platform.prompt_write", "platform", False, out.reject_message)
    # 放行：返回结构闸 verdict（用户坚持时携带降级警告文案，层归属平台）
    warn = out.warnings[0] if out.warnings else ""
    return GateVerdict("platform.prompt_write", "platform", True, warn)
