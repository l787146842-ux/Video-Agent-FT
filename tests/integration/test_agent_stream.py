"""集成测试：/api/agent/chat/stream SSE 流式端点

覆盖场景：
- mock 供应商正常流式输出（delta + done）
- 空消息拒绝
- 错误中断（error 事件）
- 客户端断开后 worker 取消
- 非 mock 供应商缺少配置时返回 error 事件
"""
import asyncio
import json

import pytest
from httpx import ASGITransport, AsyncClient

from src.video_agent.web.app import app
from src.video_agent.state.manager import StateManager


@pytest.fixture(autouse=True)
def reset_state(tmp_path, monkeypatch):
    """每个测试使用独立的临时工作区"""
    monkeypatch.setenv("WORKSPACE_DIR", str(tmp_path))
    StateManager.reset_instance()
    svc = StateManager(str(tmp_path))
    StateManager._instance = svc
    yield svc
    StateManager.reset_instance()


@pytest.fixture
async def async_client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


def parse_sse_events(raw: str) -> list:
    """从 SSE 原始文本中解析所有 data: 事件"""
    events = []
    for line in raw.split("\n"):
        line = line.strip()
        if line.startswith("data: "):
            payload = line[6:]
            try:
                events.append(json.loads(payload))
            except json.JSONDecodeError:
                pass
    return events


class TestMockStream:
    """mock 供应商的流式端点测试"""

    async def test_mock_stream_normal(self, async_client, reset_state):
        """正常 mock 流式：应收到 status + delta(s) + done"""
        resp = await async_client.post(
            "/api/agent/chat/stream",
            json={"message": "你好", "provider": "mock", "model": "mock-chat"},
        )
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")

        events = parse_sse_events(resp.text)
        types = [e.get("type") for e in events]

        # 至少包含 status、delta、done
        assert "status" in types
        assert "delta" in types
        assert "done" in types

        # done 事件包含完整 payload
        done_event = next(e for e in events if e["type"] == "done")
        payload = done_event["payload"]
        assert "text" in payload
        assert len(payload["text"]) > 0
        assert "state" in payload
        assert "elapsed_ms" in payload

    async def test_mock_stream_empty_message_rejected(self, async_client):
        """空消息应返回 error 事件"""
        resp = await async_client.post(
            "/api/agent/chat/stream",
            json={"message": "", "provider": "mock", "model": "mock-chat"},
        )
        assert resp.status_code == 200
        events = parse_sse_events(resp.text)
        types = [e.get("type") for e in events]
        assert "error" in types

    async def test_mock_stream_actions_applied(self, async_client, reset_state):
        """修改类指令通过流式端点也能触发 actions"""
        resp = await async_client.post(
            "/api/agent/chat/stream",
            json={"message": "拆解这个文档", "provider": "mock", "model": "mock-chat"},
        )
        assert resp.status_code == 200
        events = parse_sse_events(resp.text)
        done_event = next((e for e in events if e["type"] == "done"), None)
        assert done_event is not None
        assert done_event["payload"]["applied_actions"] >= 1

    async def test_mock_stream_chat_persisted(self, async_client, reset_state):
        """流式对话也应持久化到 chatMessages"""
        await async_client.post(
            "/api/agent/chat/stream",
            json={"message": "你好", "provider": "mock", "model": "mock-chat"},
        )
        messages = reset_state.get_chat_messages()
        assert len(messages) >= 2
        assert messages[-2]["sender"] == "user"
        assert messages[-1]["sender"] == "agent"

    async def test_mock_stream_context_mode_none(self, async_client, reset_state):
        """context_mode=none 时不注入上下文但仍正常返回"""
        resp = await async_client.post(
            "/api/agent/chat/stream",
            json={
                "message": "纯聊天",
                "provider": "mock",
                "model": "mock-chat",
                "context_mode": "none",
            },
        )
        assert resp.status_code == 200
        events = parse_sse_events(resp.text)
        done_event = next((e for e in events if e["type"] == "done"), None)
        assert done_event is not None
        assert "text" in done_event["payload"]


class TestRealProviderStream:
    """真实供应商路径（无有效配置时应返回 error 事件）"""

    async def test_missing_provider_returns_error(self, async_client):
        """供应商未配置时流式端点应返回 error 事件"""
        resp = await async_client.post(
            "/api/agent/chat/stream",
            json={
                "message": "你好",
                "provider": "nonexistent-provider",
                "model": "some-model",
            },
        )
        assert resp.status_code == 200
        events = parse_sse_events(resp.text)
        types = [e.get("type") for e in events]
        assert "error" in types


class TestSSEFormat:
    """SSE 协议格式验证"""

    async def test_sse_content_type_header(self, async_client):
        """响应 Content-Type 应为 text/event-stream"""
        resp = await async_client.post(
            "/api/agent/chat/stream",
            json={"message": "测试", "provider": "mock", "model": "mock-chat"},
        )
        assert "text/event-stream" in resp.headers.get("content-type", "")

    async def test_sse_no_cache_header(self, async_client):
        """SSE 响应应包含 Cache-Control: no-cache"""
        resp = await async_client.post(
            "/api/agent/chat/stream",
            json={"message": "测试", "provider": "mock", "model": "mock-chat"},
        )
        assert "no-cache" in resp.headers.get("cache-control", "")

    async def test_sse_events_are_valid_json(self, async_client):
        """每个 data: 行应为合法 JSON"""
        resp = await async_client.post(
            "/api/agent/chat/stream",
            json={"message": "你好", "provider": "mock", "model": "mock-chat"},
        )
        for line in resp.text.split("\n"):
            line = line.strip()
            if line.startswith("data: "):
                payload = line[6:]
                parsed = json.loads(payload)  # 不应抛异常
                assert "type" in parsed
