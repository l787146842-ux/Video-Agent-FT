from .base import BaseTool, ToolResult
from .manager import ToolManager
from .video.generate_video import GenerateVideoTool
from .storyboard_tools import register_storyboard_tools
from .document_tools import register_document_tools
from .analysis_tools import register_analysis_tools
from .web_tools import register_web_tools
from .structured_output import register_structured_output_tools
from .todo_tools import register_todo_tools

# 原有 Tool（CLI/旧 Workflow 用）
ToolManager.register(GenerateVideoTool())

# studio-actions 映射的标准 Tool
register_storyboard_tools()
register_document_tools()
register_analysis_tools()
register_web_tools()
# K6 批（2026-09-16 对齐 flova/dsh）：子代理完工打卡工具（子代理专属可见）
register_structured_output_tools()
# 2026-09-23 批8（用户裁决：「完全照抄 dsh」）：任务进度清单 todo_write。
# 主代理与子代理都持有——记账是两边共同需求（子代理「边做边想」尤其依赖它）。
register_todo_tools()
# （C1b 裁决 2026-08-31：skill_section_run/custom_sections 自定义章节通道退役，
# 其专属注册入口 register_skill_tools 同批删除）

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
