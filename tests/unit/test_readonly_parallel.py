"""批 7 · 只读受限并行（L3，默认关）：段识别 + 窗口调度 + 失败/取消卫生。

钉死六件事：
① 开关关闭（默认）= 与现状串行行为等价（逐调用串行、无重叠）；
② 开关开启 + 连续 low 只读段 = 并行执行、结果按原序回填；
③ 混入写类/高危/未注册工具即断段（段前后仍各自串行，写类绝不进并行）；
④ 闸机链按序拦截：拒收的调用不进入并行执行，其后调用回串行裁决；
⑤ 窗口内失败回退串行消费剩余调用；
⑥ GenerationCancelled 穿透上抛，不被并行调度吞咽。
"""
import asyncio
import json
import time
from collections import Counter

import pytest

from src.video_agent.adapters.base_chat import ChatResponse
from src.video_agent.adapters.cancel_token import GenerationCancelled
from src.video_agent.core import fc_gates, readonly_parallel as rp
from src.video_agent.core.fc_tool_runner import FCToolRunner
from src.video_agent.tools.base import ToolResult


# ---------- 计时型工具管理桩（只模拟 get_tool_risk / invoke_tool 两个接口） ----------


class _TimingToolManager:
    """记录调用区间（起止单调钟）与活跃并发峰值，供并行/串行断言。

    delay：标量或按名映射的秒级延时；
    fail_names：命中在延时后返回失败；
    cancel_names：命中延时后抛 GenerationCancelled（模拟取消检查点命中）；
    hold：(名称集, 事件) 元组——命中名的**首次尝试**在延时后阻塞于该事件（可被取消），
    确定性钉死「消费时任务仍在飞」（不依赖计时精度）；重执尝试不阻塞；
    被取消的调用不记区间（与「未完成」语义一致）；
    未注册（不在 risks 中）工具按真实 ToolManager 口径报 not found。
    """

    def __init__(self, risks, delay=0.05, fail_names=(), cancel_names=(), hold=None):
        self._risks = dict(risks)
        self._delay = delay
        self._fail = set(fail_names)
        self._cancel = set(cancel_names)
        self._hold_names, self._hold_ev = hold if hold else (frozenset(), None)
        self._attempts = Counter()
        self.invoked = []        # 调用名按发起顺序（含被取消后串行重执的重复项）
        self.intervals = []      # (name, t_start, t_end) 仅完成的调用
        self.active = 0
        self.max_active = 0

    def get_tool_risk(self, name):
        return self._risks.get(name, "high")

    def _delay_of(self, name):
        return self._delay[name] if isinstance(self._delay, dict) else self._delay

    async def invoke_tool(self, name, args):
        self.invoked.append(name)
        self._attempts[name] += 1
        if name not in self._risks:
            self.intervals.append((name, time.monotonic(), time.monotonic()))
            return ToolResult(success=False, error=f"Tool '{name}' not found")
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        t0 = time.monotonic()
        try:
            await asyncio.sleep(self._delay_of(name))
            if self._hold_ev is not None and name in self._hold_names \
                    and self._attempts[name] == 1:
                await self._hold_ev.wait()  # 首次尝试阻塞至外部放行（可被取消）
            if name in self._cancel:
                raise GenerationCancelled("测试取消")
            if name in self._fail:
                return ToolResult(success=False, error=f"{name} 读取失败")
            return ToolResult(success=True, data={"from": name, "tag": args.get("tag", "")})
        finally:
            self.active -= 1
            task = asyncio.current_task()
            if task is None or not task.cancelling():
                self.intervals.append((name, t0, time.monotonic()))


class _NoRiskCapability:
    """缺 get_tool_risk 能力的桩（保守归 high → 无并行窗口）。"""

    async def invoke_tool(self, name, args):
        return ToolResult(success=True, data={})


def _calls(*specs):
    """specs: (name, tag) 序列 → ChatResponse.tool_calls 列表。"""
    return [
        {"id": f"c{i}", "type": "function", "function": {
            "name": n, "arguments": json.dumps({"tag": tag})}}
        for i, (n, tag) in enumerate(specs)
    ]


def _execute(monkeypatch, tm, tool_calls, **kwargs):
    runner = FCToolRunner(tool_manager=tm)
    monkeypatch.setattr(FCToolRunner, "_raw_state", staticmethod(lambda: {}))
    response = ChatResponse(content="", tool_calls=tool_calls)
    return asyncio.run(runner.execute(response, injected_skill="", **kwargs))


def _overlaps(i1, i2):
    return i1[1] < i2[2] and i2[1] < i1[2]


@pytest.fixture
def parallel_on(set_global_setting):
    set_global_setting("readonly_parallel_enabled", True)


# ---------- 段识别（纯单元） ----------


def test_find_windows_segmentation_and_min_length():
    risks = {"a": "low", "b": "low", "w": "high", "c": "low", "d": "medium", "e": "low"}
    tm = _TimingToolManager(risks)
    calls = _calls(("a", ""), ("b", ""), ("w", ""), ("c", ""), ("d", ""), ("e", ""))
    # 仅 [a, b] 成窗；c 被 medium 断段、e 单发无并行收益，均不入计划
    assert rp.find_readonly_windows(calls, tm) == {0: [0, 1]}
    # 单调用段不成窗
    assert rp.find_readonly_windows(_calls(("a", ""), ("w", "")), tm) == {}


def test_find_windows_unregistered_defaults_high():
    """未注册工具经既有 get_tool_risk 口径归 high → 断段（deny-by-default）。"""
    tm = _TimingToolManager({"a": "low"})
    calls = _calls(("a", ""), ("ghost_tool", ""), ("a", ""), ("a", ""))
    assert rp.find_readonly_windows(calls, tm) == {2: [2, 3]}
    # 风险查询能力缺失 → 全部保守归 high → 无窗口
    assert rp.find_readonly_windows(calls, _NoRiskCapability()) == {}


def test_plan_batch_switch_off_returns_empty():
    """开关默认关：计划恒空（执行路径与现状等价的机械保证）。"""
    tm = _TimingToolManager({"a": "low", "b": "low"})
    calls = _calls(("a", ""), ("b", ""))
    assert rp.plan_batch(calls, tm) == ({}, {})


# ---------- ① 开关关闭 = 串行等价 ----------


def test_switch_off_keeps_serial_execution(monkeypatch):
    """默认关：连续 low 只读调用仍逐调用串行（并发峰值=1、顺序不变）。"""
    tm = _TimingToolManager({"read_a": "low", "read_b": "low", "read_c": "low"})
    result = _execute(monkeypatch, tm, _calls(("read_a", "1"), ("read_b", "2"), ("read_c", "3")))
    assert tm.max_active == 1
    assert tm.invoked == ["read_a", "read_b", "read_c"]
    assert result.applied == 3
    # 结果按原序回填
    assert [r["data"]["tag"] for r in result.tool_results] == ["1", "2", "3"]


# ---------- ② 开关开启 = 并行执行 + 原序回填 ----------


def test_switch_on_parallel_window_preserves_order(monkeypatch, parallel_on):
    """连续 low 只读段并行执行（并发峰值≥2），结果/时间线按原序回填。"""
    tm = _TimingToolManager({"read_a": "low", "read_b": "low", "read_c": "low"})
    result = _execute(monkeypatch, tm, _calls(("read_a", "1"), ("read_b", "2"), ("read_c", "3")))
    assert tm.max_active >= 2
    assert tm.invoked == ["read_a", "read_b", "read_c"]
    assert result.applied == 3
    assert [r["name"] for r in result.tool_results] == ["read_a", "read_b", "read_c"]
    assert [r["data"]["tag"] for r in result.tool_results] == ["1", "2", "3"]
    # 区间互有重叠 = 真并行
    assert _overlaps(tm.intervals[0], tm.intervals[1])


def test_switch_on_sse_events_in_original_order(monkeypatch, parallel_on):
    """SSE_TOOL_STARTED/FINISHED 仍按原序成对下发（顺序语义不变）。"""
    from src.video_agent.core.sse_events import SSE_TOOL_FINISHED, SSE_TOOL_STARTED

    tm = _TimingToolManager({"read_a": "low", "read_b": "low"})
    events = []

    async def on_event(ev):
        events.append(ev)

    _execute(monkeypatch, tm, _calls(("read_a", "1"), ("read_b", "2")), on_event=on_event)
    # 只认工具时间线事件（actions_applied 等旁路事件不在本断言范围）
    seq = [(e["type"], e.get("id")) for e in events
           if e["type"] in (SSE_TOOL_STARTED, SSE_TOOL_FINISHED)]
    assert seq == [
        (SSE_TOOL_STARTED, "c0"), (SSE_TOOL_FINISHED, "c0"),
        (SSE_TOOL_STARTED, "c1"), (SSE_TOOL_FINISHED, "c1"),
    ]


# ---------- ③ 混入写类/高危/未注册即断段 ----------


def test_high_risk_tool_breaks_window_and_never_parallel(monkeypatch, parallel_on):
    """[low, low, high, low, low]：两个只读段各自并行，高危写类串行穿过，
    与任何调用零重叠；全部结果按原序回填。"""
    risks = {"read_a": "low", "read_b": "low", "canvas_write": "high",
             "read_c": "low", "read_d": "low"}
    tm = _TimingToolManager(risks)
    result = _execute(monkeypatch, tm, _calls(
        ("read_a", "1"), ("read_b", "2"), ("canvas_write", "3"),
        ("read_c", "4"), ("read_d", "5")))
    assert tm.invoked == ["read_a", "read_b", "canvas_write", "read_c", "read_d"]
    assert result.applied == 5
    assert [r["data"]["tag"] for r in result.tool_results] == ["1", "2", "3", "4", "5"]
    iv = {n: t for n, t in zip(tm.invoked, tm.intervals)}
    # 段内并行、写类与任何调用不重叠
    assert _overlaps(iv["read_a"], iv["read_b"])
    assert _overlaps(iv["read_c"], iv["read_d"])
    for other_name, other in iv.items():
        if other_name != "canvas_write":
            assert not _overlaps(iv["canvas_write"], other)


def test_unregistered_tool_breaks_window(monkeypatch, parallel_on):
    """未注册工具（get_tool_risk→high）混入即断段：前后 low 段仍各自并行。"""
    tm = _TimingToolManager({"read_a": "low", "read_b": "low",
                             "read_c": "low", "read_d": "low"})
    calls = _calls(("read_a", "1"), ("read_b", "2"), ("ghost_tool", "3"),
                   ("read_c", "4"), ("read_d", "5"))
    result = _execute(monkeypatch, tm, calls)
    assert tm.invoked == ["read_a", "read_b", "ghost_tool", "read_c", "read_d"]
    # ghost_tool 未注册（工具层报 not found 失败）→ 不计入 applied
    assert result.applied == 4
    assert result.tool_results[2]["ok"] is False
    iv = {n: t for n, t in zip(tm.invoked, tm.intervals)}
    assert _overlaps(iv["read_a"], iv["read_b"])
    assert _overlaps(iv["read_c"], iv["read_d"])
    for other_name, other in iv.items():
        if other_name != "ghost_tool":
            assert not _overlaps(iv["ghost_tool"], other)


# ---------- ④ 闸机按序拦截 ----------


def test_gate_rejected_call_not_executed_in_window(monkeypatch, parallel_on):
    """窗口内第 2 个调用被闸机拒收：拒收调用不进入执行（不并行也不串行），
    其前已放行调用照常执行，其后调用回主循环串行逐调用裁决。"""
    from src.video_agent.core.fc_gates import GateChainResult

    real_chain = fc_gates.run_gate_chain

    def fake_chain(ctx, name, args, *, paused_this_batch):
        if name == "read_b":
            return GateChainResult(error="测试闸机拒收：read_b 不得执行")
        return real_chain(ctx, name, args, paused_this_batch=paused_this_batch)

    monkeypatch.setattr(fc_gates, "run_gate_chain", fake_chain)
    tm = _TimingToolManager({"read_a": "low", "read_b": "low", "read_c": "low"})
    result = _execute(monkeypatch, tm, _calls(("read_a", "1"), ("read_b", "2"), ("read_c", "3")))
    # read_b 未被执行；a/c 照常执行且顺序不变
    assert tm.invoked == ["read_a", "read_c"]
    assert result.applied == 2
    assert result.tool_results[0]["ok"] is True
    assert result.tool_results[1]["ok"] is False
    assert "测试闸机拒收" in result.tool_results[1]["error"]
    assert result.tool_results[2]["ok"] is True


def test_gates_run_in_order_before_parallel_execution(monkeypatch, parallel_on):
    """闸机链逐调用按序裁决先于任何并行执行：记录闸机裁决顺序与首个工具
    起步时点，裁决顺序必须是调用序，且不因并行而乱。"""
    gate_order = []
    real_chain = fc_gates.run_gate_chain

    def fake_chain(ctx, name, args, *, paused_this_batch):
        gate_order.append(name)
        return real_chain(ctx, name, args, paused_this_batch=paused_this_batch)

    monkeypatch.setattr(fc_gates, "run_gate_chain", fake_chain)
    tm = _TimingToolManager({"read_a": "low", "read_b": "low", "read_c": "low"})
    _execute(monkeypatch, tm, _calls(("read_a", "1"), ("read_b", "2"), ("read_c", "3")))
    assert gate_order == ["read_a", "read_b", "read_c"]


# ---------- ⑤ 窗口内失败回退串行消费剩余 ----------


def _run_failure_scenario(monkeypatch):
    """⑤ 公共场景：read_a 快速失败、read_b/read_c 首次尝试被 hold 事件钉在「在飞中」
    （确定性，不依赖计时精度）；回退触发后外部放行。返回 (桩, 执行结果)。"""
    async def _run():
        hold_ev = asyncio.Event()
        tm = _TimingToolManager(
            {"read_a": "low", "read_b": "low", "read_c": "low"},
            delay=0, fail_names={"read_a"},
            hold=({"read_b", "read_c"}, hold_ev))
        runner = FCToolRunner(tool_manager=tm)
        monkeypatch.setattr(FCToolRunner, "_raw_state", staticmethod(lambda: {}))
        response = ChatResponse(content="", tool_calls=_calls(
            ("read_a", "1"), ("read_b", "2"), ("read_c", "3")))
        task = asyncio.ensure_future(runner.execute(response, injected_skill=""))
        await asyncio.sleep(0.05)  # 等窗口起飞：a 已失败、b/c 阻塞于 hold
        hold_ev.set()
        result = await task
        return tm, result

    return asyncio.run(_run())


def test_window_failure_falls_back_to_serial(monkeypatch, parallel_on):
    """首调用快速失败 → 剩余在飞调用被取消后串行重执：结果按原序回填、
    成败口径正确；失败调用自身不重执。"""
    tm, result = _run_failure_scenario(monkeypatch)
    counts = Counter(tm.invoked)
    assert counts["read_a"] == 1          # 失败调用不重执
    assert counts["read_b"] == 2          # 在飞任务被取消后串行重执（只读无副作用）
    assert counts["read_c"] == 2
    assert [r["ok"] for r in result.tool_results] == [False, True, True]
    assert [r["data"]["tag"] for r in result.tool_results[1:]] == ["2", "3"]
    assert result.applied == 2


def test_window_failure_serial_tail_not_overlapping(monkeypatch, parallel_on):
    """失败点之后的串行消费两两不重叠且保持原序（与并行窗口形态可区分）。"""
    tm, result = _run_failure_scenario(monkeypatch)
    assert result.applied == 2
    # b/c 首次尝试被取消不记区间；末尾两条即串行重执的完成区间，
    # 必须两两不重叠且严格先后（串行形态）
    tail = tm.intervals[-2:]
    assert [n for n, *_ in tail] == ["read_b", "read_c"]
    assert not _overlaps(tail[0], tail[1])
    assert tail[0][2] <= tail[1][1]  # 严格先后


# ---------- ⑥ GenerationCancelled 穿透 ----------


def test_generation_cancelled_propagates_not_swallowed(monkeypatch, parallel_on):
    """窗口内取消：穿透 execute() 上抛，不得被吞咽为失败结果。"""
    tm = _TimingToolManager(
        {"read_a": "low", "read_b": "low", "read_c": "low"},
        cancel_names={"read_b"})
    runner = FCToolRunner(tool_manager=tm)
    monkeypatch.setattr(FCToolRunner, "_raw_state", staticmethod(lambda: {}))
    response = ChatResponse(content="", tool_calls=_calls(
        ("read_a", "1"), ("read_b", "2"), ("read_c", "3")))
    with pytest.raises(GenerationCancelled):
        asyncio.run(runner.execute(response, injected_skill=""))


def test_generation_cancelled_leaves_trace_events(monkeypatch, parallel_on):
    """取消留痕：补发 started/finished 事件对（时间线条目完整）。"""
    from src.video_agent.core.sse_events import SSE_TOOL_FINISHED, SSE_TOOL_STARTED

    tm = _TimingToolManager(
        {"read_a": "low", "read_b": "low"}, cancel_names={"read_a"})
    events = []

    async def on_event(ev):
        events.append(ev)

    runner = FCToolRunner(tool_manager=tm)
    monkeypatch.setattr(FCToolRunner, "_raw_state", staticmethod(lambda: {}))
    response = ChatResponse(content="", tool_calls=_calls(("read_a", "1"), ("read_b", "2")))
    with pytest.raises(GenerationCancelled):
        asyncio.run(runner.execute(response, injected_skill="", on_event=on_event))
    cancelled_trace = [
        e for e in events
        if e.get("id") == "c0" and e["type"] == SSE_TOOL_FINISHED
    ]
    assert cancelled_trace and cancelled_trace[0]["ok"] is False
    assert "已被用户取消" in cancelled_trace[0]["result_summary"]
    assert any(e["type"] == SSE_TOOL_STARTED and e.get("id") == "c0" for e in events)


def test_cancelled_backfills_trace_for_pre_consumed_calls(monkeypatch, parallel_on):
    """窗口内第 2 个调用被取消：取消点之前已成功消费入 pre 的第 1 个调用
    补留痕（started/finished 事件对 + trace ok=True）；取消事件照常补发，
    GenerationCancelled 正常穿透（主循环因穿透走不到回填消费点，不得静默丢痕）。"""
    from src.video_agent.core.sse_events import SSE_TOOL_FINISHED, SSE_TOOL_STARTED
    from src.video_agent.core.tracer import AgentTracer

    # read_a 快完成先被消费入 pre；read_b 随后命中取消（确定性：顺序消费下
    # pos 0 必先于 pos 1 被消费，不依赖计时精度）
    tm = _TimingToolManager(
        {"read_a": "low", "read_b": "low"},
        delay={"read_a": 0.01, "read_b": 0.03},
        cancel_names={"read_b"})
    events = []

    async def on_event(ev):
        events.append(ev)

    recorded = []
    _orig_record = AgentTracer.record_action

    def _spy_record(self, *a, **k):
        recorded.append(k)
        return _orig_record(self, *a, **k)

    monkeypatch.setattr(AgentTracer, "record_action", _spy_record)

    runner = FCToolRunner(tool_manager=tm)
    monkeypatch.setattr(FCToolRunner, "_raw_state", staticmethod(lambda: {}))
    response = ChatResponse(content="", tool_calls=_calls(("read_a", "1"), ("read_b", "2")))
    with pytest.raises(GenerationCancelled):
        asyncio.run(runner.execute(response, injected_skill="", on_event=on_event))

    # 第 1 个已成功调用（c0）：完整留痕 = started/finished 事件对 + trace ok=True
    a_seq = [(e["type"], e.get("id")) for e in events if e.get("id") == "c0"]
    assert a_seq == [(SSE_TOOL_STARTED, "c0"), (SSE_TOOL_FINISHED, "c0")]
    a_finished = [e for e in events
                  if e.get("id") == "c0" and e["type"] == SSE_TOOL_FINISHED]
    assert a_finished[0]["ok"] is True
    a_traces = [k for k in recorded if k.get("name") == "read_a"]
    assert a_traces and all(k.get("ok") is True for k in a_traces)
    # 被取消调用（c1）：取消事件照常补发（红× + 取消文案）
    b_finished = [e for e in events
                  if e.get("id") == "c1" and e["type"] == SSE_TOOL_FINISHED]
    assert b_finished and b_finished[0]["ok"] is False
    assert "已被用户取消" in b_finished[0]["result_summary"]
    assert any(e["type"] == SSE_TOOL_STARTED and e.get("id") == "c1" for e in events)
    # 被取消调用不得被记成成功留痕；未消费的第 2 个之后无多余事件（本例无）
    assert not any(k.get("name") == "read_b" and k.get("ok") is True for k in recorded)
