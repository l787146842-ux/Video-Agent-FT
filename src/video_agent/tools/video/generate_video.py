import os
from typing import Type, Optional
from pydantic import BaseModel, Field

from src.video_agent.tools.base import BaseTool, ToolResult
from src.video_agent.adapters.factory import AdapterFactory

class GenerateVideoParams(BaseModel):
    image_url: str = Field(..., description="首帧图片路径或URL")
    prompt: str = Field(..., description="视频生成的动态描述提示词")
    duration: int = Field(5, description="生成的视频时长，默认5秒")
    adapter_provider: str = Field("mock", description="后台使用的适配器名称")

class GenerateVideoTool(BaseTool):
    name = "generate_video"
    description = "根据传入的首帧图片和提示词，生成高清视频并返回结果。"

    def get_input_schema(self) -> Type[BaseModel]:
        return GenerateVideoParams

    async def aexecute(self, params: GenerateVideoParams) -> ToolResult:
        try:
            adapter = AdapterFactory.get_adapter("video_generation", params.adapter_provider)
            
            result = await adapter.generate(
                image_url=params.image_url,
                prompt=params.prompt,
                duration=params.duration
            )
            
            if result.status == "failed":
                 return ToolResult(success=False, error=result.error_msg)
                 
            from src.video_agent.adapters.factory import wait_until_complete
            completed_result = await wait_until_complete(adapter, result.task_id)
            
            return ToolResult(
                success=True, 
                data={
                    "task_id": completed_result.task_id, 
                    "video_url": completed_result.video_url
                }
            )

        except Exception as e:
            return ToolResult(success=False, error=str(e))
