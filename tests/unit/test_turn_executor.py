"""D-02 拆分协作臂钉死：TurnExecutor 未经 bind_turn 直驱的自洽性。

隐性契约回归：llm_call 的 tracer 不得依赖 bind_turn 装配（旧 planner
闭包实现是现场 AgentTracer.get_instance()）；收集器键亦不得因未装配
而 KeyError。生产路径每轮 bind_turn 不受影响（换装跨步共享列表）。
"""
import pytest

from src.video_agent.adapters.base_chat import BaseChatAdapter, ChatResponse
from src.video_agent.core.planner import Planner, PlannerContext
from src.video_agent.state.manager import StateManager


class FakeChatAdapter(BaseChatAdapter):
    """纯文本假 adapter（无 tool_calls，走非流式路径）"""

    @property
    def supports_function_calling(self) -> bool:
        return False

    async def chat(self, messages, **kwargs) -> ChatResponse:
        return ChatResponse(content="你好", finish_reason="stop")

    async def chat_stream(self, messages, **kwargs):
        from src.video_agent.adapters.base_chat import StreamChunk
        yield StreamChunk(type="text_delta", text="你好")


@pytest.fixture
def svc(tmp_path):
    StateManager.reset_instance()
    instance = StateManager(str(tmp_path))
    StateManager._instance = instance
    yield instance
    StateManager.reset_instance()


async def test_llm_call_without_bind_turn_is_self_contained(svc):
    """未 bind_turn 直驱 llm_call：tracer 现场回落单例，不抛 AttributeError；
    收集器回落构造期默认空列表，不抛 KeyError（mock LLM，纯文本回合）"""
    planner = Planner(llm_adapter=FakeChatAdapter())
    executor = planner._turn_executor
    assert executor._tracer is None  # 前置：确未经 bind_turn 装配
    # 仅提供最小数据契约（上下文），不装配 tracer/收集器/on_event
    executor._context = PlannerContext()

    content, finish, fc_applied, plan_ms, extra = await executor.llm_call(
        "system", [{"role": "user", "content": "你好"}],
    )
    assert content == "你好"
    assert finish == "stop"
    assert fc_applied == 0
    assert isinstance(plan_ms, float)
    assert "token_usage" in extra


class FakeToolCallAdapter(BaseChatAdapter):
    """发起工具调用的假 adapter（工具不存在 → 执行失败 → 全拒收轮形态）"""

    @property
    def supports_function_calling(self) -> bool:
        return True

    async def chat(self, messages, **kwargs) -> ChatResponse:
        return ChatResponse(
            content="现在生成形象图",
            finish_reason="tool_calls",
            tool_calls=[{
                "id": "call_1", "type": "function",
                "function": {"name": "no_such_tool", "arguments": "{}"},
            }],
        )

    async def chat_stream(self, messages, **kwargs):
        from src.video_agent.adapters.base_chat import StreamChunk
        yield StreamChunk(type="text_delta", text="现在生成形象图")


async def test_all_rejected_round_surfaces_had_fc_calls_and_feedback(svc):
    """批 9 · 回合终止盲区修复的回喂侧钉死：全拒收轮（发起过调用、
    fc_applied=0）必须 ① extra.had_fc_calls=True 上抛（agent_loop 据此
    不按纯文本轮终止）；② 拒因回喂组装为 pending tool 消息上抛
    （C2：agent_loop 轮末按 assistant(tool_calls) → tool 消息顺序 append）。"""
    planner = Planner(llm_adapter=FakeToolCallAdapter())
    executor = planner._turn_executor
    executor._context = PlannerContext()

    messages = [{"role": "user", "content": "可以"}]
    content, finish, fc_applied, plan_ms, extra = await executor.llm_call(
        "system", messages,
    )
    assert extra.get("had_fc_calls") is True
    assert fc_applied == 0
    # 拒因/失败回喂必须组装为 pending tool 消息（下一轮模型能看到）
    pending = extra.get("_pending_feedback_msgs") or []
    assert pending, "全拒收轮的回喂必须组装为 pending 消息"
    assert any(m.get("role") == "tool" and (
        "no_such_tool" in str(m.get("content")) or "失败" in str(m.get("content")))
        for m in pending)
    # C2：tool 消息携带 call_id 配对（与 _fc_tool_calls 对应）
    assert any(str(m.get("tool_call_id")) for m in pending if m.get("role") == "tool")
    fc_calls = extra.get("_fc_tool_calls") or []
    assert fc_calls, "tool_calls 原样上抛供 agent_loop 组 assistant 消息"
