"""Skill 独立执行器运行时。

上传/编辑 Skill 文档后，按章节自动注册为真实执行器：
- registry：Skill 文档 → 注册表条目（章节、可用执行器）
- executors：每个执行器只注入自己对应的 Skill 章节，独立 LLM 调用 + 结构化校验

执行器工具由 tools/__init__.py 统一注册进 ToolManager，
文本动作轨由 web/action_executor.StudioActionExecutor.execute_async 调用。
"""

from src.video_agent.skill_runtime import registry
from src.video_agent.skill_runtime.registry import (
    SkillEntry,
    get_entry,
    list_entries,
    refresh_skill,
    register_skill,
    reset_registry,
    resolve_entry,
    sync_all,
    tool_available,
    tool_sections,
    unregister_skill,
)

__all__ = [
    "registry",
    "SkillEntry",
    "get_entry",
    "list_entries",
    "refresh_skill",
    "register_skill",
    "reset_registry",
    "resolve_entry",
    "sync_all",
    "tool_available",
    "tool_sections",
    "unregister_skill",
]
