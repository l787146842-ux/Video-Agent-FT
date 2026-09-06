# -*- coding: utf-8 -*-
"""五项修法批 3 钉死回归：单步并行池（按工具声明，deny-by-default）。

钉死：
- 连续 parallel_safe 调用进有界并行池（≤PARALLEL_POOL_LIMIT），真并发；
- 结果与 SSE 事件按模型顺序提交（先完成者不插队）；
- 独占调用自成屏障：并行组不跨越未声明工具；未声明默认串行；
- parallel_safe 声明非 bool 注册期拒收（照 costly 校验段）；
- 组内失败不级联（只读成员失败只记失败回喂，不中止本批）；
- 组内取消：已启动成员跑完、取消穿透上抛（对齐 dsh）；
- 问即停 workflow_pause 未声明 parallel_safe → 永远独占。
"""
import asyncio
import time

import pytest
from pydantic import BaseModel

from src.video_agent.core.fc_tool_runner import FCToolRunner, PARALLEL_POOL_LIMIT
from src.video_agent.state.manager import StateManager
from src.video_agent.tools.base import BaseTool, ToolResult
from src.video_agent.tools.manager import ToolManager
from src.video_agent.utils.cancel_token import GenerationCancelled


class _EmptyInput(BaseModel):
    pass


class _Meter:
    """跨工具共享在飞计量器：max_active 即并发重叠证明。"""

    def __init__(self):
        self.active = 0
        self.max_active = 0

    def enter(self):
        self.active += 1
        self.max_active = max(self.max_active, self.active)

    def exit(self):
        self.active -= 1


class _ProbeTool(BaseTool):
    """并发探针：记录在飞峰值与完成顺序；可注入延迟/失败/取消。"""

    name = "probe_read"
    risk = "low"
    parallel_safe = True
    detail_tier = "output"

    def __init__(self, name="probe_read", delay=0.03, fail=False, cancel=False,
                 meter=None):
        self.name = name
        self.delay = delay
        self.fail = fail
        self.cancel = cancel
        self.meter = meter
        self.calls = 0

    def get_input_schema(self):
        return _EmptyInput

    async def aexecute(self, params):
        self.calls += 1
        if self.meter is not None:
            self.meter.enter()
        try:
            await asyncio.sleep(self.delay)
        finally:
            if self.meter is not None:
                self.meter.exit()
        if self.cancel:
            raise GenerationCancelled()
        if self.fail:
            return ToolResult(success=False, error="probe failed")
        return ToolResult(success=True, data={"ok": self.name})


class _SerialTool(_ProbeTool):
    """未声明 parallel_safe 的独占探针（默认串行）"""

    parallel_safe = False


class _ExclusiveSlowTool(_ProbeTool):
    """独占且慢的探针：验证并行组不与其重叠"""

    parallel_safe = False


class _FakeManager:
    def __init__(self, tools):
        self._tools = {t.name: t for t in tools}

    def get_tool(self, name):
        if name not in self._tools:
            raise ValueError(f"Tool '{name}' not found.")
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


@pytest.fixture
def svc(tmp_path):
    StateManager.reset_instance()
    instance = StateManager(str(tmp_path))
    StateManager._instance = instance
    yield instance
    StateManager.reset_instance()


def _resp(*names):
    class _Resp:
        tool_calls = [
            {"id": f"c{i}", "function": {"name": n, "arguments": "{}"}}
            for i, n in enumerate(names)
        ]
    return _Resp()


def _run(coro):
    return asyncio.run(coro)


# ---------- 分桶与真并发 ----------


def test_consecutive_parallel_safe_calls_run_concurrently(svc):
    """连续 parallel_safe 调用真并发：慢工具先发、快工具后发，快者先完成，
    在飞峰值 > 1 证明并发（串行实现下快者必等慢者）。"""
    meter = _Meter()
    slow = _ProbeTool(name="read_skill", delay=0.15, meter=meter)
    fast = _ProbeTool(name="read_draft", delay=0.01, meter=meter)
    runner = FCToolRunner(_FakeManager([slow, fast]))
    result = _run(runner.execute(_resp("read_skill", "read_draft")))
    assert result.applied == 2
    assert meter.max_active == 2, "两个 parallel_safe 调用必须在飞重叠（真并发）"
    assert result.tool_results[0]["data"]["ok"] == "read_skill"
    assert result.tool_results[1]["data"]["ok"] == "read_draft"


def test_model_order_commit_not_completion_order(svc):
    """结果与 SSE 事件按模型顺序提交：先发慢工具、后发快工具，
    finished 事件与 tool_results 仍按模型顺序（快者先完成也不插队）。"""
    slow = _ProbeTool(name="read_skill", delay=0.15)
    fast = _ProbeTool(name="list_skills", delay=0.01)
    runner = FCToolRunner(_FakeManager([slow, fast]))
    events = []

    async def on_event(ev):
        events.append(ev)

    result = _run(runner.execute(
        _resp("read_skill", "list_skills"), on_event=on_event))
    finished = [e for e in events
                if e.get("type") == "tool_finished" and e.get("id") in ("c0", "c1")]
    assert [e["id"] for e in finished] == ["c0", "c1"], "finished 事件须按模型顺序"
    assert [t["name"] for t in result.tool_results] == ["read_skill", "list_skills"]


def test_pool_limit_bounds_chunking(svc):
    """超池上限按 PARALLEL_POOL_LIMIT 切片：4+2 个调用分两片，各片内并发。"""
    meter = _Meter()
    tools = [
        _ProbeTool(name="read_skill", delay=0.05, meter=meter),
        _ProbeTool(name="read_draft", delay=0.05, meter=meter),
        _ProbeTool(name="list_skills", delay=0.05, meter=meter),
    ]
    # 同名多调用：三个工具名 × 2 轮 = 6 个连续 parallel_safe 调用
    runner = FCToolRunner(_FakeManager(tools))
    names = [t.name for t in tools] * 2
    result = _run(runner.execute(_resp(*names)))
    assert result.applied == 6
    # 切片并发：峰值恰为池上限（首片 4 个在飞，次片 2 个不超限）
    assert meter.max_active == PARALLEL_POOL_LIMIT


def test_exclusive_call_is_barrier(svc):
    """独占调用自成屏障：并行组不跨越未声明工具
    （read → 写类独占 → read，两组各自并发，与独占调用零重叠）。"""
    meter = _Meter()
    read_a = _ProbeTool(name="read_skill", delay=0.03, meter=meter)
    read_b = _ProbeTool(name="read_draft", delay=0.03, meter=meter)
    exclusive = _ExclusiveSlowTool(name="exclusive_write", delay=0.06, meter=meter)
    runner = FCToolRunner(_FakeManager([read_a, read_b, exclusive]))
    result = _run(runner.execute(
        _resp("read_skill", "exclusive_write", "read_draft")))
    assert result.applied == 3
    # 独占屏障：全程零在飞重叠（两读被独占调用隔开，各自成单员桶片）
    assert meter.max_active == 1


def test_unmarked_tool_default_serial(svc):
    """deny-by-default：未声明 parallel_safe 的连续调用保持串行（零重叠）。"""
    meter = _Meter()
    a = _SerialTool(name="serial_a", delay=0.04, meter=meter)
    b = _SerialTool(name="serial_b", delay=0.01, meter=meter)
    runner = FCToolRunner(_FakeManager([a, b]))
    result = _run(runner.execute(_resp("serial_a", "serial_b")))
    assert result.applied == 2
    assert meter.max_active == 1, "未声明者默认独占串行（deny-by-default）"


# ---------- 声明轴与注册校验 ----------


def test_register_rejects_non_bool_parallel_safe():
    """parallel_safe 声明非 bool → 注册期拒收（照 costly 校验段）。"""

    class _Bad(_ProbeTool):
        parallel_safe = "yes"

    with pytest.raises(ValueError, match="parallel_safe"):
        ToolManager.register(_Bad())


def test_registered_read_tools_declared_parallel_safe():
    """三个只读工具已声明 parallel_safe=True（批 3 指定名单）。"""
    from src.video_agent.tools.document_tools import ListSkillsTool, ReadSkillTool
    from src.video_agent.tools.storyboard_tools import StoryboardReadDraftTool

    for tool in (ReadSkillTool(), StoryboardReadDraftTool(), ListSkillsTool()):
        assert tool.parallel_safe is True
        assert tool.risk == "low"


def test_workflow_pause_not_parallel_safe():
    """问即停 workflow_pause 未声明 parallel_safe → 永远独占。"""
    from src.video_agent.tools.document_tools import WorkflowPauseTool

    assert getattr(WorkflowPauseTool(), "parallel_safe", False) is False


# ---------- 失败与取消语义 ----------


def test_group_member_failure_no_cascade(svc):
    """并行组内失败不级联：只读成员失败只记失败回喂，本批后续调用继续执行。"""
    bad = _ProbeTool(name="read_skill", fail=True)
    good = _ProbeTool(name="read_draft")
    exclusive = _ExclusiveSlowTool(name="exclusive_write")
    runner = FCToolRunner(_FakeManager([bad, good, exclusive]))
    result = _run(runner.execute(
        _resp("read_skill", "read_draft", "exclusive_write")))
    assert result.applied == 2  # 失败成员不计 applied，但不中止本批
    assert result.tool_results[0]["name"] == "read_skill"
    assert result.tool_results[0]["ok"] is False
    assert "probe failed" in str(result.tool_results[0]["error"])
    assert good.calls == 1 and exclusive.calls == 1


def test_cancel_in_group_lets_started_members_finish(svc):
    """组内取消（dsh 语义）：已启动成员跑完（真实结果保留），取消穿透上抛。"""

    class _CancelProbe(_ProbeTool):
        async def aexecute(self, params):
            # 模拟「执行中途收到取消」：先睡后抛
            await asyncio.sleep(0.02)
            raise GenerationCancelled()

    cancel_tool = _CancelProbe(name="read_skill", delay=0.0)
    sibling = _ProbeTool(name="read_draft", delay=0.05)
    runner = FCToolRunner(_FakeManager([cancel_tool, sibling]))
    with pytest.raises(GenerationCancelled):
        _run(runner.execute(_resp("read_skill", "read_draft")))
    assert sibling.calls == 1, "已启动的同片成员应跑完（gather 等齐）"


def test_idempotency_duplicate_key_in_group_hits_cache(svc):
    """T4 组内同键重复：同片两个同幂等键调用，后者命中前者账本（只真执行一次）。"""
    probe = _ProbeTool(name="read_skill", delay=0.02)
    runner = FCToolRunner(_FakeManager([probe]))

    class _Resp2:
        tool_calls = [
            {"id": "c0", "function": {"name": "read_skill",
                                      "arguments": '{"idempotency_key": "k1"}'}},
            {"id": "c1", "function": {"name": "read_skill",
                                      "arguments": '{"idempotency_key": "k1"}'}},
        ]

    result = _run(runner.execute(_Resp2()))
    assert result.applied == 2  # 两个调用都有结果（第二个命中缓存）
    assert probe.calls == 1, "同键重复只真执行一次"
