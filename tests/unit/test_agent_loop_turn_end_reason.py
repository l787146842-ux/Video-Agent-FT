# -*- coding: utf-8 -*-
"""8888 委派失踪批 · 批 D：轮末 turn/end 真值（core 层，P1）。

agent_loop finally 统一落 turn/end，此前恒传缺省 reason="done"——子代理 504
崩死其 turn/end 仍记 done，thread_status 判据「有 turn/end 即 completed」→
左栏误报「已完成」。批 D 让 finally 携带本轮真实出口。

钉死四出口 reason：正常 done / 停止 stopped / 取消 cancelled / 异常 error。
"""
import asyncio

import pytest

from src.video_agent.core import agent_loop as al
from src.video_agent.core.action_executor import StateOperationExecutor
from src.video_agent.core.agent_loop import run_agent_loop
from src.video_agent.utils.stop_signal import AgentStoppedError
from src.video_agent.state.manager import StateManager


@pytest.fixture
def svc(tmp_path, monkeypatch):
    StateManager.reset_instance()
    instance = StateManager(str(tmp_path))
    StateManager._instance = instance
    #  spy finally 落 turn/end 的 reason（只关心真值，不驱动事件流文件）
    captured = []
    monkeypatch.setattr(
        al.session_log, "append_turn_end",
        lambda _svc, _cid, reason="done": captured.append(reason))
    yield instance, captured
    StateManager.reset_instance()


async def _done_llm(system_prompt, messages, stream_hook=None):
    return ("全部完成", "stop", 0, 0.0, {})


async def _raise_runtime(system_prompt, messages, stream_hook=None):
    raise RuntimeError("upstream 504")


async def _raise_cancel(system_prompt, messages, stream_hook=None):
    raise asyncio.CancelledError()


async def _raise_stopped(system_prompt, messages, stream_hook=None):
    raise AgentStoppedError("thinking", 1)


async def _run(llm, svc):
    executor = StateOperationExecutor(svc)
    return await run_agent_loop(
        "x", llm_call=llm, context_builder=lambda: "ctx",
        executor=executor, history=[], session_conversation_id="conv-main")


async def test_normal_exit_reason_done(svc):
    instance, captured = svc
    result = await _run(_done_llm, instance)
    assert result.stopped is False
    assert captured == ["done"]


async def test_stopped_exit_reason_stopped(svc):
    instance, captured = svc
    result = await _run(_raise_stopped, instance)
    assert result.stopped is True
    assert captured == ["stopped"]


async def test_error_exit_reason_error(svc):
    instance, captured = svc
    with pytest.raises(RuntimeError):
        await _run(_raise_runtime, instance)
    assert captured == ["error"]


async def test_cancelled_exit_reason_cancelled(svc):
    instance, captured = svc
    with pytest.raises(asyncio.CancelledError):
        await _run(_raise_cancel, instance)
    assert captured == ["cancelled"]
