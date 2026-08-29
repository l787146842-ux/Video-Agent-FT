"""通用章节执行工具（裁决 R9：P1-9 补实现）。

frontmatter custom_sections 声明（章节标识 → skill_section_run）的唯一
运行期消费通道：读 skill_runtime/registry.py 的 custom_section 解析结果，
把当前选中 Skill 声明的自定义章节正文作为执行上下文返回。

解析口径与 SkillEntry.custom_section_text / section_for 同源（stage 键 →
章节 tag 映射 → 标题关键字 → 任意 <tag> 直取），不出现「注册了却取不到」
的半死通道；未声明/未解析一律拒收（fail-closed），模型不得凭目录摘要臆造。
"""
from typing import Type

from loguru import logger
from pydantic import BaseModel, Field

from src.video_agent.skill_runtime import registry
from src.video_agent.state.manager import StateManager
from src.video_agent.tools.base import BaseTool, ToolResult
from src.video_agent.tools.manager import ToolManager
from src.video_agent.utils.prompts import render_prompt_section


class SkillSectionRunInput(BaseModel):
    section: str = Field(
        ...,
        description="自定义章节标识（Skill frontmatter custom_sections 中声明的键，"
                    "如「音色设计」）；必须是声明过的键，未声明的标识会被拒收。",
    )
    skill: str = Field(
        "",
        description="Skill 名称或 slug；留空 = 取当前选中 Skill（项目最近使用的 Skill 兜底）。",
    )


class SkillSectionRunTool(BaseTool):
    name = registry.CUSTOM_SECTION_EXECUTOR  # "skill_section_run"（单一事实源）
    risk = "medium"  # §2.7：声明轴裁决 R9 指定档位
    detail_tier = "expand"  # 执行上下文可展开查看输入与返回正文
    description = (
        "执行当前选中 Skill 声明的自定义章节（frontmatter custom_sections）："
        "按 section 传入章节标识，返回该章节在 Skill 文档中的正文作为执行上下文。"
        "仅对 Skill 显式声明过的章节标识生效；未声明或未解析出正文会被拒收。"
    )

    def get_input_schema(self) -> Type[BaseModel]:
        return SkillSectionRunInput

    async def aexecute(self, params: SkillSectionRunInput) -> ToolResult:
        section = (params.section or "").strip()
        if not section:
            return ToolResult(success=False, error="section 不能为空")
        wanted = (params.skill or "").strip()
        if not wanted:
            # 当前选中 Skill 唯一实现 = registry.fallback_skill_from_state
            svc = StateManager.get_instance()
            wanted = registry.fallback_skill_from_state(svc.state_dict)
        # 可加载性门户（M2 停用=真停用）：显式传参也过门户，停用项章节正文不可读出；
        # 已注册但停用者以「已停用」语义拒载（外置文案，空则内置短句兜底）
        entry = registry.resolve_loadable_entry(wanted) if wanted else None
        if entry is None:
            if wanted and registry.resolve_entry(wanted) is not None:
                return ToolResult(success=False, error=render_prompt_section(
                    "shared/skill_load_reject.md", "DISABLED", name=wanted)
                    or f"Skill「{wanted}」已停用，不可执行（停用=真停用）")
            return ToolResult(
                success=False,
                error=("无法定位当前 Skill：请传 skill 参数（Skill 名称），"
                       "或先在项目中使用一个 Skill。"),
            )
        declared = entry.custom_sections
        if section not in declared:
            keys = "、".join(declared) if declared else "无"
            return ToolResult(
                success=False,
                error=(f"Skill「{entry.name}」未声明自定义章节「{section}」"
                       f"（已声明：{keys}）。只执行 frontmatter custom_sections "
                       f"显式声明的章节。"),
            )
        # 与声明可用性预检同源：同一解析链取正文
        text = entry.custom_section_text(section)
        if not text:
            return ToolResult(
                success=False,
                error=(f"Skill「{entry.name}」声明了章节「{section}」但正文未能解析"
                       f"（章节标签/标题缺失或正文为空），请检查 Skill 文档。"),
            )
        logger.info(f"[SkillSectionRun] 注入自定义章节上下文：{entry.name}/{section}")
        return ToolResult(
            success=True,
            data={"skill": entry.name, "section": section, "content": text},
        )


def register_skill_tools() -> None:
    """注册 Skill 章节执行工具（与 register_document_tools 同模式）。"""
    ToolManager.register(SkillSectionRunTool())
    logger.info("[Tools] 1 skill section execution tool registered")
