"""Skill 文档化 + write_document 文档工件"""
import pytest

import src.video_agent.web.skill_docs as sd
from src.video_agent.web.action_executor import StateOperationExecutor
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
    # description 剥离「调用规则：」前缀（Picker/结构化视图展示纯描述）
    assert "调用规则" not in d["description"]
    assert "用户上传剧本" in d["description"]
    assert "铁律" in d["content"]


def test_save_and_get_roundtrip():
    sd.save_skill_doc("my-skill", "# 我的技能\n> 调用规则：测试\n正文")
    doc = sd.get_skill_doc("my-skill")
    assert doc["name"] == "我的技能"
    assert doc["description"] == "测试"


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


# ---------- 正确性审查（Ryan）P2 批：frontmatter 交互修复钉 ----------

def test_parse_doc_ignores_yaml_comment_title():
    """P2-3：_parse_doc 在剥离 frontmatter 后的正文上找标题，
    YAML 注释行（# ...）不再污染显示名。"""
    content = (
        "---\n# 这是 YAML 注释行，不是标题\nversion: '1.0'\n---\n"
        "# 真实标题\n> 调用规则：测试\n正文"
    )
    doc = sd._parse_doc("注释名桩", content)
    assert doc["name"] == "真实标题"
    assert doc["description"] == "测试"
    assert doc["content"] == content  # 全文原样返回


def test_get_skill_doc_reads_bom_file(tmp_path):
    """P2-2：Windows 记事本带 BOM 回存的 md 照常解析标题/描述。"""
    sd.SKILL_DOCS_DIR.mkdir(parents=True, exist_ok=True)
    (sd.SKILL_DOCS_DIR / "bom桩.md").write_text(
        "\ufeff# BOM 标题\n> 调用规则：测试\n正文", encoding="utf-8")
    doc = sd.get_skill_doc("bom桩")
    assert doc is not None and doc["name"] == "BOM 标题"
    assert doc["description"] == "测试"


def test_save_skill_doc_foreign_requires_section_tag(tmp_path):
    """P2-4①：外来章节判定与 lint 口径一致（f\"<{t}>\" 存在），
    正文散文里提及工具名不标为外来（裸子串误报清偿）。"""
    # 散文提及工具名（无章节 tag）→ 保存逐字节忠实，不注 source
    prose = "# 散文桩\n正文提及 resource_prepare_and_analyze 工具名\n"
    sd.save_skill_doc("散文桩", prose)
    assert (tmp_path / "skills" / "散文桩.md").read_text(
        encoding="utf-8") == prose
    # 含外来章节 tag → 新建文档补 source 来源标记
    sd.save_skill_doc(
        "章节桩", "# 章节桩\n<resource_prepare_and_analyze>\n分析正文\n"
        "</resource_prepare_and_analyze>\n")
    saved = (tmp_path / "skills" / "章节桩.md").read_text(encoding="utf-8")
    assert "source: 用户导入" in saved


def test_save_skill_doc_unclosed_header_keeps_original(tmp_path):
    """P2-4②：头部未闭合（收尾 --- 缺失）时不前置新 frontmatter 块，
    保存原文让 lint 警告暴露，避免新块掩盖未闭合头。"""
    content = "---\nversion: '1.0'\n# 未闭合头桩\n正文提及工具名但头部未闭合\n"
    sd.save_skill_doc("未闭合头桩", content)
    assert (tmp_path / "skills" / "未闭合头桩.md").read_text(
        encoding="utf-8") == content


# ---------- write_document 文档工件 ----------

@pytest.fixture
def svc(tmp_path):
    return StateManager(str(tmp_path / "ws"))


def test_write_document_upsert(svc):
    ex = StateOperationExecutor(svc)
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
    ex = StateOperationExecutor(svc)
    assert ex.execute([{"action": "write_document", "name": "", "content": "x"}]) == 0
    assert ex.execute([{"action": "write_document", "name": "a.md", "content": "  "}]) == 0


def test_documents_in_agent_context(svc):
    ex = StateOperationExecutor(svc)
    ex.execute([{"action": "write_document", "name": "Spec.md", "content": "硬核写实科幻，60 秒"}])
    ctx = svc.build_agent_context("bound")
    assert "Spec.md" in ctx
    assert "硬核写实科幻" in ctx
