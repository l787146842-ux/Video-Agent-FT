"""Skill 上传即注册：data/skills 仍是唯一数据源，保存/删除自动刷新注册表。"""
import pytest

import src.video_agent.web.skill_docs as sd
from src.video_agent.skill_runtime import registry


@pytest.fixture(autouse=True)
def skills_dir(tmp_path, monkeypatch):
    d = tmp_path / "skills"
    d.mkdir()
    monkeypatch.setattr(sd, "SKILL_DOCS_DIR", d)
    registry.reset_registry()
    yield d
    registry.reset_registry()


def test_save_registers_executors():
    sd.save_skill_doc(
        "上传技能",
        "# 上传技能\n> 调用规则：测试\n"
        "<script_analyze>\n分析\n</script_analyze>\n"
        "<storyboard_key_elements>\n关键元素\n</storyboard_key_elements>\n",
    )
    entry = registry.resolve_entry("上传技能")
    assert entry is not None
    assert "script_analyze" in entry.available_tools
    assert "storyboard_key_elements" in entry.available_tools
    # 下拉框数据源不变：list_skill_docs 仍返回同一文档
    docs = sd.list_skill_docs()
    assert any(d.get("name") == "上传技能" for d in docs)


def test_edit_refreshes_registry():
    sd.save_skill_doc(
        "编辑技能",
        "# 编辑技能\n> 调用规则：测试\n<script_analyze>\n分析\n</script_analyze>\n",
    )
    assert "script_analyze" in registry.resolve_entry("编辑技能").available_tools
    sd.save_skill_doc(
        "编辑技能",
        "# 编辑技能\n> 调用规则：测试\n<storyboard_shots>\n分镜\n</storyboard_shots>\n",
    )
    entry = registry.resolve_entry("编辑技能")
    assert "script_analyze" not in entry.available_tools
    assert "storyboard_shots" in entry.available_tools


def test_delete_unregisters():
    sd.save_skill_doc(
        "删除技能",
        "# 删除技能\n> 调用规则：测试\n<script_analyze>\n分析\n</script_analyze>\n",
    )
    assert registry.resolve_entry("删除技能") is not None
    sd.delete_skill_doc("删除技能")
    assert registry.resolve_entry("删除技能") is None
