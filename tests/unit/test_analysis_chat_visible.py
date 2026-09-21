# -*- coding: utf-8 -*-
"""R9 analysis 对话可见契约单测（P1-G 批）。

钉死：①fc_tool_runner 在 script_analysis_report 成功路径签发 analysis_digest
（失败路径不签发、轮始清空）；②chat_service 轮末（_stream_finalize）在
final_payload 携非空 analysis_digest 时追加一条 meta=剧本分析 的对话摘要，
无 digest 时不追加（右侧时间线事件卡不动，chat 持久化归 web 层）。
"""
import json
import time

import pytest

import src.video_agent.tools.document_tools  # noqa: F401  触发工具注册
from src.video_agent.core.chat_port import ChatResponse
from src.video_agent.core.fc_tool_runner import FCToolRunner
from src.video_agent.state.manager import StateManager
from src.video_agent.tools.manager import ToolManager
from src.video_agent.web.chat_service import _StreamCtx, _stream_finalize

SUMMARY = "太阳系确认遭遇疑似二向箔的白色薄片打击。"


@pytest.fixture
def svc(tmp_path):
    StateManager.reset_instance()
    instance = StateManager(str(tmp_path))
    StateManager._instance = instance
    yield instance
    StateManager.reset_instance()


@pytest.fixture(autouse=True)
def _ensure_platform_tools():
    from src.video_agent.tools.analysis_tools import register_analysis_tools
    from src.video_agent.tools.document_tools import register_document_tools
    from src.video_agent.tools.storyboard_tools import register_storyboard_tools
    register_storyboard_tools()
    register_document_tools()
    register_analysis_tools()


def _analysis_call(summary=SUMMARY, report="**剧本分类**：A 类"):
    return ChatResponse(content="", tool_calls=[
        {"id": "c1", "type": "function", "function": {
            "name": "script_analysis_report",
            "arguments": json.dumps({
                "doc_name": "三体.md", "summary": summary,
                "report_markdown": report})}},
    ])


# ---------- fc_tool_runner 成功路径签发 digest ----------

async def test_runner_sets_digest_on_success(svc):
    runner = FCToolRunner(tool_manager=ToolManager)
    runner.reset_turn_tracking()
    assert runner.analysis_digest == ""
    await runner.execute(_analysis_call())
    assert runner.analysis_digest == SUMMARY


async def test_runner_no_digest_on_failure(svc):
    """summary 为空 → 工具明确失败 → 不签发 digest（只成功路径写入）。"""
    runner = FCToolRunner(tool_manager=ToolManager)
    runner.reset_turn_tracking()
    await runner.execute(_analysis_call(summary="   "))
    assert runner.analysis_digest == ""


async def test_runner_digest_reset_each_turn(svc):
    """轮始 reset_turn_tracking 清空上轮 digest（随轮生命周期，不跨轮泄漏）。"""
    runner = FCToolRunner(tool_manager=ToolManager)
    runner.reset_turn_tracking()
    await runner.execute(_analysis_call())
    assert runner.analysis_digest == SUMMARY
    runner.reset_turn_tracking()
    assert runner.analysis_digest == ""


# ---------- chat_service 轮末追加对话摘要 ----------

def _make_ctx(svc, final_payload, final_text="分析已完成并存档。"):
    events = []

    async def emit(ev):
        events.append(ev)

    ctx = _StreamCtx(
        svc=svc, executor=None, body=None, user_text="", llm_user_text="",
        llm_user_content="", use_studio_context=True, emit=emit,
        t0=time.monotonic(),
    )
    ctx.turn_id = "t-analysis"
    ctx.cand_model = "test-model"
    ctx.final_text = final_text
    ctx.final_payload = final_payload
    return ctx, events


def _digest_messages(svc):
    return [m for m in (svc.get_chat_messages() or [])
            if m.get("meta") == "素材分析"]


async def test_finalize_appends_digest_message(svc):
    """final_payload 携非空 analysis_digest → 追加 meta=剧本分析 的对话摘要。"""
    ctx, _events = _make_ctx(svc, {"text": "分析已完成并存档。",
                                   "analysis_digest": SUMMARY,
                                   "applied_actions": 1, "steps": 1})
    await _stream_finalize(ctx)
    msgs = _digest_messages(svc)
    assert len(msgs) == 1
    assert SUMMARY in msgs[0]["text"]
    assert msgs[0]["sender"] == "agent"
    assert msgs[0].get("turnId") == "t-analysis" or msgs[0].get("turn_id") == "t-analysis"


async def test_finalize_no_digest_no_message(svc):
    """final_payload 无 analysis_digest → 不追加剧本分析对话消息。"""
    ctx, _events = _make_ctx(svc, {"text": "普通回复", "applied_actions": 0, "steps": 1})
    await _stream_finalize(ctx)
    assert _digest_messages(svc) == []


async def test_finalize_empty_digest_no_message(svc):
    """analysis_digest 为空白 → 视同无，不追加。"""
    ctx, _events = _make_ctx(svc, {"text": "普通回复", "analysis_digest": "   "})
    await _stream_finalize(ctx)
    assert _digest_messages(svc) == []
