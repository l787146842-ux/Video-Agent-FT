# -*- coding: utf-8 -*-
"""批 C 裁决回归：聊天链路单一候选、不自动换模型（用户裁决 2026-08-20）。

fallback 链已退役：所选供应商瞬时故障（retryable 5xx）时直接报错
（人话 + 原文折叠），不得切换备用厂商、不得发 model_fallback 事件；
任务式路径不得静默死亡（事件流须有 error 终态）。
"""
from types import SimpleNamespace

import pytest

from src.video_agent.adapters.base_chat import StreamChunk  # noqa: F401  (保留导入面与旧版对齐)
from src.video_agent.exceptions import AdapterError
from src.video_agent.web import chat_service


class _FailingAdapter:
    """所选供应商：chat_stream 首次迭代即抛瞬时故障（5xx retryable）。"""

    supports_function_calling = False

    async def chat(self, messages, **kwargs):
        raise AdapterError("LLM 返回 HTTP 502: 繁忙", retryable=True, http_status=502)

    async def chat_stream(self, messages, **kwargs):
        raise AdapterError("LLM 返回 HTTP 502: 繁忙", retryable=True, http_status=502)
        yield  # 不可达：使本方法成为 async generator（async for 首次迭代时抛错）


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


def _patch_env(monkeypatch) -> None:
    """外部依赖全部换确定性假件，只保留生产路径本体。"""
    async def _no_compact(history, svc, adapter):
        return history

    monkeypatch.setattr(chat_service, "_create_chat_adapter", lambda p, m: _FailingAdapter())
    monkeypatch.setattr(chat_service, "_maybe_compact_history", _no_compact)
    monkeypatch.setattr(chat_service, "_resolve_summary_adapter", lambda *a, **k: None)
    monkeypatch.setattr(chat_service, "_resolve_skill_name_for_injection", lambda *a, **k: "")
    monkeypatch.setattr(chat_service, "_build_prelude_notes", lambda *a, **k: [])
    monkeypatch.setattr(chat_service, "_resolve_selected_draft_media_config", lambda *a, **k: ("", ""))


@pytest.mark.asyncio
async def test_task_path_retryable_error_direct(tmp_path, monkeypatch):
    """任务式路径：瞬时故障直接报错，不切换、不静默死亡。"""
    from src.video_agent.web.agent_task_manager import get_agent_task_manager

    _patch_env(monkeypatch)
    tm = get_agent_task_manager()
    sent = []
    orig_emit = tm.emit

    def emit_spy(task_id, event):
        sent.append(event)
        return orig_emit(task_id, event)

    monkeypatch.setattr(tm, "emit", emit_spy)
    await chat_service._run_agent_task(
        _make_body("req-task-nofb"), "proj-fb", "task-nofb-1", str(tmp_path),
    )

    types = [e.get("type") for e in sent]
    assert chat_service.SSE_ERROR in types, f"联不通必须直接报错: {types}"
    assert "model_fallback" not in types, f"裁决：不得自动换模型: {types}"
    err = next(e for e in sent if e.get("type") == chat_service.SSE_ERROR)
    assert "瞬时故障" in (err.get("detail") or ""), err
