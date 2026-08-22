"""Skill 运行时（通用主路径）。

上传/编辑 Skill 文档后，按章节注册进注册表：
- registry：Skill 文档 → 注册表条目（章节、阶段能力探针）
- sidecar/sidecar_schema：声明唯一源（data/skills_manifests）与 schema 校验

任务#36 B5：独立执行器族（exec_common/exec_spec/exec_tools/exec_media_gen/
exec_media_writer/exec_split/registration/capability/executors）已一步退役
物理删除；管线阶段改由通用主路径直走平台工具（prompt_builder 全文/章节
分级注入 + fc_tool_runner 闸机链）。
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
