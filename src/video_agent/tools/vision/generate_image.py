from typing import Type, Optional
from pydantic import BaseModel, Field

from src.video_agent.tools.base import BaseTool, ToolResult
from src.video_agent.adapters.factory import AdapterFactory, wait_until_complete

class GenerateImageParams(BaseModel):
    prompt: str = Field(..., description="图片生成的视觉提示词")
    reference_image: Optional[str] = Field(None, description="参考图片的本地路径")
    adapter_provider: str = Field("mock", description="后台使用的适配器名称")
    aspect_ratio: Optional[str] = Field(None, description="画面比例，如 16:9、9:16、1:1")

class GenerateImageTool(BaseTool):
    name = "generate_image"
    description = (
        "根据传入的提示词和可选的参考图片，生成一张图片并返回图片地址。"
        "每次调用只产出一张图；除非用户明确要求多张，否则每轮对话最多调用一次本工具。"
    )

    def get_input_schema(self) -> Type[BaseModel]:
        return GenerateImageParams

    async def aexecute(self, params: GenerateImageParams) -> ToolResult:
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
                 return ToolResult(success=False, error=result.error_msg)

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

        except Exception as e:
            return ToolResult(success=False, error=str(e))
