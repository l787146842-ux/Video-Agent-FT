"""P2-1：流式代码块抑制修复 —— 只屏蔽 ```studio-actions 围栏，普通代码块放行"""
import pytest

from src.video_agent.adapters.base_chat import BaseChatAdapter, ChatResponse, StreamChunk
from src.video_agent.core.planner import Planner, PlannerContext, StreamActionSuppressor
from src.video_agent.state.manager import StateManager


class TestStreamActionSuppressor:
    """增量状态机单元测试（围栏可跨 chunk 截断）"""

    @staticmethod
    def run(chunks):
        s = StreamActionSuppressor()
        out = [s.feed(c) for c in chunks]
        out.append(s.flush())
        return "".join(out)

    def test_plain_text_passes_through(self):
        assert self.run(["你好，", "世界"]) == "你好，世界"

    def test_normal_code_block_streams_fully(self):
        """普通 markdown 代码块应完整推送（旧逻辑见到 ``` 即永久停止）"""
        text = "代码如下：\n```python\nprint('hi')\n```\n结束"
        assert self.run([text]) == text

    def test_normal_code_block_across_chunks(self):
        chunks = ["代码：\n```py", "thon\nx=1\n``", "`\n完"]
        assert self.run(chunks) == "代码：\n```python\nx=1\n```\n完"

    def test_studio_actions_block_suppressed(self):
        text = ('好的\n```studio-actions\n[{"action":"add_group"}]\n```\n完成')
        assert self.run([text]) == "好的\n完成"

    def test_studio_actions_across_chunks(self):
        """围栏与 JSON 跨多个 chunk 截断时仍整块抑制"""
        chunks = ["好的\n``", "`studio-", "actions\n[{\"action\":", "\"continue\"}]\n```", "\n完成"]
        assert self.run(chunks) == "好的\n完成"

    def test_text_after_actions_block_resumes(self):
        """抑制块之后的文本与普通代码块照常推送"""
        text = ('前\n```studio-actions\n[{"a":1}]\n```\n中\n```js\n1+1\n```\n后')
        assert self.run([text]) == "前\n中\n```js\n1+1\n```\n后"

    def test_unterminated_actions_block_stays_suppressed(self):
        """流结束时 studio-actions 块未闭合：不冲刷给前端"""
        assert self.run(["前\n```studio-actions\n[{\"a\":1}"]) == "前\n"

    def test_unterminated_normal_fence_flushed(self):
        """普通围栏未闭合时照常冲刷"""
        assert self.run(["看：\n```py"]) == "看：\n```py"


class FakeTextStreamAdapter(BaseChatAdapter):
    """按 chunk 序列流式输出纯文本的假 Adapter"""

    def __init__(self, chunks):
        self._chunks = chunks

    @property
    def supports_function_calling(self) -> bool:
        return True

    async def chat(self, messages, **kwargs) -> ChatResponse:
        return ChatResponse(content="".join(self._chunks), finish_reason="stop")

    async def chat_stream(self, messages, **kwargs):
        for c in self._chunks:
            yield StreamChunk(type="text_delta", text=c)
        yield StreamChunk(type="done", finish_reason="stop")


@pytest.fixture
def svc(tmp_path):
    StateManager.reset_instance()
    instance = StateManager(str(tmp_path))
    StateManager._instance = instance
    yield instance
    StateManager.reset_instance()


class TestPlannerStreamCodeBlocks:
    """经 Planner 流式链路的端到端验证"""

    async def test_reply_with_code_block_streams_fully(self, svc):
        """含普通代码块的流式回复应完整推送（P2-1 核心诉求）"""
        reply = "示例：\n```python\nprint('ok')\n```\n请查收"
        adapter = FakeTextStreamAdapter([reply[i:i + 5] for i in range(0, len(reply), 5)])
        planner = Planner(llm_adapter=adapter)
        deltas: list = []

        async def hook(t):
            deltas.append(t)

        await planner.handle_message(
            "给我代码", PlannerContext(use_studio_context=False), stream_hook=hook,
        )
        assert "".join(deltas) == reply

    async def test_actions_block_hidden_but_rest_streams(self, svc):
        """studio-actions 块不上屏，其余文字完整"""
        reply = ('已处理\n```studio-actions\n[{"action":"continue"}]\n```\n收尾说明')
        adapter = FakeTextStreamAdapter([reply])
        planner = Planner(llm_adapter=adapter)
        deltas: list = []

        async def hook(t):
            deltas.append(t)

        await planner.handle_message(
            "干活", PlannerContext(use_studio_context=False), stream_hook=hook,
        )
        streamed = "".join(deltas)
        assert "studio-actions" not in streamed
        assert "已处理" in streamed
