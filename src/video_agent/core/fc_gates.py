# -*- coding: utf-8 -*-
"""FC 闸机裁决段。

三段结构：闸机裁决（本模块）→ 执行（fc_tool_runner）→ 批末对账（fc_reconcile）。

承载 FC 轨闸机链全链：轮内暂停纪律 → 工具风险（§2.7）→
生成确认 → 建组结构完整性 → 提示词结构。
（C1b 裁决 2026-08-31：阶段前置闸退役；规格前置 flow_gate 随 C1a 退役。）
判定实现唯一归属 guard_pipeline（宪法 §2.0 单一组合实现）；
本模块只做 FC 轨参数组装与链式组合，不各自写判定。
web 层引用（生成日志面板）经 GateContext.record_gen_log 注入，
保住分层（core 不顶层依赖 web）。
"""
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from loguru import logger

from src.video_agent.config import settings
from src.video_agent.core import guard_pipeline, stage_probes, prompt_gates
from src.video_agent.skill_runtime.registry import resolve_entry
from src.video_agent.state import storyboard_ops as ops
# MCP 命名空间判定：外部工具同管线过 risk 闸（生效风险档由 server 配置解析，
# 控制面 = deny 名单 + server risk_default + 遥测，政策单一源见 tools/mcp/policy.py）
from src.video_agent.tools.mcp.policy import is_mcp_tool
# 审批生效档唯一推导源（F1 双轴并单轴：由 risk 单轴推导——
# high→confirm、其余 none，未注册一律 confirm（deny-by-default，§2.7））
from src.video_agent.tools.manager import ToolManager
from src.video_agent.state.models import (
    ALL_CATEGORIES_TUPLE,
    CAT_KEY_ELEMENTS,
    CAT_SHOTS,
)
from src.video_agent.utils.prompts import load_prompt_section, render_prompt_section

# 闸机裁决宣告文案外置 prompts/gates/messages.md（单一事实源，
# 分节登记 gate_registry.GATE_MESSAGE_SECTIONS）；代码不内联逐字兜底，
# 分节缺失时仅 logger.warning + 最小功能性占位（M-2 同口径）。
_GATE_MSG_FILE = "gates/messages.md"

# §2.7 确认闸豁免集：被 gen_confirm 闸专属覆盖的工具（不双闸）。
# 仅覆盖 image_generate 批量轨（有目标草稿可校验）；mode='single'
# 无目标草稿、不在 gen_confirm 覆盖内，回本闸默认拦（高危默认拦）。
# 豁免为「有条件」：仅当覆盖它的 gen_confirm 闸当前确实会生效（active）时
# 才豁免——否则不豁免、继续走本闸正常 risk 判定（high→confirm），
# 杜绝「豁免无条件、覆盖有条件」的不对称导致的模型自主花钱零确认空档。
# 生效范围不用硬编码名单，改读生效审批档（risk 单轴推导，未注册→confirm）。
CONFIRM_PRIMITIVE_COVERED_TOOLS = frozenset({"image_generate"})
# 轮内暂停纪律豁免集：workflow_pause 请求确认后，同批仅读类工具与暂停工具本身可行
PAUSE_WINDOW_READONLY = frozenset({
    "read_draft", "read_skill", "read_project_doc", "read_uploaded_doc",
    "read_state_group", "workflow_pause",
})

# 分组类型边界：阶段 → 允许建组类别。与阶段前置闸分工：
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
    selected_draft_id: str = ""
    selected_type: str = ""
    warnings: List[str] = field(default_factory=list)
    gate_repeat: Dict[str, int] = field(default_factory=dict)
    # 对话内单图工具每批调用次数（prose 禁令下沉工具层）
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


def unknown_tool_error(name: str, has_tool: Optional[Callable[[str], bool]] = None) -> Optional[str]:
    """未注册工具结构化拒因（v4-2 解析层归位，话术唯一事实源）：
    MCP 命名空间或按谓词判定已注册返回 None；未注册名返回纯事实 +
    机械指引，禁原因推断（v4 话术原则）。解析层（fc_tool_runner
    ._prepare_call）传 runner 实际装配的工具管理器判存，在闸机链之前
    先行拒收；tool_risk_gate 尾部同名分支不传谓词（默认全局注册表）
    保留为最后防线（fail-closed 不变）。"""
    if is_mcp_tool(name):
        return None
    _has = has_tool or ToolManager.has_tool
    if _has(name):
        return None
    return f"工具 '{name}' 不存在。请核对可用工具清单后重试。"


def pause_window_error(name: str, paused_this_batch: bool) -> Optional[str]:
    """轮内暂停纪律闸：workflow_pause 后同批续执行拒收（暂停点必须真停，
    读只读工具与暂停工具本身豁免）——轮内暂停纪律否决权（执行路径内嵌）。"""
    if paused_this_batch and name not in PAUSE_WINDOW_READONLY:
        return (
            "本轮已用 workflow_pause 请求用户确认，请等待用户回应后再继续执行；"
            "暂停窗口内仅允许读类工具（read_*）。"
        )
    return None


def tool_risk_gate(
    ctx: GateContext, name: str, args: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """高风险工具确认闸（platform.tool_risk，宪法 §2.7）：判定唯一实现 =
    guard_pipeline.evaluate_tool_risk。生效条件数据驱动 = 生效审批档 == "confirm"
    （F1 双轴并单轴：risk 单轴推导，确认只挂高危；未注册→confirm，
    实际效果=other_high 拦截回喂，无确认卡，
    deny-by-default）；保留 risk==high 双保险（防未来推导口径变更误弹卡）。
    确认回携 = 用户「本次放行」，
    无同意硬拒（禁止静默放行），拦截/豁免 verdict 入审计。
    豁免（有条件）：image_generate 批量轨仅当覆盖它的 gen_confirm 闸确实会
    生效（active = injected_skill 非空 且 gate_mode()==strict）时才豁免（不双闸）；
    覆盖闸未激活时不豁免，回本闸正常 risk 判定（high→confirm），
    杜绝「豁免无条件、覆盖有条件」不对称导致的零确认空档。
    mode='single' 无目标草稿、不在覆盖内，回本闸默认拦。
    执行偏好三档（批 B）：花钱生成工具（costly 声明轴）可经偏好前置分支
    放行（判定归 evaluate_tool_risk，本闸只注入参数）。
    MCP 外部工具（mcp__* 命名空间）同管线过本闸，其生效风险档由 server
    配置（tool_risk/risk_default）解析而来；控制面 = deny 名单 + server 级
    risk_default + 审计遥测（用户裁决：模型可自助启用、不逐次同意），本闸
    不对未解析为 high 者强制入闸（server 配 risk_default:low 即整批放行属
    有意政策，非旁路缺陷）。花钱/不可逆底线（costly 工具地板 high，server
    配置只能上抬不能下降）见 policy.resolve_tool_risk。"""
    if name in CONFIRM_PRIMITIVE_COVERED_TOOLS:
        mode = str((args or {}).get("mode") or "batch").strip().lower()
        if mode != "single":
            # 有条件豁免：与 gen_confirm_gate 的 active 判定同源同口径
            #（injected_skill 非空 且 gate_mode()==strict）。仅当覆盖闸会
            # 真正生效时才让位；否则不豁免，继续走下方正常 risk 判定。
            gen_confirm_active = (
                bool(ctx.injected_skill)
                and prompt_gates.gate_mode() == "strict"
            )
            if gen_confirm_active:
                return None
    if ToolManager.get_tool_approval_tier(name) != "confirm" \
            and not is_mcp_tool(name):
        return None
    if ctx.tool_risk_of(name) != "high":
        return None
    # 同意账本 + 章程扩展（批 12）：暂停卡 accept 的同意范围由
    # guard_pipeline.CONSENT_CHARTER 声明 = costly 生成 ∪ 规格文档写入
    # （is_spec_doc_name 命中 = 规格确认暂停卡的兑现落账，1000 事故清偿）；
    # 文档名口径与 fc_tool_runner doc_name 一致（name → key 兜底）。
    # 其余 high（非规格写入/未注册）不吃同意，兜底拦截语义 fail-closed。
    _doc_name = str((args or {}).get("name") or (args or {}).get("key") or "").strip()
    err, warns = guard_pipeline.evaluate_tool_risk(
        name,
        override=ctx.gate_override,
        # 执行偏好分流只放宽花钱生成声明轴（数据驱动，不硬编码工具名单）
        costly=ToolManager.is_costly_tool(name),
        spec_write=(
            name in ("document_write", "write_document")
            and prompt_gates.is_spec_doc_name(_doc_name)
        ),
        skill_active=bool(ctx.injected_skill)
        and prompt_gates.gate_mode() == "strict",
        # 批 9 同意账本：暂停卡 accept 登记的当前工作轮内同意（V6 计划）
        consented=prompt_gates.generation_consented(ctx.state()),
    )
    for w in warns:
        if w not in ctx.warnings:
            ctx.warnings.append(w)
    if err:
        logger.info(f"[ToolRiskGate] 拦截 {name}：high 级操作未经用户确认")
        # 拒因如实分流（指令收拢批补丁，2026-09-09 实证：模型拼错
        # storybook_create_group 被话术误导成「要走确认/放行」）：拦截
        # 行为与 deny 范围逐字节不变，仅当被拦工具未注册时把话术换成
        # 「工具不存在」——纯事实 + 机械指引，不走确认通道。
        # （v4-2：解析层已在闸机链之前先行拒收未注册名，本分支
        # 保留为最后防线，fail-closed 不变。）
        err = unknown_tool_error(name) or err
    return err


def gen_confirm_gate(ctx: GateContext, name: str, args: Dict[str, Any]) -> Optional[str]:
    """生成确认闸（FC 轨）：判定唯一实现 =
    guard_pipeline.evaluate_gen_confirm（与文本轨逐字节一致）。
    仅覆盖 image_generate 批量轨；mode='single' 单张应急轨无目标草稿，
    不参与草稿确认校验（其花钱确认由 tool_risk 闸默认拦，高危默认拦）。"""
    if name != "image_generate" or str(args.get("mode") or "batch").strip().lower() == "single":
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
        # 批 9 同意账本：暂停卡 accept 登记的当前工作轮内生成同意（V6 计划）
        consented=prompt_gates.generation_consented(state),
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
    """建组结构完整性闸（三条机械校验的通用工具级下沉，逐条同语义）：
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
    # ① 无标题拒收：宁缺毋滥
    if not title:
        return (
            "storyboard_create_group 被拒收：未携带非空 title。"
            "分组标题是后续去重/引用的唯一锚点，请携带明确标题后重试。"
        )
    # ③ 分组类型边界：当前阶段只允许对应类别（越界 = 阶段串线）
    try:
        cur = stage_probes.current_stage(
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
    if not prompt or kind not in ("shot", "keyElement"):
        return None
    # 统一闸机管线（宪法 §2.0 单一组合实现；与文本轨同源判定）
    outcome = guard_pipeline.evaluate_prompt_write(
        prompt, kind, ctx.state(),
        gate_override=ctx.gate_override,
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
    # 错误日志入账：闸机拦截写入生成日志（顶栏日志面板可见）
    ctx.record_gen_log(prompt, hard)
    # 闸机校准：连续相同拦截升级指引，防模型陷入「拦截-重写-再拦截」空转
    sig = f"{kind}|{'|'.join(sorted(hard))}"
    n = ctx.gate_repeat.get(sig, 0) + 1
    ctx.gate_repeat[sig] = n
    text = outcome.reject_message
    if n > 1:
        escalation = render_prompt_section(
            _GATE_MSG_FILE, "PROMPT_REPEAT_ESCALATION", n=n)
        if not escalation:
            logger.warning(
                f"[fc_gates] prompts/{_GATE_MSG_FILE}::PROMPT_REPEAT_ESCALATION "
                "分节缺失，使用最小占位")
            escalation = f"[连续第 {n} 次因相同原因被拦截]"
        text += "\n" + escalation
    return text


@dataclass
class GateChainResult:
    """闸机链组合结果：error 非 None = 本工具拒收（错误文案回喂模型）。"""

    error: Optional[str] = None


def run_gate_chain(
    ctx: GateContext, name: str, args: Dict[str, Any],
    *, paused_this_batch: bool,
) -> GateChainResult:
    """闸机链组合（顺序敏感，勿调换）：轮内暂停纪律 → 工具风险 →
    生成确认 → 建组结构完整性 → 提示词结构 → 生图配额。
    任一闸拒收即短路，后续闸不再判。（C1b 裁决 2026-08-31：阶段前置闸退役。）"""
    res = GateChainResult()
    err = pause_window_error(name, paused_this_batch)
    if err is None:
        err = tool_risk_gate(ctx, name, args)
    if err is None:
        err = gen_confirm_gate(ctx, name, args)
        if err is None:
            err = structure_integrity_gate(ctx, name, args)
        if err is None:
            pg_err = prompt_gate(ctx, name, args)
            if pg_err:
                err = pg_err
    # 单张应急轨（mode='single'）每批最多一次（prose 下沉工具层）。
    # 需要多张时模型改用批量轨（mode='batch'，见 protocol.md）
    if (
        err is None and name == "image_generate"
        and str(args.get("mode") or "batch").strip().lower() == "single"
    ):
        ctx.gen_image_calls += 1
        if ctx.gen_image_calls > 1:
            err = load_prompt_section(_GATE_MSG_FILE, "SINGLE_IMAGE_QUOTA_BLOCKED")
            if not err:
                logger.warning(
                    f"[fc_gates] prompts/{_GATE_MSG_FILE}::SINGLE_IMAGE_QUOTA_BLOCKED "
                    "分节缺失，使用最小占位")
                err = "image_generate（mode='single'）每轮只调用一次。"
    res.error = err
    return res
