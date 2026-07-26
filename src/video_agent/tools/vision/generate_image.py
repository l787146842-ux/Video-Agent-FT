import os
from typing import Type, Optional
from pydantic import BaseModel, Field

from src.video_agent.tools.base import BaseTool, ToolResult
from src.video_agent.adapters.factory import AdapterFactory

class GenerateImageParams(BaseModel):
    prompt: str = Field(..., description="图片生成的视觉提示词")
    reference_image: Optional[str] = Field(None, description="参考图片的本地路径")
    adapter_provider: str = Field("mock", description="后台使用的适配器名称")

class GenerateImageTool(BaseTool):
    name = "generate_image"
    description = "根据传入的提示词和可选的参考图片，生成图片并返回图片地址。"

    def get_input_schema(self) -> Type[BaseModel]:
        return GenerateImageParams

    async def aexecute(self, params: GenerateImageParams) -> ToolResult:
        try:
            adapter = AdapterFactory.get_adapter("image_generation", params.adapter_provider)
            
            # Initiate task
            result = await adapter.generate_image(
                prompt=params.prompt, 
                reference_image=params.reference_image
            )
            
            if result.status == "failed":
                 return ToolResult(success=False, error=result.error_msg)
                 
            # Note: in real scenarios we'd want to use wait_until_complete here to hang 
            # until mock or provider finishes generating, but let's implement the wait inline or via tool state logic
            # For simplicity let's assume wait_until_complete is called.
            
            from src.video_agent.adapters.factory import wait_until_complete
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
