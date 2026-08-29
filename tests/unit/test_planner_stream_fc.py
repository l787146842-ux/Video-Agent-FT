"""P0-1/P0-2 回归：流式 Function Calling 工具调用执行 + confirmation JSON 注入防护"""
from types import SimpleNamespace

import pytest

from src.video_agent.adapters.base_chat import BaseChatAdapter, ChatResponse, StreamChunk
from src.video_agent.core.planner import Planner, PlannerContext
from src.video_agent.state.manager import StateManager


class FakeToolManager:
    """记录调用的假 ToolManager（类级接口与 ToolManager 一致）"""

    invoked: list = []

    @classmethod
    def reset(cls):
        cls.invoked = []

    @classmethod
    def get_all_tool_schemas(cls, exclude=None) -> list:
        return [{"type": "function", "function": {"name": "fake_tool", "parameters": {}}}]

    @classmethod
    def get_tool(cls, name: str):
        """确认闸双保险（ctx.tool_risk_of 经 get_tool().risk 读数）的最小桩：
        桩内工具一律声明 low（只读桩）。"""
        return SimpleNamespace(risk="low")

    @classmethod
    async def invoke_tool(cls, name: str, args: dict):
        cls.invoked.append((name, args))
        return SimpleNamespace(success=True, error="", data=None)


class FakeStreamFCAdapter(BaseChatAdapter):
    """模拟支持 FC 的流式 Adapter：text 增量 + 完整 tool_call 块 + done"""

    def __init__(self, tool_calls: list, text: str = "正在操作"):
        self._tool_calls = tool_calls  # [(name, args_dict), ...]
        self._text = text
        self._calls = 0

    @property
    def supports_function_calling(self) -> bool:
        return True

    async def chat(self, messages, **kwargs) -> ChatResponse:
        return ChatResponse(content=self._text, finish_reason="stop")

    async def chat_stream(self, messages, **kwargs):
        # 仅首轮返回 tool_calls；后续轮返回纯文本 stop，避免循环重放
        self._calls += 1
        yield StreamChunk(type="text_delta", text=self._text)
        if self._calls == 1 and self._tool_calls:
            for name, args in self._tool_calls:
                yield StreamChunk(type="tool_call", tool_name=name, tool_args=args)
            yield StreamChunk(type="done", finish_reason="tool_calls")
        else:
            yield StreamChunk(type="done", finish_reason="stop")


def make_hook(collector: list | None = None):
    """构造 async stream_hook（Planner 会 await 它）"""
    async def _hook(text: str) -> None:
        if collector is not None:
            collector.append(text)
    return _hook


@pytest.fixture
def svc(tmp_path):
    StateManager.reset_instance()
    instance = StateManager(str(tmp_path))
    StateManager._instance = instance
    yield instance
    StateManager.reset_instance()


@pytest.fixture(autouse=True)
def reset_tools():
    FakeToolManager.reset()


class TestStreamFunctionCalling:
    """流式路径下 FC 工具调用不应被静默丢弃（B1）"""

    async def test_stream_fc_tool_executed(self, svc):
        """流式 + FC 模型：tool_call 块在 done 后被统一执行"""
        adapter = FakeStreamFCAdapter([("add_group", {"group_type": "shot", "title": "流式分镜"})])
        planner = Planner(llm_adapter=adapter, tool_manager=FakeToolManager)

        deltas: list = []
        result = await planner.handle_message(
            "创建分镜",
            PlannerContext(use_studio_context=False),
            stream_hook=make_hook(deltas),
        )

        assert FakeToolManager.invoked == [("add_group", {"group_type": "shot", "title": "流式分镜"})]
        assert result.applied_actions == 1

    async def test_stream_fc_multiple_tools_in_order(self, svc):
        """多个 tool_call 按顺序全部执行"""
        adapter = FakeStreamFCAdapter([
            ("tool_a", {"x": 1}),
            ("tool_b", {"y": 2}),
        ])
        planner = Planner(llm_adapter=adapter, tool_manager=FakeToolManager)
        result = await planner.handle_message(
            "批量", PlannerContext(use_studio_context=False), stream_hook=make_hook(),
        )
        assert [name for name, _ in FakeToolManager.invoked] == ["tool_a", "tool_b"]
        assert result.applied_actions == 2

    async def test_stream_without_tool_calls_unaffected(self, svc):
        """纯文本流式回复不触发工具执行"""
        adapter = FakeStreamFCAdapter([], text="普通回复")
        planner = Planner(llm_adapter=adapter, tool_manager=FakeToolManager)
        result = await planner.handle_message(
            "你好", PlannerContext(use_studio_context=False), stream_hook=make_hook(),
        )
        assert FakeToolManager.invoked == []
        assert result.applied_actions == 0


class TestConfirmationJsonInjection:
    """FC confirmation 拼接必须 json.dumps，含引号/换行不应损坏 JSON（B2）"""

    async def test_confirmation_with_quotes_and_newlines(self, svc):
        malicious = '确认生成 "太空艇" 场景？\n包含换行与{"fake": "json"}'
        adapter = FakeStreamFCAdapter([("workflow_pause", {"message": malicious})])
        planner = Planner(llm_adapter=adapter, tool_manager=FakeToolManager)

        collected: list = []
        async for event in planner.handle_message_stream("开始", PlannerContext(use_studio_context=False)):
            collected.append(event)

        done = next(e for e in collected if e.type == "done")
        # v2 批4：确认通道 = 系统组装问句；模型原文（含引号/换行/伪 JSON）
        # 进正文通道，不再进入确认通道
        assert "请过目以上成果" in done.payload["confirmation"]
        assert malicious in (done.payload.get("text") or "")

    async def test_fc_confirmation_no_synthesized_block(self, svc):
        """audit-0819b/d 防泄漏根治：确认经结构化 extra 上抛，
        planner 不得再合成 studio-actions 文本块；含引号/换行的确认文案不损坏"""
        malicious = '含"双引号"和\n换行的确认消息'
        adapter = FakeStreamFCAdapter([("workflow_pause", {"message": malicious})])
        planner = Planner(llm_adapter=adapter, tool_manager=FakeToolManager)

        result = await planner.handle_message(
            "开始", PlannerContext(use_studio_context=False), stream_hook=make_hook(),
        )
        assert "```studio-actions" not in (result.text or ""), "合成块通道已退役，不得复活"
        assert "请过目以上成果" in (result.confirmation or "")
        assert malicious in (result.text or ""), "模型原文进正文通道不损坏"
