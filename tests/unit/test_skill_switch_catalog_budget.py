# -*- coding: utf-8 -*-
"""模型目录/条目预算/list_skills（2026-11-12 dsh 四组合口径）。

模型目录只列 modelInvocable=true；user-only 技能不出现。预算/最近使用序/
停用过滤逻辑不变。
"""
import pytest

import src.video_agent.web.skill_docs as sd
from src.video_agent.core.planner import PlannerContext
from src.video_agent.core.prompt_builder import PromptBuilder
from src.video_agent.skill_runtime import registry
from src.video_agent.tools.document_tools import ListSkillsInput, ListSkillsTool
from src.video_agent.tools.manager import ToolManager


def _doc(name: str, extra: str = "") -> str:
    return (
        f"---\nname: {name}\ndescription: {name} 测试桩\n{extra}---\n"
        f"# {name}\n\n## 一、制作流程\n流程\n"
    )


@pytest.fixture
def skills(tmp_path, monkeypatch):
    d = tmp_path / "skills"
    d.mkdir()
    monkeypatch.setattr(sd, "SKILL_DOCS_DIR", d)
    registry.reset_registry()
    sd.save_skill_doc("m-one", _doc("模型一"))
    sd.save_skill_doc("m-two", _doc("模型二"))
    sd.save_skill_doc("m-three", _doc("模型三"))
    sd.save_skill_doc("user-only", _doc("用户专用", "disable-model-invocation: true\n"))
    registry.sync_all(force=True)
    try:
        yield d
    finally:
        registry.reset_registry()


def _ctx(skill_name: str = "") -> PlannerContext:
    ctx = PlannerContext()
    ctx.use_studio_context = True
    ctx.skill_name = skill_name
    return ctx


def _pb(raw_state) -> PromptBuilder:
    return PromptBuilder(lambda: sd, lambda: "proj", lambda: raw_state)


def _base_state(**extra):
    raw = {"keyElements": [], "shots": [], "audioItems": []}
    raw.update(extra)
    return raw


def test_catalog_only_lists_model_invocable(skills):
    block = _pb(_base_state()).build_skill_catalog(_ctx(""))
    assert "模型一" in block and "模型二" in block and "模型三" in block
    assert "用户专用" not in block


def test_disabled_skill_filtered_from_catalog(skills, set_global_setting):
    set_global_setting("skills_disabled", ["m-two"])
    block = _pb(_base_state()).build_skill_catalog(_ctx(""))
    assert "模型二" not in block
    assert "模型一" in block


def test_catalog_budget_truncation_by_recency_with_pointer(skills, set_global_setting):
    set_global_setting("skill_catalog_max_entries", 2)
    raw = _base_state(usedSkills=["m-one", "m-three"])
    block = _pb(raw).build_skill_catalog(_ctx(""))
    idx_recent = block.find("- 模型三")
    idx_older = block.find("- 模型一")
    assert idx_recent >= 0 and idx_older > idx_recent
    assert "- 模型二" not in block
    assert "另有 1 个已启用 Skill 未列出" in block


async def test_list_skills_readonly_returns_model_catalog(skills, set_global_setting):
    res = await ListSkillsTool().aexecute(ListSkillsInput())
    assert res.success and res.error is None
    slugs = {s["slug"] for s in res.data["skills"]}
    assert slugs == {"m-one", "m-two", "m-three"}
    assert "user-only" not in slugs
    set_global_setting("skills_disabled", ["m-one"])
    res2 = await ListSkillsTool().aexecute(ListSkillsInput())
    assert {s["slug"] for s in res2.data["skills"]} == {"m-two", "m-three"}


def test_list_skills_registered_low_risk():
    from src.video_agent.tools import register_document_tools

    register_document_tools()
    assert "list_skills" in ToolManager._tools
    assert ToolManager.get_tool_risk("list_skills") == "low"
    assert ToolManager.get_tool_approval_tier("list_skills") == "none"


def test_skills_disabled_slug_list_sanitizer():
    from src.video_agent.web.routes.runtime_settings import _sanitize_slug_list

    assert _sanitize_slug_list("not-a-list") is None
    assert _sanitize_slug_list(["a", "", "  ", "a", "b"]) == ["a", "b"]
    assert _sanitize_slug_list([1, None]) == ["1"]
    assert len(_sanitize_slug_list([f"s{i}" for i in range(500)])) == 200
