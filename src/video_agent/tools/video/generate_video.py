from typing import Type
from pydantic import BaseModel, Field

from loguru import logger

from src.video_agent.config import settings
from src.video_agent.core.generation_fallback import (
    gen_fallback_candidates,
    is_retryable_gen_error,
)
from src.video_agent.core.provider_config import get_provider_config
from src.video_agent.tools.base import BaseTool, ToolResult
from src.video_agent.adapters.cancel_token import GenerationCancelled
from src.video_agent.adapters.factory import AdapterFactory, wait_until_complete

class GenerateVideoParams(BaseModel):
    image_url: str = Field(..., description="首帧图片路径或URL")
    prompt: str = Field(..., description="视频生成的动态描述提示词")
    duration: int = Field(5, description="生成的视频时长，默认5秒")
    adapter_provider: str = Field("", description="后台使用的适配器名称")

class GenerateVideoTool(BaseTool):
    name = "generate_video"
    risk = "high"  # §2.7：生成类（外部副作用/花钱）
    approval_tier = "confirm"  # P2-5 首批显式声明：执行前确认卡（花钱/外部副作用）
    detail_tier = "expand"  # 产出类
    description = (
        "根据传入的首帧图片和提示词，生成高清视频并返回结果。"
        "危险/花钱操作，仅当用户明确要求生成视频时才可调用，执行前会弹确认卡。"
    )

    def get_input_schema(self) -> Type[BaseModel]:
        return GenerateVideoParams

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
        for idx, (pid, mdl) in enumerate(candidates):
            try:
                adapter = (
                    first_adapter if idx == 0
                    else AdapterFactory.get_adapter("video_generation", pid)
                )
                result = await adapter.generate(
                    image_url=params.image_url,
                    prompt=params.prompt,
                    duration=params.duration,
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
