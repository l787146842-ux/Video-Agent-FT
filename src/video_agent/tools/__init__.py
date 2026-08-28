from .base import BaseTool, ToolResult
from .manager import ToolManager
from .video.generate_video import GenerateVideoTool
from .storyboard_tools import register_storyboard_tools
from .document_tools import register_document_tools
from .skill_tools import register_skill_tools

# 原有 Tool（CLI/旧 Workflow 用）
ToolManager.register(GenerateVideoTool())

# studio-actions 映射的标准 Tool
register_storyboard_tools()
register_document_tools()
# Skill 自定义章节执行通道（裁决 R9：custom_sections 声明的运行期消费）
register_skill_tools()

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
