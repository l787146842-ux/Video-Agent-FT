"""轮末策略状态机（四轮 R1，F47 清偿：agent_loop 轮末注入点收敛为单一路径）。

原 run_agent_loop 轮末段 10+ 个竞争 if 块（流程门禁暂停/失败警告/闸机自愈/
规格文档暂停/规格审阅卡/向导接管/规格收集/结构自检/结构卡/阶段兜底卡/虚报检测）
按书写顺序决定最终 confirmation——仲裁逻辑隐式且不可观测。本模块将其收敛为
声明式策略表：

- 策略按 priority 升序执行（初始表逐字节复制重构前代码顺序，零行为变更）；
- kind 语义：hard_break=命中即中止本轮；arbitrable=竞争暂停卡（按现行
  「先到先得 + not confirmation 守卫」语义顺序求值）；post_process=副作用块
  （警告/自愈/选项覆盖/审计），全部执行；
- 仲裁可观测（#4）：命中候选与胜出者经 tracer.record_card_decision 入 trace，
  /api/agent/traces 可见（对话区暂不渲染，决策点 D5）。

归属层：层 9 系统兜底卡唯一代码落点（宪法 13.3）。FC 轨的 flow_gate_pause
仍由 agent_loop 在工具执行后早返处理（位置与重构前一致），共用本表 policy_id。
虚报检测（原 agent_loop 内联）随唯一消费点迁入本模块；agent_loop 保留
re-export 壳（13.7 惯例，测试 patch/导入路径不变）。
"""
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Dict, List, Optional

from loguru import logger

from src.video_agent.core import prompt_gates
from src.video_agent.core.sse_events import SSE_STATUS
from src.video_agent.skill_runtime import registry as skill_registry
from src.video_agent.skill_runtime.guard import skill_requires_stage_pause

if TYPE_CHECKING:
    from src.video_agent.core.tracer import AgentTracer

# 策略种类
KIND_HARD_BREAK = "hard_break"
KIND_ARBITRABLE = "arbitrable"
KIND_POST_PROCESS = "post_process"

# 执行器动作白名单（阶段完成兜底卡触发条件，原 agent_loop 内联常量）
_EXECUTOR_ACTIONS = (
    "script_analyze", "storyboard_key_elements", "storyboard_shots",
    "storyboard_audio", "write_media_prompt", "audio_generate", "video_assembler",
)

# ---------- 虚报检测（自 agent_loop 迁入：唯一消费点 = false_claim_audit） ----------

_STRUCTURE_CLAIM_RE = re.compile(
    r"(?:已完成|完成|已创建|已拆解|已写入)\s*(?:关键元素)?(?:拆解|拆分|分组|故事板)"
    r"|(?:关键元素)?(?:拆解|拆分)完成|已创建\s*\d+\s*个分组并写入故事板",
)
_FUTURE_MARKER_RE = re.compile(r"确认后|接下来|之后|即将|下一步|先确认|先将")


def _claims_structure_done(*texts: str) -> bool:
    """判定文本是否声称已完成故事板结构搭建（防虚报闸的文本检测）。

    - 每个文本段独立判定（2222 事故：正文结尾与暂停文案开头跨文本拼接不得误报）；
    - 含未来/预告措辞的段落不算声称（4444 误伤措辞豁免）。
    """
    for t in texts:
        text = str(t or "")
        if _FUTURE_MARKER_RE.search(text):
            continue
        if _STRUCTURE_CLAIM_RE.search(text):
            return True
    return False


@dataclass
class RoundEndContext:
    """轮末策略求值上下文：承载 step 循环末尾的全部可读状态与可写字段。

    可写字段由各策略修改，run_round_end_policies 结束后由 agent_loop 回读。
    """
    step: int = 0
    executor: Any = None
    content: str = ""
    skill: str = ""
    flow_gates: Any = None
    # 输入态（agent_loop 填充）
    confirmation: str = ""
    confirmation_options: List[Dict[str, Any]] = field(default_factory=list)
    wants_continue: bool = False
    total_exec: int = 0
    applied: int = 0
    stream_consumed: int = 0
    executable: List[Dict[str, Any]] = field(default_factory=list)
    gate_rejections: List[str] = field(default_factory=list)
    spec_wizard_pending: bool = False
    structure_self_check_pending: bool = False
    structure_self_check_round: int = 0
    # 输出态（策略写入，agent_loop 回读）
    gate_heal: bool = False
    hard_break: bool = False
    hard_break_finish: str = ""
    result_warnings: List[str] = field(default_factory=list)
    result_text: str = ""
    # 仲裁记录（#4：候选 + 胜出者）
    candidates: List[str] = field(default_factory=list)
    winner: str = ""


@dataclass
class RoundEndPolicy:
    """单条轮末策略：稳定 policy_id + 种类 + 优先级 + 条件 + 动作。

    apply 签名统一为 (ctx, emit)——gate_heal/flow_gate_pause 需发 SSE 状态，
    其余策略忽略 emit。
    """
    policy_id: str
    kind: str
    priority: int
    condition: Callable[[RoundEndContext], bool]
    apply: Callable[[RoundEndContext, Callable], Awaitable[None]]


async def run_round_end_policies(
    ctx: RoundEndContext,
    emit: Callable[[Dict[str, Any]], Awaitable[None]],
    tracer: Optional["AgentTracer"] = None,
    policies: Optional[List[RoundEndPolicy]] = None,
) -> RoundEndContext:
    """按优先级顺序执行策略表（语义 = 重构前书写顺序，零行为变更）。

    仲裁可观测：arbitrable 策略条件为真即入候选名单；最终 confirmation
    非空时记录胜出者（第一个真正写入 confirmation 的策略）。
    """
    table = policies if policies is not None else ROUND_END_POLICIES
    for policy in sorted(table, key=lambda p: p.priority):
        try:
            hit = policy.condition(ctx)
        except Exception as e:
            logger.warning(f"[RoundEnd] 策略 {policy.policy_id} 条件求值失败（跳过）: {e}")
            continue
        if not hit:
            continue
        if policy.kind == KIND_ARBITRABLE:
            ctx.candidates.append(policy.policy_id)
        before = bool(ctx.confirmation)
        await policy.apply(ctx, emit)
        if (
            policy.kind == KIND_ARBITRABLE
            and not ctx.winner
            and ctx.confirmation
            and not before
        ):
            ctx.winner = policy.policy_id
        if ctx.hard_break:
            break
    if tracer is not None and (ctx.candidates or ctx.winner):
        tracer.record_card_decision(ctx.step, ctx.candidates, ctx.winner)
    return ctx


# ---------- 各策略实现（优先级 = 重构前代码书写顺序，D1 裁决零行为变更） ----------

def _cond_flow_gate_pause(ctx: RoundEndContext) -> bool:
    return ctx.flow_gates is not None and bool(ctx.flow_gates.consume_blocked())


async def _apply_flow_gate_pause(ctx: RoundEndContext, emit: Callable) -> None:
    # 文本轨越阶拦截强制暂停（814R3 复活语义）
    ctx.confirmation = ctx.confirmation or ctx.flow_gates.pause_message()
    ctx.confirmation_options = []
    visible_txt = ctx.executor.strip_action_blocks(ctx.content)
    if visible_txt:
        ctx.result_text = (
            f"{ctx.result_text}\n\n{visible_txt}".strip() if ctx.result_text else visible_txt
        )
    await emit({"type": SSE_STATUS, "text": "越阶操作被流程门禁拦截，已强制暂停"})
    ctx.hard_break = True
    ctx.hard_break_finish = "gate_pause"


def _cond_partial_fail_warnings(ctx: RoundEndContext) -> bool:
    return bool(ctx.total_exec) and ctx.applied < ctx.total_exec


async def _apply_partial_fail_warnings(ctx: RoundEndContext, emit: Callable) -> None:
    if ctx.gate_rejections:
        ctx.result_warnings.append(
            f"第 {ctx.step} 轮有 {ctx.total_exec - ctx.applied} 个操作被流程闸机拦截"
            f"（原因：{ctx.gate_rejections[0][:60]}…）"
        )
    elif ctx.stream_consumed == 0:
        failed_desc = ""
        try:
            failed_desc = "；".join(
                ctx.executor._describe_action(a) for a in ctx.executable[ctx.applied:][:3]
            )
        except Exception:
            failed_desc = ""
        ctx.result_warnings.append(
            f"第 {ctx.step} 轮有 {ctx.total_exec - ctx.applied} 个操作未执行成功"
            + (f"（{failed_desc}）" if failed_desc else "（目标不存在或执行失败）")
        )


def _cond_gate_heal(ctx: RoundEndContext) -> bool:
    return bool(ctx.gate_rejections) and ctx.total_exec > 0 and ctx.applied < ctx.total_exec


async def _apply_gate_heal(ctx: RoundEndContext, emit: Callable) -> None:
    # 8888 事故自愈：丢弃本轮暂停信号，拦截原因回喂模型修正后再暂停
    ctx.gate_heal = True
    blocked_n = ctx.total_exec - ctx.applied
    ctx.confirmation = ""
    ctx.confirmation_options = []
    ctx.wants_continue = True
    ctx.result_warnings.append(
        f"第 {ctx.step} 轮 {blocked_n} 个操作被流程闸机拦截，已回喂模型修正"
    )
    await emit({
        "type": SSE_STATUS,
        "text": f"系统闸机拦截了本轮 {blocked_n} 个流程操作，正在要求模型按流程修正…",
    })


def _doc_written_names(ctx: RoundEndContext) -> List[str]:
    return [
        str(a.get("name") or a.get("key") or "")
        for a in ctx.executable
        if str(a.get("action") or a.get("tool") or "").lower()
        in ("write_document", "write_doc", "save_document", "document_write")
    ]


def _cond_spec_doc_written_pause(ctx: RoundEndContext) -> bool:
    names = _doc_written_names(ctx)
    if not names or ctx.confirmation:
        return False
    try:
        wizard = bool(skill_registry.spec_wizard_active(ctx.skill))
    except Exception:
        wizard = False
    return wizard and any(prompt_gates.is_spec_doc_name(n) for n in names)


async def _apply_spec_doc_written_pause(ctx: RoundEndContext, emit: Callable) -> None:
    # 9999 事故：写完规格强制审阅，无视 continue
    ctx.confirmation, ctx.confirmation_options = prompt_gates.spec_pause_card(ctx.executor.state)
    interaction = ctx.executor.state.setdefault("interaction", {})
    interaction["pending_pause_kind"] = "spec"
    logger.info("[FlowGate] 规格文档已写入，强制暂停审阅")


def _cond_spec_review_pending(ctx: RoundEndContext) -> bool:
    interaction = ctx.executor.state.setdefault("interaction", {})
    return bool(interaction.get("spec_review_pending")) and not ctx.confirmation


async def _apply_spec_review_pending(ctx: RoundEndContext, emit: Callable) -> None:
    interaction = ctx.executor.state.setdefault("interaction", {})
    interaction.pop("spec_review_pending", None)
    ctx.confirmation, ctx.confirmation_options = prompt_gates.spec_pause_card(ctx.executor.state)
    logger.info("[FlowGate] 系统拼装规格待审阅，注入审阅卡")


def _cond_spec_wizard_takeover(ctx: RoundEndContext) -> bool:
    return ctx.spec_wizard_pending and not ctx.confirmation


async def _apply_spec_wizard_takeover(ctx: RoundEndContext, emit: Callable) -> None:
    ctx.confirmation, ctx.confirmation_options = prompt_gates.spec_pause_card(ctx.executor.state)
    interaction = ctx.executor.state.setdefault("interaction", {})
    interaction["pending_pause_kind"] = "spec"
    logger.info("[FlowGate] 规格向导激活，模型手写规格已忽略，转系统规格向导暂停卡")


def _cond_spec_collect(ctx: RoundEndContext) -> bool:
    return (
        "script_analyze" in getattr(ctx.executor, "skill_stages_done", set())
        and not prompt_gates.has_spec_document(ctx.executor.state)
        and not any(
            prompt_gates.is_spec_doc_name(n)
            for n in getattr(ctx.executor, "documents_written", []) or []
        )
        and not ctx.confirmation
    )


async def _apply_spec_collect(ctx: RoundEndContext, emit: Callable) -> None:
    # 1111/6666 事故层9兜底；scope=all 豁免只附警告
    if getattr(ctx.executor, "gate_override", False) in ("all", True):
        ctx.result_warnings.append("用户已要求全速推进，已豁免规格收集暂停（仅附警告）")
        return
    ctx.confirmation, ctx.confirmation_options = prompt_gates.spec_collect_card(ctx.executor.state)
    interaction = ctx.executor.state.setdefault("interaction", {})
    interaction["pending_pause_kind"] = "collect"
    logger.info("[FlowGate] script_analyze 完成且无规格文档，注入规格收集向导")


def _structure_kinds(ctx: RoundEndContext) -> set:
    return set(getattr(ctx.executor, "structure_kinds_created", None) or set())


def _cond_structure_self_check(ctx: RoundEndContext) -> bool:
    return (
        not ctx.confirmation
        and bool(_structure_kinds(ctx))
        and not ctx.structure_self_check_pending
        and getattr(ctx.executor, "gate_enabled", False)
        and prompt_gates.gate_mode() == "strict"
    )


async def _apply_structure_self_check(ctx: RoundEndContext, emit: Callable) -> None:
    # 8888 事故：结构首建强制自检轮（不弹卡）
    ctx.structure_self_check_pending = True
    ctx.structure_self_check_round = ctx.step
    logger.info(f"[FlowGate] 结构首建，强制自检轮（kinds={sorted(_structure_kinds(ctx))}）")


def _cond_structure_self_check_fallback(ctx: RoundEndContext) -> bool:
    return (
        not ctx.confirmation
        and ctx.structure_self_check_pending
        and ctx.step > ctx.structure_self_check_round
        and getattr(ctx.executor, "gate_enabled", False)
        and prompt_gates.gate_mode() == "strict"
    )


async def _apply_structure_self_check_fallback(ctx: RoundEndContext, emit: Callable) -> None:
    ctx.confirmation, ctx.confirmation_options = prompt_gates.structure_paused_confirmation(
        _structure_kinds(ctx)
    )
    ctx.structure_self_check_pending = False
    logger.info(
        f"[FlowGate] 自检轮后仍未暂停，注入结构审阅卡（kinds={sorted(_structure_kinds(ctx))}）"
    )


def _cond_structure_card_override(ctx: RoundEndContext) -> bool:
    # 8888 二轮：模型自发暂停时文案保留、选项换成系统阶段卡
    return (
        bool(ctx.confirmation)
        and bool(_structure_kinds(ctx))
        and getattr(ctx.executor, "gate_enabled", False)
        and prompt_gates.gate_mode() == "strict"
    )


async def _apply_structure_card_override(ctx: RoundEndContext, emit: Callable) -> None:
    _sys_msg, ctx.confirmation_options = prompt_gates.structure_paused_confirmation(
        _structure_kinds(ctx)
    )


def _cond_stage_done_fallback(ctx: RoundEndContext) -> bool:
    # 5555 事故 + B4/F29：声明驱动 + 平台兜底双语义
    if ctx.confirmation or ctx.gate_heal or ctx.applied <= 0:
        return False
    stage_pause_declared = False
    if ctx.skill:
        try:
            stage_pause_declared = skill_requires_stage_pause(ctx.skill)
        except Exception:
            stage_pause_declared = False
    names = [str(a.get("action") or a.get("tool") or "").strip() for a in ctx.executable]
    return (
        stage_pause_declared
        or any(n in ("storyboard_key_elements", "storyboard_shots", "storyboard_audio") for n in names)
    ) and any(n in _EXECUTOR_ACTIONS for n in names)


async def _apply_stage_done_fallback(ctx: RoundEndContext, emit: Callable) -> None:
    ctx.confirmation = "阶段执行完成，请审阅左侧故事板结果"
    ctx.confirmation_options = [
        {"label": "继续下一步", "description": "确认当前阶段产出，推进到下一阶段"},
        {"label": "我要调整", "description": "告诉我需要增删改的内容"},
    ]
    logger.info("[FlowGate] 阶段执行完成且模型未暂停，注入下一步引导卡")


def _cond_false_claim_audit(ctx: RoundEndContext) -> bool:
    # 虚报检测与正文拼接收纳在同一块内（原 agent_loop L715-731 语义）
    return bool(ctx.executor.strip_action_blocks(ctx.content))


async def _apply_false_claim_audit(ctx: RoundEndContext, emit: Callable) -> None:
    visible = ctx.executor.strip_action_blocks(ctx.content)
    if visible and not ctx.gate_heal:
        # 虚报警告（7777 × 4444）：声称完成结构搭建但故事板实际为空 → 只警告不拦人
        if (
            ctx.confirmation
            and _claims_structure_done(visible)
            and prompt_gates.storyboard_is_empty(ctx.executor.state)
        ):
            ctx.result_warnings.append(
                "检测到虚报：正文声称已完成结构搭建，但故事板实际仍为空；"
                "已按用户确认语义保留当前暂停（系统不没收模型暂停）。"
            )
        ctx.result_text = (
            f"{ctx.result_text}\n\n{visible}".strip() if ctx.result_text else visible
        )


# 策略表（优先级 = 重构前代码书写顺序；15 为失败警告块，原位于 flow_gate 早返之后）
ROUND_END_POLICIES: List[RoundEndPolicy] = [
    RoundEndPolicy("flow_gate_pause", KIND_HARD_BREAK, 10,
                   _cond_flow_gate_pause, _apply_flow_gate_pause),
    RoundEndPolicy("partial_fail_warnings", KIND_POST_PROCESS, 15,
                   _cond_partial_fail_warnings, _apply_partial_fail_warnings),
    RoundEndPolicy("gate_heal", KIND_POST_PROCESS, 30,
                   _cond_gate_heal, _apply_gate_heal),
    RoundEndPolicy("spec_doc_written_pause", KIND_ARBITRABLE, 40,
                   _cond_spec_doc_written_pause, _apply_spec_doc_written_pause),
    RoundEndPolicy("spec_review_pending", KIND_ARBITRABLE, 50,
                   _cond_spec_review_pending, _apply_spec_review_pending),
    RoundEndPolicy("spec_wizard_takeover", KIND_ARBITRABLE, 60,
                   _cond_spec_wizard_takeover, _apply_spec_wizard_takeover),
    RoundEndPolicy("spec_collect", KIND_ARBITRABLE, 70,
                   _cond_spec_collect, _apply_spec_collect),
    RoundEndPolicy("structure_self_check", KIND_POST_PROCESS, 80,
                   _cond_structure_self_check, _apply_structure_self_check),
    RoundEndPolicy("structure_self_check_fallback", KIND_ARBITRABLE, 90,
                   _cond_structure_self_check_fallback, _apply_structure_self_check_fallback),
    RoundEndPolicy("structure_card_override", KIND_POST_PROCESS, 100,
                   _cond_structure_card_override, _apply_structure_card_override),
    RoundEndPolicy("stage_done_fallback", KIND_ARBITRABLE, 110,
                   _cond_stage_done_fallback, _apply_stage_done_fallback),
    RoundEndPolicy("false_claim_audit", KIND_POST_PROCESS, 120,
                   _cond_false_claim_audit, _apply_false_claim_audit),
]
