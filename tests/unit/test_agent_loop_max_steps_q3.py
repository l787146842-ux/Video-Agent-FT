# -*- coding: utf-8 -*-
"""Q3 裁决（2026-09-01）钉死：多步上限不再 import 期冻结。

① current_max_steps 实时读 settings 并按 MAX_STEPS_RANGE 钳制（脏值回落）；
② run_agent_loop 每步实时读取——运行中热调上限可继续推进；
③ 显式传参钉死口径优先（测试/特殊编排不受热更新影响）。
"""
import pytest

from src.video_agent.config import settings
from src.video_agent.core import agent_loop
from src.video_agent.core.action_executor import StateOperationExecutor
from src.video_agent.core.agent_loop import current_max_steps, run_agent_loop
from src.video_agent.state.manager import StateManager


@pytest.fixture
def svc(tmp_path):
    return StateManager(str(tmp_path))


@pytest.fixture
def executor(svc):
    return StateOperationExecutor(svc)


# ---------- ① current_max_steps：实时读 + 钳制 ----------

def test_current_max_steps_reads_settings_live():
    """settings 热更新后实时反映（不冻结），超界值钳制回区间。"""
    original = settings.max_steps
    try:
        object.__setattr__(settings, "max_steps", 6)
        assert current_max_steps() == 6
        object.__setattr__(settings, "max_steps", 12)
        assert current_max_steps() == 12  # 运行中改动即刻生效
        object.__setattr__(settings, "max_steps", 999)
        assert current_max_steps() == 30  # 上界钳制
        object.__setattr__(settings, "max_steps", 0)
        assert current_max_steps() == 1   # 下界钳制
        object.__setattr__(settings, "max_steps", "脏值")
        assert current_max_steps() == 6   # 非法值回落默认
    finally:
        object.__setattr__(settings, "max_steps", original)


# ---------- ② 循环每步实时读：运行中调高上限可继续推进 ----------

async def test_loop_live_rereads_max_steps_each_iteration(executor):
    """初始上限 2：第 1 步执行中热调到 4 → 后续每步按新上限推进而非在第 2 步终止。"""
    original = agent_loop.settings.max_steps
    object.__setattr__(agent_loop.settings, "max_steps", 2)
    calls = {"n": 0}

    async def llm_call(system_prompt, messages, stream_hook=None):
        calls["n"] += 1
        if calls["n"] == 1:
            # 模拟用户在循环运行中经全局设置页调高上限（热更新通道同款写入）；
            # 于第 1 步内热调，第 2 步起每步实时读到的即为新上限 4
            object.__setattr__(agent_loop.settings, "max_steps", 4)
        if calls["n"] < 4:
            return ("处理中", "tool_calls", 1)
        return ("全部完成", "stop", 0)

    try:
        result = await run_agent_loop(
            "x", llm_call=llm_call, context_builder=lambda: "ctx", executor=executor,
            history=[], stop_scope="q3-live-reread",
        )
    finally:
        object.__setattr__(agent_loop.settings, "max_steps", original)
    assert calls["n"] == 4  # 未被初始上限 2 截断
    assert "全部完成" in result.text
    assert not any("多步上限" in w for w in result.warnings)


async def test_loop_hits_live_cap_with_continue_action(executor):
    """未热调时按实时上限终止：达上限发警告与「继续完成」按钮（现状语义不回归）。"""
    original = agent_loop.settings.max_steps
    object.__setattr__(agent_loop.settings, "max_steps", 2)

    async def llm_call(system_prompt, messages, stream_hook=None):
        return ("处理中", "tool_calls", 1)  # 永不收敛，逼到上限

    try:
        result = await run_agent_loop(
            "x", llm_call=llm_call, context_builder=lambda: "ctx", executor=executor,
            history=[], stop_scope="q3-live-cap",
        )
    finally:
        object.__setattr__(agent_loop.settings, "max_steps", original)
    assert result.steps == 2
    assert any("多步上限" in w for w in result.warnings)
    assert any(a.get("kind") == "continue" for a in result.suggested_actions)


# ---------- ③ 显式传参钉死口径优先 ----------

async def test_explicit_max_steps_pins_cap_against_hot_update(executor):
    """显式 max_steps=1：运行中热调 settings 不影响钉死口径。"""
    original = agent_loop.settings.max_steps
    object.__setattr__(agent_loop.settings, "max_steps", 9)

    async def llm_call(system_prompt, messages, stream_hook=None):
        object.__setattr__(agent_loop.settings, "max_steps", 20)
        return ("处理中", "tool_calls", 1)

    try:
        result = await run_agent_loop(
            "x", llm_call=llm_call, context_builder=lambda: "ctx", executor=executor,
            history=[], max_steps=1, stop_scope="q3-explicit-pin",
        )
    finally:
        object.__setattr__(agent_loop.settings, "max_steps", original)
    assert result.steps == 1
    assert any("多步上限" in w for w in result.warnings)
