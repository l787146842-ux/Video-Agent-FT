"""单元测试：OpenAICompatChatAdapter — 使用 respx mock HTTP 响应

覆盖场景：
- 正常 chat 调用（解析 choices）
- 流式 SSE 解析（text_delta + tool_call）
- 超时异常
- HTTP 错误（4xx / 5xx）
- 空 choices
- base64 图片提取与落盘
- 连接池复用（close 后重建）
"""
import json

import httpx
import pytest
import respx

from src.video_agent.adapters.openai_compat import (
    OpenAICompatChatAdapter,
    extract_base64_image,
    persist_data_uri,
    persist_remote_image,
)
from src.video_agent.adapters.base_chat import ChatResponse, StreamChunk
from src.video_agent.exceptions import AdapterError


BASE_URL = "https://api.test-provider.com/v1"


@pytest.fixture
def adapter():
    a = OpenAICompatChatAdapter(base_url=BASE_URL, api_key="test-key", model="test-model")
    yield a
    # 清理由测试自行处理


# ---------- 正常 chat ----------


class TestChatNormal:
    @respx.mock
    async def test_chat_success(self, adapter):
        """正常 chat 调用应返回 ChatResponse"""
        mock_response = {
            "choices": [
                {
                    "message": {"content": "你好！有什么可以帮你的？", "tool_calls": []},
                    "finish_reason": "stop",
                }
            ]
        }
        respx.post(f"{BASE_URL}/chat/completions").mock(
            return_value=httpx.Response(200, json=mock_response)
        )

        result = await adapter.chat([{"role": "user", "content": "你好"}])
        assert isinstance(result, ChatResponse)
        assert result.content == "你好！有什么可以帮你的？"
        assert result.finish_reason == "stop"
        assert result.tool_calls == []
        await adapter.close()

    @respx.mock
    async def test_chat_with_tool_calls(self, adapter):
        """chat 返回 tool_calls 时应正确解析"""
        tool_calls = [
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": "create_draft", "arguments": '{"label": "测试"}'},
            }
        ]
        mock_response = {
            "choices": [
                {
                    "message": {"content": "", "tool_calls": tool_calls},
                    "finish_reason": "tool_calls",
                }
            ]
        }
        respx.post(f"{BASE_URL}/chat/completions").mock(
            return_value=httpx.Response(200, json=mock_response)
        )

        result = await adapter.chat([{"role": "user", "content": "创建草稿"}])
        assert result.finish_reason == "tool_calls"
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0]["function"]["name"] == "create_draft"
        await adapter.close()

    @respx.mock
    async def test_chat_content_list_format(self, adapter):
        """content 为 list 格式时应拼接文本部分"""
        mock_response = {
            "choices": [
                {
                    "message": {
                        "content": [
                            {"type": "text", "text": "第一段"},
                            {"type": "image_url", "image_url": {"url": "data:image/png;base64,xxx"}},
                            {"type": "text", "text": "第二段"},
                        ]
                    },
                    "finish_reason": "stop",
                }
            ]
        }
        respx.post(f"{BASE_URL}/chat/completions").mock(
            return_value=httpx.Response(200, json=mock_response)
        )

        result = await adapter.chat([{"role": "user", "content": "描述图片"}])
        assert "第一段" in result.content
        assert "第二段" in result.content
        await adapter.close()


# ---------- 错误处理 ----------


class TestChatErrors:
    @respx.mock
    async def test_empty_choices_raises(self, adapter):
        """空 choices 应抛出 AdapterError"""
        respx.post(f"{BASE_URL}/chat/completions").mock(
            return_value=httpx.Response(200, json={"choices": []})
        )

        with pytest.raises(AdapterError, match="空 choices"):
            await adapter.chat([{"role": "user", "content": "test"}])
        await adapter.close()

    @respx.mock
    async def test_http_4xx_raises(self, adapter):
        """4xx 错误应抛出 AdapterError"""
        respx.post(f"{BASE_URL}/chat/completions").mock(
            return_value=httpx.Response(401, text="Unauthorized")
        )

        with pytest.raises(AdapterError, match="HTTP 401"):
            await adapter.chat([{"role": "user", "content": "test"}])
        await adapter.close()

    @respx.mock
    async def test_timeout_raises(self, adapter):
        """超时应抛出 AdapterError"""
        respx.post(f"{BASE_URL}/chat/completions").mock(
            side_effect=httpx.ReadTimeout("timeout")
        )

        with pytest.raises(AdapterError, match="超时"):
            await adapter.chat([{"role": "user", "content": "test"}], timeout=1)
        await adapter.close()

    @respx.mock
    async def test_connection_error_raises(self, adapter):
        """连接失败应抛出 AdapterError"""
        respx.post(f"{BASE_URL}/chat/completions").mock(
            side_effect=httpx.ConnectError("connection refused")
        )

        with pytest.raises(AdapterError, match="请求失败"):
            await adapter.chat([{"role": "user", "content": "test"}])
        await adapter.close()


# ---------- 流式 SSE ----------


class TestChatStream:
    @respx.mock
    async def test_stream_text_deltas(self, adapter):
        """流式响应应正确解析 text_delta"""
        sse_body = (
            'data: {"choices":[{"delta":{"content":"你"}}]}\n\n'
            'data: {"choices":[{"delta":{"content":"好"}}]}\n\n'
            'data: {"choices":[{"delta":{"content":"！"}}]}\n\n'
            "data: [DONE]\n\n"
        )
        respx.post(f"{BASE_URL}/chat/completions").mock(
            return_value=httpx.Response(
                200,
                content=sse_body.encode(),
                headers={"content-type": "text/event-stream"},
            )
        )

        chunks = []
        async for chunk in adapter.chat_stream([{"role": "user", "content": "你好"}]):
            chunks.append(chunk)

        text_chunks = [c for c in chunks if c.type == "text_delta"]
        assert len(text_chunks) == 3
        assert "".join(c.text for c in text_chunks) == "你好！"
        await adapter.close()

    @respx.mock
    async def test_stream_tool_call(self, adapter):
        """流式响应中的 tool_call 应正确解析"""
        tool_call_data = {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "function": {
                                    "name": "update_draft",
                                    "arguments": '{"draft_id": "d1", "prompt": "新提示"}',
                                }
                            }
                        ]
                    }
                }
            ]
        }
        sse_body = f'data: {json.dumps(tool_call_data)}\n\ndata: [DONE]\n\n'
        respx.post(f"{BASE_URL}/chat/completions").mock(
            return_value=httpx.Response(
                200,
                content=sse_body.encode(),
                headers={"content-type": "text/event-stream"},
            )
        )

        chunks = []
        async for chunk in adapter.chat_stream([{"role": "user", "content": "修改"}]):
            chunks.append(chunk)

        tool_chunks = [c for c in chunks if c.type == "tool_call"]
        assert len(tool_chunks) == 1
        assert tool_chunks[0].tool_name == "update_draft"
        assert tool_chunks[0].tool_args == {"draft_id": "d1", "prompt": "新提示"}
        await adapter.close()

    @respx.mock
    async def test_stream_http_error(self, adapter):
        """流式请求 HTTP 错误应抛出 AdapterError"""
        respx.post(f"{BASE_URL}/chat/completions").mock(
            return_value=httpx.Response(500, text="Internal Server Error")
        )

        with pytest.raises(AdapterError, match="HTTP 500"):
            async for _ in adapter.chat_stream([{"role": "user", "content": "test"}]):
                pass
        await adapter.close()

    @respx.mock
    async def test_stream_non_sse_json_fallback(self, adapter):
        """供应商不支持流式（返回 JSON）时应 fallback 为单次 text_delta"""
        mock_response = {
            "choices": [{"message": {"content": "非流式回复"}, "finish_reason": "stop"}]
        }
        respx.post(f"{BASE_URL}/chat/completions").mock(
            return_value=httpx.Response(
                200,
                json=mock_response,
                headers={"content-type": "application/json"},
            )
        )

        chunks = []
        async for chunk in adapter.chat_stream([{"role": "user", "content": "test"}]):
            chunks.append(chunk)

        assert len(chunks) == 2
        assert chunks[0].type == "text_delta"
        assert chunks[0].text == "非流式回复"
        assert chunks[1].type == "done"
        assert chunks[1].finish_reason == "stop"
        await adapter.close()

    @respx.mock
    async def test_stream_skips_invalid_json_lines(self, adapter):
        """流中非法 JSON 行应被跳过"""
        sse_body = (
            "data: {invalid json}\n\n"
            'data: {"choices":[{"delta":{"content":"有效"}}]}\n\n'
            "data: [DONE]\n\n"
        )
        respx.post(f"{BASE_URL}/chat/completions").mock(
            return_value=httpx.Response(
                200,
                content=sse_body.encode(),
                headers={"content-type": "text/event-stream"},
            )
        )

        chunks = []
        async for chunk in adapter.chat_stream([{"role": "user", "content": "test"}]):
            chunks.append(chunk)

        assert len(chunks) == 2
        assert chunks[0].text == "有效"
        assert chunks[1].type == "done"
        assert chunks[1].finish_reason == "stop"
        await adapter.close()


# ---------- base64 图片提取 ----------


class TestBase64Image:
    def test_extract_base64_image_found(self):
        """从文本中提取 data URI"""
        text = '这是图片 data:image/png;base64,iVBORw0KGgo= 结束'
        result = extract_base64_image(text)
        assert result.startswith("data:image/png;base64,")

    def test_extract_base64_image_not_found(self):
        """无图片时返回空字符串"""
        assert extract_base64_image("纯文本无图片") == ""

    def test_persist_data_uri_invalid(self):
        """非法 data URI 应抛出 AdapterError"""
        with pytest.raises(AdapterError, match="无法解析"):
            persist_data_uri("not-a-data-uri")

    def test_persist_data_uri_valid(self, tmp_path, monkeypatch):
        """合法 base64 应落盘并返回 URL"""
        import src.video_agent.adapters.openai_compat as mod
        monkeypatch.setattr(mod, "ASSETS_DIR", tmp_path)

        # 1x1 红色 PNG
        import base64
        png_bytes = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg=="
        )
        data_uri = f"data:image/png;base64,{base64.b64encode(png_bytes).decode()}"
        url = persist_data_uri(data_uri)
        assert url.startswith("/workspace/assets/gen-")
        assert url.endswith(".png")

    @respx.mock
    async def test_persist_remote_image_downloads_and_saves(self, monkeypatch):
        """远程临时外链应立即下载落盘，返回本地素材 URL"""
        import src.video_agent.adapters.openai_compat as mod

        class FakeStorage:
            def __init__(self):
                self.saved = []

            def save(self, data, filename, content_type):
                self.saved.append((data, filename, content_type))
                return f"/workspace/assets/{filename}"

        fake = FakeStorage()
        monkeypatch.setattr(mod, "get_storage", lambda: fake)

        png = b"\x89PNG\r\n\x1a\nfake-png"
        respx.get("https://tmp.example.com/a.png").mock(
            return_value=httpx.Response(
                200, content=png, headers={"content-type": "image/png"}
            )
        )

        url = await mod.persist_remote_image("https://tmp.example.com/a.png")
        assert url.startswith("/workspace/assets/gen-")
        assert url.endswith(".png")
        assert fake.saved and fake.saved[0][0] == png

    @respx.mock
    async def test_persist_remote_image_keeps_url_on_404(self):
        """远程外链已失效（404）时保留原 URL，不阻塞图片生成"""
        import src.video_agent.adapters.openai_compat as mod
        respx.get("https://tmp.example.com/dead.png").mock(
            return_value=httpx.Response(404)
        )
        url = await mod.persist_remote_image("https://tmp.example.com/dead.png")
        assert url == "https://tmp.example.com/dead.png"


# ---------- 连接池管理 ----------


class TestConnectionPool:
    @respx.mock
    async def test_client_reuse(self, adapter):
        """多次调用应复用同一 httpx client"""
        mock_response = {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}
        respx.post(f"{BASE_URL}/chat/completions").mock(
            return_value=httpx.Response(200, json=mock_response)
        )

        await adapter.chat([{"role": "user", "content": "1"}])
        client1 = adapter._client
        await adapter.chat([{"role": "user", "content": "2"}])
        client2 = adapter._client
        assert client1 is client2
        await adapter.close()

    async def test_close_releases_client(self, adapter):
        """close() 后 _client 应为 None"""
        # 触发 client 创建
        adapter._get_client()
        assert adapter._client is not None
        await adapter.close()
        assert adapter._client is None

    @respx.mock
    async def test_client_recreated_after_close(self, adapter):
        """close() 后再次调用应重建 client"""
        mock_response = {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}
        respx.post(f"{BASE_URL}/chat/completions").mock(
            return_value=httpx.Response(200, json=mock_response)
        )

        await adapter.chat([{"role": "user", "content": "1"}])
        await adapter.close()
        assert adapter._client is None

        await adapter.chat([{"role": "user", "content": "2"}])
        assert adapter._client is not None
        await adapter.close()


# ---------- 400 大 max_tokens 钳制重试（五项修法批 1） ----------

_CLAMP_400_BODY = '{"error":{"code":"1210","message":"max_tokens must be <= 131072"}}'


def _clamp_gate_handler(request: httpx.Request) -> httpx.Response:
    """按请求里的 max_tokens 分流：超 glm-4.6 保证值（131072）拒 400，放行 200。"""
    body = json.loads(request.content)
    if body.get("max_tokens", 0) > 131_072:
        return httpx.Response(400, text=_CLAMP_400_BODY)
    return httpx.Response(
        200,
        json={"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]},
    )


class TestMaxTokensClamp:
    @respx.mock
    @pytest.mark.allow_degradation
    async def test_chat_clamps_on_400_and_retries_once(self):
        """400 点名拒收大 max_tokens → 钳到模型安全帽重试一次并按模型记忆"""
        route = respx.post(f"{BASE_URL}/chat/completions").mock(
            side_effect=_clamp_gate_handler
        )
        a = OpenAICompatChatAdapter(base_url=BASE_URL, api_key="k", model="glm-4.6")
        result = await a.chat([{"role": "user", "content": "你好"}])  # 默认 256k → 400 → 钳 131072
        assert result.content == "ok"
        assert route.call_count == 2
        assert a._max_tokens_caps == {"glm-4.6": 131_072}

        # 记忆生效：后续请求下发前预钳，一次到位不再吃 400
        await a.chat([{"role": "user", "content": "再来"}])
        assert route.call_count == 3
        sent = json.loads(route.calls.last.request.content)
        assert sent["max_tokens"] == 131_072
        # 显式小值不受钳制影响（只降不升）
        await a.chat([{"role": "user", "content": "小值"}], max_tokens=1024)
        sent = json.loads(route.calls.last.request.content)
        assert sent["max_tokens"] == 1024
        await a.close()

    @respx.mock
    @pytest.mark.allow_degradation
    async def test_stream_clamps_on_400_and_retries(self):
        """流式同口径：400 点名 max_tokens → 钳制重试产出正常流"""
        route = respx.post(f"{BASE_URL}/chat/completions").mock(
            side_effect=_clamp_gate_handler
        )
        a = OpenAICompatChatAdapter(base_url=BASE_URL, api_key="k", model="glm-4.6")
        chunks = []
        async for chunk in a.chat_stream([{"role": "user", "content": "你好"}]):
            chunks.append(chunk)
        assert any(c.type == "text_delta" and c.text == "ok" for c in chunks)
        assert any(c.type == "done" for c in chunks)
        assert route.call_count == 2
        assert a._max_tokens_caps == {"glm-4.6": 131_072}
        await a.close()

    @respx.mock
    async def test_chat_no_clamp_when_value_below_cap(self):
        """max_tokens 未超模型安全帽 → 400 点名也不钳制，直接上抛（一次请求）"""
        route = respx.post(f"{BASE_URL}/chat/completions").mock(
            return_value=httpx.Response(400, text=_CLAMP_400_BODY)
        )
        a = OpenAICompatChatAdapter(base_url=BASE_URL, api_key="k", model="glm-4.6")
        with pytest.raises(AdapterError, match="HTTP 400"):
            await a.chat([{"role": "user", "content": "x"}], max_tokens=1024)
        assert route.call_count == 1
        assert a._max_tokens_caps == {}
        await a.close()

    @respx.mock
    async def test_chat_no_clamp_when_body_not_naming_field(self):
        """400 未点名 max_tokens → 不钳制不重试（防无关 400 被误吃一次纠正式重提）"""
        route = respx.post(f"{BASE_URL}/chat/completions").mock(
            return_value=httpx.Response(400, text='{"error":"invalid request"}')
        )
        a = OpenAICompatChatAdapter(base_url=BASE_URL, api_key="k", model="glm-4.6")
        with pytest.raises(AdapterError, match="HTTP 400"):
            await a.chat([{"role": "user", "content": "x"}])  # 256k > 帽，但报文未点名
        assert route.call_count == 1
        await a.close()

    @respx.mock
    @pytest.mark.allow_degradation
    async def test_image_fallback_clamps_on_400(self, tmp_path, monkeypatch):
        """生图 chat 回退同口径：400 点名 → 钳制重试一次并按模型记忆"""
        import src.video_agent.adapters.openai_compat as mod
        from src.video_agent.adapters.openai_compat import OpenAICompatImageAdapter

        monkeypatch.setattr(mod, "ASSETS_DIR", tmp_path)
        png_uri = (
            "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
            "AAAADUlEQVR42mP8/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg=="
        )

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            if body.get("max_tokens", 0) > 131_072:
                return httpx.Response(400, text=_CLAMP_400_BODY)
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": f"![]({png_uri})"},
                                   "finish_reason": "stop"}]},
            )

        route = respx.post(f"{BASE_URL}/chat/completions").mock(side_effect=handler)
        img = OpenAICompatImageAdapter(base_url=BASE_URL, api_key="k", model="glm-4.6")
        result = await img._try_chat_fallback("画一只猫", "1:1", [])
        assert result is not None and result.image_urls
        assert route.call_count == 2
        assert img._max_tokens_caps == {"glm-4.6": 131_072}
        await img.close()
