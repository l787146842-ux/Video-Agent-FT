"""草稿/分组动作域。

承载：草稿/分组的增删改动作（add_draft/add_group/update_draft/
update_group/delete_draft/delete_group/flow_directive）——分组定位
（显式 group_id → 跨类别按 id → label 模糊匹配 → 单分组兜底 → 多分组
拒绝盲捡）、内联草稿结构纯净闸剥离、提示词客观补印（@引用/镜头时长）、
规格补印（分辨率/供应商偏好）、时长同步。执行器以参数传入（ex），
实例方法壳保留在 StateOperationExecutor（测试 patch 目标不变）。

闸机判定（_gate_check/_record_presented 等）仍归执行器门面持有，
本模块经 ex.* 回调，与 action_gen.py 同一委托范式。
"""
import re
from typing import TYPE_CHECKING, Any, Dict, Optional

from loguru import logger

from src.video_agent.config import settings
from src.video_agent.core import prompt_gates
from src.video_agent.core import workflow_runtime
from src.video_agent.core.ports import provider_config_port
from src.video_agent.state.models import CAT_KEY_ELEMENTS, CAT_SHOTS, ALL_CATEGORIES
from src.video_agent.state import storyboard_ops as ops
from src.video_agent.utils import gen_id

if TYPE_CHECKING:
    from src.video_agent.core.action_executor import StateOperationExecutor


def apply_draft_patch(ex: "StateOperationExecutor", action: Dict) -> bool:
    draft_id = action.get("draft_id") or action.get("target_id") or action.get("id") or "current"
    draft_type = action.get("draft_type") or action.get("kind") or action.get("target_type") or ""
    patch = action.get("patch") or action.get("fields") or action.get("updates") or {}
    if action.get("prompt") and "prompt" not in patch:
        patch["prompt"] = action["prompt"]

    result = ex._find_draft(draft_id, draft_type)
    if not result:
        return False
    group, draft = result
    # 闸机：strict 模式拒绝结构不合格的提示词写入（不含提示词的其它字段 patch 不受影响）
    if "prompt" in patch:
        # 故事板待确认窗口（步骤3→步骤4 分界）：流程闸，只警告不拦人
        if ex.gate_enabled and prompt_gates.gate_mode() == "strict" \
                and prompt_gates.storyboard_pending(ex.state):
            logger.info("[FlowGate] 提示词写入时故事板待确认（警告，不拦人）")
            ex.gate_warnings.append(prompt_gates.STORYBOARD_PENDING_GATE_ERROR)
        # 客观补全：镜头时长可从 duration 算出来，
        # 写入前按 Skill 声明的规则自动补印，不指望模型自觉、也不重复拒绝重写
        if ex._kind_of_group(group) == "shot":
            filled_dur = prompt_gates.autofill_shot_duration(
                str(patch.get("prompt") or ""), "shot", group,
                rules=ex.gate_rules,
            )
            if filled_dur and filled_dur != patch.get("prompt"):
                patch["prompt"] = filled_dur
        if not ex._gate_check(
            str(patch.get("prompt") or ""), ex._kind_of_group(group), group=group,
        ):
            return False
    ok, dropped = ops.patch_draft(draft, patch)
    if dropped:
        # 文本轨容忍路径：白名单外字段丢弃并留痕（拒收口径归 FC 轨工具层）
        logger.warning(f"[StudioActions] update_draft 白名单外字段被丢弃: {dropped}")
    stamp_spec_resolution(ex, group, draft)
    if ok and str(patch.get("prompt") or "").strip():
        ex._record_presented(draft.get("id", ""))
    # 时长参数同步：写入分镜提示词时把分镜时长补印到草稿时长参数（客观兜底）
    if ok and ex._kind_of_group(group) == "shot":
        ex._sync_shot_duration(group, draft, patch)
    return ok


def stamp_spec_resolution(ex: "StateOperationExecutor", group: Dict[str, Any], draft: Dict[str, Any]) -> None:
    """分辨率补印（唯一权威源=全局设置）：草稿缺分辨率时按全局设置填充，
    参数栏与全局设置一致，防前端硬编码回填污染。"""
    if not isinstance(draft, dict):
        return
    try:
        params = provider_config_port().spec_production_params(ex.state) or {}
    except Exception:
        return
    cat = ops.category_for_group_type(ex._kind_of_group(group))
    cur_img = str(draft.get("imageResolution") or "").strip()
    if cat == CAT_KEY_ELEMENTS and (
        not cur_img or cur_img == settings.default_image_resolution
    ):
        v = str(params.get("image_resolution") or "").strip()
        if v:
            draft["imageResolution"] = v
    cur_vid = str(draft.get("resolution") or "").strip()
    if cat == CAT_SHOTS and (
        not cur_vid or cur_vid == settings.default_video_resolution
    ):
        v = str(params.get("video_resolution") or "").strip()
        if v:
            draft["resolution"] = v


def apply_group_patch(ex: "StateOperationExecutor", action: Dict) -> bool:
    group_id = action.get("group_id") or action.get("target_id") or action.get("id") or "current"
    group_type = action.get("group_type") or action.get("kind") or action.get("target_type") or ""
    patch = action.get("patch") or action.get("fields") or action.get("updates") or {}
    # 模型路径标题确定性归一（用户 REST 改名路径不受影响，用户意志优先）
    if isinstance(patch, dict) and str(patch.get("title") or "").strip():
        patch = dict(patch)
        patch["title"] = ops.normalize_group_title(str(patch["title"]))

    group = ex._find_group(group_id, group_type)
    if not group:
        return False
    ok, dropped = ops.patch_group(group, patch)
    if dropped:
        # 文本轨容忍路径：白名单外字段丢弃并留痕（拒收口径归 FC 轨工具层）
        logger.warning(f"[StudioActions] update_group 白名单外字段被丢弃: {dropped}")
    return ok


def apply_delete_draft(ex: "StateOperationExecutor", action: Dict) -> bool:
    draft_id = action.get("draft_id") or action.get("id") or ""
    draft_type = action.get("draft_type") or action.get("kind") or ""
    if not draft_id or draft_id == "current":
        draft_id = ex.selected_draft_id
    return ops.delete_draft(ex.state, draft_id, draft_type)


def apply_delete_group(ex: "StateOperationExecutor", action: Dict) -> bool:
    group_id = action.get("group_id") or action.get("id") or ""
    group_type = action.get("group_type") or action.get("kind") or ""
    return ops.delete_group(ex.state, group_id, group_type)


def apply_add_group(ex: "StateOperationExecutor", action: Dict) -> bool:
    """创建新的故事板分组（关键元素 / 分镜 / 音频）"""
    group_type = str(
        action.get("group_type") or action.get("draft_type")
        or action.get("kind") or action.get("target_type") or ""
    ).strip()
    # 客观依赖（分镜 sceneRefs 必须引用已存在元素）由 fc_tool_runner
    # _structure_integrity_gate 校验兜底
    return apply_add_group_inner(ex, action)


def apply_add_group_inner(ex: "StateOperationExecutor", action: Dict) -> bool:
    ok = add_group_core(ex, action)
    if ok:
        kind = prompt_gates.normalize_structure_kind(
            action.get("group_type") or action.get("draft_type")
            or action.get("kind") or action.get("target_type") or ""
        )
        if kind:
            ex.structure_kinds_created.add(kind)
    # 结构首次建立 → 故事板阶段完成才置待确认标记（暂停点归位 Skill 阶段边界）
    if ok and ex.gate_enabled and prompt_gates.gate_mode() == "strict":
        if prompt_gates.storyboard_stage_complete(ex.state, getattr(ex, "skill_name", "")):
            workflow_runtime.apply_interaction(
                ex.state, set_flags={"storyboard_pending": True})
    return ok


def add_group_core(ex: "StateOperationExecutor", action: Dict) -> bool:
    group_type = (
        action.get("group_type") or action.get("draft_type")
        or action.get("kind") or action.get("target_type") or ""
    ).lower().strip()

    # 映射到 state 中的 key（含中文别名，与 FC 轨同一映射）
    cat_key = ops.category_for_group_type(group_type)

    group_data = action.get("group") or action.get("data") or {}
    # 也允许 patch 字段携带 title/desc
    patch = action.get("patch") or {}
    # 标题兜底链：title → name → element_id → element_name → group_title
    title = (
        action.get("title") or group_data.get("title") or patch.get("title")
        or action.get("name") or group_data.get("name")
        or action.get("element_id") or action.get("element_name")
        or action.get("group_title") or "Agent 新建分组"
    )
    # 标题确定性归一（剥英文标识/编号前缀，双轨共用 ops）
    _raw_title = str(title)
    title = ops.normalize_group_title(_raw_title)
    if title != _raw_title:
        logger.info(f"[StudioActions] 分组标题归一：{_raw_title} -> {title}")
    desc = action.get("desc") or group_data.get("desc") or patch.get("desc") or ""

    new_id = group_data.get("id") or gen_id('shot' if cat_key == CAT_SHOTS else 'ke' if cat_key == CAT_KEY_ELEMENTS else 'audio')

    new_group: Dict[str, Any] = {
        "id": new_id,
        "title": title,
        "desc": desc,
        "drafts": [],
    }
    # 分镜特有字段（允许放在 action 顶层或 group 子对象里）
    def pick(field, default=""):
        return action.get(field) or group_data.get(field) or patch.get(field) or default

    if cat_key == CAT_SHOTS:
        rough = pick("roughDesc")
        if isinstance(rough, str) and len(rough) > 200:
            # 概述截断：超长 roughDesc 撑爆卡片/上下文
            rough = rough[:200] + "…"
        new_group["roughDesc"] = rough
        if not desc and rough:
            desc = rough  # 只写 roughDesc 不写 desc 时自动同步，前端卡片不显示空白
        new_group["desc"] = desc
        # 全局设置：分镜默认时长（Agent 自拆按 max_shot_duration 控制）
        new_group["duration"] = pick("duration", f"{settings.max_shot_duration}s")
        new_group["timeRange"] = pick("timeRange")
        new_group["shotType"] = pick("shotType")
        refs = action.get("sceneRefs") or group_data.get("sceneRefs") or []
        new_group["sceneRefs"] = refs if isinstance(refs, list) else [refs]
    badge = pick("badgeLabel")
    if cat_key != CAT_SHOTS:
        #角标归一（泛化「关键元素」/缺省 → 按 desc 锚点映射人物/场景/道具/声音特征）
        badge = ops.normalize_badge_label(badge, str(desc or ""), group_type=group_type)
    if badge:
        new_group["badgeLabel"] = badge

    ex.state.setdefault(cat_key, []).append(new_group)

    # 如果 action 中携带了 drafts 列表，一并添加
    inline_drafts = group_data.get("drafts") or action.get("drafts") or []
    for d in inline_drafts:
        if isinstance(d, dict):
            append_draft_to_group(ex, new_group, d)

    # 如果 action 中携带了单个 draft，也添加
    single_draft = action.get("draft")
    if single_draft and isinstance(single_draft, dict) and not inline_drafts:
        append_draft_to_group(ex, new_group, single_draft)

    return True


def append_draft_to_group(ex: "StateOperationExecutor", group: Dict, draft_data: Dict) -> Optional[Dict]:
    """向指定 group 添加一个 draft，返回新建的 draft；闸机拒绝其提示词时不添加（返回 None）。

    结构纯净闸（步骤3）：Skill 激活且 strict 时，内联草稿的详细提示词
    （> STRUCTURE_INLINE_PROMPT_MAX 字）被剥离后照常建卡，详细提示词留到步骤4。"""
    data = draft_data
    if ex.structure_phase and ex.gate_enabled and prompt_gates.gate_mode() == "strict":
        inline_prompt = str(data.get("prompt") or "").strip()
        if inline_prompt:
            data = {**data, "prompt": ""}
            ex.prompts_stripped += 1
            logger.info(
                f"[FlowGate] 剥离 add_draft 内联详细提示词（{len(inline_prompt)} 字，"
                "结构阶段只建骨架）"
            )
    if ex._kind_of_group(group) == "shot" and str(data.get("prompt") or "").strip():
        filled_dur = prompt_gates.autofill_shot_duration(
            str(data.get("prompt") or ""), "shot", group,
            rules=ex.gate_rules,
        )
        if filled_dur and filled_dur != data.get("prompt"):
            data = {**data, "prompt": filled_dur}
    if not ex._gate_check(str(data.get("prompt") or ""), ex._kind_of_group(group), group=group):
        return None
    draft = ops.append_draft(group, data)
    stamp_spec_resolution(ex, group, draft)
    # 全局设置补印：草稿未自带供应商时按全局设置填充（唯一权威源），
    # 防前端默认首选供应商回填污染（参数栏与全局设置不一致）
    cat = ops.category_for_group_type(ex._kind_of_group(group))
    if provider_config_port().stamp_draft_spec_preference(ex.state, draft, cat):
        logger.info(
            f"[StudioActions] 新建草稿按规格偏好补印供应商: "
            f"{draft.get('providerId')}/{draft.get('model') or ''}"
        )
    if str(data.get("prompt") or "").strip():
        ex._record_presented(draft.get("id", ""))
    return draft


def apply_flow_directive(ex: "StateOperationExecutor", action: Dict) -> bool:
    # 模型解读用户一条龙意图后发出；平台机械登记（本条消息生效）
    if bool(action.get("auto_continue")):
        inter = ex.state.setdefault("interaction", {})
        inter["auto_continue"] = True
        logger.info("[FlowDirective] 一条龙指令登记（本条消息生效）")
    return True


def apply_add_draft(ex: "StateOperationExecutor", action: Dict) -> bool:
    group_id = action.get("group_id") or action.get("groupId") or "current"
    group_type = (
        action.get("group_type") or action.get("groupType")
        or action.get("draft_type") or action.get("kind") or ""
    )
    draft_data = action.get("draft") or action.get("payload") or {}
    if not draft_data and action.get("patch"):
        # 模型把建卡字段放进 patch/fields 而非 draft 时
        # 不得静默落成空默认草稿，提示词必须写入
        draft_data = action.get("patch") or {}

    label = str(draft_data.get("label") or "").strip()
    group = None
    if str(group_id) in ("", "current") and label:
        # 未指定有效分组时按 label 名称智能匹配，
        # 优先于「current → 第一个分组」的旧兜底
        group = match_group_by_label(ex, label)
    # 显式 group_id 或前端已选中草稿时才走 find_group；
    # 「current + 无选中」会盲捡第一个分组，交给下方多分组防护
    if group is None and (
        str(group_id) not in ("", "current")
        or str(getattr(ex, "selected_draft_id", "") or "").strip()
    ):
        group = ex._find_group(group_id, group_type)
        if group is None and str(group_id) not in ("", "current"):
            # 显式 group_id 但未带 group_type：跨全类别按 id 定位
            # （别名归一化场景：type/groupId/payload 驼峰 schema）
            for cat_key in ALL_CATEGORIES:
                group = next(
                    (g for g in ex.state.get(cat_key, [])
                     if isinstance(g, dict) and g.get("id") == group_id),
                    None,
                )
                if group:
                    break
    if group is None and label:
        group = match_group_by_label(ex, label)
    if not group:
        all_groups = [
            g for cat_key in ALL_CATEGORIES
            for g in ex.state.get(cat_key, [])
            if isinstance(g, dict)
        ]
        if len(all_groups) > 1:
            # 未携带有效 group_id 且 label 无法定位时盲捡第一个分组，
            # 提示词全污染进程心组——多分组场景直接拒绝并回喂模型纠正
            ex.gate_rejections.append(
                "add_draft 未指定有效分组且 label 无法定位；"
                "当前存在多个分组，已拒绝盲捡，请携带正确的 group_id 或分组标题重试"
            )
            logger.warning("[StudioActions] add_draft 多分组盲捡被拒")
            return False
        if all_groups:
            group = all_groups[0]
    # 如果仍然找不到分组，自动创建一个
    if not group:
        auto_action = {**action, "group_type": group_type, "title": draft_data.get("label", "Agent 新建分组")}
        apply_add_group_inner(ex, auto_action)
        # 取刚创建的分组（与 apply_add_group 同一类别映射）
        cat_key = ops.category_for_group_type(group_type)
        groups = ex.state.get(cat_key, [])
        if groups:
            group = groups[-1]  # 刚添加的在末尾
        if not group:
            return False

    appended = append_draft_to_group(ex, group, draft_data)
    if appended is not None:
        kind = prompt_gates.normalize_structure_kind(group_type) or ex._kind_of_group(group)
        if kind:
            ex.structure_kinds_created.add(kind)
        if kind == "shot":
            ex._sync_shot_duration(group, appended)
    return appended is not None


def match_group_by_label(ex: "StateOperationExecutor", label: str) -> Optional[Dict[str, Any]]:
    """按草稿 label 名称模糊匹配目标分组（防 add_draft 未携带有效
    group_id 时盲捡第一个分组，导致提示词全进第一个分组）。

    取 label 第一段（按 - / — 切分，如「艾AA - 角色概念图」→「艾AA」），
    与分组标题（剥 [Element_X] 前缀后）双向包含匹配。
    """
    key = re.split(r"[-—–]", label or "")[0].strip()
    if not key or len(key) < 2:
        return None
    for cat_key in ALL_CATEGORIES:
        for g in ex.state.get(cat_key, []):
            title = str(g.get("title") or "")
            core = re.sub(r"\[[^\]]*\]", "", title).strip()
            if key in title or key in core or (core and core in key):
                return g
    return None
