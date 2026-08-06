"""附件链路：文档清单注入（正文按需检索）、资产绑定、路径穿越防护"""
import pytest

import src.video_agent.web.attachments as attachments_mod
from src.video_agent.web.attachments import (
    attachment_context, bind_attachments, store_uploaded_docs,
)
from src.video_agent.state.manager import StateManager


@pytest.fixture
def assets_dir(tmp_path, monkeypatch):
    d = tmp_path / "assets"
    d.mkdir()
    monkeypatch.setattr(attachments_mod, "ASSETS_DIR", d)
    return d


def test_md_manifest_injected_not_full_text(assets_dir):
    """新契约：文本附件只注入清单（名称/字数/预览），正文靠 read_uploaded_doc 检索"""
    (assets_dir / "story.md").write_text("# 太阳系二维化\n二向箔来袭。", encoding="utf-8")
    ctx = attachment_context([
        {"name": "太阳系逐渐二维化.md", "url": "/workspace/assets/story.md", "kind": "doc"},
    ])
    assert "太阳系逐渐二维化.md" in ctx
    assert "已存档" in ctx and "read_uploaded_doc" in ctx
    # 不再以「=== 全文 ===」段落形式注入正文
    assert "=== 文档结束 ===" not in ctx


def test_long_doc_manifest_small(assets_dir):
    """超大文档的清单注入体积恒定（预览 200 字上限），不再随正文长度膨胀"""
    (assets_dir / "big.txt").write_text("x" * 50000, encoding="utf-8")
    ctx = attachment_context([
        {"name": "big.txt", "url": "/workspace/assets/big.txt", "kind": "doc"},
    ])
    assert "50000 字" in ctx
    assert len(ctx) < 1000


def test_store_uploaded_docs_persists_content(assets_dir, tmp_path):
    """文本附件正文存入 state.uploadedDocs（同名覆盖），供按需检索"""
    (assets_dir / "story.md").write_text("剧本正文 A", encoding="utf-8")
    svc = StateManager(str(tmp_path))
    store_uploaded_docs(svc, [
        {"id": "att-1", "name": "剧本.md", "url": "/workspace/assets/story.md", "kind": "doc"},
    ])
    docs = svc.state_dict["uploadedDocs"]
    assert len(docs) == 1 and docs[0]["content"] == "剧本正文 A"
    # 同名重传：覆盖不新增
    (assets_dir / "story.md").write_text("剧本正文 B", encoding="utf-8")
    store_uploaded_docs(svc, [
        {"name": "剧本.md", "url": "/workspace/assets/story.md", "kind": "doc"},
    ])
    assert len(svc.state_dict["uploadedDocs"]) == 1
    assert svc.state_dict["uploadedDocs"][0]["content"] == "剧本正文 B"


def test_missing_doc_reported(assets_dir):
    ctx = attachment_context([
        {"name": "ghost.md", "url": "/workspace/assets/ghost.md", "kind": "doc"},
    ])
    assert "未在服务器上找到" in ctx


def test_path_traversal_blocked(assets_dir, tmp_path):
    # assets 目录之外的敏感文件
    secret = tmp_path / "secret.md"
    secret.write_text("TOP-SECRET", encoding="utf-8")
    ctx = attachment_context([
        {"name": "x.md", "url": "/workspace/assets/../secret.md", "kind": "doc"},
    ])
    # basename 化后指向 assets/secret.md（不存在），绝不能读到外部文件
    assert "TOP-SECRET" not in ctx


def test_image_attachment_noted(assets_dir):
    (assets_dir / "ref.png").write_bytes(b"\x89PNG")
    ctx = attachment_context([
        {"name": "参考图.png", "url": "/workspace/assets/ref.png", "kind": "image"},
    ])
    assert "参考图.png" in ctx
    assert "参考图/引用资产" in ctx


def test_pdf_capability_notice(assets_dir):
    """无效/损坏 PDF：抽取出空时降级提示用户，不假装读到内容"""
    (assets_dir / "doc.pdf").write_bytes(b"%PDF")
    ctx = attachment_context([
        {"name": "剧本.pdf", "url": "/workspace/assets/doc.pdf", "kind": "doc"},
    ])
    assert "未抽取出文本内容" in ctx
    assert "剧本.pdf" in ctx


# 手工构造的最小合法 PDF（含文本层 "HELLO PDF"），验证真实抽取链路
_MINIMAL_PDF = (
    b"%PDF-1.4\n"
    b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n"
    b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n"
    b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] "
    b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >> endobj\n"
    b"4 0 obj << /Length 44 >> stream\n"
    b"BT /F1 12 Tf 50 100 Td (HELLO PDF) Tj ET\n"
    b"endstream\nendobj\n"
    b"5 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n"
    b"trailer << /Root 1 0 R /Size 6 >>\n%%EOF"
)


def test_pdf_text_extracted_and_archived(assets_dir, tmp_path):
    """PDF 剧本：服务端抽取文本层，与 .md/.txt 同等对待（清单注入 + uploadedDocs 存档）"""
    (assets_dir / "script.pdf").write_bytes(_MINIMAL_PDF)
    ctx = attachment_context([
        {"name": "剧本.pdf", "url": "/workspace/assets/script.pdf", "kind": "doc"},
    ])
    assert "已存档" in ctx and "read_uploaded_doc" in ctx
    assert "未抽取出文本内容" not in ctx

    svc = StateManager(str(tmp_path))
    store_uploaded_docs(svc, [
        {"name": "剧本.pdf", "url": "/workspace/assets/script.pdf", "kind": "doc"},
    ])
    docs = svc.state_dict["uploadedDocs"]
    assert len(docs) == 1
    assert "HELLO PDF" in docs[0]["content"]


def test_bind_attachments_persists(tmp_path):
    svc = StateManager(str(tmp_path))
    bind_attachments(svc, [
        {"id": "ast-1", "name": "story.md", "url": "/workspace/assets/story.md", "kind": "doc"},
    ])
    asset = next(a for a in svc.state_dict["assets"] if a["url"] == "/workspace/assets/story.md")
    assert asset["isBound"] is True
    assert asset["type"] == "doc"
    # 重复绑定不产生重复条目
    bind_attachments(svc, [
        {"name": "story.md", "url": "/workspace/assets/story.md", "kind": "doc"},
    ])
    assert sum(1 for a in svc.state_dict["assets"] if a["url"] == "/workspace/assets/story.md") == 1
