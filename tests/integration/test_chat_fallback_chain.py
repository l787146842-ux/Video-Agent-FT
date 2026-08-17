# -*- coding: utf-8 -*-
"""fallback 链路径级集成测试（chat_service L495 NameError 盲区立法）。

背景：既有三条相关测试全部绕过生产路径（直调 tm._apply_event /
直调 tracer.record_fallback / 只测开关字段），_real_stream 的 fallback
except 分支零覆盖，导致 next_provider 未定义的 NameError 在全绿下潜伏。

本文件钉死两条真实消费路径（同类全覆盖）：
- 任务式：_run_agent_task → _stream_worker_impl → _real_stream；
- SSE 直连：stream_worker → _stream_worker_impl → _real_stream。

主候选注入瞬时故障（retryable AdapterError）后断言：
次候选接管 + model_fallback 事件携带次候选组合 + tracer 记录次候选参数
+ 无内部错误外泄（任务式）/ 有终态事件（SSE 直连不静默卡死）。
"""
from types import SimpleNamespace

import pytest

from src.video_agent.adapters.base_chat import StreamChunk
from src.video_agent.exceptions import AdapterError
from src.video_agent.state.manager import StateManager
from src.video_agent.web import chat_service


class _FailingAdapter:
    """主候选：chat_stream 首次迭代即抛瞬时故障。"""

    supports_function_calling = False

    async def chat(self, messages, **kwargs):
        raise AdapterError("LLM 返回 HTTP 502: 繁忙", retryable=True, http_status=502)

    async def chat_stream(self, messages, **kwargs):
        raise AdapterError("LLM 返回 HTTP 502: 繁忙", retryable=True, http_status=502)
        yield  # 不可达：使本方法成为 async generator（async for 首次迭代时抛错）


class _OkAdapter:
    """次候选：正常产出正文并结束。"""

    supports_function_calling = False

    async def chat(self, messages, **kwargs):
        raise AssertionError("流式路径不应调用 chat()")

    async def chat_stream(self, messages, **kwargs):
        yield StreamChunk(type="text_delta", text="收到，已切换备用通道。")
        yield StreamChunk(type="done", finish_reason="stop")


def _make_body(request_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        request_id=request_id,
        provider="provA", model="m1",
        message="写一段开场白", messages=[],
        attachments=[], images=[], content_parts=[], videos=[],
        skill_name="", skill_slug="",
        selected_draft_id="", selected_type="", asset_mode="",
        context_mode="studio",
        doc_blocks=None, skill_blocks=None, gate_overrides=None,
        user_id="", thinking_level="",
    )


def _patch_fallback_env(monkeypatch) -> None:
    """外部依赖全部换确定性假件，只保留生产路径本体。"""
    async def _fake_candidates(provider_id, model):
        return [("provA", "m1"), ("provB", "m1")]

    async def _no_compact(history, svc, adapter):
        return history

    def _fake_adapter(provider_id, model):
        return _FailingAdapter() if provider_id == "provA" else _OkAdapter()

    monkeypatch.setattr(chat_service, "_fallback_candidates", _fake_candidates)
    monkeypatch.setattr(chat_service, "_create_chat_adapter", _fake_adapter)
    monkeypatch.setattr(chat_service, "_maybe_compact_history", _no_compact)
    monkeypatch.setattr(chat_service, "_resolve_summary_adapter", lambda *a, **k: None)
    monkeypatch.setattr(chat_service, "is_mock_provider", lambda *a, **k: False)
    monkeypatch.setattr(chat_service, "_channel_supports_fc", lambda *a, **k: False)
    monkeypatch.setattr(chat_service, "_resolve_skill_name_for_injection", lambda *a, **k: "")
    monkeypatch.setattr(chat_service, "_build_prelude_notes", lambda *a, **k: [])
    monkeypatch.setattr(chat_service, "_resolve_selected_draft_media_config", lambda *a, **k: ("", ""))

    from src.video_agent.config import settings
    if not settings.model_fallback_enabled:
        monkeypatch.setattr(settings, "model_fallback_enabled", True)


@pytest.mark.asyncio
async def test_task_path_fallback_chain(tmp_path, monkeypatch):
    """任务式路径：主候选瞬时故障 → 次候选接管，不得外泄内部错误气泡。"""
    from src.video_agent.web.agent_task_manager import get_agent_task_manager

    _patch_fallback_env(monkeypatch)
    tm = get_agent_task_manager()
    sent = []
    orig_emit = tm.emit

    def emit_spy(task_id, event):
        sent.append(event)
        return orig_emit(task_id, event)

    monkeypatch.setattr(tm, "emit", emit_spy)
    await chat_service._run_agent_task(
        _make_body("req-task-fb"), "proj-fb", "task-fb-1", str(tmp_path),
    )

    types = [e.get("type") for e in sent]
    assert chat_service.SSE_ERROR not in types, f"fallback 不得外泄内部错误: {sent}"
    assert "model_fallback" in types, f"缺 model_fallback 事件: {types}"
    assert chat_service.SSE_DONE in types, f"任务必须走到终态 done: {types}"


@pytest.mark.asyncio
async def test_sse_direct_fallback_chain(tmp_path, monkeypatch):
    """SSE 直连路径：worker 不得静默死亡，事件流须有 model_fallback + 终态。"""
    _patch_fallback_env(monkeypatch)
    svc = StateManager(str(tmp_path))
    monkeypatch.setattr(StateManager, "get_instance", classmethod(lambda cls: svc))

    events = []
    async def emit(ev):
        events.append(ev)

    await chat_service.stream_worker(_make_body("req-sse-fb"), emit)

    types = [e.get("type") for e in events]
    assert chat_service.SSE_ERROR not in types, f"fallback 不得报错: {events}"
    assert "model_fallback" in types, f"缺 model_fallback 事件: {types}"
    assert chat_service.SSE_DONE in types, f"流必须有终态事件（防静默卡死）: {types}"


@pytest.mark.asyncio
async def test_fallback_tracer_records_next_candidate(tmp_path, monkeypatch):
    """参数对账：tracer 与 model_fallback 事件都必须记录次候选（非失败方）。"""
    from src.video_agent.core.tracer import AgentTracer

    _patch_fallback_env(monkeypatch)
    calls = []
    monkeypatch.setattr(
        AgentTracer, "record_fallback", lambda self, p, m: calls.append((p, m)),
    )
    svc = StateManager(str(tmp_path))
    monkeypatch.setattr(StateManager, "get_instance", classmethod(lambda cls: svc))

    events = []
    async def emit(ev):
        events.append(ev)

    await chat_service.stream_worker(_make_body("req-sse-tracer"), emit)

    assert calls == [("provB", "m1")], f"tracer 应记录次候选组合: {calls}"
    fb = next(e for e in events if e.get("type") == "model_fallback")
    assert fb.get("provider") == "provB" and fb.get("model") == "m1"
