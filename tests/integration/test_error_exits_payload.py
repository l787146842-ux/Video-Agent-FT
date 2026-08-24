# -*- coding: utf-8 -*-
"""P9 错误出口统一：非流式 HTTP 错误出口全部走 ErrorPayload 契约。

照 test_error_payload.py 范式逐端点断言三层契约（error_code/friendly/raw）：
- 契约类错误（用户输入不合法/资源不存在）→ 友好文案 + error_code，kind=unknown；
- 未预期异常 → friendly 兜底文案 + raw 技术细节；
- 各端点 HTTP 状态码语义维持原状（400/404/409/413/500/502 不回退）。

前端镜像消费面：src/web/lib/error-payload.ts 的 httpErrorPayload
（body.code 存在即直接采信，兼容字段 detail/error_code 并存不破坏）。
"""
import pytest
from fastapi.testclient import TestClient

from src.video_agent.state.manager import StateManager
from src.video_agent.web.app import app


@pytest.fixture(autouse=True)
def reset_state(tmp_path, monkeypatch):
    """每个测试使用独立临时工作区（与 test_api_chat 同范式）"""
    monkeypatch.setenv("WORKSPACE_DIR", str(tmp_path))
    StateManager.reset_instance()
    svc = StateManager(str(tmp_path))
    StateManager._instance = svc
    yield svc
    StateManager.reset_instance()


@pytest.fixture
def client():
    return TestClient(app)


def _assert_contract(resp, *, status, detail, code, kind="unknown", error_code=None, has_raw=False):
    """三层契约断言：状态码保持 + detail/message 友好文案 + code/kind + 兼容字段"""
    assert resp.status_code == status
    body = resp.json()
    assert body["detail"] == detail
    assert body["message"] == detail
    assert body["code"] == code
    assert body["kind"] == kind
    if error_code is not None:
        assert body["error_code"] == error_code
    assert has_raw == ("raw" in body and bool(body["raw"]))
    return body


class TestValidationExits:
    """契约类 400 出口：友好文案 + VALIDATION_ERROR（状态码不变）"""

    def test_generation_logs_media_type(self, client):
        resp = client.post("/api/generation-logs", json={"media_type": "hologram", "status": "started"})
        _assert_contract(
            resp, status=400, detail="media_type 必须为 image/video/audio",
            code="err.unknown.validation_error", error_code="VALIDATION_ERROR",
        )

    def test_storyboard_reorder_invalid_category(self, client):
        resp = client.patch("/api/storyboard/reorder", json={"category": "bogus", "group_ids": []})
        _assert_contract(
            resp, status=400, detail="Invalid category: bogus",
            code="err.unknown.validation_error", error_code="VALIDATION_ERROR",
        )

    def test_project_document_empty_name(self, client):
        resp = client.put("/api/project/document", json={"name": "  ", "content": "x"})
        _assert_contract(
            resp, status=400, detail="文档名不能为空",
            code="err.unknown.validation_error", error_code="VALIDATION_ERROR",
        )

    def test_skills_format_empty_content(self, client):
        resp = client.post("/api/skills/format", json={"content": "   "})
        _assert_contract(
            resp, status=400, detail="内容不能为空",
            code="err.unknown.validation_error", error_code="VALIDATION_ERROR",
        )

    def test_skills_assistant_empty_body(self, client):
        resp = client.post("/api/skills/assistant", json={"content": "", "messages": []})
        _assert_contract(
            resp, status=400, detail="内容不能为空",
            code="err.unknown.validation_error", error_code="VALIDATION_ERROR",
        )

    def test_image_proxy_bad_scheme(self, client):
        resp = client.get("/api/image-proxy", params={"url": "ftp://example.com/a.png"})
        body = _assert_contract(
            resp, status=400, detail="禁止访问该协议: ftp",
            code="err.unknown.validation_error", error_code="VALIDATION_ERROR",
        )
        assert "raw" not in body


class TestNotFoundExits:
    """资源不存在 404 出口：NOT_FOUND（状态码不变）"""

    def test_agent_task_events(self, client):
        resp = client.get("/api/agent/tasks/nonexistent-task/events")
        _assert_contract(
            resp, status=404, detail="任务 'nonexistent-task' 不存在",
            code="err.unknown.not_found", error_code="NOT_FOUND",
        )

    def test_conversation_messages(self, client):
        resp = client.get("/api/conversations/ghost/messages")
        _assert_contract(
            resp, status=404, detail="对话不存在",
            code="err.unknown.not_found", error_code="NOT_FOUND",
        )

    def test_project_switch(self, client):
        resp = client.post("/api/project/switch", json={"project_id": "proj-ghost"})
        _assert_contract(
            resp, status=404, detail="项目 'proj-ghost' 不存在",
            code="err.unknown.not_found", error_code="NOT_FOUND",
        )

    def test_storyboard_draft_patch(self, client):
        resp = client.patch("/api/storyboard/drafts/draft-ghost", json={"label": "x"})
        _assert_contract(
            resp, status=404, detail="Draft draft-ghost not found",
            code="err.unknown.not_found", error_code="NOT_FOUND",
        )

    def test_video_batch_get(self, client):
        resp = client.get("/api/generate/video-batch/batch-ghost")
        _assert_contract(
            resp, status=404, detail="批次 'batch-ghost' 不存在",
            code="err.unknown.not_found", error_code="NOT_FOUND",
        )

    def test_unknown_api_path(self, client):
        """/api 未知路径兜底 404 也走契约（app.py SPA catch-all）"""
        resp = client.get("/api/definitely-not-a-route")
        _assert_contract(
            resp, status=404, detail="Not Found",
            code="err.unknown.not_found", error_code="NOT_FOUND",
        )


class TestUnexpectedExits:
    """未预期异常出口：friendly 兜底 + raw 技术细节（状态码不变）"""

    def test_config_save_failure_raw_detail(self, client, monkeypatch):
        import src.video_agent.web.routes.config as config_mod

        def _boom(overrides):  # noqa: ARG001
            raise OSError("disk full")

        monkeypatch.setattr(config_mod, "_save_runtime_overrides", _boom)
        resp = client.post("/api/config/model-fallback", json={"enabled": True})
        body = _assert_contract(
            resp, status=500, detail="开关保存失败",
            code="err.upstream.server_error", kind="upstream", has_raw=True,
        )
        assert body["raw"] == "disk full"
        # 兼容字段：既有 error_code 通道仍在
        assert body["error_code"] == "INTERNAL_ERROR"


class TestConflictExits:
    """409 版本闸出口：StateConflictError 统一转译（状态码不变）"""

    def test_put_state_stale_version(self, client, reset_state):
        svc = reset_state
        client.put("/api/project/state", json={"base_version": svc.board_version, "shots": []})
        resp = client.put(
            "/api/project/state", json={"base_version": svc.board_version - 1, "shots": []}
        )
        body = _assert_contract(
            resp, status=409, detail="版本冲突：状态已被其他窗口更新，请刷新后重试",
            code="err.unknown.state_conflict", error_code="STATE_CONFLICT",
        )
        # 前端 storyboard store 按 409 + /版本冲突/ 文案静默丢弃——两要素不回退
        assert "版本冲突" in body["detail"]


class TestCliHelpGuard:
    """cli_status._help_args 命令注入守卫（无 CLI 环境下端点提前 200 返回，直测函数）"""

    def test_unsafe_subcommand_raises_contract_error(self):
        from src.video_agent.exceptions import VideoAgentError
        from src.video_agent.web.routes.cli_status import _help_args

        with pytest.raises(VideoAgentError) as ei:
            _help_args("bad;rm")
        assert ei.value.status_code == 400
        assert ei.value.error_code == "VALIDATION_ERROR"


class TestRateLimitExit:
    """限流 429 中间件出口：同走 ErrorPayload 契约（quota 归类，状态码不变）"""

    def test_rate_limited_payload_contract(self):
        import asyncio
        import json
        from types import SimpleNamespace

        from src.video_agent.web.middleware.rate_limit import (
            RateLimitMiddleware,
            _TokenBucket,
        )

        async def _call_next(request):  # noqa: ARG001
            raise AssertionError("限流命中后不应继续下行")

        mw = RateLimitMiddleware(app=None, rate=1)
        bucket = _TokenBucket(1)
        bucket.tokens = 0.0  # 打空令牌桶，强制命中限流
        mw._buckets[("testclient", "chat")] = bucket

        req = SimpleNamespace(
            url=SimpleNamespace(path="/api/agent/chat"),
            method="POST",
            client=SimpleNamespace(host="testclient"),
            headers={},
        )
        resp = asyncio.run(mw.dispatch(req, _call_next))
        assert resp.status_code == 429
        body = json.loads(resp.body)
        assert body["detail"] == "请求过于频繁，请稍后再试"
        assert body["error_code"] == "RATE_LIMITED"
        assert body["kind"] == "quota"
        assert body["code"] == "err.quota.rate_limited"
