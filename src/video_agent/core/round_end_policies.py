"""轮末策略状态机（清偿：agent_loop 轮末注入点收敛为单一路径）。

原 run_agent_loop 轮末段 10+ 个竞争 if 块（流程门禁暂停/失败警告/闸机自愈/
规格文档暂停/规格审阅卡/向导接管/规格收集/结构自检/结构卡/阶段兜底卡/虚报检测）
按书写顺序决定最终 confirmation——仲裁逻辑隐式且不可观测。本模块将其收敛为
声明式策略表：

- 策略按 priority 升序执行（初始表逐字节复制重构前代码顺序，零行为变更）；
- kind 语义：hard_break=命中即中止本轮；arbitrable=竞争暂停卡（按现行
  「先到先得 + not confirmation 守卫」语义顺序求值）；post_process=副作用块
  （警告/自愈/选项覆盖/审计），全部执行；
- 仲裁可观测（#4）：命中候选与胜出者经 tracer.record_card_decision 入 trace，
  /api/agent/traces 可见（对话区暂不渲染，决策点）。

归属层：层 9 系统兜底卡唯一代码落点（宪法 13.3）。FC 轨的 flow_gate_pause
仍由 agent_loop 在工具执行后早返处理（位置与重构前一致），共用本表 policy_id。
虚报检测（原 agent_loop 内联）随唯一消费点迁入本模块；agent_loop 保留
re-export 壳（13.7 惯例，测试 patch/导入路径不变）。
"""
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Dict, List, Optional

from loguru import logger

from src.video_agent.core import live_metrics, prompt_gates
from src.video_agent.core.sse_events import status_event
from src.video_agent.skill_runtime import registry as skill_registry
from src.video_agent.skill_runtime.guard import skill_requires_stage_pause
from src.video_agent.state.models import ALL_CATEGORIES_TUPLE, CAT_KEY_ELEMENTS, CAT_SHOTS

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

# fakestop：延续承诺措辞——正文声称要继续/正在做，却以 stop 收尾且零操作。
# 只覆盖任务流常见承诺句式，配合 applied==0 + skill 激活条件使用，防普通对话误触发。
_CONTINUATION_PROMISE_RE = re.compile(
    r"马上继续|继续推进|继续执行|现在(?:进行|执行|调用|写入|分析|拆解|开始)|"
    r"接下来(?:我|将|会)|即将开始|马上开始|立刻开始",
)


def _claims_structure_done(*texts: str) -> bool:
    """判定文本是否声称已完成故事板结构搭建（防虚报闸的文本检测）。

    - 每个文本段独立判定（正文结尾与暂停文案开头跨文本拼接不得误报）；
    - 含未来/预告措辞的段落不算声称（误伤措辞豁免）。
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
    # 输入态（agent_loop 填充）
    confirmation: str = ""
    confirmation_options: List[Dict[str, Any]] = field(default_factory=list)
    wants_continue: bool = False
    total_exec: int = 0
    applied: int = 0
    executable: List[Dict[str, Any]] = field(default_factory=list)
    gate_rejections: List[str] = field(default_factory=list)
    spec_wizard_pending: bool = False
    # 输出态（策略写入，agent_loop 回读）
    gate_heal: bool = False
    hard_break: bool = False
    hard_break_finish: str = ""
    result_warnings: List[str] = field(default_factory=list)
    result_text: str = ""
    # fakestop：轮末策略机械追加的建议动作（agent_loop 回读并入 result）
    suggested_actions: List[Dict[str, str]] = field(default_factory=list)
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
            # 策略条件求值失败入遥测（防闸机接线静默断裂）
            live_metrics.record_degradation(f"round_end.{policy.policy_id}")
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


# ---------- 各策略实现（优先级 = 重构前代码书写顺序， 裁决零行为变更） ----------

def _cond_partial_fail_warnings(ctx: RoundEndContext) -> bool:
    return bool(ctx.total_exec) and ctx.applied < ctx.total_exec


async def _apply_partial_fail_warnings(ctx: RoundEndContext, emit: Callable) -> None:
    if ctx.gate_rejections:
        ctx.result_warnings.append(
            f"第 {ctx.step} 轮有 {ctx.total_exec - ctx.applied} 个操作被流程闸机拦截"
            f"（原因：{ctx.gate_rejections[0][:60]}…）"
        )
    elif not ctx.gate_rejections:
        # 4-4 双轨退役：stream_consumed 分支已删（流式预执行不复存在）
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
    # 自愈：丢弃本轮暂停信号，拦截原因回喂模型修正后再暂停
    ctx.gate_heal = True
    blocked_n = ctx.total_exec - ctx.applied
    ctx.confirmation = ""
    ctx.confirmation_options = []
    ctx.wants_continue = True
    ctx.result_warnings.append(
        f"第 {ctx.step} 轮 {blocked_n} 个操作被流程闸机拦截，已回喂模型修正"
    )
    await emit(status_event(
        "agent.gateHeal",
        f"系统闸机拦截了本轮 {blocked_n} 个流程操作，正在要求模型按流程修正…",
        {"count": blocked_n},
    ))


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
    # 写完规格强制审阅，无视 continue
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


def _structure_kinds(ctx: RoundEndContext) -> set:
    return set(getattr(ctx.executor, "structure_kinds_created", None) or set())


def _cond_structure_stage_review(ctx: RoundEndContext) -> bool:
    # 暂停点归位 Skill 阶段边界（13.3/C6，用户裁决）：
    # 平台不再强制自检轮/首建硬暂停；故事板阶段完成且模型未暂停才注入审阅卡
    return (
        not ctx.confirmation
        and bool(_structure_kinds(ctx))
        and getattr(ctx.executor, "_storyboard_empty_before", False)
        and not prompt_gates.flow_auto_continue(ctx.executor.state)
        and getattr(ctx.executor, "gate_enabled", False)
        and prompt_gates.gate_mode() == "strict"
        and prompt_gates.storyboard_stage_complete(
            ctx.executor.state, getattr(ctx.executor, "skill_name", "") or "")
    )


async def _apply_structure_stage_review(ctx: RoundEndContext, emit: Callable) -> None:
    ctx.confirmation, ctx.confirmation_options = prompt_gates.structure_paused_confirmation(
        _structure_kinds(ctx)
    )
    logger.info(
        f"[FlowGate] 故事板阶段完成且模型未暂停，注入审阅卡（kinds={sorted(_structure_kinds(ctx))}）"
    )


def _cond_stage_done_fallback(ctx: RoundEndContext) -> bool:
    # + ：声明驱动 + 平台兜底双语义； 一条龙豁免引导卡
    if ctx.confirmation or ctx.gate_heal or ctx.applied <= 0:
        return False
    if prompt_gates.flow_auto_continue(ctx.executor.state):
        return False
    stage_pause_declared = False
    if ctx.skill:
        try:
            stage_pause_declared = skill_requires_stage_pause(ctx.skill)
        except Exception:
            live_metrics.record_degradation("round_end.stage_pause_declared")
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
    # 虚报检测与正文拼接收纳在同一块内（原 agent_loop 5-731 语义）；
    # 单轨化：文本动作块通道已退役，正文即模型可见文本，无需清洗
    return bool((ctx.content or "").strip())


async def _apply_false_claim_audit(ctx: RoundEndContext, emit: Callable) -> None:
    visible = (ctx.content or "").strip()
    if visible and not ctx.gate_heal:
        # 虚报警告（×）：声称完成结构搭建但故事板实际为空 → 只警告不拦人
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


def _cond_aborted_continuation_audit(ctx: RoundEndContext) -> bool:
    # fakestop：模型说「马上继续/现在进行…」却零操作、无暂停地收尾，
    # 用户会困惑「怎么停了」。确定性三问全中（状态可算、机器可判、无创作空间），收归系统。
    return (
        bool(ctx.skill)
        and ctx.applied == 0
        and not ctx.confirmation
        and not ctx.wants_continue
        and not ctx.gate_heal
        and not ctx.suggested_actions
        and bool(_CONTINUATION_PROMISE_RE.search(ctx.content or ""))
    )


async def _apply_aborted_continuation_audit(ctx: RoundEndContext, emit: Callable) -> None:
    ctx.suggested_actions.append({"kind": "continue", "label": "继续", "value": "继续"})
    logger.info("[RoundEnd] audit-0819-fakestop: 延续承诺措辞且零操作，机械追加继续按钮")


# ---------- 状态驱动的下一步建议（确定性交互收归系统，层 9） ----------

# 判定表语义：客观状态特征 → 唯一一条下一步建议（kind=next，点击机械发送 value）。
# 只读状态不写状态；生成类建议的点击本身构成「针对当前动作的显式用户指令」，
# 仍须过 platform.gen_confirm 闸（建议不绕过任何闸机）。
_SUGGEST_CONFIRMED_TAG = "已确认"


def _iter_storyboard_drafts(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    drafts: List[Dict[str, Any]] = []
    for cat_key in ALL_CATEGORIES_TUPLE:
        for group in state.get(cat_key, []) or []:
            if not isinstance(group, dict):
                continue
            for d in group.get("drafts", []) or []:
                if isinstance(d, dict):
                    drafts.append(d)
    return drafts


def suggest_next_actions(state: Dict[str, Any]) -> List[Dict[str, str]]:
    """按工作台客观状态返回下一步建议（空列表 = 不建议）。

      中性化：只报客观状态（未确认/停摆），不点名下一步流程
    （排序意见归 Skill）；确认类建议仅针对客观待确认对象。
    """
    try:
        drafts = _iter_storyboard_drafts(state or {})
    except Exception:
        return []
    # 中途停摆引导（闭环）——关键元素已拆但分镜未拆 → 中性继续引导
    if (state or {}).get(CAT_KEY_ELEMENTS) and not (state or {}).get(CAT_SHOTS):
        return [{"kind": "next", "label": "继续故事板设计",
                 "value": "请按当前 Skill 流程继续故事板设计阶段"}]
    if not drafts:
        return []
    confirmed = [d for d in drafts if str(d.get("tag") or "") == _SUGGEST_CONFIRMED_TAG]
    if len(confirmed) < len(drafts):
        return [{"kind": "next", "label": "确认故事板草稿",
                 "value": "请审阅并确认当前故事板草稿"}]
    has_prompt = [d for d in confirmed if str(d.get("prompt") or "").strip()]
    if len(has_prompt) < len(confirmed):
        return [{"kind": "next", "label": "推进下一阶段",
                 "value": "请按当前 Skill 流程推进下一阶段"}]
    generated = [
        d for d in confirmed
        if d.get("imgUrl") or d.get("videoUrl") or d.get("audioUrl")
    ]
    if len(generated) < len(confirmed):
        return [{"kind": "next", "label": "推进下一阶段",
                 "value": "请按当前 Skill 流程推进下一阶段"}]
    return []


# 策略表（优先级 = 重构前代码书写顺序；15 为失败警告块，原位于 flow_gate 早返之后）
ROUND_END_POLICIES: List[RoundEndPolicy] = [
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
    RoundEndPolicy("structure_stage_review", KIND_ARBITRABLE, 80,
                   _cond_structure_stage_review, _apply_structure_stage_review),
    RoundEndPolicy("stage_done_fallback", KIND_ARBITRABLE, 110,
                   _cond_stage_done_fallback, _apply_stage_done_fallback),
    RoundEndPolicy("false_claim_audit", KIND_POST_PROCESS, 120,
                   _cond_false_claim_audit, _apply_false_claim_audit),
    RoundEndPolicy("aborted_continuation_audit", KIND_POST_PROCESS, 130,
                   _cond_aborted_continuation_audit, _apply_aborted_continuation_audit),
]
