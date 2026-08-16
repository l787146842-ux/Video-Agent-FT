"""Skill 文档化 + write_document 文档工件"""
import pytest

import src.video_agent.web.skill_docs as sd
from src.video_agent.web.action_executor import StudioActionExecutor
from src.video_agent.state.manager import StateManager


@pytest.fixture(autouse=True)
def isolate_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(sd, "SKILL_DOCS_DIR", tmp_path / "skills")
    yield


def test_default_doc_created_and_parsed():
    docs = sd.list_skill_docs()
    assert len(docs) == 1
    d = docs[0]
    assert d["slug"] == sd.DEFAULT_SKILL_SLUG
    assert d["name"] == "剧本生视频（需上传剧本）"
    assert "调用规则" in d["description"]
    assert "铁律" in d["content"]


def test_save_and_get_roundtrip():
    sd.save_skill_doc("my-skill", "# 我的技能\n> 调用规则：测试\n正文")
    doc = sd.get_skill_doc("my-skill")
    assert doc["name"] == "我的技能"
    assert doc["description"] == "调用规则：测试"


def test_slug_traversal_rejected():
    with pytest.raises(ValueError):
        sd.save_skill_doc("../evil", "x")
    with pytest.raises(ValueError):
        sd.get_skill_doc("a/b")
    with pytest.raises(ValueError):
        sd.save_skill_doc("..", "x")


def test_empty_content_rejected():
    with pytest.raises(ValueError):
        sd.save_skill_doc("ok-name", "   ")


# ---------- write_document 文档工件 ----------

@pytest.fixture
def svc(tmp_path):
    return StateManager(str(tmp_path / "ws"))


def test_write_document_upsert(svc):
    ex = StudioActionExecutor(svc)
    assert ex.execute([{"action": "write_document", "name": "Final_Video_Spec.md",
                        "content": "# 规格\n时长: 60s"}]) == 1
    docs = svc.state_dict["documents"]
    assert len(docs) == 1 and docs[0]["name"] == "Final_Video_Spec.md"
    assert ex.documents_written == ["Final_Video_Spec.md"]

    # 同名更新不新增条目
    assert ex.execute([{"action": "write_document", "name": "Final_Video_Spec.md",
                        "content": "# 规格 v2"}]) == 1
    assert len(svc.state_dict["documents"]) == 1
    assert svc.state_dict["documents"][0]["content"] == "# 规格 v2"
    assert ex.documents_written == ["Final_Video_Spec.md"]  # 去重


def test_write_document_requires_name_and_content(svc):
    ex = StudioActionExecutor(svc)
    assert ex.execute([{"action": "write_document", "name": "", "content": "x"}]) == 0
    assert ex.execute([{"action": "write_document", "name": "a.md", "content": "  "}]) == 0


def test_documents_in_agent_context(svc):
    ex = StudioActionExecutor(svc)
    ex.execute([{"action": "write_document", "name": "Spec.md", "content": "硬核写实科幻，60 秒"}])
    ctx = svc.build_agent_context("bound")
    assert "Spec.md" in ctx
    assert "硬核写实科幻" in ctx
