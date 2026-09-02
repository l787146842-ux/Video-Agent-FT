"""
ErrorPayload 契约单测（任务 #19：错误语义结构化，替代前端正则猜文案）。

覆盖：
- classify_exception 各 kind 归类（auth/quota/network/upstream/content/unknown）
- code 命名空间（err.<kind>.<slug>）
- sse_fields / http_body 形态（SSE 事件与 HTTP 响应共用结构，兼容字段不破坏）
- legacy error_code 桥接
- chat_errors._emit_stream_error 错误出口携带 code/kind
- agent_task_manager replay 同源下发 error_payload

前端镜像：src/web/lib/error-payload.ts + src/web/lib/__tests__/error-payload.test.ts
"""
import asyncio

import pytest

from src.video_agent.exceptions import AdapterError, VideoAgentError
from src.video_agent.web.error_payload import (
    ALL_KINDS,
    CODE_AUTH_FORBIDDEN,
    CODE_AUTH_INVALID_KEY,
    CODE_CONTENT_POLICY,
    CODE_NETWORK_CONNECTION,
    CODE_NETWORK_TIMEOUT,
    CODE_QUOTA_INSUFFICIENT,
    CODE_QUOTA_RATE_LIMITED,
    CODE_UNKNOWN,
    CODE_UPSTREAM_RELAY_REJECTED,
    CODE_UPSTREAM_SERVER,
    ErrorPayload,
    classify_exception,
    classify_http_status,
    classify_legacy_code,
)


class TestKindClassify:
    """各 kind 归类（供应商 401/403→auth、429→quota、超时/断连→network、
    5xx→upstream、内容策略→content、其余 unknown）"""

    def test_auth_401(self):
        p = classify_exception(AdapterError("LLM 返回 HTTP 401: invalid key", http_status=401))
        assert p.kind == "auth" and p.code == CODE_AUTH_INVALID_KEY

    def test_auth_403(self):
        p = classify_exception(AdapterError("LLM 返回 HTTP 403: forbidden", http_status=403))
        assert p.kind == "auth" and p.code == CODE_AUTH_FORBIDDEN

    def test_quota_429(self):
        p = classify_exception(AdapterError("LLM 返回 HTTP 429", http_status=429))
        assert p.kind == "quota" and p.code == CODE_QUOTA_RATE_LIMITED

    def test_quota_insufficient_by_marker(self):
        # 上游常以 400 包裹额度不足，靠特征归类（与 _friendly_stream_error 触发词同源）
        p = classify_exception(AdapterError("insufficient_user_quota: 剩余额度：$0.1", http_status=400))
        assert p.kind == "quota" and p.code == CODE_QUOTA_INSUFFICIENT

    def test_upstream_5xx(self):
        for status in (500, 502, 529):
            p = classify_exception(AdapterError(f"LLM 返回 HTTP {status}", http_status=status))
            assert p.kind == "upstream" and p.code == CODE_UPSTREAM_SERVER

    def test_relay_rejected_ahead_of_auth(self):
        # 中继拒收通知单可出现在 403 上——须归 upstream 而非 auth
        p = classify_exception(AdapterError("LLM 中继拒收通知单（HTTP 403）: 10605", http_status=403))
        assert p.kind == "upstream" and p.code == CODE_UPSTREAM_RELAY_REJECTED

    def test_network_timeout_by_message(self):
        p = classify_exception(AdapterError("LLM 请求失败: Read timed out", retryable=True))
        assert p.kind == "network" and p.code == CODE_NETWORK_TIMEOUT

    def test_network_timeout_by_exception_type(self):
        p = classify_exception(TimeoutError("读取超时"))
        assert p.kind == "network" and p.code == CODE_NETWORK_TIMEOUT

    def test_network_connection(self):
        p = classify_exception(ConnectionError("无法连接上游服务"))
        assert p.kind == "network" and p.code == CODE_NETWORK_CONNECTION

    def test_content_policy(self):
        p = classify_exception(AdapterError("内容审核未通过: data_inspection failed", http_status=400))
        assert p.kind == "content" and p.code == CODE_CONTENT_POLICY

    def test_unknown_fallback(self):
        p = classify_exception(RuntimeError("莫名其妙"))
        assert p.kind == "unknown" and p.code == CODE_UNKNOWN

    def test_message_and_raw_passthrough(self):
        p = classify_exception(RuntimeError("x"), message="人话", raw="原始报文")
        assert p.message == "人话" and p.raw == "原始报文"


class TestLegacyBridge:
    """既有 error_code 通道桥接（旧码未下线期间归类一致）"""

    @pytest.mark.parametrize("legacy,kind,code", [
        ("UNAUTHORIZED", "auth", CODE_AUTH_INVALID_KEY),
        ("FORBIDDEN_ORIGIN", "auth", "err.auth.forbidden_origin"),
        ("RATE_LIMITED", "quota", CODE_QUOTA_RATE_LIMITED),
        ("TIMEOUT", "network", CODE_NETWORK_TIMEOUT),
        ("NETWORK_ERROR", "network", CODE_NETWORK_CONNECTION),
        ("ADAPTER_ERROR", "upstream", CODE_UPSTREAM_SERVER),
    ])
    def test_mapped(self, legacy, kind, code):
        p = classify_legacy_code(legacy, "m")
        assert p.kind == kind and p.code == code

    def test_unmapped_slug_readable(self):
        p = classify_legacy_code("DUPLICATE_REQUEST", "m")
        assert p.kind == "unknown" and p.code == "err.unknown.duplicate_request"

    def test_exception_with_legacy_code_no_status(self):
        p = classify_exception(VideoAgentError("限流", error_code="RATE_LIMITED", status_code=400))
        assert p.kind == "quota"


class TestPayloadShape:
    """契约形态（HTTP 与 SSE 共用；兼容字段不破坏既有消费）"""

    def test_sse_fields(self):
        p = ErrorPayload(code="err.auth.invalid_key", kind="auth", message="鉴权失败", raw="r")
        assert p.sse_fields() == {"code": "err.auth.invalid_key", "kind": "auth", "message": "鉴权失败"}

    def test_http_body_compat_fields(self):
        p = ErrorPayload(code="err.quota.rate_limited", kind="quota", message="限流", raw="上游原文")
        body = p.http_body("RATE_LIMITED")
        # 既有消费字段（detail/error_code）仍在 + 新契约字段
        assert body["detail"] == "限流"
        assert body["error_code"] == "RATE_LIMITED"
        assert body["code"] == "err.quota.rate_limited"
        assert body["kind"] == "quota"
        assert body["message"] == "限流"
        assert body["raw"] == "上游原文"

    def test_http_body_no_raw_when_empty(self):
        body = ErrorPayload(code="err.unknown", kind="unknown", message="x").http_body()
        assert "raw" not in body and "error_code" not in body

    def test_all_kinds_closed_set(self):
        assert set(ALL_KINDS) == {"auth", "quota", "network", "upstream", "content", "unknown"}

    def test_classify_http_status(self):
        assert classify_http_status(401).kind == "auth"
        assert classify_http_status(429).kind == "quota"
        assert classify_http_status(503).kind == "upstream"
        assert classify_http_status(400).kind == "unknown"


class TestChatServiceErrorExit:
    """chat_errors._emit_stream_error：SSE error 事件携带结构化 code/kind"""

    def test_emit_stream_error_carries_code_kind(self):
        from src.video_agent.web.chat_errors import _emit_stream_error

        events = []

        async def emit(ev):
            events.append(ev)

        exc = AdapterError("LLM 返回 HTTP 401: bad key", http_status=401)
        asyncio.run(_emit_stream_error(None, None, exc, emit, use_studio_context=False))

        assert len(events) == 1
        ev = events[0]
        # 既有字段不破坏
        assert ev["type"] == "error"
        assert ev["detail"] and ev["error_code"] == "ADAPTER_ERROR"
        # 新契约字段
        assert ev["code"] == CODE_AUTH_INVALID_KEY
        assert ev["kind"] == "auth"
        assert ev["message"] == ev["detail"]

    def test_emit_stream_error_quota_marker(self):
        from src.video_agent.web.chat_errors import _emit_stream_error

        events = []

        async def emit(ev):
            events.append(ev)

        exc = AdapterError("insufficient_user_quota: 预扣费失败", http_status=400)
        asyncio.run(_emit_stream_error(None, None, exc, emit, use_studio_context=False))
        assert events[0]["kind"] == "quota"
        assert events[0]["code"] == CODE_QUOTA_INSUFFICIENT


class TestReplayErrorPayload:
    """agent_task_manager：error 事件结构化归类入账，replay 同源下发"""

    def _manager(self):
        from src.video_agent.web.agent_task_manager import AgentTaskManager

        class FakeStore:
            def exists(self, key):
                return True

            def save(self, key, payload):
                pass

            def load(self, key):
                return {}

        return AgentTaskManager(store=FakeStore(), legacy_file="nonexistent.json")

    def _record(self, mgr, task_id="t1"):
        record = {
            "task_id": task_id, "project_id": "p", "model": "m",
            "status": "running", "reasoning": "", "text": "", "status_text": "",
            "tools": [], "snapshot": None, "done_payload": None,
            "stopped_payload": None, "fallback": None, "error": None,
            "pending_guidance": [], "_subscribers": [], "_task": None,
        }
        mgr._tasks[task_id] = record
        return record

    def test_apply_error_event_stores_payload(self):
        mgr = self._manager()
        record = self._record(mgr)
        mgr._apply_event(record, {
            "type": "error", "detail": "鉴权失败", "raw": "上游报文",
            "code": "err.auth.invalid_key", "kind": "auth",
        })
        assert record["status"] == "error"
        assert record["error"] == "鉴权失败"
        assert record["error_payload"] == {
            "code": "err.auth.invalid_key", "kind": "auth", "raw": "上游报文",
        }

    def test_apply_legacy_error_event_no_payload(self):
        mgr = self._manager()
        record = self._record(mgr)
        mgr._apply_event(record, {"type": "error", "detail": "旧事件"})
        assert "error_payload" not in record

    def test_replay_carries_error_payload(self):
        mgr = self._manager()
        record = self._record(mgr)
        record["status"] = "error"
        record["error"] = "鉴权失败"
        record["error_payload"] = {"code": "err.auth.invalid_key", "kind": "auth", "raw": ""}
        q = mgr.subscribe("t1")
        replay = q.get_nowait()
        assert replay["type"] == "replay"
        assert replay["payload"]["error_payload"]["kind"] == "auth"
