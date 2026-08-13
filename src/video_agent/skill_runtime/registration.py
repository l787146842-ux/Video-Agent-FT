"""Skill 执行器工具注册（独立模块，避免 tools/__init__ ↔ executors 循环导入）。"""


def register_skill_runtime_tools() -> None:
    """把独立执行器注册进 ToolManager（FC 路径可用）。"""
    from loguru import logger

    from src.video_agent.skill_runtime.executors import (
        AudioGenerateTool,
        ScriptAnalyzeTool,
        StoryboardAudioTool,
        StoryboardKeyElementsTool,
        StoryboardShotsTool,
        VideoAssemblerTool,
        WriteMediaPromptTool,
    )
    from src.video_agent.tools.manager import ToolManager

    for cls in (
        ScriptAnalyzeTool,
        StoryboardKeyElementsTool,
        StoryboardShotsTool,
        StoryboardAudioTool,
        WriteMediaPromptTool,
        AudioGenerateTool,
        VideoAssemblerTool,
    ):
        ToolManager.register(cls())
    logger.info("[SkillRuntime] 已注册 7 个 Skill 独立执行器工具")
