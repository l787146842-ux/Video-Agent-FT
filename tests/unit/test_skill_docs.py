"""Skill 文档化 + write_document 文档工件（Q2 后写入归 FC 工具 document_write）"""
import pytest

import src.video_agent.web.skill_docs as sd
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
    # 批3 单一包形态：<slug>/SKILL.md
    pkg = sd.SKILL_DOCS_DIR / "bom桩"
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "SKILL.md").write_text(
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
    assert (tmp_path / "skills" / "散文桩" / "SKILL.md").read_text(
        encoding="utf-8") == prose
    # 含外来章节 tag → 新建文档补 source 来源标记
    sd.save_skill_doc(
        "章节桩", "# 章节桩\n<resource_prepare_and_analyze>\n分析正文\n"
        "</resource_prepare_and_analyze>\n")
    saved = (tmp_path / "skills" / "章节桩" / "SKILL.md").read_text(encoding="utf-8")
    assert "source: 用户导入" in saved


def test_save_skill_doc_unclosed_header_keeps_original(tmp_path):
    """P2-4②：头部未闭合（收尾 --- 缺失）时不前置新 frontmatter 块，
    保存原文让 lint 警告暴露，避免新块掩盖未闭合头。"""
    content = "---\nversion: '1.0'\n# 未闭合头桩\n正文提及工具名但头部未闭合\n"
    sd.save_skill_doc("未闭合头桩", content)
    assert (tmp_path / "skills" / "未闭合头桩" / "SKILL.md").read_text(
        encoding="utf-8") == content


# ---------- write_document 文档工件 ----------

@pytest.fixture
def svc(tmp_path):
    return StateManager(str(tmp_path / "ws"))


@pytest.mark.asyncio
async def test_write_document_upsert(svc, monkeypatch):
    """Q2 后文本轨退役：文档写入归 FC 工具 document_write（upsert 语义不回归）。"""
    from src.video_agent.tools.document_tools import DocumentWriteTool, WriteDocumentInput

    monkeypatch.setattr(StateManager, "get_instance", classmethod(lambda cls: svc))
    tool = DocumentWriteTool()
    r = await tool.aexecute(WriteDocumentInput(
        name="Final_Video_Spec.md", content="# 规格\n时长: 60s"))
    assert r.success
    docs = svc.state_dict["documents"]
    specs = [d for d in docs if d["name"] == "Final_Video_Spec.md"]
    assert len(specs) == 1  # 规格写入可能附带铁律文档，同名规格仅一条
    assert specs[0]["content"] == "# 规格\n时长: 60s"

    # 同名更新不新增条目（覆盖）
    r2 = await tool.aexecute(WriteDocumentInput(
        name="Final_Video_Spec.md", content="# 规格 v2"))
    assert r2.success and r2.data.get("action") == "updated"
    specs2 = [d for d in svc.state_dict["documents"] if d["name"] == "Final_Video_Spec.md"]
    assert len(specs2) == 1
    assert specs2[0]["content"] == "# 规格 v2"


def test_write_document_schema_requires_fields():
    """Q2 后口径：document_write 输入经 pydantic 严格 schema，
    name/content 字段缺失即校验失败（弱口径空值宽容随文本轨退役）。"""
    from pydantic import ValidationError
    from src.video_agent.tools.document_tools import WriteDocumentInput

    with pytest.raises(ValidationError):
        WriteDocumentInput(content="x")  # 缺 name
    with pytest.raises(ValidationError):
        WriteDocumentInput(name="a.md")  # 缺 content


def test_documents_in_agent_context(svc):
    """文档写入后随 Agent 上下文可见（写入动作归 document_write，
    此处直置状态验上下文组装口径）。"""
    svc.state_dict["documents"] = [
        {"id": "doc-1", "name": "Spec.md", "content": "硬核写实科幻，60 秒"}]
    ctx = svc.build_agent_context("bound")
    assert "Spec.md" in ctx
    assert "硬核写实科幻" in ctx
