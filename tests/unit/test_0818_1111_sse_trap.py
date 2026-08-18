"""回归测试 0818-1111：9router「缺省 stream 当流式」陷阱与执行器流式/回喂治理。

事故：1111 项目执行器非流式调用经 9router 时，中介对缺省 stream 字段按
流式路由，200 回 SSE 文本，resp.json() 裸崩 JSONDecodeError，流程静默失败。
本文件按批次钉死修复：B1 协议声明+契约报错；B2 执行器流式+黑匣子；B3 回喂治理。
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
