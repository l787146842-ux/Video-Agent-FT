# -*- coding: utf-8 -*-
"""P2-3（提示词大换序 A 案）：状态上下文出 system —— history 尾部消息（user 通道）注入。

钉死两类核心断言：
1. 「state 内容仍被模型可见」：状态 JSON 经 history 最后一条消息注入，
   adapter 实际收到的消息末尾可见完整状态（移的是位置/通道，不是删内容）；
2. 「system 字节在 state 变化时保持稳定」：状态变化只改尾部消息，
   system 本体（含 Skill 块）逐字节不变——供应商前缀缓存命中前提。

另钉：预算保险丝迁移（截断后仍超预算 → 尾部状态消息降级重建）；
非工作台上下文/空状态不注入（零增量）。
"""
import pytest

from src.video_agent.adapters.base_chat import BaseChatAdapter, ChatResponse
from src.video_agent.core.planner import Planner, PlannerContext
from src.video_agent.state.manager import StateManager


class _EchoAdapter(BaseChatAdapter):
    """非流式假 adapter：捕获模型实际收到的消息"""

    def __init__(self):
        self.seen = []

    @property
    def supports_function_calling(self) -> bool:
        return False

    async def chat(self, messages, **kwargs) -> ChatResponse:
        self.seen.append(list(messages))
        return ChatResponse(content="好", finish_reason="stop", token_usage=10)

    async def chat_stream(self, messages, **kwargs):
        yield  # pragma: no cover


@pytest.fixture
def svc(tmp_path):
    StateManager.reset_instance()
    instance = StateManager(str(tmp_path))
    StateManager._instance = instance
    yield instance
    StateManager.reset_instance()


def _executor(svc, adapter=None):
    planner = Planner(llm_adapter=adapter or _EchoAdapter())
    return planner, planner._turn_executor


# ---------- 断言类一：state 内容仍被模型可见 ----------

async def test_state_visible_to_model_via_tail_message(svc):
    """状态 JSON 作为 history 最后一条消息到达模型（近生成端）"""
    planner, executor = _executor(svc)
    executor._context = PlannerContext(
        use_studio_context=True, state_json='{"ke": "主角"}')
    adapter = planner.llm_adapter
    await executor.llm_call("SYSTEM-PREFIX", [{"role": "user", "content": "你好"}])
    msgs = adapter.seen[0]
    assert msgs[0]["role"] == "system" and msgs[0]["content"] == "SYSTEM-PREFIX"
    assert msgs[-1]["role"] == "user"
    assert "当前工作台状态 JSON 如下" in msgs[-1]["content"]
    assert '{"ke": "主角"}' in msgs[-1]["content"]


async def test_state_refreshed_between_steps(svc):
    """多步循环按轮刷新：状态变化后下一次调用尾部消息即最新状态"""
    planner, executor = _executor(svc)
    box = {"state": '{"version": 1}'}
    executor._context = PlannerContext(
        use_studio_context=True, state_builder=lambda: box["state"])
    adapter = planner.llm_adapter
    msgs1 = [{"role": "user", "content": "开工"}]
    msgs2 = [{"role": "user", "content": "继续"}]
    await executor.llm_call("S", msgs1)
    box["state"] = '{"version": 2}'
    await executor.llm_call("S", msgs2)
    first, second = adapter.seen
    assert '"version": 1' in first[-1]["content"]
    assert '"version": 2' in second[-1]["content"]
    # 入参 messages 不被注入污染（状态消息只存在于当次请求，不入持久化历史）
    assert msgs1 == [{"role": "user", "content": "开工"}]
    assert msgs2 == [{"role": "user", "content": "继续"}]


# ---------- 断言类二：system 字节在 state 变化时保持稳定 ----------

async def test_system_bytes_stable_when_state_changes(svc):
    """状态只改尾部消息：system 本体逐字节稳定（含协议/目录等稳定前缀），
    且状态不再出现在 system 段"""
    planner, executor = _executor(svc)
    box = {"state": '{"version": 1}'}
    executor._context = PlannerContext(
        use_studio_context=True, state_builder=lambda: box["state"])
    adapter = planner.llm_adapter
    await executor.llm_call("SYSTEM-BODY", [{"role": "user", "content": "a"}])
    box["state"] = '{"version": 2, "extra": "x"}'
    await executor.llm_call("SYSTEM-BODY", [{"role": "user", "content": "b"}])
    first, second = adapter.seen
    assert first[0]["content"] == second[0]["content"] == "SYSTEM-BODY"
    assert "version" not in first[0]["content"]
    # 尾部消息承载差异（前缀稳定、变化收敛在生成端附近）
    assert first[-1]["content"] != second[-1]["content"]


def test_system_prompt_stable_across_state_rebuilds(svc):
    """prompt_builder 层：状态变化两次构建 system 逐字节一致；
    状态经尾部消息可见（两类断言的组装层镜像）"""
    planner, _ = _executor(svc)
    box = {"state": '{"a": 1}'}
    ctx = PlannerContext(use_studio_context=True, state_builder=lambda: box["state"])
    p1 = planner._build_system_prompt(ctx)
    box["state"] = '{"a": 2}'
    p2 = planner._build_system_prompt(ctx)
    assert p1 == p2
    assert '{"a": 2}' in planner._prompt_builder.build_state_tail_message(ctx)


# ---------- 零增量：非工作台上下文 / 空状态不注入 ----------

async def test_no_tail_message_without_studio_context(svc):
    planner, executor = _executor(svc)
    executor._context = PlannerContext(use_studio_context=False, state_json='{"a":1}')
    adapter = planner.llm_adapter
    await executor.llm_call("S", [{"role": "user", "content": "你好"}])
    assert len(adapter.seen[0]) == 2  # 仅 system + user，未注入尾部消息


async def test_no_tail_message_when_state_empty(svc):
    planner, executor = _executor(svc)
    executor._context = PlannerContext(use_studio_context=True, state_json="")
    adapter = planner.llm_adapter
    await executor.llm_call("S", [{"role": "user", "content": "你好"}])
    assert len(adapter.seen[0]) == 2


def test_no_tail_message_when_context_missing(svc):
    """直驱自洽：未装配 context 时尾部消息组装返回空串（不抛异常）；
    llm_call 本体仍要求调用方提供 context（既有直驱契约不变）"""
    _, executor = _executor(svc)
    assert executor._context is None
    assert executor._state_tail_message() == ""


# ---------- 预算保险丝迁移：尾部状态消息降级重建 ----------

def test_degrade_state_tail_when_over_budget(svc):
    """截断后仍超预算 → 尾部状态消息用降级状态（只留组标题/计数）重建"""
    planner, executor = _executor(svc)
    executor._context = PlannerContext(
        use_studio_context=True,
        state_json='{"full": "大状态"}',
        degraded_state_builder=lambda: '{"degraded": true}',
    )
    tail = planner._prompt_builder.build_state_tail_message(executor._context)
    msgs = [
        {"role": "system", "content": "S"},
        {"role": "user", "content": "你好"},
        {"role": "user", "content": tail},
    ]
    out = executor._degrade_state_tail(msgs, max_tokens=1, state_tail=tail)
    assert '{"degraded": true}' in out[-1]["content"]
    assert '{"full": "大状态"}' not in out[-1]["content"]


def test_degrade_state_tail_noop_within_budget(svc):
    """未超预算不重建（正常路径零开销语义）"""
    planner, executor = _executor(svc)
    executor._context = PlannerContext(
        use_studio_context=True,
        state_json='{"full": "大状态"}',
        degraded_state_builder=lambda: '{"degraded": true}',
    )
    tail = planner._prompt_builder.build_state_tail_message(executor._context)
    msgs = [
        {"role": "system", "content": "S"},
        {"role": "user", "content": tail},
    ]
    out = executor._degrade_state_tail(msgs, max_tokens=10_000_000, state_tail=tail)
    assert out[-1]["content"] == tail


def test_degrade_state_tail_noop_without_degraded_builder(svc):
    """无降级构建器时维持原消息（保险丝缺省不阻断）"""
    planner, executor = _executor(svc)
    executor._context = PlannerContext(
        use_studio_context=True, state_json='{"full": "大状态"}')
    tail = planner._prompt_builder.build_state_tail_message(executor._context)
    msgs = [
        {"role": "system", "content": "S"},
        {"role": "user", "content": tail},
    ]
    out = executor._degrade_state_tail(msgs, max_tokens=1, state_tail=tail)
    assert out[-1]["content"] == tail
