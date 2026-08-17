"""0817 运行事故回归：trace 与 SSE 成败口径一致（失败不得刷新后变绿√）。

事故现场：6666 项目 2026-08-17 运行，live 时间线红×的工具失败，
刷新后 trace 重建却显示绿√——失败分支 trace ok 与 SSE ok 口径反转。
"""

import asyncio
import json

import pytest

from src.video_agent.adapters.base_chat import ChatResponse
from src.video_agent.core.fc_tool_runner import FCToolRunner
from src.video_agent.core.tracer import AgentTracer
from src.video_agent.tools.base import ToolResult


class _FailTM:
    """所有工具一律失败（模拟 read_uploaded_doc / script_analyze 失败轮）。"""

    async def invoke_tool(self, name, args):
        return ToolResult(success=False, error="模拟失败：文档未就绪")


def _run_with_trace(monkeypatch, tool_name, args, raw_state):
    """跑一次 execute，返回 (SSE 事件列表, trace 挂起动作列表)。"""
    AgentTracer.reset()
    tracer = AgentTracer.get_instance()
    tracer.start_trace("0817-regression")
    monkeypatch.setattr(FCToolRunner, "_raw_state", staticmethod(lambda: raw_state))
    events = []

    async def on_event(ev):
        events.append(ev)

    runner = FCToolRunner(tool_manager=_FailTM())
    response = ChatResponse(content="", tool_calls=[
        {"id": "c1", "type": "function", "function": {
            "name": tool_name, "arguments": json.dumps(args)}},
    ])
    asyncio.run(runner.execute(response, on_event=on_event))
    return events, list(tracer._pending_actions)


def test_0817_trace_ok_matches_sse_on_normal_failure(monkeypatch):
    """普通工具失败：SSE 发 ok=False（live 红×），trace 也必须 ok=False，
    刷新重建时间线不得把失败渲染成绿√。"""
    events, actions = _run_with_trace(
        monkeypatch, "read_uploaded_doc", {"name": "三体简短版.md"}, {})
    sse = [e for e in events if e.get("type") == "tool_finished"]
    assert len(sse) == 1 and sse[0]["ok"] is False
    rec = [a for a in actions if a["name"] == "read_uploaded_doc"]
    assert len(rec) == 1
    assert rec[0]["ok"] is False, "trace 与 SSE 口径必须一致：失败记 False"


def test_0817_trace_ok_neutral_on_spec_silent_reject(monkeypatch):
    """规格手写被向导拒收（814G3 静默）：用户侧中性（无红×），
    trace 与 SSE 同口径记 ok=True。"""
    events, actions = _run_with_trace(
        monkeypatch, "document_write",
        {"name": "Final_Video_Spec.md", "content": "x"},
        {"documents": []})
    sse = [e for e in events if e.get("type") == "tool_finished"]
    assert len(sse) == 1 and sse[0]["ok"] is True
    rec = [a for a in actions if a["name"] == "document_write"]
    assert len(rec) == 1
    assert rec[0]["ok"] is True, "规格静默拒收对用户中性，trace 不得红×"
