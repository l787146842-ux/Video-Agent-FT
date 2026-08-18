"""Skill 执行器工具注册（独立模块，避免 tools/__init__ ↔ executors 循环导入）。"""


def register_skill_runtime_tools() -> None:
    """把独立执行器注册进 ToolManager（FC 路径可用）。"""
    from loguru import logger

    from src.video_agent.skill_runtime.executors import (
        AudioGenerateTool,
        ScriptAnalyzeTool,
        SkillSectionRunTool,
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
        # 814E1：通用章节执行器（平台级，任何 Skill 可用）；
        # 依赖图调度工具随 0818 架构板正批退役（顺序归编排器）
        SkillSectionRunTool,
    ):
        ToolManager.register(cls())
    logger.info("[SkillRuntime] 已注册 8 个 Skill 执行器工具")
