"""WorkflowEngine：依赖顺序、并发上限、失败停止、死锁检测、重试、skipped、llm_config 桥接"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.video_agent.workflows.engine import WorkflowEngine
from src.video_agent.workflows.models import (
    ModelConfig,
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

    async def executor(phase, ctx):
        order.append(phase.phase_id)
        return {}

    wf = make_def([("a", []), ("b", ["a"]), ("c", ["b"])])
    engine = WorkflowEngine(wf, phase_executor=executor)
    assert await engine.run() is True
    assert order == ["a", "b", "c"]


async def test_concurrency_cap_enforced():
    running = 0
    peak = 0

    async def executor(phase, ctx):
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

    async def executor(phase, ctx):
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
    async def executor(phase, ctx):
        return {}

    # b 依赖不存在的 x → 永远无法就绪
    wf = make_def([("a", []), ("b", ["x"])])
    engine = WorkflowEngine(wf, phase_executor=executor)
    assert await engine.run() is False
    assert "a" in engine.completed_phases
    assert "b" not in engine.completed_phases


async def test_retry_then_succeed():
    attempts = {"n": 0}

    async def executor(phase, ctx):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise RuntimeError("first attempt fails")
        return {"detail": "ok"}

    wf = make_def([("a", [])], max_retries=1, base_delay=0)
    engine = WorkflowEngine(wf, phase_executor=executor)
    assert await engine.run() is True
    assert attempts["n"] == 2


async def test_skipped_satisfies_dependencies():
    async def executor(phase, ctx):
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

    async def executor(phase, ctx):
        return {}

    wf = make_def([("a", [])])
    engine = WorkflowEngine(wf, phase_executor=executor, on_event=on_event)
    await engine.run()
    assert events == ["phase_started", "phase_completed"]


# ---------- 交互模式测试（Web 用） ----------


async def test_step_executes_one_phase_then_waits():
    """交互模式：step() 执行一个阶段后暂停等待确认"""
    executed = []

    async def executor(phase, ctx):
        executed.append(phase.phase_id)
        return {"detail": f"{phase.phase_id} done"}

    wf = make_def([("story", []), ("image", ["story"]), ("video", ["image"])])
    engine = WorkflowEngine(wf, phase_executor=executor)

    # 第一步：执行 story
    result = await engine.step()
    assert result["status"] == "completed"
    assert result["phase"] == "story"
    assert executed == ["story"]
    assert engine.is_awaiting_confirmation is True


async def test_step_blocked_without_advance():
    """未调用 advance() 时 step() 应返回 waiting"""
    async def executor(phase, ctx):
        return {}

    wf = make_def([("a", []), ("b", ["a"])])
    engine = WorkflowEngine(wf, phase_executor=executor)

    await engine.step()  # 执行 a，进入等待确认
    result = await engine.step()  # 未 advance，应返回 waiting
    assert result["status"] == "waiting"


async def test_advance_then_step_continues():
    """用户确认后 advance() + step() 应推进到下一阶段"""
    executed = []

    async def executor(phase, ctx):
        executed.append(phase.phase_id)
        return {}

    wf = make_def([("a", []), ("b", ["a"]), ("c", ["b"])])
    engine = WorkflowEngine(wf, phase_executor=executor)

    # 执行 a
    r1 = await engine.step()
    assert r1["phase"] == "a"

    # 确认并执行 b
    engine.advance()
    assert engine.is_awaiting_confirmation is False
    r2 = await engine.step()
    assert r2["phase"] == "b"

    # 确认并执行 c
    engine.advance()
    r3 = await engine.step()
    assert r3["phase"] == "c"

    assert executed == ["a", "b", "c"]


async def test_step_returns_done_when_all_complete():
    """所有阶段完成后 step() 应返回 done"""
    async def executor(phase, ctx):
        return {}

    wf = make_def([("a", []), ("b", ["a"])])
    engine = WorkflowEngine(wf, phase_executor=executor)

    await engine.step()   # a
    engine.advance()
    await engine.step()   # b
    engine.advance()
    result = await engine.step()  # 全部完成
    assert result["status"] == "done"


async def test_step_handles_failure():
    """交互模式下 phase 失败应返回 failed 状态"""
    async def executor(phase, ctx):
        if phase.phase_id == "a":
            raise RuntimeError("模拟失败")
        return {}

    wf = make_def([("a", []), ("b", ["a"])])
    engine = WorkflowEngine(wf, phase_executor=executor)

    result = await engine.step()
    assert result["status"] == "failed"
    assert result["phase"] == "a"
    assert "模拟失败" in result.get("error", "")


async def test_step_blocked_on_deadlock():
    """依赖无法满足时 step() 应返回 blocked"""
    async def executor(phase, ctx):
        return {}

    # b 依赖不存在的 x
    wf = make_def([("a", []), ("b", ["x"])])
    engine = WorkflowEngine(wf, phase_executor=executor)

    # 先执行 a
    r1 = await engine.step()
    assert r1["phase"] == "a"

    # a 完成后 b 仍无法执行（依赖 x 不存在）
    engine.advance()
    r2 = await engine.step()
    assert r2["status"] == "blocked"


async def test_step_skipped_phase():
    """交互模式下 skipped phase 应正确标记"""
    async def executor(phase, ctx):
        if phase.phase_id == "audio":
            return {"skipped": True, "detail": "未接入"}
        return {}

    wf = make_def([("story", []), ("audio", ["story"])])
    engine = WorkflowEngine(wf, phase_executor=executor)

    await engine.step()  # story
    engine.advance()
    result = await engine.step()  # audio → skipped
    assert result["status"] == "skipped"
    assert "audio" in engine.skipped_phases


async def test_current_phase_property():
    """current_phase 属性应返回下一个可执行阶段"""
    async def executor(phase, ctx):
        return {}

    wf = make_def([("a", []), ("b", ["a"])])
    engine = WorkflowEngine(wf, phase_executor=executor)

    assert engine.current_phase == "a"
    await engine.step()
    engine.advance()
    assert engine.current_phase == "b"
    await engine.step()
    engine.advance()
    assert engine.current_phase is None


async def test_interaction_events_emitted():
    """交互模式下事件应正常发射"""
    events = []

    async def on_event(e):
        events.append(e["event"])

    async def executor(phase, ctx):
        return {}

    wf = make_def([("a", [])])
    engine = WorkflowEngine(wf, phase_executor=executor, on_event=on_event)
    await engine.step()
    assert "phase_started" in events
    assert "phase_completed" in events


# ---------- phase_context 阶段间数据传递 ----------


async def test_phase_context_passing():
    """前一阶段的输出应存入 phase_context，供下游阶段读取"""
    received_contexts = {}

    async def executor(phase, ctx):
        received_contexts[phase.phase_id] = dict(ctx)  # 拷贝当前 context
        return {"output": f"{phase.phase_id}_result"}

    wf = make_def([("story", []), ("storyboard", ["story"]), ("image", ["storyboard"])])
    engine = WorkflowEngine(wf, phase_executor=executor)
    assert await engine.run() is True

    # story 执行时 context 为空
    assert received_contexts["story"] == {}
    # storyboard 执行时 context 含 story 的输出
    assert received_contexts["storyboard"]["story"] == {"output": "story_result"}
    # image 执行时 context 含 story + storyboard 的输出
    assert received_contexts["image"]["story"] == {"output": "story_result"}
    assert received_contexts["image"]["storyboard"] == {"output": "storyboard_result"}


async def test_phase_context_available_in_engine():
    """引擎的 phase_context 属性应在运行后包含所有阶段结果"""
    async def executor(phase, ctx):
        return {"data": phase.phase_id}

    wf = make_def([("a", []), ("b", ["a"])])
    engine = WorkflowEngine(wf, phase_executor=executor)
    await engine.run()
    assert engine.phase_context["a"] == {"data": "a"}
    assert engine.phase_context["b"] == {"data": "b"}


# ---------- phase.llm_config 桥接测试 ----------


async def test_llm_config_consumed_by_executor():
    """工作流定义中的 phase.llm_config 应被执行器读取并作为中间优先级使用"""
    from src.video_agent.workflows.interactive import build_executors

    svc = MagicMock()
    svc.build_agent_context.return_value = "{}"
    svc.add_chat_message = MagicMock()
    executor_mock = MagicMock()
    run_ctx = {"outline": ""}

    # 全局 provider 为空，phase_configs 为空 → 应 fallback 到 phase.llm_config
    executors = build_executors(
        svc, executor_mock, run_ctx,
        chat_provider="",  # 全局为空
        chat_model="",
        image_provider="",
        image_model="",
        goal_getter=lambda: "test",
        phase_configs={},  # 无 API 覆盖
    )

    # 构造带 llm_config 的 PhaseDefinition
    phase_with_config = PhaseDefinition(
        phase_id="story",
        name="编剧",
        depends_on=[],
        execution=PhaseExecution(skill="story"),
        timeout_seconds=600,
        llm_config=ModelConfig(provider="my_provider", model="my_model", adapter_type="chat"),
    )

    # mock call_chat_completion 捕获实际使用的 provider/model
    captured = {}

    async def fake_chat(provider, model, messages, **kwargs):
        captured["provider"] = provider
        captured["model"] = model
        return "故事内容", "stop"

    with patch("src.video_agent.workflows.interactive.call_chat_completion", side_effect=fake_chat):
        with patch("src.video_agent.workflows.interactive.is_mock_provider", return_value=False):
            result = await executors["story"](phase_with_config, {})

    assert captured["provider"] == "my_provider"
    assert captured["model"] == "my_model"
    assert "skipped" not in result


async def test_phase_configs_overrides_llm_config():
    """phase_configs（API 运行时）优先级高于 phase.llm_config"""
    from src.video_agent.workflows.interactive import build_executors

    svc = MagicMock()
    svc.build_agent_context.return_value = "{}"
    svc.add_chat_message = MagicMock()
    executor_mock = MagicMock()
    run_ctx = {"outline": ""}

    executors = build_executors(
        svc, executor_mock, run_ctx,
        chat_provider="global_p",
        chat_model="global_m",
        image_provider="",
        image_model="",
        goal_getter=lambda: "test",
        phase_configs={"story": {"provider": "api_p", "model": "api_m"}},  # API 覆盖
    )

    phase_with_config = PhaseDefinition(
        phase_id="story",
        name="编剧",
        depends_on=[],
        execution=PhaseExecution(skill="story"),
        timeout_seconds=600,
        llm_config=ModelConfig(provider="def_p", model="def_m", adapter_type="chat"),
    )

    captured = {}

    async def fake_chat(provider, model, messages, **kwargs):
        captured["provider"] = provider
        captured["model"] = model
        return "故事内容", "stop"

    with patch("src.video_agent.workflows.interactive.call_chat_completion", side_effect=fake_chat):
        with patch("src.video_agent.workflows.interactive.is_mock_provider", return_value=False):
            await executors["story"](phase_with_config, {})

    # API 覆盖优先于 llm_config
    assert captured["provider"] == "api_p"
    assert captured["model"] == "api_m"


async def test_llm_config_image_generation_type():
    """llm_config adapter_type='image_generation' 应被 _resolve_image 读取"""
    from src.video_agent.workflows.interactive import build_executors

    svc = MagicMock()
    svc.get_groups.return_value = {"keyElements": [], "shots": []}
    executor_mock = MagicMock()
    run_ctx = {"outline": ""}

    executors = build_executors(
        svc, executor_mock, run_ctx,
        chat_provider="",
        chat_model="",
        image_provider="",  # 全局为空
        image_model="",
        goal_getter=lambda: "test",
        phase_configs={},
    )

    phase_with_img = PhaseDefinition(
        phase_id="image",
        name="关键帧",
        depends_on=[],
        execution=PhaseExecution(skill="image"),
        timeout_seconds=600,
        llm_config=ModelConfig(provider="img_provider", model="img_model", adapter_type="image_generation"),
    )

    # 无待生成图片 → 返回“没有待生成的关键帧”（证明没有因缺少 provider 而 skipped）
    result = await executors["image"](phase_with_img, {})
    assert "skipped" not in result
    assert "没有待生成" in result["detail"]
