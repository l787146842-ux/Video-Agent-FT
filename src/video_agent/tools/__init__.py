from .base import BaseTool, ToolResult
from .manager import ToolManager
from .vision.generate_image import GenerateImageTool
from .video.generate_video import GenerateVideoTool
from .storyboard_tools import register_storyboard_tools
from .document_tools import register_document_tools

# 原有 Tool（CLI/旧 Workflow 用）
ToolManager.register(GenerateImageTool())
ToolManager.register(GenerateVideoTool())

# Phase 3: studio-actions 映射的标准 Tool
register_storyboard_tools()
register_document_tools()

__all__ = [
    "BaseTool",
    "ToolResult",
    "ToolManager"
]
