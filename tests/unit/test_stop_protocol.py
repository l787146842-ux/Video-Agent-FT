"""端到端中断协议（任务 #17）后端单测。

目标不变式：**任何中断都有痕迹、都有出口**。

钉死：
- agent_loop 协作式取消检查点命中 → 干净收尾退出（result.stopped、stopped 终态事件、
  llm_call 不再续轮、标志清理无残留）；
- 检查点 1（模型调用前/思考阶段）与检查点 2（模型调用返回后）分别触发；
- CancelledError 硬取消落地：有停止标志 → 收敛为干净收尾；无标志 → 原样上抛；
- snapshot_inflight_generations 在途登记（图片/视频 media_type 判定、跳过已完结）；
- stopped 终态事件结构与 phase 合法集合。

停止信号只经 stop_signal 标志注册表与任务注册表传递（不触碰闸机）。
"""
import asyncio

import pytest

from src.video_agent.core.agent_loop import run_agent_loop
from src.video_agent.utils.stop_signal import (
    AgentStoppedError,
    clear_stop,
    current_stop_id,
    is_stop_requested,
    request_stop,
)
from src.video_agent.core.action_executor import StateOperationExecutor
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
        return ("再见", "stop", 0, 0.0, {})

    events = []

    async def on_event(ev):
        events.append(ev)

    result = await run_agent_loop(
        "x", llm_call=llm_call, context_builder=lambda: "ctx", executor=executor,
        history=[], on_event=on_event, stop_scope=scope,
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
        return ("处理中", "tool_calls", 1, 0.0, {})

    events = []

    async def on_event(ev):
        events.append(ev)
        # actions_applied 发于检查点 2 之后、下一轮检查点 1 之前——
        # 在此置标志可精确命中第 2 轮的「模型调用前」检查点
        if ev.get("type") == "actions_applied":
            request_stop(scope)

    result = await run_agent_loop(
        "x", llm_call=llm_call, context_builder=lambda: "ctx", executor=executor,
        history=[], on_event=on_event, stop_scope=scope,
    )
    assert result.stopped is True
    assert result.stop_phase == "thinking"
    # 第 2 轮检查点命中 → 第 2 轮 llm_call 未执行
    assert calls["n"] == 1
    stopped = _stopped_events(events)
    assert stopped and stopped[0]["phase"] == "thinking"
    assert not is_stop_requested(scope)


# ---------- CancelledError 守门 ----------

async def test_cancelled_with_stop_flag_emits_stopped_then_reraises(executor):
    """硬取消落地且停止标志在位 → 先发 stopped 终态事件（干净收尾痕迹），
    随后 CancelledError 原样上抛（8888 事故批，对齐 dsh abort 语义：
    硬取消是一次性投递，吞掉返回会让孤儿循环在 worker 死后继续跑）。"""
    scope = "test-stop-cancel-flag"

    async def llm_call(system_prompt, messages, stream_hook=None):
        request_stop(scope)
        raise asyncio.CancelledError()

    events = []

    async def on_event(ev):
        events.append(ev)

    with pytest.raises(asyncio.CancelledError):
        await run_agent_loop(
            "x", llm_call=llm_call, context_builder=lambda: "ctx", executor=executor,
            history=[], on_event=on_event, stop_scope=scope,
        )
    # 收尾痕迹已落：stopped 终态事件照发（不当故障处理）
    assert _stopped_events(events)
    # 标志已清：不误杀下一任务
    assert not is_stop_requested(scope)


async def test_cancelled_without_flag_reraises(executor):
    """硬取消但无停止标志（异常取消）→ 原样上抛，不得冒充用户停止。"""
    scope = "test-stop-cancel-noflag"

    async def llm_call(system_prompt, messages, stream_hook=None):
        raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await run_agent_loop(
            "x", llm_call=llm_call, context_builder=lambda: "ctx", executor=executor,
            history=[], stop_scope=scope,
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
        return ("再见", "stop", 0, 0.0, {})

    events = []

    async def on_event(ev):
        events.append(ev)
        if ev.get("type") == "stopped":
            # stopped 事件先于收尾清理发出：此刻模拟重连后的新停止请求
            request_stop(scope)

    result = await run_agent_loop(
        "x", llm_call=llm_call, context_builder=lambda: "ctx", executor=executor,
        history=[], on_event=on_event, stop_scope=scope,
    )
    assert result.stopped is True
    assert _stopped_events(events), "旧运行照常收敛为 stopped 终态"
    # 新代停止请求未被旧运行收尾误清（下一轮循环开头才会残留清理）
    assert is_stop_requested(scope) is True
    clear_stop(scope)


# ---------- 子代理停止清理作用域隔离（8888 事故批） ----------

async def test_subagent_own_scope_keeps_parent_flag_alive(executor):
    """子代理独立 stop_scope_own：父标志触发子循环停止，但子收尾只清自己的
    作用域，父标志保持置位（8888 事故钉死：子代理 finalize 清掉共享标志，
    主循环失聪成孤儿，与续跑新循环并行 4 分钟）。"""
    parent_scope = "parent-scope-8888"
    child_scope = "parent-scope-8888::sub::conv-child"
    request_stop(parent_scope)

    calls = {"n": 0}

    async def llm_call(system_prompt, messages, stream_hook=None):
        calls["n"] += 1
        return ("不应到达", "stop", 0, 0.0, {})

    events = []

    async def on_event(ev):
        events.append(ev)

    result = await run_agent_loop(
        "x", llm_call=llm_call, context_builder=lambda: "ctx", executor=executor,
        history=[], on_event=on_event,
        stop_scope=parent_scope, stop_scope_own=child_scope,
    )
    assert result.stopped is True          # 子循环照常干净收尾
    assert calls["n"] == 0                 # 检查点 1 命中，模型调用未发生
    assert _stopped_events(events)         # 子循环自己的 stopped 终态事件已发
    # 核心断言：父标志未被子循环收尾清掉（父循环下一检查点可见）
    assert is_stop_requested(parent_scope) is True
    assert not is_stop_requested(child_scope)
    clear_stop(parent_scope)


async def test_top_level_own_scope_defaults_to_stop_scope(executor):
    """顶级循环不传 stop_scope_own = 与 stop_scope 同：收尾清理行为不变。"""
    scope = "top-level-scope"

    async def llm_call(system_prompt, messages, stream_hook=None):
        request_stop(scope)
        return ("再见", "stop", 0, 0.0, {})

    result = await run_agent_loop(
        "x", llm_call=llm_call, context_builder=lambda: "ctx", executor=executor,
        history=[], stop_scope=scope,
    )
    assert result.stopped is True
    assert not is_stop_requested(scope)    # 顶级循环收尾清自己的标志（原语义）


# ---------- 会话忙闲闸（8888 事故批） ----------

async def test_conversation_busy_gate_rejects_second_loop(executor):
    """同会话已有活跃循环 → 第二个 run_agent_loop 拒收（CONVERSATION_BUSY）；
    首个循环结束后闸释放，可再次运行。"""
    from src.video_agent.core.agent_loop import (
        is_conversation_loop_active,
    )
    from src.video_agent.exceptions import VideoAgentError

    cid = "conv-busy-gate"
    started = asyncio.Event()
    release = asyncio.Event()

    async def llm_call(system_prompt, messages, stream_hook=None):
        started.set()
        await release.wait()
        return ("完成", "stop", 0, 0.0, {})

    first = asyncio.create_task(run_agent_loop(
        "x", llm_call=llm_call, context_builder=lambda: "ctx", executor=executor,
        history=[], stop_scope="busy-scope-1",
        session_conversation_id=cid,
    ))
    await started.wait()
    assert is_conversation_loop_active(cid)

    async def llm_call_never(system_prompt, messages, stream_hook=None):
        raise AssertionError("忙时第二个循环不应发起模型调用")

    with pytest.raises(VideoAgentError) as ei:
        await run_agent_loop(
            "x", llm_call=llm_call_never, context_builder=lambda: "ctx",
            executor=executor, history=[], stop_scope="busy-scope-2",
            session_conversation_id=cid,
        )
    assert ei.value.error_code == "CONVERSATION_BUSY"
    assert ei.value.status_code == 429

    release.set()
    result = await first
    assert result.stopped is False
    assert not is_conversation_loop_active(cid)   # 出口对称释放

    # 释放后可再次运行（不残留闸）
    async def llm_call_ok(system_prompt, messages, stream_hook=None):
        return ("再跑", "stop", 0, 0.0, {})

    again = await run_agent_loop(
        "x", llm_call=llm_call_ok, context_builder=lambda: "ctx", executor=executor,
        history=[], stop_scope="busy-scope-1",
        session_conversation_id=cid,
    )
    assert "再跑" in again.text


async def test_busy_gate_skipped_without_conversation_binding(executor):
    """无会话绑定（测试/非 studio 路径）不设闸：并行循环互不影响。"""
    calls = {"n": 0}

    async def llm_call(system_prompt, messages, stream_hook=None):
        calls["n"] += 1
        await asyncio.sleep(0.01)
        return ("ok", "stop", 0, 0.0, {})

    await asyncio.gather(*[
        run_agent_loop(
            "x", llm_call=llm_call, context_builder=lambda: "ctx", executor=executor,
            history=[], stop_scope=f"no-cid-{i}",
        ) for i in range(3)
    ])
    assert calls["n"] == 3


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
