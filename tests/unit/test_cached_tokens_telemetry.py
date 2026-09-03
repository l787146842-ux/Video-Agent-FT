"""P2-1 KV-cache 遥测链路单测：

- base_chat.extract_prompt_cache_usage 各家字段口径（OpenAI/Anthropic/DeepSeek/缺失）
- OpenAICompatChatAdapter 非流式/流式提取 cached tokens
- TurnExecutor 的 5 元组上抛缓存命中 + 样本入 live_metrics 滚动窗口
- live_metrics 命中率汇聚
- tracer end_step 落 StepTrace.cached_tokens（0 不写键）
"""
import httpx
import pytest
import respx

from src.video_agent.adapters.base_chat import (
    BaseChatAdapter,
    ChatResponse,
    extract_prompt_cache_usage,
)
from src.video_agent.adapters.openai_compat import OpenAICompatChatAdapter
from src.video_agent.utils import live_metrics
from src.video_agent.core.planner import Planner, PlannerContext
from src.video_agent.core.tracer import AgentTracer
from src.video_agent.state.manager import StateManager

BASE_URL = "https://api.test-provider.com/v1"


# ---------- extract_prompt_cache_usage 口径 ----------


def test_extract_openai_style():
    usage = {
        "prompt_tokens": 1000,
        "completion_tokens": 50,
        "total_tokens": 1050,
        "prompt_tokens_details": {"cached_tokens": 640},
    }
    assert extract_prompt_cache_usage(usage) == (1000, 640)


def test_extract_anthropic_relay_style():
    # Anthropic 语义：input_tokens 不含 cache_read_input_tokens，
    # 分母补全：800 + 512 = 1312，命中 512 不被钳低报。
    usage = {"input_tokens": 800, "cache_read_input_tokens": 512, "output_tokens": 10}
    assert extract_prompt_cache_usage(usage) == (1312, 512)


def test_extract_anthropic_large_cache_read_not_underreported():
    # 命中量远大于 input_tokens 时，分母补全后命中不被 min 钳到极低。
    usage = {"input_tokens": 100, "cache_read_input_tokens": 9900}
    assert extract_prompt_cache_usage(usage) == (10000, 9900)


def test_extract_deepseek_style():
    usage = {"prompt_tokens": 900, "prompt_cache_hit_tokens": 896, "prompt_cache_miss_tokens": 4}
    assert extract_prompt_cache_usage(usage) == (900, 896)


def test_extract_missing_or_invalid_returns_zeros():
    assert extract_prompt_cache_usage(None) == (0, 0)
    assert extract_prompt_cache_usage({}) == (0, 0)
    assert extract_prompt_cache_usage({"total_tokens": 10}) == (0, 0)
    assert extract_prompt_cache_usage("not-a-dict") == (0, 0)


def test_extract_non_numeric_values_do_not_raise():
    # docstring 承诺畸形回落 (0,0)：非数字值不得抛异常击穿响应解析。
    assert extract_prompt_cache_usage({"prompt_tokens": "abc"}) == (0, 0)
    assert extract_prompt_cache_usage(
        {"input_tokens": "x", "cache_read_input_tokens": "y"}) == (0, 0)
    assert extract_prompt_cache_usage(
        {"prompt_tokens": -5, "prompt_tokens_details": {"cached_tokens": None}}
    ) == (0, 0)
    # 部分畸形不拖累有效字段。
    assert extract_prompt_cache_usage(
        {"prompt_tokens": 500, "prompt_tokens_details": {"cached_tokens": "bad"}}
    ) == (500, 0)


def test_extract_cached_capped_by_prompt():
    usage = {"prompt_tokens": 100, "prompt_tokens_details": {"cached_tokens": 999}}
    prompt, cached = extract_prompt_cache_usage(usage)
    assert prompt == 100 and cached <= prompt


# ---------- adapter 非流式 / 流式提取 ----------


@pytest.fixture
def adapter():
    return OpenAICompatChatAdapter(base_url=BASE_URL, api_key="k", model="m")


@respx.mock
async def test_chat_extracts_cached_tokens(adapter):
    respx.post(f"{BASE_URL}/chat/completions").mock(
        return_value=httpx.Response(200, json={
            "choices": [{"message": {"content": "好"}, "finish_reason": "stop"}],
            "usage": {
                "prompt_tokens": 1000, "total_tokens": 1010,
                "prompt_tokens_details": {"cached_tokens": 640},
            },
        })
    )
    result = await adapter.chat([{"role": "user", "content": "你好"}])
    assert result.token_usage == 1010
    assert result.prompt_tokens == 1000
    assert result.cached_tokens == 640
    await adapter.close()


@respx.mock
async def test_chat_without_usage_keeps_zero(adapter):
    respx.post(f"{BASE_URL}/chat/completions").mock(
        return_value=httpx.Response(200, json={
            "choices": [{"message": {"content": "好"}, "finish_reason": "stop"}],
        })
    )
    result = await adapter.chat([{"role": "user", "content": "你好"}])
    assert result.prompt_tokens == 0 and result.cached_tokens == 0
    await adapter.close()


@respx.mock
async def test_stream_done_chunk_carries_cached_tokens(adapter):
    sse_body = (
        'data: {"choices":[{"delta":{"content":"你"}}]}\n\n'
        'data: {"choices":[],"usage":{"total_tokens":120,"prompt_tokens":100,'
        '"prompt_tokens_details":{"cached_tokens":64}}}\n\n'
        "data: [DONE]\n\n"
    )
    respx.post(f"{BASE_URL}/chat/completions").mock(
        return_value=httpx.Response(
            200, content=sse_body.encode("utf-8"),
            headers={"content-type": "text/event-stream"},
        )
    )
    chunks = []
    async for chunk in adapter.chat_stream([{"role": "user", "content": "你好"}]):
        chunks.append(chunk)
    done = next(c for c in chunks if c.type == "done")
    assert done.usage_tokens == 120
    assert done.prompt_tokens == 100
    assert done.cached_tokens == 64
    await adapter.close()


# ---------- live_metrics 滚动窗口命中率 ----------


def test_cache_stats_rolling_hit_rate():
    live_metrics.reset_cache_stats()
    live_metrics.record_cache_usage("proj-x", 1000, 600)
    live_metrics.record_cache_usage("proj-x", 1000, 200)
    stats = live_metrics.get_cache_stats("proj-x")
    assert stats["samples"] == 2
    assert stats["prompt_tokens"] == 2000
    assert stats["cached_tokens"] == 800
    assert stats["hit_rate"] == 0.4
    live_metrics.reset_cache_stats()


def test_cache_stats_skips_no_usage_and_empty_project():
    live_metrics.reset_cache_stats()
    live_metrics.record_cache_usage("proj-y", 0, 999)  # 端点未返回 usage 不入样
    live_metrics.record_cache_usage("", 100, 50)  # 无项目归属不入样
    assert live_metrics.get_cache_stats("proj-y")["samples"] == 0
    assert live_metrics.get_cache_stats("")["samples"] == 0
    live_metrics.reset_cache_stats()


# ---------- TurnExecutor：5 元组上抛 + 样本入窗 ----------


class FakeCacheAdapter(BaseChatAdapter):
    """非流式假 adapter：返回携带缓存命中的响应"""

    @property
    def supports_function_calling(self) -> bool:
        return False

    async def chat(self, messages, **kwargs) -> ChatResponse:
        return ChatResponse(
            content="你好", finish_reason="stop",
            token_usage=1000, prompt_tokens=900, cached_tokens=512,
        )

    async def chat_stream(self, messages, **kwargs):
        yield  # pragma: no cover


@pytest.fixture
def svc(tmp_path):
    StateManager.reset_instance()
    instance = StateManager(str(tmp_path))
    StateManager._instance = instance
    yield instance
    StateManager.reset_instance()


async def test_llm_call_propagates_cached_tokens(svc):
    live_metrics.reset_cache_stats()
    planner = Planner(llm_adapter=FakeCacheAdapter())
    executor = planner._turn_executor
    executor._context = PlannerContext()

    _content, _finish, _applied, _ms, extra = await executor.llm_call(
        "system", [{"role": "user", "content": "你好"}],
    )
    assert extra["token_usage"] == 1000
    assert extra["cached_tokens"] == 512
    # 本轮样本已入滚动窗口（命中率可汇聚）
    stats = live_metrics.get_cache_stats(svc.active_project_id)
    assert stats["samples"] == 1 and stats["cached_tokens"] == 512
    live_metrics.reset_cache_stats()


# ---------- tracer：StepTrace 落盘缓存命中 ----------


def test_tracer_end_step_records_cached_tokens():
    tracer = AgentTracer()  # 新实例：不触单例、不落盘（不调 finish_trace）
    tracer.start_trace("t")
    tracer.start_step()
    tracer.end_step(1, actions_applied=0, finish_reason="stop",
                    token_usage=1000, cached_tokens=640)
    rec = tracer._current
    assert rec is not None
    assert rec.steps[0].cached_tokens == 640
    sd = rec.to_dict()["steps"][0]
    assert sd["cached_tokens"] == 640
    # 0 命中不写键（历史格式不变，单条体积不增）
    tracer.start_step()
    tracer.end_step(2, actions_applied=0, finish_reason="stop", token_usage=10)
    sd2 = tracer._current.to_dict()["steps"][1]
    assert "cached_tokens" not in sd2
