from typing import Type, Optional
from pydantic import BaseModel, Field

from src.video_agent.tools.base import BaseTool, ToolResult
from src.video_agent.adapters.cancel_token import GenerationCancelled
from src.video_agent.adapters.factory import AdapterFactory, wait_until_complete

class GenerateImageParams(BaseModel):
    prompt: str = Field(..., description="图片生成的视觉提示词")
    reference_image: Optional[str] = Field(None, description="参考图片的本地路径")
    adapter_provider: str = Field("", description="后台使用的适配器名称")
    aspect_ratio: Optional[str] = Field(None, description="画面比例，如 16:9、9:16、1:1")

class GenerateImageTool(BaseTool):
    name = "generate_image"
    risk = "high"  # §2.7：生成类（外部副作用/花钱）
    approval_tier = "confirm"  # P2-5 首批显式声明：执行前确认卡（花钱/外部副作用）
    detail_tier = "expand"  # 产出类
    description = (
        "根据传入的提示词和可选的参考图片，生成单张图片并返回图片地址（单张应急轨）。"
        "危险/花钱操作，仅当用户明确要求出图时才可调用，执行前会弹确认卡；"
        "需要多张/批量出图时请改用工作台批量工具 image_generate（本工具每轮调用次数由系统限制）。"
    )

    def get_input_schema(self) -> Type[BaseModel]:
        return GenerateImageParams

    async def aexecute(self, params: GenerateImageParams) -> ToolResult:
        if not (params.adapter_provider or "").strip():
            # T5：供应商未配置=入参/配置问题，改参（补 provider）后可重试
            return ToolResult(
                success=False,
                error="尚未配置生成供应商，请先到「设置」中配置生成供应商",
                error_code="validation", retryable=False,
            )
        try:
            adapter = AdapterFactory.get_adapter("image_generation", params.adapter_provider)
            
            # Initiate task
            extra: dict = {}
            if params.aspect_ratio:
                extra["aspect_ratio"] = params.aspect_ratio
            result = await adapter.generate_image(
                prompt=params.prompt,
                reference_image=params.reference_image,
                **extra,
            )
            
            if result.status == "failed":
                 # T5：上游明确失败，单次可再试（换参/重试一次）
                 return ToolResult(
                     success=False, error=result.error_msg,
                     error_code="upstream", retryable=True,
                 )

            # 同步完成的适配器（如 agy CLI 直接出图）：初始结果已带图片 URL，
            # 直接进入轮询会调到 fetch_result 拿到空列表，导致 image_urls 丢失
            if result.status in ("succeeded", "completed") and result.image_urls:
                completed_result = result
            else:
                completed_result = await wait_until_complete(adapter, result.task_id)
            
            return ToolResult(
                success=True, 
                data={
                    "task_id": completed_result.task_id, 
                    "image_urls": completed_result.image_urls
                }
            )

        except GenerationCancelled:
            # 取消穿透：不得被错误兜底吞咽为失败结果，上抛收敛至停止分支
            raise
        except Exception as e:
            # T5：未分类异常兜底，不标可重试（防盲重试空转）
            return ToolResult(success=False, error=str(e), error_code="upstream")
