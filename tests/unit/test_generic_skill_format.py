"""通用 Agent Skills 格式回归（2026-11-11 去标签迁移）。

钉死四件事：
1. 无标签、任意 Markdown 标题的 skill 可注册、可注入主文档全文；
2. `<planner>` 等旧标签只作普通文本，不触发任何章节映射；
3. 分册（references/）可按路径 read_skill 读取，返回三段式；
4. 坏包仍 fail-closed，但 /api/skills/docs 的 failed[] 可见。
"""
import pytest

import src.video_agent.web.skill_docs as sd
from src.video_agent.core.prompt_builder import PromptBuilder
from src.video_agent.skill_runtime import registry
from src.video_agent.tools.document_tools import ReadSkillInput, ReadSkillTool

DOC = (
    "---\nname: 通用演示\ndescription: 任意标题的通用 skill\n---\n"
    "# 通用演示\n\n"
    "## 一、制作流程\n流程正文 GENERIC_FLOW\n\n"
    "## 二、参考资料\n需要时读 `references/notes.md`。\n"
)


@pytest.fixture
def skills_dir(tmp_path, monkeypatch):
    d = tmp_path / "skills"
    d.mkdir()
    monkeypatch.setattr(sd, "SKILL_DOCS_DIR", d)
    registry.reset_registry()
    yield d
    registry.reset_registry()


def _pb():
    return PromptBuilder(
        lambda: sd, lambda: "proj",
        lambda: {"keyElements": [], "shots": [], "audioItems": []},
    )


def test_generic_skill_registers_and_injects_full_doc(skills_dir):
    sd.save_skill_doc("通用演示", DOC)
    entry = registry.get_entry("通用演示")
    assert entry is not None
    assert entry.available_tools  # 标题可推导阶段探针
    block = _pb().build_selected_skill_block("通用演示")
    assert "GENERIC_FLOW" in block
    assert "## 二、参考资料" in block
    assert "<planner>" not in block


def test_legacy_tags_are_plain_text(skills_dir):
    assert sd.split_skill_sections("<planner>\n流程\n</planner>\n") == {}
    sd.save_skill_doc(
        "旧标签文本",
        "---\nname: 旧标签文本\ndescription: 标签只作普通文本\n---\n"
        "# 旧标签文本\n\n## 制作流程\n<planner>这不是机制</planner>\n",
    )
    entry = registry.get_entry("旧标签文本")
    assert entry is not None
    assert "这不是机制" in entry.content


@pytest.mark.asyncio
async def test_generic_reference_read_returns_three_parts(skills_dir):
    sd.save_skill_doc("通用演示", DOC)
    refs = skills_dir / "通用演示" / "references"
    refs.mkdir(parents=True)
    (refs / "notes.md").write_text("分册正文 REF_MARK", encoding="utf-8")
    registry.refresh_skill("通用演示")
    res = await ReadSkillTool().aexecute(
        ReadSkillInput(name="通用演示", resource="references/notes.md"))
    assert res.success
    assert "REF_MARK" in res.data["content"]
    assert "<skill_content" in res.data["content"]
    assert "<skill_resources>" in res.data["content"]
    assert "<skill_instructions>" in res.data["content"]


def test_bad_pack_is_visible_in_failed_list(skills_dir):
    sd.save_skill_doc("通用演示", DOC)
    bad = skills_dir / "坏包"
    bad.mkdir()
    (bad / "SKILL.md").write_text(
        "---\ndescription: 缺 name\n---\n# 坏包\n", encoding="utf-8")
    registry.sync_all(force=True)
    failures = registry.scan_failures()
    assert "坏包" in failures
    assert "name" in failures["坏包"]
    assert registry.get_entry("坏包") is None
