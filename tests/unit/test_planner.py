"""Planner 单元测试：基础降级行为（audit-0819b 单轨化后收缩）。

原多步 continue/文本确认/文本动作执行/5555 引导卡用例均钉文本块通道，
已随双轨退役删除（ADR-0001）；循环级语义覆盖迁 test_agent_loop.py
（FC 桁），确认合成块回归钉死见 test_audit0819_leak_and_fakestop.py。
"""
import pytest

from src.video_agent.core.planner import Planner, PlannerContext, PlannerResponse
from src.video_agent.state.manager import StateManager
from src.video_agent.adapters.base_chat import BaseChatAdapter, ChatResponse


class FakeChatAdapter(BaseChatAdapter):
    """按次序返回预设回复的假 LLM Adapter"""

    def __init__(self, replies: list):
        self._replies = replies
        self._call_idx = 0
        self.calls: list = []

    @property
    def supports_function_calling(self) -> bool:
        return False

    async def chat(self, messages, **kwargs) -> ChatResponse:
        self.calls.append(messages)
        reply = self._replies[min(self._call_idx, len(self._replies) - 1)]
        self._call_idx += 1
        if isinstance(reply, ChatResponse):
            return reply
        return ChatResponse(content=reply, finish_reason="stop")

    async def chat_stream(self, messages, **kwargs):
        # 简单实现：一次性返回全部内容
        response = await self.chat(messages, **kwargs)
        from src.video_agent.adapters.base_chat import StreamChunk
        yield StreamChunk(type="text_delta", text=response.content)


@pytest.fixture
def svc(tmp_path):
    StateManager.reset_instance()
    instance = StateManager(str(tmp_path))
    StateManager._instance = instance
    yield instance
    StateManager.reset_instance()


@pytest.fixture
def context():
    return PlannerContext(use_studio_context=False)


class TestPlannerMultiStep:
    """基础收尾语义（多步 continue 文本通道已退役，ADR-0001）"""

    async def test_single_step_no_continue(self, svc, context):
        """无工具调用的纯文本回复 → 单步收尾"""
        adapter = FakeChatAdapter(["你好，我是 Agent。"])
        planner = Planner(llm_adapter=adapter)
        result = await planner.handle_message("你好", context)

        assert isinstance(result, PlannerResponse)
        assert result.steps == 1
        assert "你好" in result.text
        assert len(adapter.calls) == 1


class TestPlannerNoAdapter:
    """无 Adapter 时的降级行为"""

    async def test_no_adapter_returns_empty(self, svc, context):
        """llm_adapter=None 时返回空响应"""
        planner = Planner(llm_adapter=None)
        result = await planner.handle_message("你好", context)

        assert result.steps >= 1
        # 无 adapter 时 _call_llm 返回空 content
        assert result.applied_actions == 0


class TestNoStageNoGuideCard:
    """日常对话（无阶段执行器）不补引导卡（5555 引导卡的文本轨场景
    已随双轨退役删除，ADR-0001；保留「不误伤日常对话」断言）"""

    async def test_no_stage_no_guide_card(self, svc, context):
        adapter = FakeChatAdapter(["好的，已收到。"])
        planner = Planner(llm_adapter=adapter)
        result = await planner.handle_message("你好", context)
        assert not result.confirmation
