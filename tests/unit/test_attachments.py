"""附件链路：文档正文注入 LLM、资产绑定、路径穿越防护"""
import pytest

import src.video_agent.web.routes.agent as agent_route
from src.video_agent.state.manager import StateManager


@pytest.fixture
def assets_dir(tmp_path, monkeypatch):
    d = tmp_path / "assets"
    d.mkdir()
    monkeypatch.setattr(agent_route, "UPLOAD_ASSETS_DIR", d)
    return d


def test_md_content_injected(assets_dir):
    (assets_dir / "story.md").write_text("# 太阳系二维化\n二向箔来袭。", encoding="utf-8")
    ctx = agent_route._attachment_context([
        {"name": "太阳系逐渐二维化.md", "url": "/workspace/assets/story.md", "kind": "doc"},
    ])
    assert "太阳系二维化" in ctx
    assert "二向箔来袭" in ctx
    assert "素材文档《太阳系逐渐二维化.md》全文" in ctx


def test_long_doc_truncated(assets_dir):
    (assets_dir / "big.txt").write_text("x" * 50000, encoding="utf-8")
    ctx = agent_route._attachment_context([
        {"name": "big.txt", "url": "/workspace/assets/big.txt", "kind": "doc"},
    ])
    assert "已截断" in ctx
    assert len(ctx) < 50000


def test_missing_doc_reported(assets_dir):
    ctx = agent_route._attachment_context([
        {"name": "ghost.md", "url": "/workspace/assets/ghost.md", "kind": "doc"},
    ])
    assert "未在服务器上找到" in ctx


def test_path_traversal_blocked(assets_dir, tmp_path):
    # assets 目录之外的敏感文件
    secret = tmp_path / "secret.md"
    secret.write_text("TOP-SECRET", encoding="utf-8")
    ctx = agent_route._attachment_context([
        {"name": "x.md", "url": "/workspace/assets/../secret.md", "kind": "doc"},
    ])
    # basename 化后指向 assets/secret.md（不存在），绝不能读到外部文件
    assert "TOP-SECRET" not in ctx


def test_image_attachment_noted(assets_dir):
    (assets_dir / "ref.png").write_bytes(b"\x89PNG")
    ctx = agent_route._attachment_context([
        {"name": "参考图.png", "url": "/workspace/assets/ref.png", "kind": "image"},
    ])
    assert "参考图.png" in ctx
    assert "参考图/引用资产" in ctx


def test_pdf_capability_notice(assets_dir):
    (assets_dir / "doc.pdf").write_bytes(b"%PDF")
    ctx = agent_route._attachment_context([
        {"name": "剧本.pdf", "url": "/workspace/assets/doc.pdf", "kind": "doc"},
    ])
    assert "暂不支持解析" in ctx


def test_bind_attachments_persists(tmp_path):
    svc = StateManager(str(tmp_path))
    agent_route._bind_attachments(svc, [
        {"id": "ast-1", "name": "story.md", "url": "/workspace/assets/story.md", "kind": "doc"},
    ])
    asset = next(a for a in svc.state_dict["assets"] if a["url"] == "/workspace/assets/story.md")
    assert asset["isBound"] is True
    assert asset["type"] == "doc"
    # 重复绑定不产生重复条目
    agent_route._bind_attachments(svc, [
        {"name": "story.md", "url": "/workspace/assets/story.md", "kind": "doc"},
    ])
    assert sum(1 for a in svc.state_dict["assets"] if a["url"] == "/workspace/assets/story.md") == 1
