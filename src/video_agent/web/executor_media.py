"""StudioActionExecutor 的媒体插入与生成触发块（M7：从 action_executor.py 拆出）。

以 mixin 形式混入 StudioActionExecutor，依赖宿主属性：
state / svc / chat_inserts / selected_draft_id / selected_type /
_find_draft / _gen_confirm_gate。
行为与原实现逐行一致，仅搬家不改逻辑。
"""
import re
from typing import Dict, List

from loguru import logger

from src.video_agent.config import settings
from src.video_agent.state import storyboard_ops as ops
from src.video_agent.web.generation import (
    collect_shot_video_refs,
    submit_image_task,
    submit_video_task,
)
from src.video_agent.web.provider_config import (
    resolve_provider_ref,
    spec_media_preference,
    spec_production_params,
)
from src.video_agent.web.prompt_refs import media_of_draft


class StudioActionMediaMixin:
    """故事板媒体 → 对话输入框 + 生图/生视频触发（仅用户明确触发）。"""

    # ---------- 故事板媒体 → 对话输入框（纯前端信号，不改状态） ----------

    def _apply_insert_chat_media(self, action: Dict) -> bool:
        """把故事板草稿卡片的媒体（图片/视频/音频）插入前端对话输入框。

        支持三种定位方式：
        - draft_ids: 明确的草稿 ID 数组（优先）
        - target: "current" / "all" / "all_keyElements" / "all_shots" / "all_audio"
        - media_type: image/video/audio 过滤（可选）
        单次最多 settings.max_chat_inserts 个，防止一次灌满输入框。
        """
        media_type = str(action.get("media_type") or action.get("kind") or "").lower().strip()
        if media_type not in ("", "image", "video", "audio"):
            media_type = ""
        limit = int(action.get("limit") or settings.max_chat_inserts)
        limit = min(limit, settings.max_chat_inserts)

        pairs: List[tuple] = []
        draft_ids = action.get("draft_ids") or action.get("ids") or []
        if isinstance(draft_ids, str):
            draft_ids = [draft_ids]
        if draft_ids:
            for did in draft_ids:
                found = self._find_draft(str(did), "")
                if found:
                    pairs.append(found)
        else:
            target = str(action.get("target") or "current").strip()
            if target == "current":
                found = self._find_draft("current", "")
                if found:
                    pairs.append(found)
            elif target in ("all", "all_keyelements", "all_keyElements", "all_shots", "all_shot", "all_audio"):
                t = target.lower()
                if t.startswith("all_key"):
                    draft_type = "keyelement"
                elif t.startswith("all_shot"):
                    draft_type = "shot"
                elif t.startswith("all_audio"):
                    draft_type = "audio"
                else:
                    draft_type = ""
                pairs = self._collect_drafts("all", draft_type)

        added = 0
        existing_urls = {it.get("url") for it in self.chat_inserts}
        for group, draft in pairs:
            if added >= limit:
                break
            url, kind = media_of_draft(draft)
            if not url or url in existing_urls:
                continue
            if media_type and kind != media_type:
                continue
            name = draft.get("label") or group.get("title") or draft.get("id", "")
            self.chat_inserts.append({
                "kind": kind,
                "url": url,
                "name": name,
                # 视频用首帧/已有概念图作缩略图，前端无需额外拉取
                "thumb": draft.get("imgUrl") or "" if kind == "video" else "",
            })
            existing_urls.add(url)
            added += 1

        if added:
            logger.info(f"[StudioActions] insert_chat_media: {added} 个媒体待插入对话输入框")
        return added > 0

    # ---------- 图片生成（仅用户明确触发） ----------

    def _selected_draft_media_config(self) -> tuple:
        """解析中间预览面板选中草稿的 (providerId, aspectRatio, imageResolution)，作为生图缺省配置。"""
        return ops.selected_draft_media_config(self.state, self.selected_draft_id, self.selected_type)

    def _apply_generate_image(self, action: Dict) -> bool:
        """Agent 触发生图（仅当用户明确要求时）。支持批量。

        LLM 指定的供应商/模型/比例/分辨率会同步回写到目标草稿，
        使中间预览框底部的参数选择跳转到对应配置。
        """
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
        sel_provider, sel_ratio, sel_resolution = self._selected_draft_media_config()

        # 根据 target 确定类型
        if target in ("all_keyelements", "all_keyElements"):
            draft_type = "keyelement"
            target = "all"
        elif target in ("all_shots", "all_shot"):
            draft_type = "shot"
            target = "all"

        pairs = self._collect_drafts(target, draft_type)
        if not pairs:
            return False

        # 生成确认闸（混合形态硬边界）：未经用户确认的 Prompt Draft 不得生成
        pairs = self._gen_confirm_gate(pairs)
        if not pairs:
            return False

        # 规格文档偏好（用户意志落盘）：LLM 未指定供应商时优先于草稿自动回填的默认值，
        # 防前端默认首选供应商（如 Grsai）覆盖规格中设定的生图渠道
        spec_pid, spec_model = ("", "")
        if not provider_id:
            spec_pid, spec_model = spec_media_preference(self.state)
        # 规格制作参数（7777 二轮）：规格交互选定的图片分辨率，主动填入参数栏
        spec_image_res = str(spec_production_params(self.state).get("image_resolution") or "")

        submitted = 0
        for group, draft in pairs:
            prompt = (draft.get("prompt") or "").strip()
            if not prompt:
                continue
            refs = self._resolve_scene_refs(group) if group else []
            # provider 回退链：LLM 指定 → 规格文档偏好 → 目标草稿自身（预览框已选参数）→ 中间面板选中草稿
            eff_provider = provider_id or spec_pid or (draft.get("providerId") or "") or sel_provider
            # model 回退链：LLM 指定 → 规格偏好（仅当供应商来自规格）→ 目标草稿自身 → 供应商默认模型（generation 层兑底）
            eff_model = model or (spec_model if eff_provider == spec_pid else "") or (draft.get("model") or "")
            # 比例回退链：LLM 指定 → 目标草稿自身 → 中间面板选中草稿 → 16:9
            eff_ratio = act_ratio or (draft.get("aspectRatio") or "") or sel_ratio or "16:9"
            # 分辨率回退链（7777 二轮，与供应商链口径一致）：
            # LLM 指定 → 规格选定 → 目标草稿自身 → 中间面板选中草稿 → 1K
            eff_resolution = act_resolution or spec_image_res or (draft.get("imageResolution") or "") or sel_resolution or "1K"
            # 参数回写草稿：中间预览框底部参数选择跳转到对应供应商/模型/比例/分辨率
            draft["providerId"] = eff_provider
            if eff_model:
                draft["model"] = eff_model
            draft["aspectRatio"] = eff_ratio
            draft["imageResolution"] = eff_resolution
            self._submit_image_task(
                draft, eff_provider, eff_model, refs,
                aspect_ratio=eff_ratio, resolution=eff_resolution,
            )
            submitted += 1
        if submitted:
            logger.info(f"[StudioActions] generate_image: 已提交 {submitted} 个生图任务")
        return submitted > 0

    def _collect_drafts(self, target: str, draft_type: str) -> List[tuple]:
        """收集目标 (group, draft) 对；委托领域层唯一实现"""
        return ops.collect_drafts(self.state, target, draft_type)

    def _resolve_scene_refs(self, group: Dict) -> List[Dict[str, str]]:
        """解析分镜的 sceneRefs → 对应关键元素的概念图 URL 作为参考图"""
        return ops.resolve_scene_refs(self.state, group)

    # ---------- 分镜视频生成（仅用户明确触发） ----------

    def _apply_generate_video(self, action: Dict) -> bool:
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

        # 规格制作参数（7777 二轮）：视频分辨率 + 分镜最大时长；
        # 时长上限由用户在规格交互中按出视频模型选定，不再写死 15s
        _spec_params = spec_production_params(self.state)
        spec_video_res = str(_spec_params.get("video_resolution") or "")
        shot_cap = _spec_params.get("shot_max_duration")

        if target in ("all_shots", "all_shot"):
            draft_type = "shot"
            target = "all"

        pairs = self._collect_drafts(target, draft_type)
        if not pairs:
            return False

        # 生成确认闸（混合形态硬边界）：未经用户确认的 Prompt Draft 不得生成
        pairs = self._gen_confirm_gate(pairs)
        if not pairs:
            return False

        submitted = 0
        for group, draft in pairs:
            prompt = (draft.get("prompt") or "").strip()
            if not prompt:
                continue
            # 参数回退链：LLM 指定 → 规格选定（7777 二轮）→ 目标草稿自身参数 → 默认值
            eff_provider = provider_id or (draft.get("providerId") or "")
            eff_model = model or (draft.get("model") or "")
            eff_ratio = (draft.get("aspectRatio") or "16:9")
            eff_resolution = act_resolution or spec_video_res or (draft.get("resolution") or "720p")
            dur_raw = str(draft.get("duration") or "").strip().lower()
            try:
                eff_duration = act_duration or int(re.sub(r"[^0-9]", "", dur_raw) or 5)
            except ValueError:
                eff_duration = 5
            # 分镜最大时长上限：规格选定优先（按出视频模型由用户选），缺失兜底 15s
            eff_duration = max(1, min(eff_duration, shot_cap or 15))

            # 参数回写草稿：预览框参数区同步跳转
            if eff_provider:
                draft["providerId"] = eff_provider
            if eff_model:
                draft["model"] = eff_model
            draft["resolution"] = eff_resolution

            image_refs, audio_refs = collect_shot_video_refs(self.state, group, draft)
            submit_video_task(
                self.state, draft, "shot", eff_provider, eff_model,
                duration=eff_duration, resolution=eff_resolution, aspect_ratio=eff_ratio,
                image_refs=image_refs, audio_refs=audio_refs,
                source="agent", on_failure_save=self.svc.save_debounced,
            )
            submitted += 1
        if submitted:
            logger.info(f"[StudioActions] generate_video: 已提交 {submitted} 个视频生成任务")
        return submitted > 0

    def _submit_image_task(self, draft: Dict, provider_id: str, model: str, refs: List[Dict], aspect_ratio: str = "16:9", resolution: str = "1K") -> None:
        """提交异步生图任务（委托 generation 层的 submit_image_task，批次5 下沉）"""
        submit_image_task(
            self.state, draft, provider_id, model, refs,
            aspect_ratio=aspect_ratio, resolution=resolution,
            on_failure_save=self.svc.save_debounced,
        )
