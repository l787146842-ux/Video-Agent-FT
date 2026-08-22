from typing import Type
from pydantic import BaseModel, Field

from loguru import logger

from src.video_agent.config import settings
from src.video_agent.tools.base import BaseTool, ToolResult
from src.video_agent.adapters.factory import AdapterFactory, wait_until_complete

class GenerateVideoParams(BaseModel):
    image_url: str = Field(..., description="首帧图片路径或URL")
    prompt: str = Field(..., description="视频生成的动态描述提示词")
    duration: int = Field(5, description="生成的视频时长，默认5秒")
    adapter_provider: str = Field("mock", description="后台使用的适配器名称")

class GenerateVideoTool(BaseTool):
    name = "generate_video"
    risk = "high"  # §2.7：生成类（外部副作用/花钱）
    description = "根据传入的首帧图片和提示词，生成高清视频并返回结果。"

    def get_input_schema(self) -> Type[BaseModel]:
        return GenerateVideoParams

    async def aexecute(self, params: GenerateVideoParams) -> ToolResult:
        from src.video_agent.web.generation import (
            _gen_fallback_candidates,
            _is_retryable_gen_error,
        )
        from src.video_agent.web.provider_config import get_provider_config

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
            candidates = await _gen_fallback_candidates(
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
            except Exception as e:
                last_error = str(e)
                if idx == len(candidates) - 1 or not _is_retryable_gen_error(e):
                    return ToolResult(success=False, error=last_error)
                logger.warning(
                    f"[generate_video] 厂商 {pid} 失败（{str(e)[:60]}），"
                    f"同模型 {mdl} 切换厂商 {candidates[idx + 1][0]} 重试"
                )
        return ToolResult(success=False, error=last_error)
