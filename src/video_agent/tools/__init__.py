from .base import BaseTool, ToolResult
from .manager import ToolManager
from .vision.generate_image import GenerateImageTool
from .video.generate_video import GenerateVideoTool

ToolManager.register(GenerateImageTool())
ToolManager.register(GenerateVideoTool())

__all__ = [
    "BaseTool",
    "ToolResult",
    "ToolManager"
]
