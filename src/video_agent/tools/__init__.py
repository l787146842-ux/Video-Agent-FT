from .base import BaseTool, ToolResult
from .manager import ToolManager
from .vision.generate_image import GenerateImageTool
from .video.generate_video import GenerateVideoTool
from .storyboard_tools import register_storyboard_tools
from .document_tools import register_document_tools

# 原有 Tool（CLI/旧 Workflow 用）
ToolManager.register(GenerateImageTool())
ToolManager.register(GenerateVideoTool())

# studio-actions 映射的标准 Tool
register_storyboard_tools()
register_document_tools()

# MCP 外部工具接入层：deny-first，无配置 = 零工具；
# 注册期任何异常诚实降级，不阻断平台工具链
from src.video_agent.tools.mcp import register_mcp_tools

try:
    register_mcp_tools()
except Exception:
    from loguru import logger as _mcp_logger
    _mcp_logger.exception("[mcp] 注册异常，MCP 接入层降级为零工具")

__all__ = [
    "BaseTool",
    "ToolResult",
    "ToolManager"
]
