"""回归测试 0818-1111：9router「缺省 stream 当流式」陷阱。

事故：1111 项目非流式调用经 9router 时，中介对缺省 stream 字段按
流式路由，200 回 SSE 文本，resp.json() 裸崩 JSONDecodeError，流程静默失败。
本文件按批次钉死修复：B1 协议声明+契约报错；B3 回喂治理。
（B2 执行器流式取稿+黑匣子用例已随任务#36 B5 执行器一步退役删除。）
"""
import json

import httpx
import pytest
import respx

from src.video_agent.adapters.openai_compat import OpenAICompatChatAdapter
from src.video_agent.exceptions import AdapterError

BASE_URL = "https://api.test-0818-1111.com/v1"


@pytest.fixture
def adapter():
    a = OpenAICompatChatAdapter(base_url=BASE_URL, api_key="test-key", model="qd/qmodel_38max")
    yield a


# ---------- B1：非流式协议声明 + 非 JSON 契约报错 ----------


class TestB1StreamDeclaration:
    @respx.mock
    async def test_chat_payload_declares_stream_false(self, adapter):
        """0818-1111：chat() 必须显式声明 stream:false（中介缺省当流式）。"""
        route = respx.post(f"{BASE_URL}/chat/completions").mock(
            return_value=httpx.Response(200, json={
                "choices": [{"message": {"content": "ok", "tool_calls": []}, "finish_reason": "stop"}]
            })
        )
        await adapter.chat([{"role": "user", "content": "你好"}])
        sent = json.loads(route.calls.last.request.content)
        assert sent["stream"] is False
        await adapter.close()

    @respx.mock
    async def test_stream_tool_call_carries_provider_id(self, adapter):
        """C1：流式 tool_call chunk 携带供应商 tool_call id（tool role 配对用）"""
        sse_body = (
            'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_prov_1",'
            '"function":{"name":"read_skill","arguments":"{\\"name\\":\\"s\\"}"}}]}}]}\n\n'
            'data: {"choices":[{"delta":{},"finish_reason":"tool_calls"}]}\n\n'
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
        tc = next(c for c in chunks if c.type == "tool_call")
        assert tc.tool_call_id == "call_prov_1"
        assert tc.tool_name == "read_skill"
        await adapter.close()

    @respx.mock
    async def test_chat_non_json_body_raises_adapter_error(self, adapter):
        """0818-1111：200 但回 SSE 文本时抛 AdapterError，不漏裸 JSONDecodeError。"""
        respx.post(f"{BASE_URL}/chat/completions").mock(
            return_value=httpx.Response(
                200,
                content=b'data: {"choices":[]}\n\ndata: [DONE]\n\n',
                headers={"content-type": "text/event-stream"},
            )
        )
        with pytest.raises(AdapterError) as ei:
            await adapter.chat([{"role": "user", "content": "你好"}])
        assert "非 JSON" in str(ei.value)
        await adapter.close()

    @respx.mock
    async def test_chat_stream_non_json_body_raises_adapter_error(self, adapter):
        """0818-1111 G4：流式路径的非 SSE 回退分支同样不得漏裸 JSONDecodeError。"""
        respx.post(f"{BASE_URL}/chat/completions").mock(
            return_value=httpx.Response(
                200,
                content=b'oops not json',
                headers={"content-type": "application/json"},
            )
        )
        with pytest.raises(AdapterError) as ei:
            async for _ in adapter.chat_stream([{"role": "user", "content": "你好"}]):
                pass
        assert "非 JSON" in str(ei.value)
        await adapter.close()


# ---------- B2：执行器流式取稿 + 黑匣子（TestB2ExecutorStreaming 已随
# 任务#36 B5 执行器一步退役删除：_llm_json_call/黑匣子档案不复存在） ----------


# ---------- B3：失败回喂结构化 + 去祈使化 ----------


class TestB3FailureFeedback:
    def test_failure_feedback_structured_and_escalates(self):
        """0818-1111：失败回喂 = 客观分类 + 单句建议；同工具二次失败升级为不得重试。"""
        from src.video_agent.core.fc_feedback import compose_failure_feedback

        err = "执行器 LLM 返回的 JSON 无法解析: xxx"
        first = compose_failure_feedback("script_analyze", err, 1)
        assert first.startswith("[output_format]")
        assert "重试一次" in first
        second = compose_failure_feedback("script_analyze", err, 2)
        assert "不得再次重试" in second
        assert "向用户说明" in second

    def test_fc_runner_failure_branch_uses_structured_feedback(self):
        """0818-1111：FC 轨失败分支必须走结构化回喂，裸错误串不得复活。"""
        import inspect
        from src.video_agent.core import fc_tool_runner

        src = inspect.getsource(fc_tool_runner)
        assert "compose_failure_feedback(" in src
        assert '"error": str(result.error or "执行失败")[:200]' not in src
