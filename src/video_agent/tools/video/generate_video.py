from typing import Any, Dict, Type
from pydantic import BaseModel, Field

from loguru import logger

from src.video_agent.config import settings
from src.video_agent.core import ports
from src.video_agent.core.generation_fallback import (
    gen_fallback_candidates,
    is_retryable_gen_error,
)
from src.video_agent.core.provider_config import get_provider_config
from src.video_agent.tools.base import BaseTool, ProviderInjectionContext, ToolResult
from src.video_agent.utils.cancel_token import GenerationCancelled
from src.video_agent.adapters.factory import AdapterFactory, wait_until_complete

class GenerateVideoParams(BaseModel):
    image_url: str = Field(..., description="首帧图片路径或URL")
    prompt: str = Field(..., description="视频生成的动态描述提示词")
    duration: int = Field(0, description="生成的视频时长（秒）；留空/0 = 按目标草稿卡自身的时长")
    resolution: str = Field("", description="视频分辨率（如 720p/1080p）；留空 = 按目标草稿卡自身的分辨率")
    aspect_ratio: str = Field("", description="画面比例（如 16:9）；留空 = 按目标草稿卡自身的比例")
    adapter_provider: str = Field("", description="后台使用的适配器名称")

class GenerateVideoTool(BaseTool):
    name = "generate_video"
    risk = "high"  # §2.7：生成类（外部副作用/花钱）；确认档由 risk 单轴推导（F1）
    costly = True  # 批 B 花钱生成声明轴：执行偏好三档可放宽其确认闸（留痕）
    detail_tier = "expand"  # 产出类
    provider_kind = "video"  # I-3 裁决 2026-09-03：provider 注入声明轴
    description = (
        "根据传入的首帧图片和提示词生成视频并返回视频地址。"
        "生成渠道由系统按优先级自动注入供应商。"
    )

    def get_input_schema(self) -> Type[BaseModel]:
        return GenerateVideoParams

    def apply_provider_defaults(self, args: Dict[str, Any], ctx: ProviderInjectionContext) -> None:
        """I-3：generate_video 渠道与制作参数注入下沉到工具自身（调度器不感知）。

        优先级 = 模型显式指定 > 目标草稿卡自身配置 > 全局默认渠道。按卡类型解析
        （分区内混有三类卡，禁止「分区 → 媒体类型」映射）。经 provider_config
        端口访问声明（依赖倒置，保 monkeypatch 可见）。

        2026-10-09 用户裁决「执行时按卡内已填参数」（除分镜最大时长外全部制作
        参数）：**时长/分辨率/画幅也从目标卡读**（旧实现 tool 层只注入渠道，
        分辨率根本没进 generate() 调用 ⇒ 卡上选的 720p 从来不生效；时长则由
        模型入参决定，卡上的分镜时长被绕过）。
        """
        port = ports.provider_config_port()
        draft = port.find_selected_draft(
            ctx.state, ctx.selected_draft_id, ctx.selected_type)
        if not str(args.get("adapter_provider") or "").strip():
            _vp, _vm = port.resolve_selected_draft_media_config(
                ctx.state, ctx.selected_draft_id, ctx.selected_type, kind="video")
            if _vp:
                args["adapter_provider"] = _vp
                logger.info("[generate_video] provider 注入（选中草稿卡）: {}/{}", _vp, _vm)
        # 制作参数：卡为空则不写（留给执行期回落全局设置，避免在此臆造）
        card = port.resolve_draft_production_params(draft or {}, "video")
        if not int(args.get("duration") or 0) and card.get("duration"):
            args["duration"] = int(card["duration"])
            logger.info("[generate_video] 时长注入（选中草稿卡）: {}s", args["duration"])
        if not str(args.get("resolution") or "").strip() and card.get("video_resolution"):
            args["resolution"] = card["video_resolution"]
            logger.info("[generate_video] 分辨率注入（选中草稿卡）: {}", args["resolution"])
        if not str(args.get("aspect_ratio") or "").strip() and card.get("aspect_ratio"):
            args["aspect_ratio"] = card["aspect_ratio"]
            logger.info("[generate_video] 画幅注入（选中草稿卡）: {}", args["aspect_ratio"])

    async def aexecute(self, params: GenerateVideoParams) -> ToolResult:
        if not (params.adapter_provider or "").strip():
            # T5：供应商未配置=入参/配置问题，改参后可重试
            return ToolResult(
                success=False,
                error="尚未配置生成供应商，请先到「设置」中配置生成供应商",
                error_code="validation", retryable=False,
            )
        # 同模型跨厂商降级（与 submit_video_task 同口径）：
        # 仅失败才切；模型取主厂商配置的首个视频模型，候选只收列出同名模型的厂商
        first_adapter = AdapterFactory.get_adapter("video_generation", params.adapter_provider)
        eff_model = getattr(first_adapter, "model", "") or ""
        if not eff_model:
            cfg = get_provider_config(params.adapter_provider) or {}
            models = [m for m in (cfg.get("video_models") or []) if m]
            eff_model = str(models[0]) if models else ""
        candidates = [(params.adapter_provider, eff_model)]
        if settings.model_fallback_enabled and eff_model:
            candidates = await gen_fallback_candidates(
                params.adapter_provider, eff_model, "video"
            )

        last_error = "执行失败"
        # 制作参数末级兜底（卡与入参都没有值时按全局设置，避免 adapter 默认值
        # 悄悄接管）：分辨率/时长/画幅各取「入参 → 全局设置」。
        eff_resolution = str(params.resolution or "").strip() or settings.default_video_resolution
        eff_duration = int(params.duration or 0) or int(settings.max_shot_duration or 5)
        eff_aspect = str(params.aspect_ratio or "").strip() or "16:9"
        for idx, (pid, mdl) in enumerate(candidates):
            try:
                adapter = (
                    first_adapter if idx == 0
                    else AdapterFactory.get_adapter("video_generation", pid)
                )
                result = await adapter.generate(
                    image_url=params.image_url,
                    prompt=params.prompt,
                    duration=eff_duration,
                    resolution=eff_resolution,
                    aspect_ratio=eff_aspect,
                    model=mdl or None,
                )
                if result.status == "failed":
                    raise RuntimeError(result.error_msg or "视频生成失败")
                completed_result = await wait_until_complete(adapter, result.task_id)
                return ToolResult(
                    success=True,
                    data={
                        "task_id": completed_result.task_id,
                        "video_url": completed_result.video_url,
                    },
                )
            except GenerationCancelled:
                # 取消穿透：不得被 fallback 重试/错误兜底吞咽，上抛收敛至停止分支
                raise
            except Exception as e:
                last_error = str(e)
                if idx == len(candidates) - 1 or not is_retryable_gen_error(e):
                    # T5：跨厂商降级链未成功/不可重试错误；降级已内部耗尽，不标可重试
                    return ToolResult(
                        success=False, error=last_error,
                        error_code="upstream", retryable=False,
                    )
                logger.warning(
                    f"[generate_video] 厂商 {pid} 失败（{str(e)[:60]}），"
                    f"同模型 {mdl} 切换厂商 {candidates[idx + 1][0]} 重试"
                )
        # T5：降级链全部耗尽，同口径标注上游失败且不可重试
        return ToolResult(success=False, error=last_error, error_code="upstream")
