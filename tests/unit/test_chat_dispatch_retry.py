"""chat 客户端错误分类分流与重试路径（任务 #26）。

钉死：
- transient（429/5xx）经 with_retry 指数退避重试，成功后正常返回；
  重试耗尽仍 transient → 结构化 AdapterError（retryable=True + kind）
- permanent（400/401/403）立即上抛结构化 AdapterError，一次都不重试
- 幂等语义：同一轮请求的重试全程复用同一 payload 与同一 X-Request-Id
"""
from types import SimpleNamespace

import httpx
import pytest

import src.video_agent.adapters.base_chat as bc
from src.video_agent.adapters.base_chat import dispatch_chat_request, new_request_id
from src.video_agent.adapters.openai_compat import OpenAICompatChatAdapter
from src.video_agent.exceptions import AdapterError


class FakeClient:
    """记录每次 post 的 payload/请求头，按序回放响应（mock adapter 传输层）"""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def post(self, url, json=None, headers=None):
        self.calls.append({"url": url, "json": json, "headers": headers or {}})
        idx = min(len(self.calls) - 1, len(self.responses) - 1)
        resp = self.responses[idx]
        if isinstance(resp, Exception):
            raise resp
        return resp


def _ok_response(content="ok"):
    return httpx.Response(200, json={
        "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
        "usage": {"total_tokens": 3},
    })


def _make_adapter(monkeypatch, responses):
    adapter = OpenAICompatChatAdapter(base_url="http://x", api_key="k", model="m")
    fake = FakeClient(responses)
    monkeypatch.setattr(adapter, "_get_client", lambda timeout=None: fake)
    return adapter, fake


# ---------- dispatch_chat_request：分流入口 ----------

async def test_dispatch_permanent_4xx_raises_immediately():
    """permanent 4xx：不重试，立即抛结构化错误"""
    calls = {"n": 0}

    async def fn():
        calls["n"] += 1
        return httpx.Response(401, text="Unauthorized")

    with pytest.raises(AdapterError) as ei:
        await dispatch_chat_request(fn, context="chat")
    assert calls["n"] == 1  # 一次都不重试
    assert ei.value.http_status == 401
    assert ei.value.kind == "auth"
    assert ei.value.retryable is False


async def test_dispatch_transient_exhausted_raises_structured():
    """transient 重试耗尽：抛结构化 AdapterError（retryable=True + kind）"""
    calls = {"n": 0}

    async def fn():
        calls["n"] += 1
        return httpx.Response(503, text="busy")

    # 收敛重试参数：上限 2 次、退避可忽略
    async def _no_sleep(_s):
        return None

    import src.video_agent.adapters.retry as retry_mod
    orig_settings = bc.settings
    bc.settings = SimpleNamespace(adapter_retry_max=2, adapter_retry_base_delay=0.001)
    orig_sleep = retry_mod.asyncio.sleep
    retry_mod.asyncio.sleep = _no_sleep
    try:
        with pytest.raises(AdapterError) as ei:
            await dispatch_chat_request(fn, context="chat")
    finally:
        bc.settings = orig_settings
        retry_mod.asyncio.sleep = orig_sleep
    assert calls["n"] == 3  # 首调 + 2 次重试，不多不少
    assert ei.value.http_status == 503
    assert ei.value.kind == "upstream"
    assert ei.value.retryable is True


# ---------- chat() 端到端分流（mock adapter） ----------

async def test_chat_429_retried_then_success_idempotent(monkeypatch):
    """429（transient/quota）退避重试后成功；重试全程复用同一请求标识（幂等）"""
    adapter, fake = _make_adapter(monkeypatch, [
        httpx.Response(429, text="rate limited"),
        _ok_response("回来了"),
    ])
    result = await adapter.chat([{"role": "user", "content": "hi"}])
    assert result.content == "回来了"
    assert len(fake.calls) == 2
    # 幂等语义：同一轮请求标识在重试间保持一致，payload 同体
    ids = [c["headers"].get("X-Request-Id") for c in fake.calls]
    assert ids[0] and ids[0] == ids[1]
    assert fake.calls[0]["json"] is fake.calls[1]["json"]
    await adapter.close()


async def test_chat_5xx_exhausted_raises_transient_error(monkeypatch):
    """5xx 重试耗尽：结构化上抛（retryable=True），适配层耗尽才进上层错误路径"""
    adapter, fake = _make_adapter(monkeypatch, [httpx.Response(500, text="oops")])
    with pytest.raises(AdapterError) as ei:
        await adapter.chat([{"role": "user", "content": "hi"}])
    # settings.adapter_retry_max=2（config 默认）→ 首调 + 2 次重试
    assert len(fake.calls) == 3
    assert ei.value.retryable is True
    assert ei.value.kind == "upstream"
    assert ei.value.http_status == 500
    await adapter.close()


async def test_chat_401_permanent_no_retry(monkeypatch):
    """401（permanent/auth）：立即上抛，一次都不重试"""
    adapter, fake = _make_adapter(monkeypatch, [httpx.Response(401, text="bad key")])
    with pytest.raises(AdapterError) as ei:
        await adapter.chat([{"role": "user", "content": "hi"}])
    assert len(fake.calls) == 1
    assert ei.value.retryable is False
    assert ei.value.kind == "auth"
    await adapter.close()


async def test_chat_403_permanent_no_retry(monkeypatch):
    """403（permanent/auth）：同 401，不重试"""
    adapter, fake = _make_adapter(monkeypatch, [httpx.Response(403, text="forbidden")])
    with pytest.raises(AdapterError) as ei:
        await adapter.chat([{"role": "user", "content": "hi"}])
    assert len(fake.calls) == 1
    assert ei.value.kind == "auth"
    await adapter.close()


async def test_chat_timeout_exhausted_classified(monkeypatch):
    """超时（transient/timeout）重试耗尽：kind=timeout、retryable=True"""
    adapter, fake = _make_adapter(monkeypatch, [httpx.ReadTimeout("slow")])
    with pytest.raises(AdapterError) as ei:
        await adapter.chat([{"role": "user", "content": "hi"}])
    assert len(fake.calls) == 3
    assert ei.value.retryable is True
    assert ei.value.kind == "timeout"
    assert "超时" in str(ei.value)
    await adapter.close()


def test_new_request_id_unique():
    a, b = new_request_id(), new_request_id()
    assert a and b and a != b
