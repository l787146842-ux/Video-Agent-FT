"""Planner 单元测试：多步循环、FC 模式、confirmation 中断"""
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
    """多步循环测试"""

    async def test_single_step_no_continue(self, svc, context):
        """无 continue 信号 → 单步结束"""
        adapter = FakeChatAdapter(["你好，我是 Agent。"])
        planner = Planner(llm_adapter=adapter)
        result = await planner.handle_message("你好", context)

        assert isinstance(result, PlannerResponse)
        assert result.steps == 1
        assert "你好" in result.text
        assert len(adapter.calls) == 1

    async def test_continue_triggers_multi_step(self, svc, context):
        """continue 信号触发多步"""
        r1 = '第一步\n```studio-actions\n[{"action":"continue"}]\n```'
        r2 = '第二步完成'
        adapter = FakeChatAdapter([r1, r2])
        planner = Planner(llm_adapter=adapter)
        result = await planner.handle_message("执行任务", context)

        assert result.steps == 2
        assert len(adapter.calls) == 2

    async def test_max_steps_cap(self, svc, context):
        """达到 MAX_STEPS 上限后终止"""
        # 每轮都请求 continue
        reply = '继续\n```studio-actions\n[{"action":"continue"}]\n```'
        adapter = FakeChatAdapter([reply])  # 会重复使用最后一个
        planner = Planner(llm_adapter=adapter)
        result = await planner.handle_message("无限循环", context)

        from src.video_agent.core.agent_loop import MAX_STEPS
        assert result.steps == MAX_STEPS
        assert any("上限" in w for w in result.warnings)


class TestPlannerConfirmation:
    """confirmation 中断测试"""

    async def test_confirmation_stops_loop(self, svc, context):
        """request_confirmation 信号中断循环"""
        reply = '请确认\n```studio-actions\n[{"action":"request_confirmation","message":"确认继续？"}]\n```'
        adapter = FakeChatAdapter([reply])
        planner = Planner(llm_adapter=adapter)
        result = await planner.handle_message("执行", context)

        assert result.confirmation == "确认继续？"
        assert result.steps == 1  # 第一轮就中断


class TestPlannerActions:
    """studio-actions 执行测试"""

    async def test_actions_applied(self, svc, context):
        """studio-actions 中的操作应被执行"""
        reply = (
            '已创建分组\n```studio-actions\n'
            '[{"action":"add_group","group_type":"shot","title":"测试分镜","draft":{"label":"d","prompt":"p"}}]\n```'
        )
        adapter = FakeChatAdapter([reply])
        planner = Planner(llm_adapter=adapter)
        result = await planner.handle_message("创建分镜", context)

        assert result.applied_actions == 1
        # 验证状态确实被修改
        shots = svc.state_dict.get("shots", [])
        assert any(g.get("title") == "测试分镜" for g in shots)

    async def test_visible_text_excludes_actions(self, svc, context):
        """返回的 text 不应包含 studio-actions 块"""
        reply = '可见文本\n```studio-actions\n[{"action":"continue"}]\n```'
        adapter = FakeChatAdapter([reply, "完成"])
        planner = Planner(llm_adapter=adapter)
        result = await planner.handle_message("测试", context)

        assert "studio-actions" not in result.text
        assert "可见文本" in result.text


class TestPlannerNoAdapter:
    """无 Adapter 时的降级行为"""

    async def test_no_adapter_returns_empty(self, svc, context):
        """llm_adapter=None 时返回空响应"""
        planner = Planner(llm_adapter=None)
        result = await planner.handle_message("你好", context)

        assert result.steps >= 1
        # 无 adapter 时 _call_llm 返回空 content
        assert result.applied_actions == 0
