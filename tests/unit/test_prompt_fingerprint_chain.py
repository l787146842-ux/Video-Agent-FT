"""P2-6 traces 唯一事实源：模型可见消息指纹链 + 「凡入 llm_call 必入 trace」断言。

口径（与 P2-1 cached_tokens 同克制）：
- 指纹 = sha256(prev + 规范化消息) 前 16 hex，链式落盘进 StepTrace；
- 无指纹不写键（历史 trace 格式不变，单条体积不增）；
- 模型调用无在场 trace 时告警 + 计数（不中断主链），断言测试兜底。
"""
import pytest

from src.video_agent.adapters.base_chat import BaseChatAdapter, ChatResponse
from src.video_agent.core import tracer as tr_mod
from src.video_agent.core.planner import Planner, PlannerContext
from src.video_agent.core.tracer import AgentTracer, fingerprint_messages
from src.video_agent.state.manager import StateManager

_MSGS_A = [
    {"role": "system", "content": "你是影视创作助手"},
    {"role": "user", "content": "你好"},
]
_MSGS_B = [
    {"role": "system", "content": "你是影视创作助手"},
    {"role": "user", "content": "换个问题"},
]


# ---------- 指纹函数：确定性 / 敏感性 / 链式 / 多模态归一 ----------


def test_fingerprint_deterministic():
    assert fingerprint_messages(_MSGS_A) == fingerprint_messages(list(_MSGS_A))


def test_fingerprint_sensitive_to_content_and_order():
    assert fingerprint_messages(_MSGS_A) != fingerprint_messages(_MSGS_B)
    assert fingerprint_messages(_MSGS_A) != fingerprint_messages(list(reversed(_MSGS_A)))


def test_fingerprint_chained_by_prev():
    fp1 = fingerprint_messages(_MSGS_A)
    # prev 参与哈希：同一消息在不同链前驱下指纹不同（篡改任一环全链对不上）
    assert fingerprint_messages(_MSGS_A, prev="") != fingerprint_messages(_MSGS_A, prev=fp1)


def test_fingerprint_normalizes_multimodal_content():
    msgs = [{
        "role": "user",
        "content": [
            {"type": "text", "text": "看这张图"},
            {"type": "image_url", "image_url": {"url": "https://x/a.png"}},
        ],
    }]
    fp = fingerprint_messages(msgs)
    assert fp and len(fp) == 16
    # 图片 URL 变化不改指纹（占位归一），文本变化则改
    msgs2 = [{
        "role": "user",
        "content": [
            {"type": "text", "text": "看这张图"},
            {"type": "image_url", "image_url": {"url": "https://x/b.png"}},
        ],
    }]
    assert fingerprint_messages(msgs2) == fp
    msgs3 = [{
        "role": "user",
        "content": [{"type": "text", "text": "看另一张图"}, {"type": "image_url"}],
    }]
    assert fingerprint_messages(msgs3) != fp


# ---------- tracer：链式入 step + 无指纹不写键 ----------


def test_fingerprint_chain_links_and_drains_into_step():
    tracer = AgentTracer()  # 新实例：不触单例、不调 finish_trace 不落盘
    tracer.start_trace("指纹链测试")
    tracer.start_step()
    assert tracer.record_prompt_fingerprint(_MSGS_A) is True
    assert tracer.record_prompt_fingerprint(_MSGS_B) is True
    tracer.end_step(1, actions_applied=0, finish_reason="stop")

    step = tracer._current.steps[0]
    assert len(step.prompt_fingerprints) == 2
    first, second = step.prompt_fingerprints
    assert first["prev"] == "" and first["msgs"] == 2  # 链头无前驱
    assert second["prev"] == first["fp"]  # 链式：后环指向 前环
    # 链式口径与裸函数一致（可事后重放校验）
    assert first["fp"] == fingerprint_messages(_MSGS_A, prev="")
    assert second["fp"] == fingerprint_messages(_MSGS_B, prev=first["fp"])
    # to_dict 落键
    sd = tracer._current.to_dict()["steps"][0]
    assert len(sd["prompt_fingerprints"]) == 2


def test_no_fingerprint_key_when_empty():
    tracer = AgentTracer()
    tracer.start_trace("无指纹")
    tracer.start_step()
    tracer.end_step(1)
    sd = tracer._current.to_dict()["steps"][0]
    assert "prompt_fingerprints" not in sd  # 历史格式不变


def test_new_trace_resets_chain_head():
    tracer = AgentTracer()
    tracer.start_trace("第一轮")
    tracer.start_step()
    tracer.record_prompt_fingerprint(_MSGS_A)
    tracer.end_step(1)
    tracer.finish_trace()

    tracer.start_trace("第二轮")
    tracer.start_step()
    tracer.record_prompt_fingerprint(_MSGS_A)
    tracer.end_step(1)
    entry = tracer._current.steps[0].prompt_fingerprints[0]
    assert entry["prev"] == ""  # 新 trace 链头重新起链


def test_fingerprint_persisted_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(tr_mod, "DATA_DIR", tmp_path)
    t1 = AgentTracer()
    t1.start_trace("落盘测试")
    t1.start_step()
    t1.record_prompt_fingerprint(_MSGS_A)
    t1.end_step(1, finish_reason="stop")
    rec = t1.finish_trace()
    assert rec["steps"][0]["prompt_fingerprints"][0]["prev"] == ""

    t2 = AgentTracer()
    loaded = next(x for x in t2.get_recent_traces(10) if x["trace_id"] == rec["trace_id"])
    assert loaded["steps"][0]["prompt_fingerprints"][0]["fp"] == (
        rec["steps"][0]["prompt_fingerprints"][0]["fp"])


# ---------- 断言：凡入 llm_call 必入 trace（缺则告警，不中断） ----------


def test_record_without_active_trace_warns_and_counts():
    tracer = AgentTracer()  # 未 start_trace：无在场 trace
    assert tracer.record_prompt_fingerprint(_MSGS_A) is False
    assert tracer._unlogged_llm_calls == 1
    assert tracer.metrics()["unlogged_llm_calls"] == 1


class _EchoAdapter(BaseChatAdapter):
    """非流式假 adapter：捕获实际收到的消息（= 模型可见）"""

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


async def test_llm_call_always_logged_into_trace(svc):
    """凡入 llm_call 必入 trace：模型调用在场即指纹入链，
    且指纹针对模型实际收到的消息（审计可重放）。"""
    tracer = AgentTracer()
    adapter = _EchoAdapter()
    planner = Planner(llm_adapter=adapter)
    executor = planner._turn_executor
    executor._context = PlannerContext()
    executor._tracer = tracer

    tracer.start_trace("断言测试")
    tracer.start_step()
    await executor.llm_call("system 提示", [{"role": "user", "content": "你好"}])
    tracer.end_step(1, actions_applied=0, finish_reason="stop")

    steps = tracer._current.steps
    assert len(steps[0].prompt_fingerprints) == 1
    entry = steps[0].prompt_fingerprints[0]
    # 指纹口径 = 模型实际所见（adapter 收到的最终消息，含 system、经截断）
    assert entry["fp"] == fingerprint_messages(adapter.seen[0], prev="")
    assert tracer._unlogged_llm_calls == 0


async def test_llm_call_without_trace_counts_unlogged(svc):
    """反向用例：直驱调用未开 trace → 告警计数 +1（主链不中断，调用仍成功）"""
    tracer = AgentTracer()
    planner = Planner(llm_adapter=_EchoAdapter())
    executor = planner._turn_executor
    executor._context = PlannerContext()
    executor._tracer = tracer

    content, _finish, _applied, _ms, _extra = await executor.llm_call(
        "system", [{"role": "user", "content": "你好"}],
    )
    assert content == "好"  # 主链不受影响
    assert tracer._unlogged_llm_calls == 1
