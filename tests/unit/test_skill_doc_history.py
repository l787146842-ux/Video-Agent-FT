"""Skill 文档版本历史：保存自动备份 + 列表 + 裁剪"""
import pytest

from src.video_agent.web import skill_docs


@pytest.fixture(autouse=True)
def _tmp_skill_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(skill_docs, "SKILL_DOCS_DIR", tmp_path)
    return tmp_path


def _save(slug, content):
    skill_docs.save_skill_doc(slug, content)


class TestSkillDocHistory:
    def test_first_save_no_history(self):
        _save("demo", "# v1")
        assert skill_docs.list_skill_doc_history("demo") == []

    def test_overwrite_creates_history(self):
        _save("demo", "# v1")
        _save("demo", "# v2")
        versions = skill_docs.list_skill_doc_history("demo")
        assert len(versions) == 1
        assert versions[0]["content"] == "# v1"

    def test_history_order_newest_first(self):
        _save("demo", "# v1")
        _save("demo", "# v2")
        _save("demo", "# v3")
        versions = skill_docs.list_skill_doc_history("demo")
        assert [v["content"] for v in versions][:2] == ["# v2", "# v1"]

    def test_history_pruned_to_max(self):
        for i in range(skill_docs._HISTORY_MAX + 3):
            _save("demo", f"# v{i}")
        versions = skill_docs.list_skill_doc_history("demo")
        assert len(versions) == skill_docs._HISTORY_MAX

    def test_invalid_slug_rejected(self):
        with pytest.raises(ValueError):
            skill_docs.list_skill_doc_history("../escape")
