"""run_agent_loop 承重路径补强（P1-11b）：停止/取消/引导注入/坏输出分支。

钉死 agent_loop 此前未覆盖的承重分支（只加测试不改生产代码）：
① 步间引导注入（pending_injector）：成功注入发 guidance_injected、
   注入器抛异常安全降级、空正文条目跳过；
② llm_call 直接抛 AgentStoppedError → 收敛干净收尾（无 stop_id 走无条件清理）；
③ 坏输出重试期间的两处停止检查点（重试前命中 / 重试 llm 抛停止）；
④ GenerationCancelled 穿透 → 收敛 _finalize_stop 同款收尾；
⑤ 空正文兜底：暂停说明回填正文 / 仅操作数告知；
⑥ finish=length 截断告警；⑦ _bad_output_nudge 外置文案缺失回落内置文案。
"""
import pytest

from src.video_agent.core import agent_loop
from src.video_agent.core.action_executor import StateOperationExecutor
from src.video_agent.core.agent_loop import run_agent_loop
from src.video_agent.utils.stop_signal import (
    AgentStoppedError,
    is_stop_requested,
    request_stop,
)
from src.video_agent.utils.cancel_token import GenerationCancelled
from src.video_agent.state.manager import StateManager


def _p5(reply):
    """测试数据便捷写法：3/4 元组补齐为 5 元组契约 (plan_ms=0.0 / extra={})。"""
    if len(reply) == 5:
        return reply
    return reply + (0.0, {}) if len(reply) == 3 else reply + ({},)


@pytest.fixture
def svc(tmp_path):
    return StateManager(str(tmp_path))


@pytest.fixture
def executor(svc):
    return StateOperationExecutor(svc)


def _events_collecter():
    events = []

    async def on_event(ev):
        events.append(ev)

    return events, on_event


# ---------- ⑦ _bad_output_nudge 已随批 2 退役（判空 = 正常收轮），用例删除 ----------

# ---------- ① 步间引导注入（pending_injector） ----------

async def test_guidance_injected_between_steps(executor):
    """第 2 轮前送达引导：注入正文入 messages 并发 guidance_injected 事件"""
    scope = "guide-inject-ok"
    replies = iter([
        ("处理中", "tool_calls", 1),
        ("已按您的补充完成", "stop", 1),
    ])
    injected = {"n": 0}

    async def llm_call(system_prompt, messages, stream_hook=None):
        return _p5(next(replies))

    def pending_injector():
        injected["n"] += 1
        return [{"id": "g1", "text": "请加快进度"}]

    events, on_event = _events_collecter()
    result = await run_agent_loop(
        "x", llm_call=llm_call, context_builder=lambda: "ctx", executor=executor,
        history=[], max_steps=5, on_event=on_event,
        pending_injector=pending_injector, stop_scope=scope,
    )
    assert injected["n"] >= 1                      # 第 2 轮触发过注入器
    guide = [e for e in events if e.get("type") == "guidance_injected"]
    assert len(guide) == 1
    assert guide[0]["id"] == "g1" and guide[0]["text"] == "请加快进度"
    assert "已按您的补充完成" in result.text


async def test_guidance_injector_exception_degrades_safely(executor):
    """注入器抛异常：安全降级为空注入，循环不受影响照常收尾"""
    scope = "guide-inject-err"
    replies = iter([
        ("处理中", "tool_calls", 1),
        ("完成", "stop", 1),
    ])

    async def llm_call(system_prompt, messages, stream_hook=None):
        return _p5(next(replies))

    def pending_injector():
        raise RuntimeError("注入器故障")

    events, on_event = _events_collecter()
    result = await run_agent_loop(
        "x", llm_call=llm_call, context_builder=lambda: "ctx", executor=executor,
        history=[], max_steps=5, on_event=on_event,
        pending_injector=pending_injector, stop_scope=scope,
    )
    assert result.stopped is False
    assert "完成" in result.text
    assert not [e for e in events if e.get("type") == "guidance_injected"]


async def test_guidance_blank_text_skipped(executor):
    """空正文引导条目跳过：不入 messages、不发事件（无意义的引导不注入）"""
    scope = "guide-inject-blank"
    replies = iter([
        ("处理中", "tool_calls", 1),
        ("完成", "stop", 1),
    ])

    async def llm_call(system_prompt, messages, stream_hook=None):
        return _p5(next(replies))

    def pending_injector():
        return [{"id": "g2", "text": "   "}, {"id": "g3", "text": ""}]

    events, on_event = _events_collecter()
    await run_agent_loop(
        "x", llm_call=llm_call, context_builder=lambda: "ctx", executor=executor,
        history=[], max_steps=5, on_event=on_event,
        pending_injector=pending_injector, stop_scope=scope,
    )
    assert not [e for e in events if e.get("type") == "guidance_injected"]


# ---------- ② llm_call 直抛 AgentStoppedError → 干净收尾 ----------

async def test_llm_raises_agent_stopped_error_clean_exit(executor):
    """planner 层检查点抛 AgentStoppedError（无 stop_id）：收敛收尾、
    走无条件清标志分支，发 stopped 终态事件"""
    scope = "stop-llm-raise"

    async def llm_call(system_prompt, messages, stream_hook=None):
        raise AgentStoppedError("streaming", 1)

    events, on_event = _events_collecter()
    result = await run_agent_loop(
        "x", llm_call=llm_call, context_builder=lambda: "ctx", executor=executor,
        history=[], max_steps=3, on_event=on_event, stop_scope=scope,
    )
    assert result.stopped is True
    assert result.stop_phase == "streaming"
    assert [e for e in events if e.get("type") == "stopped"]
    assert not is_stop_requested(scope)


# ---------- ③ 坏输出重试期间的停止检查点 ----------

async def test_stop_before_bad_output_retry(executor):
    """空输出入坏输出重试，重试前检查点命中停止 → 干净收尾（停止优先于重试）"""
    scope = "stop-badretry-before"

    async def llm_call(system_prompt, messages, stream_hook=None):
        # 首调即置停止标志：返回空输出后，重试前检查点命中
        request_stop(scope)
        return ("", "", 0, 0.0, {})

    events, on_event = _events_collecter()
    result = await run_agent_loop(
        "x", llm_call=llm_call, context_builder=lambda: "ctx", executor=executor,
        history=[], max_steps=3, on_event=on_event, stop_scope=scope,
    )
    assert result.stopped is True
    assert result.stop_phase == "thinking"
    assert [e for e in events if e.get("type") == "stopped"]
    assert not is_stop_requested(scope)


# test_stop_during_bad_output_retry_llm 已随批 2 退役删除
# （坏输出 nudge 重试退役，判空 = 正常收轮；停止检查点语义由其余用例覆盖）


# ---------- ④ GenerationCancelled 穿透收敛收尾 ----------

async def test_generation_cancelled_converges_to_stop(executor):
    """工具/adapters 检查点协作退出（GenerationCancelled）：
    收敛 _finalize_stop 同款收尾，落 stopped 终态、stopped=True"""
    scope = "stop-cancelled"

    async def llm_call(system_prompt, messages, stream_hook=None):
        raise GenerationCancelled()

    events, on_event = _events_collecter()
    result = await run_agent_loop(
        "x", llm_call=llm_call, context_builder=lambda: "ctx", executor=executor,
        history=[], max_steps=3, on_event=on_event, stop_scope=scope,
    )
    assert result.stopped is True
    assert result.stop_phase == "tool_executing"
    assert [e for e in events if e.get("type") == "stopped"]
    assert not is_stop_requested(scope)


# ---------- ⑤ 空正文兜底 ----------

async def test_empty_text_falls_back_to_confirmation(executor):
    """暂停轮无正文：用暂停说明回填正文，不向用户展示空内容"""
    llm_replies = iter([
        ("", "stop", 1, 0.0, {"confirmation": "请确认是否继续", "confirmation_options": []}),
    ])

    async def llm_call(system_prompt, messages, stream_hook=None):
        return _p5(next(llm_replies))

    result = await run_agent_loop(
        "x", llm_call=llm_call, context_builder=lambda: "ctx", executor=executor,
        history=[], max_steps=3,
    )
    assert result.confirmation == "请确认是否继续"
    assert result.text == "请确认是否继续"


async def test_tool_round_then_empty_stop_emits_bad_output_notice(executor):
    """工具轮（applied=2）后模型空响应收尾：给明确异常提示，不伪装成空内容；
    累计操作数跨轮保留（步数上限退役后循环由模型输出驱动收尾，不再靠封顶中断）。"""
    replies = iter([
        ("", "tool_calls", 2),
        ("", "stop", 0),
    ])

    async def llm_call(system_prompt, messages, stream_hook=None):
        return _p5(next(replies))

    result = await run_agent_loop(
        "x", llm_call=llm_call, context_builder=lambda: "ctx", executor=executor,
        history=[],
    )
    assert result.applied_actions == 2
    assert "空响应" in result.text


# ---------- ⑥ finish=length 截断告警 ----------

async def test_length_finish_appends_truncation_warning(executor):
    """max_tokens 截断（finish=length）：附告警提示可能不完整，链路继续"""
    replies = iter([
        ("内容可能被截断", "length", 1),
        ("全部完成", "stop", 1),
    ])

    async def llm_call(system_prompt, messages, stream_hook=None):
        return _p5(next(replies))

    result = await run_agent_loop(
        "x", llm_call=llm_call, context_builder=lambda: "ctx", executor=executor,
        history=[], max_steps=5,
    )
    assert any("截断" in w for w in result.warnings)
    assert "全部完成" in result.text
