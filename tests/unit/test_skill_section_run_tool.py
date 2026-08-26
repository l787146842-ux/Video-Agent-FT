# -*- coding: utf-8 -*-
"""P1-9（裁决 R9）：skill_section_run 通用章节执行器补实现。

钉死语义：
① 注册可见——工具进 ToolManager 注册表，risk=medium（裁决档位），
   注册名 = registry.CUSTOM_SECTION_EXECUTOR 单一事实源；
② 存量试点 Skill「多人对话访谈」音色设计章节声明被真实消费——
   声明键可取回章节正文（与声明可用性预检同源）；
③ fail-closed：未声明的章节标识 / 定位不到 Skill 一律拒收。
"""
import pytest

from src.video_agent.skill_runtime import registry
from src.video_agent.tools.manager import ToolManager
from src.video_agent.tools.skill_tools import (
    SkillSectionRunInput,
    SkillSectionRunTool,
)


# ---------- ① 注册可见 ----------

def test_skill_section_run_registered_visible():
    """工具注册进平台注册表：模型可见 schema，风险分级 = 裁决档位 medium"""
    from src.video_agent.tools import register_skill_tools  # noqa: F401（接线点）

    register_skill_tools()
    assert registry.CUSTOM_SECTION_EXECUTOR in ToolManager._tools, \
        "skill_section_run 未注册进 ToolManager"
    assert ToolManager.get_tool_risk(registry.CUSTOM_SECTION_EXECUTOR) == "medium"
    names = {s["function"]["name"] for s in ToolManager.get_all_tool_schemas()}
    assert registry.CUSTOM_SECTION_EXECUTOR in names, "工具未进模型可见 schema 集"


def test_skill_section_run_name_single_source():
    """注册名唯一事实源 = registry.CUSTOM_SECTION_EXECUTOR（防双名漂移）"""
    assert SkillSectionRunTool.name == "skill_section_run"
    assert registry.CUSTOM_SECTION_EXECUTOR == SkillSectionRunTool.name


# ---------- ② 存量声明被真实消费 ----------

@pytest.mark.asyncio
async def test_interview_tone_design_section_returns_body():
    """多人对话访谈：音色设计章节可取回正文（frontmatter 声明保持不动）"""
    tool = SkillSectionRunTool()
    result = await tool.aexecute(
        SkillSectionRunInput(section="音色设计", skill="多人对话访谈"))
    assert result.success is True, result.error
    assert result.data["skill"] == "多人对话访谈"
    assert "音色档案" in result.data["content"]
    assert "每位发言者" in result.data["content"]


@pytest.mark.asyncio
async def test_current_skill_fallback_from_state():
    """skill 留空 → 取当前选中 Skill（usedSkills 末位兜底，单一实现）"""
    from src.video_agent.state.manager import StateManager

    svc = StateManager.get_instance()
    svc.state_dict["usedSkills"] = ["多人对话访谈"]
    tool = SkillSectionRunTool()
    result = await tool.aexecute(SkillSectionRunInput(section="音色设计"))
    assert result.success is True, result.error
    assert "音色档案" in result.data["content"]


# ---------- ③ fail-closed ----------

@pytest.mark.asyncio
async def test_undeclared_section_rejected():
    """未声明的章节标识拒收（模型不得臆造章节通道）"""
    tool = SkillSectionRunTool()
    result = await tool.aexecute(
        SkillSectionRunInput(section="不存在章节", skill="多人对话访谈"))
    assert result.success is False
    assert "未声明自定义章节" in result.error
    assert "音色设计" in result.error  # 报错带已声明清单，模型可自纠


@pytest.mark.asyncio
async def test_no_skill_located_rejected():
    """无 Skill 选中且未传 skill 参数 → 拒收并给指引"""
    tool = SkillSectionRunTool()
    result = await tool.aexecute(SkillSectionRunInput(section="音色设计"))
    assert result.success is False
    assert "无法定位当前 Skill" in result.error
