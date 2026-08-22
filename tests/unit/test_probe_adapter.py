"""ProviderProbeAdapter 单测 — mock httpx transport 覆盖成功/超时/重试路径。

迁移自 web/routes/providers.py 的 2 处 httpx 直调（_fetch_model_list / probe-async），
错误语义契约在此固化：
- 超时 → ProbeTimeoutError（路由层回「连接超时（15s）」类文案）
- HTTP 错误状态 → ProbeHTTPError（status_code + 响应体前 200 字符）
- probe_models_endpoint 非 200 不抛异常（返回 status_code + raw）
- 超时值沿用迁移前原值（15s / 12s）
"""
import httpx
import pytest

from src.video_agent.adapters import probe_adapter as pa
from src.video_agent.exceptions import AdapterError

BASE_URL = "https://api.example.com"


def _patch_client(monkeypatch, handler):
    """给 ProviderProbeAdapter 内部的 AsyncClient 注入 MockTransport"""
    real_cls = httpx.AsyncClient

    def factory(**kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_cls(**kwargs)

    monkeypatch.setattr(pa.httpx, "AsyncClient", factory)


def _no_retry_sleep(monkeypatch):
    async def _sleep(_seconds):
        return None

    monkeypatch.setattr("src.video_agent.adapters.retry.asyncio.sleep", _sleep)


def test_normalize_openai_base_url():
    assert pa.normalize_openai_base_url("https://api.x.com") == "https://api.x.com/v1"
    assert pa.normalize_openai_base_url("https://api.x.com/") == "https://api.x.com/v1"
    assert pa.normalize_openai_base_url("https://api.x.com/v1") == "https://api.x.com/v1"


async def test_fetch_model_list_success_sorted(monkeypatch):
    """GET {base_url}/v1/models，返回排序后的模型 id（空 id 过滤）"""
    seen_urls = []

    def handler(request):
        seen_urls.append(str(request.url))
        return httpx.Response(200, json={"data": [
            {"id": "zeta-model"}, {"id": "alpha-model"}, {"id": ""},
        ]})

    _patch_client(monkeypatch, handler)
    models = await pa.ProviderProbeAdapter().fetch_model_list(BASE_URL, "sk-test")
    assert models == ["alpha-model", "zeta-model"]
    assert seen_urls == [f"{BASE_URL}/v1/models"]


async def test_fetch_model_list_sends_bearer_header(monkeypatch):
    def handler(request):
        assert request.headers.get("authorization") == "Bearer sk-123"
        return httpx.Response(200, json={"data": []})

    _patch_client(monkeypatch, handler)
    assert await pa.ProviderProbeAdapter().fetch_model_list(BASE_URL, "sk-123") == []


async def test_fetch_model_list_timeout_raises_probe_timeout(monkeypatch):
    def handler(request):
        raise httpx.ConnectTimeout("connect timeout", request=request)

    _patch_client(monkeypatch, handler)
    with pytest.raises(pa.ProbeTimeoutError) as exc_info:
        await pa.ProviderProbeAdapter().fetch_model_list(BASE_URL, "")
    assert exc_info.value.retryable is True


async def test_fetch_model_list_401_raises_probe_http_error(monkeypatch):
    """4xx 不重试，ProbeHTTPError 携带状态码与响应体摘要（供路由层组装文案）"""
    _patch_client(monkeypatch, lambda request: httpx.Response(401, text="invalid key"))
    with pytest.raises(pa.ProbeHTTPError) as exc_info:
        await pa.ProviderProbeAdapter().fetch_model_list(BASE_URL, "bad")
    err = exc_info.value
    assert err.status_code == 401
    assert err.http_status == 401
    assert err.body_text == "invalid key"
    assert err.retryable is False


async def test_fetch_model_list_retries_5xx_then_succeeds(monkeypatch):
    """max_retries>0：5xx 指数退避重试后成功（with_retry 路径）"""
    _no_retry_sleep(monkeypatch)
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(500, text="oops")
        return httpx.Response(200, json={"data": [{"id": "m1"}]})

    _patch_client(monkeypatch, handler)
    models = await pa.ProviderProbeAdapter().fetch_model_list(BASE_URL, "", max_retries=2)
    assert models == ["m1"]
    assert calls["n"] == 2


async def test_fetch_model_list_retries_exhausted_5xx_raises(monkeypatch):
    """末次重试仍 5xx：with_retry 契约抛 AdapterError，绝不把失败响应当成功"""
    _no_retry_sleep(monkeypatch)
    _patch_client(monkeypatch, lambda request: httpx.Response(500, text="oops"))
    with pytest.raises(AdapterError):
        await pa.ProviderProbeAdapter().fetch_model_list(BASE_URL, "", max_retries=1)


async def test_probe_models_endpoint_json_200(monkeypatch):
    payload = {"object": "list", "data": [{"id": "m1"}]}
    _patch_client(monkeypatch, lambda request: httpx.Response(
        200, json=payload, headers={"content-type": "application/json"}))
    result = await pa.ProviderProbeAdapter().probe_models_endpoint(BASE_URL, "")
    assert result.status_code == 200
    assert result.raw == payload


async def test_probe_models_endpoint_non_json_wraps_text(monkeypatch):
    """非 JSON 响应：截取文本前 500 字符装入 {"text": ...}（迁移前行为）"""
    long_text = "x" * 800
    _patch_client(monkeypatch, lambda request: httpx.Response(
        404, text=long_text, headers={"content-type": "text/html"}))
    result = await pa.ProviderProbeAdapter().probe_models_endpoint(BASE_URL, "")
    assert result.status_code == 404
    assert result.raw == {"text": "x" * 500}


async def test_probe_models_endpoint_non_200_does_not_raise(monkeypatch):
    """probe-async 语义：非 200 不抛异常，status_code 透传给路由层决策"""
    _patch_client(monkeypatch, lambda request: httpx.Response(500, json={"error": "boom"}))
    result = await pa.ProviderProbeAdapter().probe_models_endpoint(BASE_URL, "")
    assert result.status_code == 500
    assert result.raw == {"error": "boom"}


async def test_probe_models_endpoint_timeout(monkeypatch):
    def handler(request):
        raise httpx.ReadTimeout("read timeout", request=request)

    _patch_client(monkeypatch, handler)
    with pytest.raises(pa.ProbeTimeoutError):
        await pa.ProviderProbeAdapter().probe_models_endpoint(BASE_URL, "")


def test_default_timeouts_preserve_legacy_values():
    """超时值沿用迁移前原值：模型清单 15s / 协议探测 12s"""
    assert pa.PROBE_TIMEOUT_MODELS == 15.0
    assert pa.PROBE_TIMEOUT_DETECT == 12.0


def test_singleton_get_and_reset():
    pa.reset_provider_probe_adapter()
    a = pa.get_provider_probe_adapter()
    assert pa.get_provider_probe_adapter() is a
    pa.reset_provider_probe_adapter()
    assert pa.get_provider_probe_adapter() is not a
