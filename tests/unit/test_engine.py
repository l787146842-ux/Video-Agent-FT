"""WorkflowEngine：依赖顺序、并发上限、失败停止、死锁检测、重试、skipped"""
import asyncio

import pytest

from src.video_agent.workflows.engine import WorkflowEngine
from src.video_agent.workflows.models import (
    PhaseDefinition,
    PhaseExecution,
    RetryPolicy,
    WorkflowContextConfig,
    WorkflowDefinition,
)


def make_def(phases, max_parallel=2, max_retries=0, base_delay=0):
    return WorkflowDefinition(
        workflow_id="wf_test",
        name="test",
        context=WorkflowContextConfig(
            max_parallel_tasks=max_parallel,
            retry_policy=RetryPolicy(max_retries=max_retries, backoff="linear", base_delay_seconds=base_delay),
        ),
        phases=[
            PhaseDefinition(
                phase_id=pid, name=pid, depends_on=deps,
                execution=PhaseExecution(skill=pid), timeout_seconds=10,
            )
            for pid, deps in phases
        ],
    )


async def test_dependency_order():
    order = []

    async def executor(phase):
        order.append(phase.phase_id)
        return {}

    wf = make_def([("a", []), ("b", ["a"]), ("c", ["b"])])
    engine = WorkflowEngine(wf, phase_executor=executor)
    assert await engine.run() is True
    assert order == ["a", "b", "c"]


async def test_concurrency_cap_enforced():
    running = 0
    peak = 0

    async def executor(phase):
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.05)
        running -= 1
        return {}

    # 4 个无依赖 phase，并发上限 2——旧引擎会一次全发出去
    wf = make_def([("p1", []), ("p2", []), ("p3", []), ("p4", [])], max_parallel=2)
    engine = WorkflowEngine(wf, phase_executor=executor)
    assert await engine.run() is True
    assert peak <= 2


async def test_failure_stops_downstream():
    executed = []

    async def executor(phase):
        executed.append(phase.phase_id)
        if phase.phase_id == "a":
            raise RuntimeError("boom")
        return {}

    wf = make_def([("a", []), ("b", ["a"])])
    engine = WorkflowEngine(wf, phase_executor=executor)
    assert await engine.run() is False
    assert "b" not in engine.completed_phases
    assert "a" in engine.failed_phases
    assert engine.phase_results["a"]["status"] == "failed"


async def test_deadlock_detected():
    async def executor(phase):
        return {}

    # b 依赖不存在的 x → 永远无法就绪
    wf = make_def([("a", []), ("b", ["x"])])
    engine = WorkflowEngine(wf, phase_executor=executor)
    assert await engine.run() is False
    assert "a" in engine.completed_phases
    assert "b" not in engine.completed_phases


async def test_retry_then_succeed():
    attempts = {"n": 0}

    async def executor(phase):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise RuntimeError("first attempt fails")
        return {"detail": "ok"}

    wf = make_def([("a", [])], max_retries=1, base_delay=0)
    engine = WorkflowEngine(wf, phase_executor=executor)
    assert await engine.run() is True
    assert attempts["n"] == 2


async def test_skipped_satisfies_dependencies():
    async def executor(phase):
        if phase.phase_id == "a":
            return {"skipped": True, "detail": "未接入"}
        return {}

    wf = make_def([("a", []), ("b", ["a"])])
    engine = WorkflowEngine(wf, phase_executor=executor)
    assert await engine.run() is True
    assert "a" in engine.skipped_phases
    assert engine.phase_results["a"]["status"] == "skipped"
    assert "b" in engine.completed_phases


async def test_events_emitted():
    events = []

    async def on_event(e):
        events.append(e["event"])

    async def executor(phase):
        return {}

    wf = make_def([("a", [])])
    engine = WorkflowEngine(wf, phase_executor=executor, on_event=on_event)
    await engine.run()
    assert events == ["phase_started", "phase_completed"]
