"""
Studio Actions — 兼容入口（re-export）。

实际实现已拆分至：
- action_parser.py：解析 / 修复 / 提取 studio-actions JSON
- action_executor.py：StudioActionExecutor 执行器类

本文件仅保留向后兼容的 re-export，外部代码可继续从 actions 导入。
"""

# 解析器 re-export
from src.video_agent.web.action_parser import (  # noqa: F401
    strip_action_blocks,
    has_action_block,
    parse_actions_from_reply,
    parse_json_tolerant,
    repair_json,
    normalize_actions,
)

# 执行器 re-export
from src.video_agent.web.action_executor import StudioActionExecutor  # noqa: F401
