"""Skill 分册（references/）读写回归（2026-11-11 裁决）。

事故：references/ 此前只对 read_skill 开放，Skill 工作台完全看不到分册——
用户无法查看/编辑/新增分册，等于分册「存在但不可维护」。

本文件钉死存储层的列表/读/写/删与安全校验。
"""
import pytest

import src.video_agent.web.skill_docs as sd
from src.video_agent.skill_runtime import registry

DOC = (
    "---\nname: 分册用例\ndescription: 分册读写用例\n---\n"
    "# 分册用例\n\n## 一、制作流程\n\n读 `references/媒体生成.md`。\n"
)


@pytest.fixture
def skills_dir(tmp_path, monkeypatch):
    d = tmp_path / "skills"
    d.mkdir()
    monkeypatch.setattr(sd, "SKILL_DOCS_DIR", d)
    registry.reset_registry()
    sd.save_skill_doc("分册用例", DOC)
    yield d
    registry.reset_registry()


def test_list_refs_empty_when_no_dir(skills_dir):
    """无 references/ 目录 = 零分册（合法，不报错）。"""
    assert sd.list_skill_refs("分册用例") == []


def test_save_and_list_ref(skills_dir):
    sd.save_skill_ref("分册用例", "媒体生成.md", "# 媒体生成\n\n正文 REF_BODY\n")
    refs = sd.list_skill_refs("分册用例")
    assert [r["name"] for r in refs] == ["媒体生成.md"]
    assert refs[0]["title"] == "媒体生成"
    assert refs[0]["chars"] > 0


def test_get_ref_returns_content(skills_dir):
    sd.save_skill_ref("分册用例", "媒体生成.md", "# 媒体生成\n\n正文 REF_BODY\n")
    ref = sd.get_skill_ref("分册用例", "媒体生成.md")
    assert ref is not None and "REF_BODY" in ref["content"]


def test_get_missing_ref_returns_none(skills_dir):
    assert sd.get_skill_ref("分册用例", "不存在.md") is None


def test_save_ref_overwrites(skills_dir):
    sd.save_skill_ref("分册用例", "媒体生成.md", "# 旧\nOLD\n")
    sd.save_skill_ref("分册用例", "媒体生成.md", "# 新\nNEW\n")
    ref = sd.get_skill_ref("分册用例", "媒体生成.md")
    assert "NEW" in ref["content"] and "OLD" not in ref["content"]


def test_delete_ref(skills_dir):
    sd.save_skill_ref("分册用例", "媒体生成.md", "# 媒体生成\n正文\n")
    sd.delete_skill_ref("分册用例", "媒体生成.md")
    assert sd.list_skill_refs("分册用例") == []
    with pytest.raises(ValueError):
        sd.delete_skill_ref("分册用例", "媒体生成.md")


def test_ref_requires_existing_skill(skills_dir):
    """分册必须挂在已存在的 Skill 下（不能凭空造出孤立目录）。"""
    with pytest.raises(ValueError):
        sd.save_skill_ref("不存在的Skill", "媒体生成.md", "# x\n正文\n")


@pytest.mark.parametrize("bad", [
    "../逃逸.md", "sub/dir.md", "sub\\dir.md", "..", ".", "", "无后缀", "a.txt",
])
def test_ref_name_rejects_traversal_and_non_md(skills_dir, bad):
    """分册名禁止路径上跳/子目录/非 .md（fail-closed）。"""
    with pytest.raises(ValueError):
        sd.save_skill_ref("分册用例", bad, "# x\n正文\n")


def test_empty_ref_content_rejected(skills_dir):
    with pytest.raises(ValueError):
        sd.save_skill_ref("分册用例", "媒体生成.md", "   ")


def test_saved_ref_enters_resource_manifest(skills_dir):
    """保存分册后注册表资源清单同步刷新（read_skill 白名单即时生效）。"""
    sd.save_skill_ref("分册用例", "媒体生成.md", "# 媒体生成\n正文\n")
    entry = registry.get_entry("分册用例")
    assert entry is not None
    assert "references/媒体生成.md" in entry.resource_manifest
