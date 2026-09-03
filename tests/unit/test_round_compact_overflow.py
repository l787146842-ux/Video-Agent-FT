# -*- coding: utf-8 -*-
"""第 5 批（Q6/Q7）/ 用户裁决 2026-09-01：循环内语义压缩 + 超预算不拦发。

钉死语义：
- 预算逼近（>=0.8×预算）时最旧轮组整组摘要替换（FC 配对原子、用户原话不孤立压）；
- 摘要按轮组指纹缓存（同内容不重复烧调用）；失败静默回落截断链；
- 短对话（未达触发比例）零变化；
- 四级保险丝用尽仍超预算：默认（policy=warn）警告后照发；
  policy=error 回拨开关（抛 GenerationError 不发请求）。
"""
import pytest

from src.video_agent.adapters.base_chat import BaseChatAdapter, ChatResponse
from src.video_agent.config import settings
from src.video_agent.core import round_compact
from src.video_agent.core.planner import Planner, PlannerContext
from src.video_agent.exceptions import GenerationError
from src.video_agent.state.manager import StateManager


class SummaryAdapter(BaseChatAdapter):
    """记录调用次数的摘要假 adapter"""

    def __init__(self, summary="摘要：确定了赛博朋克风格", fail=False):
        self.calls = 0
        self.summary = summary
        self.fail = fail

    @property
    def supports_function_calling(self) -> bool:
        return False

    async def chat(self, messages, **kwargs) -> ChatResponse:
        self.calls += 1
        if self.fail:
            raise RuntimeError("upstream down")
        return ChatResponse(content=self.summary, finish_reason="stop")

    async def chat_stream(self, messages, **kwargs):
        from src.video_agent.adapters.base_chat import StreamChunk
        self.calls += 1
        yield StreamChunk(type="text_delta", text=self.summary)


@pytest.fixture(autouse=True)
def _clear_compact_cache():
    """模块级指纹缓存跨用例隔离。"""
    round_compact._COMPACT_CACHE.clear()
    yield
    round_compact._COMPACT_CACHE.clear()


def _big_turns(n=3, size=600):
    """n 个真实用户轮组：真实用户消息 + assistant(tool_calls) + 系统回喂。"""
    msgs = []
    for i in range(n):
        msgs.append({"role": "user", "content": f"第{i}轮用户指令" + "长" * size})
        msgs.append({"role": "assistant", "content": "",
                     "tool_calls": [{"id": f"c{i}", "type": "function",
                                     "function": {"name": "read_draft", "arguments": "{}"}}]})
        msgs.append({"role": "user", "content": "（系统）本轮调用的工具已执行完毕，结果如下：\n- read_draft：执行成功" + "喂" * size})
    return msgs


@pytest.mark.asyncio
async def test_compact_replaces_oldest_round_atomically():
    """超触发比例：最旧轮组整组（含 FC 配对）替换为单条摘要。"""
    msgs = _big_turns(3)
    before = list(msgs)
    adapter = SummaryAdapter()
    # 预算设小使总量 >= 0.8*max_tokens
    ok = await round_compact.compact_oldest_round(msgs, adapter, max_tokens=800, keep_recent=4)
    assert ok is True
    assert adapter.calls == 1
    assert len(msgs) == len(before) - 2  # 3 条轮组 -> 1 条摘要
    assert msgs[0]["content"].startswith("（系统）早期轮次已压缩为摘要")
    assert "赛博朋克" in msgs[0]["content"]
    # 保护窗内最近 4 条原样
    assert msgs[-4:] == before[-4:]


@pytest.mark.asyncio
async def test_compact_fingerprint_cache():
    """同内容轮组二次压缩命中指纹缓存，不重复烧摘要调用。"""
    adapter = SummaryAdapter()
    first = _big_turns(3)
    assert await round_compact.compact_oldest_round(first, adapter, 800, 4) is True
    second = _big_turns(3)
    assert await round_compact.compact_oldest_round(second, adapter, 800, 4) is True
    assert adapter.calls == 1  # 第二次走缓存


@pytest.mark.asyncio
async def test_compact_below_threshold_noop():
    """未达触发比例：零变化。"""
    msgs = [{"role": "user", "content": "短消息"}, {"role": "assistant", "content": "好"}]
    adapter = SummaryAdapter()
    assert await round_compact.compact_oldest_round(msgs, adapter, max_tokens=100000) is False
    assert adapter.calls == 0
    assert len(msgs) == 2


@pytest.mark.asyncio
async def test_compact_adapter_failure_falls_back():
    """摘要调用失败：静默回落（False + 消息不变）。"""
    msgs = _big_turns(3)
    before = list(msgs)
    adapter = SummaryAdapter(fail=True)
    assert await round_compact.compact_oldest_round(msgs, adapter, 800, 4) is False
    assert msgs == before


@pytest.mark.asyncio
async def test_compact_lone_user_message_preserved():
    """保护窗外只剩孤立单条真实用户消息：不压（用户原话逐字保留）。"""
    msgs = [{"role": "user", "content": "唯一一轮" + "长" * 700}] + _big_turns(2)
    adapter = SummaryAdapter()
    # keep_recent 覆盖后两轮（6 条）→ 保护起点=1，最旧组仅 1 条
    assert await round_compact.compact_oldest_round(msgs, adapter, 800, keep_recent=6) is False
    assert adapter.calls == 0
    assert msgs[0]["content"].startswith("唯一一轮")


@pytest.mark.asyncio
async def test_compact_edge_branches():
    """边缘分支：多模态采样、采样上限 break、合成头顺移、空摘要回落。"""
    # 多模态 content parts 采样 + 第二条超采样上限触发 break
    huge_text = "x" * (round_compact._MAX_DIALOG_CHARS + 100)
    msgs = [
        {"role": "user", "content": [{"type": "text", "text": "看图"}, {"type": "image_url", "image_url": {"url": "u"}}]},
        {"role": "assistant", "content": "好"},
        {"role": "user", "content": huge_text},
    ] + _big_turns(2)
    adapter = SummaryAdapter()
    assert await round_compact.compact_oldest_round(msgs, adapter, 800, keep_recent=4) is True
    assert msgs[0]["content"].startswith("（系统）早期轮次已压缩为摘要")
    round_compact._COMPACT_CACHE.clear()

    # 合成摘要头顺移：索引 0 非真实用户消息且保护窗覆盖其余 → 不压
    synth = [{"role": "user", "content": "（系统）早期轮次已压缩为摘要：旧"},
             {"role": "user", "content": "新指令"}, {"role": "assistant", "content": "好"}]
    adapter2 = SummaryAdapter()
    assert await round_compact.compact_oldest_round(synth, adapter2, 1, keep_recent=2) is False
    assert adapter2.calls == 0
    round_compact._COMPACT_CACHE.clear()

    # 空摘要回落：adapter 返回空串 → False 且不变
    empty = _big_turns(3)
    adapter3 = SummaryAdapter(summary="   ")
    assert await round_compact.compact_oldest_round(empty, adapter3, 800, 4) is False
    assert len(empty) == 9


# ---------- 超预算不拦发（默认）/ policy=error 回拨拦发 ----------

@pytest.fixture
def svc(tmp_path):
    StateManager.reset_instance()
    instance = StateManager(str(tmp_path))
    StateManager._instance = instance
    yield instance
    StateManager.reset_instance()


def _executor_with(adapter):
    planner = Planner(llm_adapter=adapter)
    executor = planner._turn_executor
    executor._context = PlannerContext()
    return executor


@pytest.mark.asyncio
async def test_overflow_policy_error_raises(svc):
    """policy=error（回拨开关）：保险丝用尽仍超预算 → GenerationError，不发请求。"""
    adapter = SummaryAdapter(summary="你好")
    executor = _executor_with(adapter)
    huge = [{"role": "user", "content": "巨" * 400} for _ in range(5)]
    object.__setattr__(settings, "context_window_size", 100)
    object.__setattr__(settings, "context_overflow_policy", "error")
    try:
        with pytest.raises(GenerationError) as ei:
            await executor.call_llm("sys", huge)
        assert "超模型窗口" in str(ei.value)
        assert adapter.calls == 0  # 主调用未发出（摘要尝试不计入：组不满足条件）
    finally:
        object.__setattr__(settings, "context_window_size", 128000)
        object.__setattr__(settings, "context_overflow_policy", "warn")


@pytest.mark.asyncio
async def test_stream_channel_same_ladder(svc):
    """流式通道同口径：压缩阶梯 + 默认（warn）放行（覆盖 call_llm_stream 分支）。"""
    adapter = SummaryAdapter(summary="你好")
    executor = _executor_with(adapter)
    huge = [{"role": "user", "content": "巨" * 400} for _ in range(5)]
    object.__setattr__(settings, "context_window_size", 100)
    try:
        chunks = []
        async for chunk in executor.call_llm_stream("sys", huge):
            chunks.append(chunk)
        assert any(c.type == "text_delta" for c in chunks)
        assert adapter.calls == 1
    finally:
        object.__setattr__(settings, "context_window_size", 128000)
        object.__setattr__(settings, "context_overflow_policy", "warn")


@pytest.mark.asyncio
async def test_overflow_default_warn_passthrough(svc):
    """默认（policy=warn）：四级用尽仍超预算 → 警告后照发（主调用发出）。"""
    adapter = SummaryAdapter(summary="你好")
    executor = _executor_with(adapter)
    huge = [{"role": "user", "content": "巨" * 400} for _ in range(5)]
    object.__setattr__(settings, "context_window_size", 100)
    try:
        resp = await executor.call_llm("sys", huge)
        assert resp.content == "你好"
        assert adapter.calls == 1
        # 第 5 批预算可见：分配账记入 live 注册表（context-usage 端点同源）
        from src.video_agent.utils import live_metrics
        bd = live_metrics.get_budget_breakdown(
            StateManager.get_instance().active_project_id)
        assert bd is not None and bd["total"] > 0 and bd["budget"] == 80
        assert bd["history"] > 0 and "system" in bd and "tools" in bd
    finally:
        object.__setattr__(settings, "context_window_size", 128000)
        object.__setattr__(settings, "context_overflow_policy", "warn")
