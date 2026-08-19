"""生成动作域（自 action_executor.py 切出，零行为变更）。

承载：文本轨 studio-actions 的生图/分镜视频生成动作——参数回退链
（LLM 指定 → 草稿自身 → 全局设置 → 平台默认）、生成确认闸接入、
参数回写草稿、任务提交。执行器以参数传入（ex），实例方法壳保留在
StudioActionExecutor（测试 patch 目标=执行器实例属性，不变）。
"""
import re
from typing import TYPE_CHECKING, Dict

from loguru import logger

from src.video_agent.config import settings
from src.video_agent.web.generation import collect_shot_video_refs, submit_video_task
from src.video_agent.web.provider_config import resolve_provider_ref, spec_media_preference

if TYPE_CHECKING:
    from src.video_agent.web.action_executor import StudioActionExecutor


def apply_generate_image(ex: "StudioActionExecutor", action: Dict) -> bool:
    """Agent 触发生图（仅当用户明确要求时）。支持批量。

    LLM 指定的供应商/模型/比例/分辨率会同步回写到目标草稿，
    使中间预览框底部的参数选择跳转到对应配置。
    """
    # 聊天框出图开关：关 = Agent 在对话中不主动触发生图
    if not settings.chat_image_enabled:
        ex._reject(
            "聊天框出图已在全局设置中关闭，如需生图请先在顶栏「全局设置」开启「聊天框出图」。"
        )
        return False
    target = str(action.get("target") or action.get("draft_id") or "all").strip()
    draft_type = str(action.get("draft_type") or "").strip().lower()
    # 供应商兼容显示名（LLM 常传界面上的名称如 Grsai）→ 内部 id
    provider_id = resolve_provider_ref(
        str(action.get("provider_id") or action.get("provider") or "")
    )
    model = action.get("model") or ""
    # LLM 显式指定的比例/分辨率（可选）：命中时回写草稿并优先使用
    act_ratio = str(action.get("aspect_ratio") or action.get("ratio") or "").strip()
    act_resolution = str(
        action.get("image_resolution") or action.get("resolution") or ""
    ).strip().upper()
    if act_resolution not in ("1K", "2K", "4K"):
        act_resolution = ""

    # 中间面板选中草稿的生图配置（provider/比例/分辨率回退链的最后一级）
    sel_provider, sel_ratio, sel_resolution = ex._selected_draft_media_config()

    # 根据 target 确定类型
    if target in ("all_keyelements", "all_keyElements"):
        draft_type = "keyelement"
        target = "all"
    elif target in ("all_shots", "all_shot"):
        draft_type = "shot"
        target = "all"

    pairs = ex._collect_drafts(target, draft_type)
    if not pairs:
        return False

    # 生成确认闸（混合形态硬边界）：未经用户确认的 Prompt Draft 不得生成
    pairs = ex._gen_confirm_gate(pairs)
    if not pairs:
        return False

    # 用户裁决：模型能力参数唯一权威源 = 全局设置；优先级 =
    # LLM 指定 > 草稿自身（用户在预览框的直接选择）> 全局设置 > 平台默认。
    # 防前端默认首选供应商（如 Grsai）覆盖全局设置中配置的生图渠道
    spec_pid, spec_model = ("", "")
    if not provider_id:
        spec_pid, spec_model = spec_media_preference(ex.state)

    submitted = 0
    for group, draft in pairs:
        prompt = (draft.get("prompt") or "").strip()
        if not prompt:
            continue
        refs = ex._resolve_scene_refs(group) if group else []
        # provider 回退链：LLM 指定 → 草稿自身（预览框已选）→ 全局设置 → 中间面板选中草稿 → 平台默认
        eff_provider = provider_id or (draft.get("imageProviderId") or draft.get("providerId") or "") or spec_pid or sel_provider or settings.default_image_provider_id
        # model 回退链：LLM 指定 → 草稿自身 → 全局设置（仅当供应商一致）→ 供应商默认模型（generation 层兜底）
        eff_model = model or (draft.get("imageModel") or draft.get("model") or "") or (spec_model if eff_provider == spec_pid else "") or (settings.default_image_model if eff_provider == settings.default_image_provider_id else "")
        # 比例回退链：LLM 指定 → 目标草稿自身 → 中间面板选中草稿 → 16:9
        eff_ratio = act_ratio or (draft.get("aspectRatio") or "") or sel_ratio or "16:9"
        # 分辨率回退链：LLM 指定 → 目标草稿自身 → 中间面板选中草稿 → 全局设置 → 1K
        eff_resolution = act_resolution or (draft.get("imageResolution") or "") or sel_resolution or settings.default_image_resolution or "1K"
        # 参数回写草稿：中间预览框底部参数选择跳转到对应供应商/模型/比例/分辨率
        draft["imageProviderId"] = eff_provider
        draft["providerId"] = eff_provider
        if eff_model:
            draft["imageModel"] = eff_model
            draft["model"] = eff_model
        draft["aspectRatio"] = eff_ratio
        draft["imageResolution"] = eff_resolution
        ex._submit_image_task(
            draft, eff_provider, eff_model, refs,
            aspect_ratio=eff_ratio, resolution=eff_resolution,
        )
        submitted += 1
    if submitted:
        logger.info(f"[StudioActions] generate_image: 已提交 {submitted} 个生图任务")
    return submitted > 0


def apply_generate_video(ex: "StudioActionExecutor", action: Dict) -> bool:
    """Agent 触发分镜视频生成（仅当用户明确要求时）。支持批量。

    参考素材自动挂接（对齐 Skill 步骤6）：
    - sceneRefs 引用的关键元素概念图 → 多参考图（MultiModalToVideo）；
    - 草稿 refAssets/audioUrl 中的音色参考音频 → reference_audio；
    - 提示词 @引用 → 位置标记重写 + 对应素材随请求发送。
    供应商/模型/分辨率回退链与生图一致（LLM 指定 → 草稿自身参数）。
    """
    target = str(action.get("target") or action.get("draft_id") or "all").strip()
    draft_type = str(action.get("draft_type") or "shot").strip().lower()
    provider_id = resolve_provider_ref(
        str(action.get("provider_id") or action.get("provider") or "")
    )
    model = action.get("model") or ""
    act_resolution = str(action.get("resolution") or "").strip().lower()
    try:
        act_duration = int(action.get("duration") or 0)
    except (TypeError, ValueError):
        act_duration = 0

    if target in ("all_shots", "all_shot"):
        draft_type = "shot"
        target = "all"

    pairs = ex._collect_drafts(target, draft_type)
    if not pairs:
        return False

    # 生成确认闸（混合形态硬边界）：未经用户确认的 Prompt Draft 不得生成
    pairs = ex._gen_confirm_gate(pairs)
    if not pairs:
        return False

    submitted = 0
    for group, draft in pairs:
        prompt = (draft.get("prompt") or "").strip()
        if not prompt:
            continue
        # 参数回退链：LLM 指定 → 目标草稿自身参数 → 全局设置默认
        eff_provider = provider_id or (draft.get("videoProviderId") or draft.get("providerId") or "") or settings.default_video_provider_id
        eff_model = model or (draft.get("videoModel") or draft.get("model") or "") or (settings.default_video_model if eff_provider == settings.default_video_provider_id else "")
        eff_ratio = (draft.get("videoAspectRatio") or draft.get("aspectRatio") or "16:9")
        eff_resolution = act_resolution or (draft.get("resolution") or "") or settings.default_video_resolution or "720p"
        dur_raw = str(draft.get("duration") or "").strip().lower()
        try:
            eff_duration = act_duration or int(re.sub(r"[^0-9]", "", dur_raw) or settings.max_shot_duration)
        except ValueError:
            eff_duration = settings.max_shot_duration
        eff_duration = max(1, min(eff_duration, 15))  # 模型单镜头上限 15s

        # 参数回写草稿：预览框参数区同步跳转
        if eff_provider:
            draft["videoProviderId"] = eff_provider
            draft["providerId"] = eff_provider
        if eff_model:
            draft["videoModel"] = eff_model
            draft["model"] = eff_model

        image_refs, audio_refs = collect_shot_video_refs(ex.state, group, draft)
        submit_video_task(
            ex.state, draft, "shot", eff_provider, eff_model,
            duration=eff_duration, resolution=eff_resolution, aspect_ratio=eff_ratio,
            image_refs=image_refs, audio_refs=audio_refs,
            source="agent", on_failure_save=ex.svc.save_debounced,
        )
        submitted += 1
    if submitted:
        logger.info(f"[StudioActions] generate_video: 已提交 {submitted} 个视频生成任务")
    return submitted > 0
