"""POST /api/skills/assistant 契约测试（mock adapter，不触网）。

验证：代码块提取 / 无代码块回落 null / LLM 失败回落 null。
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.video_agent.web.routes import plugins as pr


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(pr.router, prefix="/api")
    return TestClient(app)


class _FakeResult:
    def __init__(self, text: str):
        self.text = text


class _FakeAdapter:
    def __init__(self, text: str):
        self._text = text

    async def generate(self, messages, temperature=0.3):  # noqa: ARG002
        return _FakeResult(self._text)


class _BoomAdapter:
    async def generate(self, messages, temperature=0.3):  # noqa: ARG002
        raise RuntimeError("boom")


def test_extract_skill_block_last_block_wins():
    text = "说明\n```markdown\n# 旧\n```\n再改一版\n```markdown\n# 新 Skill\n\n> 调用规则：x\n```\n"
    out = pr._extract_skill_block(text)
    assert out is not None and "# 新 Skill" in out


def test_extract_skill_block_no_block():
    assert pr._extract_skill_block("普通回复，没有代码块") is None


def test_extract_skill_block_block_without_title():
    assert pr._extract_skill_block("```markdown\n纯散文\n```") is None


def test_route_returns_content(client, monkeypatch):
    monkeypatch.setattr(
        pr, "_resolve_chat_adapter",
        lambda provider, model: _FakeAdapter(
            "已优化。\n```markdown\n# 探针 Skill\n\n> 调用规则：x\n```"),
    )
    resp = client.post("/api/skills/assistant", json={
        "content": "# 旧\n", "messages": [{"role": "user", "content": "改标题"}],
    })
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["content"] and "# 探针 Skill" in data["content"]
    assert "已优化" in data["reply"]


def test_route_no_block_content_null(client, monkeypatch):
    monkeypatch.setattr(
        pr, "_resolve_chat_adapter",
        lambda provider, model: _FakeAdapter("你的请求不明确，保持原文。"),
    )
    resp = client.post("/api/skills/assistant", json={
        "content": "# 旧\n", "messages": [{"role": "user", "content": "嗯"}],
    })
    assert resp.status_code == 200, resp.text
    assert resp.json()["content"] is None


def test_route_llm_failure_content_null(client, monkeypatch):
    monkeypatch.setattr(
        pr, "_resolve_chat_adapter",
        lambda provider, model: _BoomAdapter(),
    )
    resp = client.post("/api/skills/assistant", json={
        "content": "# 旧\n", "messages": [{"role": "user", "content": "改"}],
    })
    assert resp.status_code == 200, resp.text
    assert resp.json()["content"] is None


def test_route_empty_body_400(client):
    resp = client.post("/api/skills/assistant", json={"content": "", "messages": []})
    assert resp.status_code == 400
