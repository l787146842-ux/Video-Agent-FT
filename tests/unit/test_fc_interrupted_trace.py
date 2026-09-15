# -*- coding: utf-8 -*-
"""8888 委派失踪批 · 批 C：委派中断留痕（core 层，P1）。

事故：`run_subagent` 派发裸 `await launcher(...)` 不兜异常，独占段只对
GenerationCancelled 留痕，其它异常穿透 → `_commit_call` 未执行 → 主 trace
step4 只有 model_reasoning、无 run_subagent action（委派像从没发生过）。

钉死契约（照抄既有「取消留痕」范式）：
- 独占派发段非取消异常：先以失败态记 SSE tool_finished + trace action（ok=False），
  **原样上抛**（不吞为 ToolResult(success=False)）；
- 并行桶成员非取消异常：同款留痕后再上抛首例（G4 同类路径）。
"""
import asyncio

import pytest
from pydantic import BaseModel

from src.video_agent.core import fc_tool_runner as ftr
from src.video_agent.core.fc_tool_runner import FCToolRunner
from src.video_agent.state.manager import StateManager
from src.video_agent.tools.base import BaseTool, ToolResult


class _EmptyInput(BaseModel):
    pass


class _ExclusiveTool(BaseTool):
    name = "probe_exclusive"
    risk = "low"
    parallel_safe = False
    detail_tier = "output"

    def get_input_schema(self):
        return _EmptyInput

    async def aexecute(self, params):
        return ToolResult(success=True, data={"ok": self.name})


class _ParallelTool(_ExclusiveTool):
    name = "probe_parallel"
    parallel_safe = True


class _FakeManager:
    def __init__(self, tools):
        self._tools = {t.name: t for t in tools}

    def get_tool(self, name):
        return self._tools[name]

    async def invoke_tool(self, name, kwargs):
        tool = self._tools[name]
        params = tool.get_input_schema().model_validate(kwargs or {})
        return await tool.aexecute(params)

    def is_costly_tool(self, name):
        return False

    def get_tool_risk(self, name):
        t = self._tools.get(name)
        return getattr(t, "risk", "high") if t else "high"


class _FakeTracer:
    def __init__(self):
        self.actions = []

    def record_action(self, **kw):
        self.actions.append(kw)


def _resp(*names):
    class _R:
        tool_calls = [
            {"id": f"c{i}", "function": {"name": n, "arguments": "{}"}}
            for i, n in enumerate(names)
        ]
    return _R()


@pytest.fixture
def svc(tmp_path):
    StateManager.reset_instance()
    inst = StateManager(str(tmp_path))
    StateManager._instance = inst
    yield inst
    StateManager.reset_instance()


@pytest.fixture
def tracer(monkeypatch):
    fake = _FakeTracer()
    monkeypatch.setattr(ftr.AgentTracer, "get_instance", staticmethod(lambda: fake))
    return fake


def _dispatch_raises(runner, monkeypatch, exc):
    async def _boom(name, args):
        raise exc
    monkeypatch.setattr(runner, "_dispatch_tool", _boom)


# ---------- 独占派发段：非取消异常留痕后原样上抛 ----------

def test_exclusive_interrupt_records_and_reraises(svc, tracer, monkeypatch):
    runner = FCToolRunner(_FakeManager([_ExclusiveTool()]))
    _dispatch_raises(runner, monkeypatch, RuntimeError("HTTP 504 gateway timeout"))

    events = []

    async def on_event(ev):
        events.append(ev)

    # 原样上抛：不吞为 ToolResult(success=False)
    with pytest.raises(RuntimeError):
        asyncio.run(runner.execute(_resp("probe_exclusive"), on_event=on_event))

    assert any(
        a.get("name") == "probe_exclusive" and a.get("ok") is False
        for a in tracer.actions
    ), "中断的调用须在 trace 记 action（ok=False）"
    assert any("504" in (a.get("result_summary") or "") for a in tracer.actions)

    fin = [e for e in events
           if e.get("type") == "tool_finished" and e.get("id") == "c0"]
    assert fin and fin[-1]["ok"] is False
    assert "504" in fin[-1]["result_summary"], "SSE 也须留失败态痕迹"


# ---------- 并行桶段：成员非取消异常留痕后上抛（G4 同类路径） ----------

def test_parallel_bucket_interrupt_records_and_reraises(svc, tracer, monkeypatch):
    runner = FCToolRunner(_FakeManager([_ParallelTool()]))
    _dispatch_raises(runner, monkeypatch, ValueError("parallel boom"))

    with pytest.raises(ValueError):
        asyncio.run(runner.execute(_resp("probe_parallel")))

    assert any(
        a.get("name") == "probe_parallel" and a.get("ok") is False
        for a in tracer.actions
    ), "并行成员的非取消异常同样不得零留痕"
