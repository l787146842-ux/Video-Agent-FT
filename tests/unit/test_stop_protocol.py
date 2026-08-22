"""端到端中断协议（任务 #17）后端单测。

目标不变式：**任何中断都有痕迹、都有出口**。

钉死：
- agent_loop 协作式取消检查点命中 → 干净收尾退出（result.stopped、stopped 终态事件、
  llm_call 不再续轮、标志清理无残留）；
- 检查点 1（模型调用前/思考阶段）与检查点 2（模型调用返回后）分别触发；
- CancelledError 硬取消落地：有停止标志 → 收敛为干净收尾；无标志 → 原样上抛；
- snapshot_inflight_generations 在途登记（图片/视频 media_type 判定、跳过已完结）；
- /agent/stop 端点：登记在途 + 置协作式停止标志 + 返回 inflight；
- stopped 终态事件结构与 phase 合法集合。

停止信号只经 stop_signal 标志注册表与任务注册表传递（不触碰闸机）。
"""
import asyncio

import pytest

from src.video_agent.core.agent_loop import run_agent_loop
from src.video_agent.core.stop_signal import (
    AgentStoppedError,
    clear_stop,
    current_stop_id,
    is_stop_requested,
    request_stop,
)
from src.video_agent.web.action_executor import StateOperationExecutor
from src.video_agent.state.manager import StateManager


@pytest.fixture
def svc(tmp_path):
    return StateManager(str(tmp_path))


@pytest.fixture
def executor(svc):
    return StateOperationExecutor(svc)


def _stopped_events(events):
    return [e for e in events if e.get("type") == "stopped"]


# ---------- 检查点干净退出 ----------

async def test_checkpoint_after_llm_clean_exit(executor):
    """检查点 2（模型调用返回后）：llm_call 内置标志 → 命中干净收尾。

    无流式正文、无 FC → phase=thinking；llm_call 只被调一次（不再续轮）。
    """
    scope = "test-stop-after-llm"
    calls = {"n": 0}

    async def llm_call(system_prompt, messages, stream_hook=None):
        calls["n"] += 1
        # 模拟停止端点在模型调用进行中置标志（并发停止）
        request_stop(scope)
        return ("再见", "stop", 0)

    events = []

    async def on_event(ev):
        events.append(ev)

    result = await run_agent_loop(
        "x", llm_call=llm_call, context_builder=lambda: "ctx", executor=executor,
        history=[], max_steps=5, on_event=on_event, stop_scope=scope,
    )
    assert result.stopped is True
    assert result.stop_phase == "thinking"
    assert calls["n"] == 1
    stopped = _stopped_events(events)
    assert len(stopped) == 1
    assert stopped[0]["phase"] == "thinking"
    assert "step" in stopped[0]
    # 收尾后标志已清：不误杀下一任务
    assert not is_stop_requested(scope)


async def test_checkpoint_before_model_call_clean_exit(executor):
    """检查点 1（模型调用前/思考阶段）：第 1 轮 FC 批 actions_applied 后置标志，
    第 2 轮循环顶部命中——第 2 轮 llm_call 根本不会被调用。"""
    scope = "test-stop-before-llm"
    calls = {"n": 0}

    async def llm_call(system_prompt, messages, stream_hook=None):
        calls["n"] += 1
        # 第 1 轮：FC 工具轮续跑；不在此置标志（否则检查点 2 先命中）
        return ("处理中", "tool_calls", 1)

    events = []

    async def on_event(ev):
        events.append(ev)
        # actions_applied 发于检查点 2 之后、下一轮检查点 1 之前——
        # 在此置标志可精确命中第 2 轮的「模型调用前」检查点
        if ev.get("type") == "actions_applied":
            request_stop(scope)

    result = await run_agent_loop(
        "x", llm_call=llm_call, context_builder=lambda: "ctx", executor=executor,
        history=[], max_steps=5, on_event=on_event, stop_scope=scope,
    )
    assert result.stopped is True
    assert result.stop_phase == "thinking"
    # 第 2 轮检查点命中 → 第 2 轮 llm_call 未执行
    assert calls["n"] == 1
    stopped = _stopped_events(events)
    assert stopped and stopped[0]["phase"] == "thinking"
    assert not is_stop_requested(scope)


# ---------- CancelledError 守门 ----------

async def test_cancelled_with_stop_flag_converges_to_stop(executor):
    """硬取消落地且停止标志在位 → 收敛为用户停止（发 stopped 终态事件），不当故障。"""
    scope = "test-stop-cancel-flag"

    async def llm_call(system_prompt, messages, stream_hook=None):
        request_stop(scope)
        raise asyncio.CancelledError()

    events = []

    async def on_event(ev):
        events.append(ev)

    result = await run_agent_loop(
        "x", llm_call=llm_call, context_builder=lambda: "ctx", executor=executor,
        history=[], max_steps=3, on_event=on_event, stop_scope=scope,
    )
    assert result.stopped is True
    assert result.stop_phase == "thinking"
    assert _stopped_events(events)
    assert not is_stop_requested(scope)


async def test_cancelled_without_flag_reraises(executor):
    """硬取消但无停止标志（异常取消）→ 原样上抛，不得冒充用户停止。"""
    scope = "test-stop-cancel-noflag"

    async def llm_call(system_prompt, messages, stream_hook=None):
        raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await run_agent_loop(
            "x", llm_call=llm_call, context_builder=lambda: "ctx", executor=executor,
            history=[], max_steps=3, stop_scope=scope,
        )


# ---------- stopped 事件结构 / phase 归一 ----------

def test_agent_stopped_error_phase_normalization():
    e = AgentStoppedError("bogus_phase", 3)
    assert e.phase == "thinking"  # 非法 phase 归一为 thinking
    assert e.step == 3
    assert AgentStoppedError("streaming").phase == "streaming"
    assert AgentStoppedError("tool_executing").phase == "tool_executing"


def test_stop_flag_scope_isolation():
    """scope 隔离：不同作用域标志互不串。"""
    request_stop("scope-a")
    assert is_stop_requested("scope-a")
    assert not is_stop_requested("scope-b")
    assert not is_stop_requested("chat")
    clear_stop("scope-a")
    assert not is_stop_requested("scope-a")


# ---------- 代际 token（clear_stop 与 in-flight cancel 竞态防御） ----------

def test_stop_generation_token_monotonic():
    """request_stop 返回单调递增代际 token；current_stop_id 可快照。"""
    scope = "gen-scope"
    assert current_stop_id(scope) == 0
    sid1 = request_stop(scope)
    assert sid1 == 1 and current_stop_id(scope) == 1
    sid2 = request_stop(scope)
    assert sid2 == 2 and is_stop_requested(scope)
    # 旧代清理不得误清新代停止请求（快速重连竞态防御）
    assert clear_stop(scope, stop_id=sid1) is False
    assert is_stop_requested(scope)
    # 匹配代际才清除
    assert clear_stop(scope, stop_id=sid2) is True
    assert not is_stop_requested(scope)


def test_clear_stop_without_id_unconditional():
    """不带 id 的清理无条件生效（循环开头清上一轮残留场景）。"""
    scope = "gen-scope-2"
    request_stop(scope)
    request_stop(scope)
    assert clear_stop(scope) is True
    assert not is_stop_requested(scope)


async def test_quick_reconnect_new_stop_survives_old_finalize(executor):
    """快速重连：旧运行收尾（stopped 事件已发）之际用户又发了新停止请求
    （代际前进）→ 旧运行收尾的代际匹配清理不得误清新请求。"""
    scope = "test-stop-reconnect"

    async def llm_call(system_prompt, messages, stream_hook=None):
        request_stop(scope)
        return ("再见", "stop", 0)

    events = []

    async def on_event(ev):
        events.append(ev)
        if ev.get("type") == "stopped":
            # stopped 事件先于收尾清理发出：此刻模拟重连后的新停止请求
            request_stop(scope)

    result = await run_agent_loop(
        "x", llm_call=llm_call, context_builder=lambda: "ctx", executor=executor,
        history=[], max_steps=5, on_event=on_event, stop_scope=scope,
    )
    assert result.stopped is True
    assert _stopped_events(events), "旧运行照常收敛为 stopped 终态"
    # 新代停止请求未被旧运行收尾误清（下一轮循环开头才会残留清理）
    assert is_stop_requested(scope) is True
    clear_stop(scope)


# ---------- 在途外部生成任务登记 ----------

def test_snapshot_inflight_generations(monkeypatch):
    from src.video_agent.web import task_manager as tm_mod

    class _Stub:
        tasks = {
            "img1": {"status": "processing", "model": "m1", "draft_id": "d1", "prompt": "一只猫"},
            "vid1": {"status": "pending", "adapter_type": "video_generation",
                     "model": "v1", "draft_id": "d2", "prompt": "一段视频"},
            # 已完结任务不得计入在途
            "done1": {"status": "done", "model": "x", "prompt": "跳过我"},
        }

    monkeypatch.setattr(tm_mod, "_instance", _Stub())
    out = tm_mod.snapshot_inflight_generations()
    by_id = {o["task_id"]: o for o in out}
    assert set(by_id) == {"img1", "vid1"}
    assert by_id["img1"]["media_type"] == "image"
    assert by_id["vid1"]["media_type"] == "video"
    assert by_id["img1"]["summary"] == "一只猫"


# ---------- /agent/stop 端点：登记在途 + 置标志 ----------

async def test_agent_stop_endpoint_registers_inflight(monkeypatch):
    from src.video_agent.web import task_manager as tm_mod
    from src.video_agent.web.routes import agent as agent_route

    class _Stub:
        tasks = {
            "g1": {"status": "processing", "model": "m", "draft_id": "d", "prompt": "生成一张海报"},
        }

    monkeypatch.setattr(tm_mod, "_instance", _Stub())
    try:
        resp = await agent_route.agent_stop()
        assert resp["ok"] is True
        assert resp["cancelled"] == 0  # 测试内无在途 chat worker
        assert len(resp["inflight"]) == 1
        assert resp["inflight"][0]["media_type"] == "image"
        # 停止标志已置（协作式检查点可读到）
        assert is_stop_requested("chat") is True
    finally:
        clear_stop("chat")
