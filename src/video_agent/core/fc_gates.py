# -*- coding: utf-8 -*-
"""FC 闸机裁决段（任务#23 D1：fc_tool_runner 巨石三段拆分 1/3）。

三段结构：闸机裁决（本模块）→ 执行（fc_tool_runner）→ 批末对账（fc_reconcile）。

承载 FC 轨闸机链全链：轮内暂停纪律 → 阶段前置 → 规格前置（flow）→
工具风险（§2.7）→ 生成确认 → 建组结构完整性 → 提示词结构。
判定实现唯一归属 guard_pipeline（宪法 §2.0 单一组合实现）；
本模块只做 FC 轨参数组装与链式组合，不各自写判定。
web 层引用（生成日志面板）经 GateContext.record_gen_log 注入，
保住分层（core 不顶层依赖 web）。

FCToolRunner 对本模块每个闸函数保留同名承重壳方法（壳清单登记于
fc_tool_runner.py 尾部注释，13.7 惯例），既有调用/测试 patch 路径不变。
"""
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from loguru import logger

from src.video_agent.config import settings
from src.video_agent.core import guard_pipeline, pipeline_orchestrator, prompt_gates
# 分级注入阈值（read_skill 短路判定与 prompt_builder 同口径，任务#36 B5）
from src.video_agent.core.prompt_builder import GENERIC_FULL_INJECT_LIMIT
from src.video_agent.skill_runtime.registry import resolve_entry, skill_flow_enabled
from src.video_agent.state import storyboard_ops as ops
# MCP 命名空间判定（任务#37 B4：外部工具同管线过 risk 闸，不旁路）
from src.video_agent.tools.mcp.policy import is_mcp_tool
from src.video_agent.state.models import (
    ALL_CATEGORIES_TUPLE,
    CAT_KEY_ELEMENTS,
    CAT_SHOTS,
)

# §2.7 风险分级：high 级且无既有确认原语覆盖的工具名单，执行前须用户一次性确认
# （platform.tool_risk 闸）。生成类 high（image_generate）由 gen_confirm 闸覆盖。
# MCP 外部工具（mcp__* 命名空间）不在此名单内也强制过闸（任务#37 B4：
# 外部副作用不可信，high 级一律经 guard_pipeline 确认闸，判定不旁路）。
TOOL_RISK_CONFIRM_TOOLS = frozenset({
    "canvas_add_node", "canvas_update_node", "canvas_delete_node",
    "canvas_batch_add_nodes", "document_write",
})
# 轮内暂停纪律豁免集：workflow_pause 请求确认后，同批仅读类工具与暂停工具本身可行
PAUSE_WINDOW_READONLY = frozenset({
    "read_draft", "read_skill", "read_project_doc", "read_uploaded_doc",
    "workflow_pause",
})

# 分组类型边界（任务#36 护栏移植③，原 exec_common._apply_actions 的
# only_group_type 下沉）：阶段 → 允许建组类别。与阶段前置闸分工：
# 前置闸管「阶段没到不许来」，本闸管「来了只许干本阶段的事」。
STAGE_ALLOWED_GROUP_KINDS: Dict[str, Tuple[str, ...]] = {
    "structure": ("keyElement", "shot", "audio"),  # 结构阶段三类皆可建
    "ke_media": ("keyElement",),  # 元素图阶段只许补建关键元素
    "shot_media": ("shot",),      # 分镜视频阶段只许补建分镜
    "audio_assets": ("audio",),   # 音频阶段只许补建音频分组
}


@dataclass
class GateContext:
    """闸机链运行上下文（FCToolRunner 每批组装一次，各闸函数统一读取）。

    state/tool_risk_of/record_gen_log 为注入的可调用对象：闸机裁决段
    不持有 runner 实例、不顶层引用 web 层（core→web 依赖经注入解耦）。
    warnings/gate_repeat 直接绑定 runner 的列表/字典对象，写入即时可见。
    """

    injected_skill: str = ""
    gate_override: Any = False
    gate_rules: Optional[Dict[str, Any]] = None
    selected_draft_id: str = ""
    selected_type: str = ""
    warnings: List[str] = field(default_factory=list)
    gate_repeat: Dict[str, int] = field(default_factory=dict)
    # 对话内单图工具每批调用次数（prose 禁令下沉工具层，13.6 审计）
    gen_image_calls: int = 0
    state: Callable[[], Dict[str, Any]] = lambda: {}
    tool_risk_of: Callable[[str], str] = lambda name: "high"
    record_gen_log: Callable[[str, List[str]], None] = (
        lambda prompt, hard: None)


def resolve_current_refs(ctx: GateContext, name: str, args: Dict[str, Any]) -> None:
    """把 FC 工具参数里的 "current"/空 引用解析为真实 id（对齐文本轨语义）：
    前端选中草稿优先，未选中时回落第一个可用对象（与 ops.find_draft 兜底一致）。
    必须在闸机与工具调用之前执行，否则闸机/回写会命中错误的卡片。"""
    if name in ("storyboard_patch_draft", "storyboard_confirm_draft"):
        if str(args.get("draft_id") or "").strip() in ("", "current"):
            found = ops.find_draft(
                ctx.state(), "current", str(args.get("draft_type") or ""),
                selected_draft_id=ctx.selected_draft_id,
                selected_type=ctx.selected_type,
            )
            if found:
                args["draft_id"] = found[1].get("id") or ""
    elif name == "storyboard_add_draft":
        if str(args.get("group_id") or "").strip() in ("", "current"):
            group = ops.find_group(
                ctx.state(), "current", str(args.get("group_type") or ""),
                selected_draft_id=ctx.selected_draft_id,
                selected_type=ctx.selected_type,
            )
            if group:
                args["group_id"] = group.get("id") or ""
    elif name == "storyboard_media_to_chat":
        if str(args.get("target") or "").strip() == "current":
            found = ops.find_draft(
                ctx.state(), "current", "",
                selected_draft_id=ctx.selected_draft_id,
                selected_type=ctx.selected_type,
            )
            if found and found[1].get("id"):
                ids = list(args.get("draft_ids") or [])
                if found[1]["id"] not in ids:
                    ids.append(found[1]["id"])
                args["draft_ids"] = ids
                args["target"] = ""


def skill_full_text_injected(skill_name: str) -> bool:
    """选中 Skill 的全文是否真的直注入 system prompt（read_skill 短路前提）。

    判定与 prompt_builder.build_selected_skill_block 同构（任务#36 B5 通用主路径）：
    - legacy：全文直注；
    - 通用主路径：全文 ≤ min(GENERIC_FULL_INJECT_LIMIT, max_doc_chars) → 直注；
      超长分级注入（只注 planner 章节+章节目录）→ 未全量注入，续读必须真读。
      直注分支内 prompt_builder 仍按 max_doc_chars 硬截断，故短路阈值与其
      单一来源对齐：max_doc_chars 低于分级阈值时，超出部分并未注入。
    内容长度不可探测时保守返回 False（不短路，不失续读能力）。
    """
    mode = str(getattr(settings, "skill_runtime", "auto") or "auto").strip().lower()
    if mode == "legacy":
        return True
    try:
        entry = resolve_entry(skill_name)
    except Exception:
        entry = None
    content = str((entry.content if entry is not None else "") or "").strip()
    if not content:
        return False
    limit = min(GENERIC_FULL_INJECT_LIMIT,
                int(getattr(settings, "max_doc_chars", GENERIC_FULL_INJECT_LIMIT)))
    return len(content) <= limit


def strip_structure_prompt(ctx: GateContext, name: str, args: Dict[str, Any]) -> bool:
    """结构纯净闸（步骤3）：Skill 激活且 strict 时，create_group/add_draft 携带的
    内联草稿带提示词时，剥离 prompt 字段
    后放行建结构（不丢分组、不造成虚报），详细提示词留到用户确认后的步骤4。
    返回 True = 发生了剥离（回喂时附说明）。"""
    if not ctx.injected_skill or prompt_gates.gate_mode() != "strict":
        return False
    if name not in ("storyboard_create_group", "storyboard_add_draft"):
        return False
    draft = args.get("draft")
    if not isinstance(draft, dict):
        return False
    prompt = str(draft.get("prompt") or "").strip()
    if not prompt:
        return False
    draft["prompt"] = ""
    logger.info(f"[FlowGate] 剥离 {name} 内联详细提示词（{len(prompt)} 字，结构阶段只建骨架）")
    return True


def pause_window_error(name: str, paused_this_batch: bool) -> Optional[str]:
    """轮内暂停纪律闸：workflow_pause 后同批续执行拒收（暂停点必须真停，
    读只读工具与暂停工具本身豁免）——轮内暂停纪律否决权（执行路径内嵌，ADR-0004）。"""
    if paused_this_batch and name not in PAUSE_WINDOW_READONLY:
        return (
            "本轮已用 workflow_pause 请求用户确认，请等待用户回应后再继续执行；"
            "暂停窗口内仅允许读类工具（read_*）。"
        )
    return None


def stage_precondition_gate(ctx: GateContext, name: str) -> Optional[str]:
    """阶段前置闸（platform.stage_precondition）：
    工具归属阶段的前置阶段未完成 → 拒收（机械强制，不依赖控制流入口）。
    仅 strict 模式启用；用户坚持（gate_override）可一次性豁免并留痕。"""
    if not ctx.injected_skill or prompt_gates.gate_mode() != "strict":
        return None
    try:
        err = pipeline_orchestrator.evaluate_stage_precondition(
            name, ctx.state(), ctx.injected_skill)
    except Exception:
        return None  # 判定异常不阻断对话（闸机失败-open 惯例，审计可查）
    if err is None:
        return None
    if ctx.gate_override in (True, "all"):
        ctx.warnings.append(f"用户坚持放行：{err}")
        guard_pipeline.audit_verdicts(
            [guard_pipeline.GateVerdict(
                "platform.stage_precondition", "platform", True,
                message=f"用户坚持豁免：{err}")],
            skill_name=ctx.injected_skill, action=name, overridden=True,
        )
        return None
    guard_pipeline.audit_verdicts(
        [guard_pipeline.GateVerdict(
            "platform.stage_precondition", "platform", False, message=err)],
        skill_name=ctx.injected_skill, action=name,
    )
    return err


def flow_gate(ctx: GateContext, name: str) -> Optional[str]:
    """规格前置（与文本轨对齐）：只对显式声明 flow.spec_gate 的 Skill
    生效，且不硬拦——规格未写入时追加一条可视线索到操作时间线，
    模型后续自行决定补写（用户指令优先）。返回恒 None（不再硬拒绝）。"""
    if not ctx.injected_skill or prompt_gates.gate_mode() != "strict":
        return None
    if name not in ("storyboard_create_group", "storyboard_add_draft"):
        return None
    if prompt_gates.has_spec_document(ctx.state()):
        return None
    declared = False
    try:
        declared = skill_flow_enabled(ctx.injected_skill, "spec_gate")
    except Exception:
        declared = False
    if not declared:
        return None
    # 执行侧强制已接管（ensure_spec_gate 拦截越阶工具调用），
    # 此处不再向用户追加 ⚠ 警告（只记日志，模型侧由拦截回喂知晓）
    logger.info(f"[FlowGate] {name}：规格文档未写入（Skill 声明 spec_gate，执行侧门禁生效）")
    return None


def tool_risk_gate(ctx: GateContext, name: str) -> Optional[str]:
    """高风险工具确认闸（platform.tool_risk，宪法 §2.7）：判定唯一实现 =
    guard_pipeline.evaluate_tool_risk。仅对 high 且无既有确认原语覆盖的
    工具生效；确认回携 = flow_directive 一条龙同意 / 用户「本次放行」，
    无同意硬拒（禁止静默放行），拦截/豁免 verdict 入审计。
    适用范围 = TOOL_RISK_CONFIRM_TOOLS 名单 + 全部 MCP 外部工具
    （任务#37 B4：外部工具统一风控，risk 闸不得旁路）。"""
    if name not in TOOL_RISK_CONFIRM_TOOLS and not is_mcp_tool(name):
        return None
    if ctx.tool_risk_of(name) != "high":
        return None
    err, warns = guard_pipeline.evaluate_tool_risk(
        name,
        override=ctx.gate_override,
        flow_consent=prompt_gates.flow_auto_continue(ctx.state()),
    )
    for w in warns:
        if w not in ctx.warnings:
            ctx.warnings.append(w)
    if err:
        logger.info(f"[ToolRiskGate] 拦截 {name}：high 级操作未经用户确认")
    return err


def gen_confirm_gate(ctx: GateContext, name: str, args: Dict[str, Any]) -> Optional[str]:
    """生成确认闸（FC 轨， 双轨收敛一期）：判定唯一实现 =
    guard_pipeline.evaluate_gen_confirm（与文本轨逐字节一致）。"""
    if name != "image_generate":
        return None
    # 一条龙：用户本条消息的显式指令作为本批生成同意（留痕），不弹确认闸
    if prompt_gates.flow_auto_continue(ctx.state()):
        logger.info("[FlowDirective] 一条龙指令作为本批生成同意（留痕）")
        return None
    state = ctx.state()
    target = str(args.get("target") or "all_keyElements").strip()
    targets: List[Dict[str, Any]] = []
    if target in ("all_keyElements", "all_keyelements"):
        for g in state.get(CAT_KEY_ELEMENTS, []):
            for d in g.get("drafts", []):
                if (d.get("prompt") or "").strip():
                    targets.append(d)
    elif target in ("all_shots", "all_shot"):
        for g in state.get(CAT_SHOTS, []):
            for d in g.get("drafts", []):
                if (d.get("prompt") or "").strip():
                    targets.append(d)
    else:
        for cat in ALL_CATEGORIES_TUPLE:
            for g in state.get(cat, []):
                for d in g.get("drafts", []):
                    if d.get("id") == target and (d.get("prompt") or "").strip():
                        targets.append(d)
    if not targets:
        return None  # 无目标：交给工具自身报「未找到有提示词的草稿」
    err, warns = guard_pipeline.evaluate_gen_confirm(
        targets,
        active=bool(ctx.injected_skill) and prompt_gates.gate_mode() == "strict",
        override=ctx.gate_override,
        action=name,
    )
    for w in warns:
        if w not in ctx.warnings:
            ctx.warnings.append(w)
    if err:
        logger.info(f"[GenGate] 拦截 image_generate：{len(targets)} 个目标草稿存在未确认 Prompt Draft")
    return err


def structure_integrity_gate(
    ctx: GateContext, name: str, args: Dict[str, Any],
) -> Optional[str]:
    """建组结构完整性闸（任务#36 护栏移植，原 exec_common._apply_actions
    三条机械校验的通用工具级下沉，逐条同语义）：
    ① 无标题 add_group 拒收（防整批分组全落默认标题）；
    ② 分镜 sceneRefs 完整度（非空且覆盖标题提及的关键元素）；
    ③ 分组类型边界（only_group_type 按当前阶段推导）。
    仅 strict 模式启用；返回非 None = 硬拒绝（错误文案回喂模型重写）。"""
    if name != "storyboard_create_group":
        return None
    if not ctx.injected_skill or prompt_gates.gate_mode() != "strict":
        return None
    title = str(args.get("title") or "").strip()
    kind = prompt_gates.normalize_structure_kind(
        str(args.get("group_type") or ""))
    # ① 无标题拒收：宁缺毋滥（原  无标题 add_group 拒收同语义）
    if not title:
        return (
            "storyboard_create_group 被拒收：未携带非空 title。"
            "分组标题是后续去重/引用的唯一锚点，请携带明确标题后重试。"
        )
    # ③ 分组类型边界：当前阶段只允许对应类别（越界 = 阶段串线）
    try:
        cur = pipeline_orchestrator.current_stage(
            ctx.state(), ctx.injected_skill)
    except Exception:
        cur = None
    if cur is not None:
        allowed = STAGE_ALLOWED_GROUP_KINDS.get(cur.key)
        if allowed is not None and kind and kind not in allowed:
            wanted = "、".join(allowed)
            return (
                f"storyboard_create_group 被拒收：当前处于「{cur.title}」阶段，"
                f"只允许建 {wanted} 类分组，本次请求的 {kind} 属越界分组，"
                "请先完成当前阶段再执行对应阶段的建组。"
            )
    # ② 分镜 sceneRefs 完整度：非空且覆盖标题提及的关键元素
    # （标题点名的角色漏引 = 跨镜一致性断链；refs 兼容 id/标题两种写法，
    # 与 prompt_gates.shot_refs_missing_element 同口径）
    if kind == "shot":
        refs = [str(r) for r in (args.get("scene_refs") or [])
                if str(r).strip()]
        ke_map = [
            (str(k.get("title") or "").strip(), str(k.get("id") or ""))
            for k in (ctx.state().get(CAT_KEY_ELEMENTS) or [])
            if isinstance(k, dict)
        ]
        missing = [
            t for t, kid in ke_map
            if t and t in title
            and kid not in refs and t not in refs
        ]
        if not refs or missing:
            detail = (
                "sceneRefs 为空" if not refs
                else f"标题提及的 {'、'.join(missing[:3])} 未被引用"
            )
            return (
                f"storyboard_create_group 被拒收：分镜「{title[:12]}」{detail}。"
                "sceneRefs 须非空并覆盖标题提及的角色/场景（关键元素 id 或标题），"
                "请补全引用后重试。"
            )
    return None


def prompt_gate(ctx: GateContext, name: str, args: Dict[str, Any]) -> Optional[str]:
    """写入前闸机：Skill 流程激活时校验待写入的提示词结构。
    返回非 None = strict 模式硬拒绝（工具不执行，错误文案带回给模型重写）。
    判定唯一实现 = guard_pipeline.evaluate_prompt_write（宪法 §2.0）。"""
    if not ctx.injected_skill or prompt_gates.gate_mode() == "off":
        return None
    prompt, kind = "", ""
    if name == "storyboard_patch_draft":
        patch = args.get("patch") if isinstance(args.get("patch"), dict) else {}
        prompt = str(patch.get("prompt") or "").strip()
        kind = str(args.get("draft_type") or "").strip()
        if prompt and kind not in ("shot", "keyElement", "audio"):
            kind = prompt_gates.resolve_kind_by_draft_id(
                ctx.state(), str(args.get("draft_id") or ""),
                str(args.get("draft_type") or ""),
                ctx.selected_draft_id, ctx.selected_type,
            )
    elif name in ("storyboard_create_group", "storyboard_add_draft"):
        draft = args.get("draft")
        prompt = str(draft.get("prompt") or "").strip() if isinstance(draft, dict) else ""
        gt = str(args.get("group_type") or "").strip().lower()
        kind = {"keyelement": "keyElement", "shot": "shot", "audio": "audio"}.get(gt, "")
    else:
        return None
    # 客观补全（888）：@引用与镜头时长可从 sceneRefs/duration 算出来，
    # 写入前按 Skill 声明的规则自动补印回待写入参数，不指望模型自觉
    if kind == "shot" and prompt:
        group: Optional[Dict[str, Any]] = None
        if name == "storyboard_patch_draft":
            found = ops.find_draft(
                ctx.state(), str(args.get("draft_id") or ""),
                str(args.get("draft_type") or ""),
                selected_draft_id=ctx.selected_draft_id,
                selected_type=ctx.selected_type,
            )
            if found:
                group = found[0]
        else:
            group = {
                "id": str(args.get("group_id") or ""),
                "title": str(args.get("title") or ""),
                "sceneRefs": args.get("sceneRefs") or [],
                "duration": str(args.get("duration") or ""),
            }
        if group is not None:
            target = patch if name == "storyboard_patch_draft" else draft
            if isinstance(target, dict):
                filled_refs = prompt_gates.autofill_at_refs(
                    prompt, "shot", group, ctx.state(), rules=ctx.gate_rules,
                )
                if filled_refs != prompt:
                    target["prompt"] = filled_refs
                    prompt = filled_refs
                filled_dur = prompt_gates.autofill_shot_duration(
                    prompt, "shot", group, rules=ctx.gate_rules,
                )
                if filled_dur and filled_dur != prompt:
                    target["prompt"] = filled_dur
                    prompt = filled_dur
    if not prompt or kind not in ("shot", "keyElement"):
        return None
    # 故事板待确认窗口（步骤3→步骤4 分界）：流程闸，只警告不拦人
    if prompt_gates.gate_mode() == "strict" \
            and prompt_gates.storyboard_pending(ctx.state()):
        ctx.warnings.append(prompt_gates.STORYBOARD_PENDING_GATE_ERROR)
        logger.info("[FlowGate] 提示词写入时故事板待确认（警告，不拦人）")
    # 统一闸机管线（宪法 §2.0 单一组合实现； 恢复接线，与文本轨同源判定）
    outcome = guard_pipeline.evaluate_prompt_write(
        prompt, kind, ctx.state(),
        gate_rules=ctx.gate_rules,
        gate_override=ctx.gate_override,
        element_image_missing=prompt_gates.element_images_missing(ctx.state()),
    )
    ctx.warnings.extend(outcome.warnings)
    guard_pipeline.audit_verdicts(
        outcome.verdicts, skill_name=ctx.injected_skill, action=name,
        overridden=outcome.overridden,
    )
    if outcome.ok:
        return None
    hard = outcome.hard_errors
    logger.info(f"[PromptGate] 拦截不合格提示词写入（{kind}）: {hard}")
    # 错误日志入账：闸机拦截写入生成日志（顶栏日志面板可见，恢复错误日志可见性）
    ctx.record_gen_log(prompt, hard)
    # 闸机校准：连续相同拦截升级指引，防模型陷入「拦截-重写-再拦截」空转
    sig = f"{kind}|{'|'.join(sorted(hard))}"
    n = ctx.gate_repeat.get(sig, 0) + 1
    ctx.gate_repeat[sig] = n
    text = outcome.reject_message
    if n > 1:
        text += (
            f"\n[连续第 {n} 次因相同原因被拦截] 上一次重写未修正上述问题，"
            "请逐条对照原因彻底改写（不是换措辞：中文占比/字数/镜头语言标记必须实质达标），禁止再次提交相似文本。"
        )
    return text


@dataclass
class GateChainResult:
    """闸机链组合结果：error 非 None = 本工具拒收（错误文案回喂模型）；
    prompt_gate_blocked = 本次被提示词闸拦截的写入数（批末防虚报对账用）。"""

    error: Optional[str] = None
    prompt_gate_blocked: int = 0


def run_gate_chain(
    ctx: GateContext, name: str, args: Dict[str, Any],
    *, paused_this_batch: bool,
) -> GateChainResult:
    """闸机链组合（顺序敏感，勿调换）：轮内暂停纪律 → 阶段前置（平台不变量）
    → 规格前置 → 工具风险 → 生成确认 → 建组结构完整性 → 提示词结构
    → 生图配额。任一闸拒收即短路，后续闸不再判。"""
    res = GateChainResult()
    err = pause_window_error(name, paused_this_batch)
    if err is None:
        err = stage_precondition_gate(ctx, name)
    if err is None:
        err = flow_gate(ctx, name)
    if err is None:
        err = tool_risk_gate(ctx, name)
    if err is None:
        err = gen_confirm_gate(ctx, name, args)
        if err is None:
            err = structure_integrity_gate(ctx, name, args)
        if err is None:
            pg_err = prompt_gate(ctx, name, args)
            if pg_err:
                res.prompt_gate_blocked = 1
                err = pg_err
    # 对话内单图工具每批最多一次（prose 下沉工具层，13.6 审计）。
    # 需要多张时模型改用 image_generate 批量工具（两者分工互斥，见 system_fc.md）
    if err is None and name == "generate_image":
        ctx.gen_image_calls += 1
        if ctx.gen_image_calls > 1:
            err = (
                "generate_image 每轮只调用一次；"
                "需要多张图片时改用 image_generate 批量工具（明确 target 范围）。"
            )
    res.error = err
    return res
