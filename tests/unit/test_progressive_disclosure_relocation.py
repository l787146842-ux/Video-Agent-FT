"""渐进式披露条款归位层 10（整改计划批 4；Rule 6 迁移快照锁语义）。

四条 read_* 用法条款从 prompts/shared/important_rules.md 归位到对应工具的
description（宪法 13.3：工具用法归层 10）；平台协议只留一句总纲。
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
def important_rules() -> str:
    return (ROOT / "prompts/shared/important_rules.md").read_text(encoding="utf-8")


def test_platform_keeps_single_overview(important_rules: str):
    """平台层只留总纲一句（含术语「渐进式披露」，既有预算/快照测试依赖该锚点）"""
    assert "渐进式披露总纲" in important_rules
    assert "read_* 工具按需读取" in important_rules


def test_per_tool_instructions_not_duplicated(important_rules: str):
    """逐工具用法分身已迁走，平台层不得复述（P1 单一事实源）"""
    for gone in (
        "read_draft（draft_id=",       # read_draft 用法归工具描述
        "read_skill（name=Skill 名称）",  # read_skill 用法归工具描述
        "read_project_doc 读取规格文档",  # read_project_doc 用法归工具描述
        "要求用户重新粘贴",              # read_uploaded_doc 用法归工具描述
    ):
        assert gone not in important_rules, f"平台层残留工具用法分身: {gone}"


def test_tool_descriptions_carry_usage():
    """层 10 承载完整用法：每个 read_* 工具描述自带渐进式披露语义"""
    draft_desc = StoryboardReadDraftTool().description
    assert "目录信息" in draft_desc and "全文" in draft_desc
    assert "draft_type" in draft_desc  # 迁移补强的参数建议

    skill_desc = ReadSkillTool().description
    assert "Skill 目录" in skill_desc and "全文" in skill_desc

    doc_desc = ReadProjectDocTool().description
    assert "清单" in doc_desc and "规格文档" in doc_desc

    up_desc = ReadUploadedDocTool().description
    assert "不会自动注入" in up_desc
    assert "重新粘贴" in up_desc  # 迁移补强的禁止项


def test_non_tool_clauses_kept(important_rules: str):
    """非工具类条款保留在平台层（编号规则/拆解规则/真实性/Skill 归口）"""
    for kept in (
        '"current"',
        "组号-卡序号",
        "storyboard_create_group",
        "不要只说“已创建”",
        "由所选 Skill 文档规定",
    ):
        assert kept in important_rules, f"平台层条款丢失: {kept}"
