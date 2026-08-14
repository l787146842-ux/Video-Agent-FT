"""Skill 执行器工具注册（独立模块，避免 tools/__init__ ↔ executors 循环导入）。"""


def register_skill_runtime_tools() -> None:
    """把独立执行器注册进 ToolManager（FC 路径可用）。"""
    from loguru import logger

    from src.video_agent.skill_runtime.executors import (
        AudioGenerateTool,
        ScriptAnalyzeTool,
        SkillPipelinePlanTool,
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
        # 814E1/E2：通用章节执行器 + 依赖图调度（平台级，任何 Skill 可用）
        SkillSectionRunTool,
        SkillPipelinePlanTool,
    ):
        ToolManager.register(cls())
    logger.info("[SkillRuntime] 已注册 9 个 Skill 执行器/调度工具")
