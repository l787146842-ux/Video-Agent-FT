"""集成测试：/api/agent/chat 端到端（使用 FastAPI TestClient）

演示兜底已彻底删除：聊天链路经 stub 适配器/Planner 验证传输与持久化契约，
未配置供应商时明确报错（PROVIDER_NOT_CONFIGURED）。
"""
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from src.video_agent.web.app import app
from src.video_agent.state.manager import StateManager


@pytest.fixture(autouse=True)
def reset_state(tmp_path, monkeypatch):
    """每个测试使用独立的临时工作区"""
    monkeypatch.setenv("WORKSPACE_DIR", str(tmp_path))
    StateManager.reset_instance()
    svc = StateManager(str(tmp_path))
    # 注入单例
    StateManager._instance = svc
    yield svc
    StateManager.reset_instance()


@pytest.fixture
def client():
    return TestClient(app)


def _stub_chat_planner(monkeypatch, reply_text: str = "stub 回答"):
    """stub 聊天链路内部（适配器端点解析 + Planner 循环），保传输/持久化契约。

    与 test_truncate_resend 的流式 stub 同模式：不触网、不依赖任何供应商配置。
    """
    import src.video_agent.web.chat_service as cs

    monkeypatch.setattr(cs, "_create_chat_adapter", lambda p, m: object())
    monkeypatch.setattr(cs, "_resolve_summary_adapter", lambda body, cands: None)

    async def fake_handle_message(self, content, ctx, on_event=None):  # noqa: ARG001
        return SimpleNamespace(
            text=reply_text, applied_actions=0, steps=1, warnings=[],
            confirmation="", action_log=[], confirmation_options=[],
            pause_id="", pause_kind="", image_urls=[], documents_written=[],
            suggested_actions=None,
        )

    monkeypatch.setattr(cs.Planner, "handle_message", fake_handle_message)


class TestAgentChatContract:
    """错误契约出口（ErrorPayload 三层 + 兼容字段）"""

    def test_empty_message_rejected(self, client):
        resp = client.post("/api/agent/chat", json={"message": "", "provider": "provA"})
        assert resp.status_code == 400

    def test_empty_message_error_payload(self, client):
        """P9：空消息 400 出口走 ErrorPayload 契约（三层 + 兼容字段）"""
        resp = client.post("/api/agent/chat", json={"message": "", "provider": "provA"})
        body = resp.json()
        assert body["detail"] == "消息不能为空"
        assert body["message"] == "消息不能为空"
        assert body["error_code"] == "EMPTY_MESSAGE"
        assert body["kind"] == "unknown"
        assert body["code"] == "err.unknown.empty_message"
        assert "raw" not in body

    def test_value_error_error_payload(self, client, monkeypatch):
        """P9：ValueError→400 契约出口（友好文案 + error_code，状态码不变）"""
        import src.video_agent.web.routes.agent as agent_mod

        async def _boom(body):  # noqa: ARG001
            raise ValueError("参数不合法")

        monkeypatch.setattr(agent_mod, "non_stream_worker", _boom)
        resp = client.post("/api/agent/chat", json={"message": "你好"})
        assert resp.status_code == 400
        body = resp.json()
        assert body["detail"] == "参数不合法"
        assert body["error_code"] == "VALIDATION_ERROR"
        assert body["code"] == "err.unknown.validation_error"
        assert body["kind"] == "unknown"

    def test_adapter_error_error_payload(self, client, monkeypatch):
        """P9：上游失败→502 契约出口（归类到 auth，raw 可空，状态码不变）"""
        import src.video_agent.web.routes.agent as agent_mod
        from src.video_agent.exceptions import AdapterError

        async def _boom(body):  # noqa: ARG001
            raise AdapterError("LLM 返回 HTTP 401: invalid key", http_status=401)

        monkeypatch.setattr(agent_mod, "non_stream_worker", _boom)
        resp = client.post("/api/agent/chat", json={"message": "你好"})
        assert resp.status_code == 502
        body = resp.json()
        assert body["detail"] == "LLM 返回 HTTP 401: invalid key"
        assert body["error_code"] == "ADAPTER_ERROR"
        assert body["kind"] == "auth"
        assert body["code"] == "err.auth.invalid_key"

    def test_provider_not_configured_error_payload(self, client):
        """批次F：未配置聊天供应商 → 400 明确报错（不再有演示兜底），
        错误码走既有 ErrorPayload 分类机制（前端据此挂「检查 API 配置」按钮）"""
        resp = client.post("/api/agent/chat", json={"message": "你好", "provider": ""})
        assert resp.status_code == 400
        body = resp.json()
        assert "配置聊天供应商" in body["detail"]
        assert body["error_code"] == "PROVIDER_NOT_CONFIGURED"
        assert body["kind"] == "unknown"
        assert body["code"] == "err.unknown.provider_not_configured"


class TestAgentChatBehavior:
    """聊天链路行为（stub 适配器/Planner，不触网）"""

    def test_chat_history_persisted(self, client, reset_state, monkeypatch):
        """对话应被持久化到 chatMessages"""
        _stub_chat_planner(monkeypatch)
        resp = client.post("/api/agent/chat", json={
            "message": "你好",
            "provider": "provA",
            "model": "model-A",
        })
        assert resp.status_code == 200
        messages = reset_state.get_chat_messages()
        # 至少有 user + agent 两条
        assert len(messages) >= 2
        assert messages[-2]["sender"] == "user"
        assert messages[-1]["sender"] == "agent"

    def test_context_mode_none_skips_context_injection(self, client, reset_state, monkeypatch):
        """context_mode=none 时不注入工作台上下文，state 不下发（非流式同构）"""
        _stub_chat_planner(monkeypatch)
        resp = client.post("/api/agent/chat", json={
            "message": "纯文本对话",
            "provider": "provA",
            "model": "model-A",
            "context_mode": "none",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "text" in data
        assert data.get("state") is None

    def test_selected_draft_context(self, client, reset_state, monkeypatch):
        """选中态参数应被接受"""
        _stub_chat_planner(monkeypatch)
        resp = client.post("/api/agent/chat", json={
            "message": "确认这个草稿",
            "provider": "provA",
            "model": "model-A",
            "selected_draft_id": "ke-1-d1",
            "selected_type": "keyElement",
        })
        assert resp.status_code == 200


class TestAgentChatValidation:
    """请求校验"""

    def test_missing_message_field_returns_422(self, client):
        """缺少必填字段 message 时 FastAPI 返回 422 验证错误"""
        resp = client.post("/api/agent/chat", json={"provider": "provA"})
        # message 是必填字段，缺失时 FastAPI 返回 422
        assert resp.status_code == 422
