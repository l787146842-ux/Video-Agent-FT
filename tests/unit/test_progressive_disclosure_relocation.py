"""渐进式披露条款归位层 10（整改计划批 4；Rule 6 迁移快照锁语义）。

四条 read_* 用法条款从平台协议（protocol.md 重要规则段）归位到对应工具的
description（工具用法归 Tool description 层）；平台协议只留一句总纲。
本测试锁迁移后语义：总纲在场、逐工具分身不在场、工具描述承载完整用法。
"""
from pathlib import Path

import pytest

from src.video_agent.tools.document_tools import (
    ReadProjectDocTool,
    ReadSkillTool,
    ReadUploadedDocTool,
)
from src.video_agent.tools.storyboard_tools import StoryboardReadDraftTool

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def protocol_text() -> str:
    return (ROOT / "prompts/planner/protocol.md").read_text(encoding="utf-8")


def test_platform_keeps_single_overview(protocol_text: str):
    """平台层只留总纲一句（含术语「渐进式披露」，既有预算/快照测试依赖该锚点）
    （2026-09-26 锚点同步：批N 把「read_* 工具按需读取」改写为「按任务分工决定由谁读」
    时未同步本测试，此处按现行总纲原文修正锚点，锁定语义不变）"""
    assert "渐进式披露总纲" in protocol_text
    assert "读取本身没有限制，但按任务分工决定由谁读" in protocol_text


def test_per_tool_instructions_not_duplicated(protocol_text: str):
    """逐工具用法分身已迁走，平台层不得复述（P1 单一事实源）"""
    for gone in (
        "read_draft（draft_id=",       # read_draft 用法归工具描述
        "read_skill（name=Skill 名称）",  # read_skill 用法归工具描述
        "read_project_doc 读取规格文档",  # read_project_doc 用法归工具描述
        "要求用户重新粘贴",              # read_uploaded_doc 用法归工具描述
    ):
        assert gone not in protocol_text, f"平台层残留工具用法分身: {gone}"


def test_tool_descriptions_carry_usage():
    """层 10 承载机械契约（2026-09-15 铺满批更新：dsh 正面契约——
    工具描述只留「做什么 + 参数格式 + 返回什么」，
    上下文注入解释/工作流引导归 prompts 层）。"""
    draft_desc = StoryboardReadDraftTool().description
    assert "全文" in draft_desc  # 机械契约：读取提示词全文
    assert "draft_type" in draft_desc  # 参数格式
    assert "目录信息" not in draft_desc  # 上下文注入解释已迁出

    skill_desc = ReadSkillTool().description
    assert "section" in skill_desc  # 参数格式
    assert "已注入流程段" not in skill_desc  # 上下文注入解释已迁出

    doc_desc = ReadProjectDocTool().description
    assert "全文" in doc_desc  # 机械契约
    assert "清单" not in doc_desc  # 上下文注入解释已迁出

    up_desc = ReadUploadedDocTool().description
    assert "name" in up_desc  # 参数格式
    assert "不自动注入" not in up_desc  # 上下文注入解释已迁出


def test_non_tool_clauses_kept(protocol_text: str):
    """非工具类条款保留在平台层（真实性/Skill 归口）。
    （2026-09-12 指令体量治理批：编号/current 语义与拆解建组条款迁出——
    编号归 read_draft/view_storyboard_media 描述，current 语义归 storyboard
    工具描述，拆解建组归 storyboard_create_group 描述 D-17 既有承载。）"""
    for kept in (
        "完成声称必须真的调用了对应工具",
        "由所选 Skill 文档规定",
        "渐进式披露总纲",
    ):
        assert kept in protocol_text, f"平台层条款丢失: {kept}"
    for gone in ('"current"', "组号-卡序号", "storyboard_create_group"):
        assert gone not in protocol_text, f"平台层残留工具用法分身: {gone}"
