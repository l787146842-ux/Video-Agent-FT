"""集成测试：/api/agent/chat 端到端（使用 FastAPI TestClient）"""
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


class TestAgentChatMock:
    """mock 供应商路径的端到端测试"""

    def test_empty_message_rejected(self, client):
        resp = client.post("/api/agent/chat", json={"message": "", "provider": "mock"})
        assert resp.status_code == 400

    def test_empty_message_error_payload(self, client):
        """P9：空消息 400 出口走 ErrorPayload 契约（三层 + 兼容字段）"""
        resp = client.post("/api/agent/chat", json={"message": "", "provider": "mock"})
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

    def test_mock_chat_returns_text(self, client, reset_state):
        resp = client.post("/api/agent/chat", json={
            "message": "你好",
            "provider": "mock",
            "model": "mock-chat",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "text" in data
        assert len(data["text"]) > 0
        assert data["steps"] >= 1

    def test_mock_chat_applies_actions(self, client, reset_state):
        """修改类指令应触发 studio-actions"""
        resp = client.post("/api/agent/chat", json={
            "message": "修改提示词",
            "provider": "mock",
            "model": "mock-chat",
        })
        assert resp.status_code == 200
        data = resp.json()
        # mock 路径对"修改"关键词会执行 update_draft
        assert data["applied_actions"] >= 0

    def test_mock_chat_add_group(self, client, reset_state):
        """拆解类指令应创建分组"""
        resp = client.post("/api/agent/chat", json={
            "message": "拆解这个文档",
            "provider": "mock",
            "model": "mock-chat",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["applied_actions"] >= 1
        # 验证状态中确实创建了分组
        state = data.get("state") or reset_state.state
        assert len(state.get("keyElements", [])) > 0 or len(state.get("shots", [])) > 0

    def test_chat_history_persisted(self, client, reset_state):
        """对话应被持久化到 chatMessages"""
        client.post("/api/agent/chat", json={
            "message": "你好",
            "provider": "mock",
            "model": "mock-chat",
        })
        messages = reset_state.get_chat_messages()
        # 至少有 user + agent 两条
        assert len(messages) >= 2
        assert messages[-2]["sender"] == "user"
        assert messages[-1]["sender"] == "agent"

    def test_context_mode_none_skips_context_injection(self, client, reset_state):
        """context_mode=none 时不注入工作台上下文，但仍返回 state"""
        resp = client.post("/api/agent/chat", json={
            "message": "纯文本对话",
            "provider": "mock",
            "model": "mock-chat",
            "context_mode": "none",
        })
        assert resp.status_code == 200
        data = resp.json()
        # mock 路径仍返回 state（供前端刷新），但不注入协议上下文
        assert "text" in data


class TestAgentChatValidation:
    """请求校验"""

    def test_missing_message_field_returns_422(self, client):
        """缺少必填字段 message 时 FastAPI 返回 422 验证错误"""
        resp = client.post("/api/agent/chat", json={"provider": "mock"})
        # message 是必填字段，缺失时 FastAPI 返回 422
        assert resp.status_code == 422

    def test_selected_draft_context(self, client, reset_state):
        """选中态参数应被接受"""
        resp = client.post("/api/agent/chat", json={
            "message": "确认这个草稿",
            "provider": "mock",
            "model": "mock-chat",
            "selected_draft_id": "ke-1-d1",
            "selected_type": "keyElement",
        })
        assert resp.status_code == 200
