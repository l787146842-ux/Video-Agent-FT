"""MediaFetchAdapter 单测 — mock httpx transport 覆盖成功/超时/重试路径。

迁移自 web 层 2 处 httpx 直调（multimodal_builder 远程图片代下载、
routes/upload image-proxy），行为契约在此固化：
- 非 200 默认不抛异常（status_code 透传给调用方决策）
- raise_on_http_error=True 时 >=400 抛 FetchError（image-proxy raise_for_status 语义）
- 网络异常统一转 FetchError（路由层转 502）
- max_retries>0 复用 with_retry 指数退避重试
"""
import httpx
import pytest

from src.video_agent.adapters import fetch_adapter as fa
from src.video_agent.exceptions import AdapterError

URL = "https://cdn.example.com/a.png"


def _patch_client(monkeypatch, handler):
    """给 MediaFetchAdapter 内部的 AsyncClient 注入 MockTransport"""
    real_cls = httpx.AsyncClient

    def factory(**kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_cls(**kwargs)

    monkeypatch.setattr(fa.httpx, "AsyncClient", factory)


def _no_retry_sleep(monkeypatch):
    async def _sleep(_seconds):
        return None

    monkeypatch.setattr("src.video_agent.adapters.retry.asyncio.sleep", _sleep)


async def test_download_success_returns_bytes_and_content_type(monkeypatch):
    def handler(request):
        return httpx.Response(200, content=b"PNGDATA", headers={"content-type": "image/png"})

    _patch_client(monkeypatch, handler)
    result = await fa.MediaFetchAdapter().download(URL)
    assert result.status_code == 200
    assert result.content == b"PNGDATA"
    assert result.content_type == "image/png"


async def test_download_non_200_passes_through_without_raising(monkeypatch):
    """multimodal_builder 语义：非 200 不抛异常，由调用方按 status_code 降级"""
    _patch_client(monkeypatch, lambda request: httpx.Response(404, content=b""))
    result = await fa.MediaFetchAdapter().download(URL)
    assert result.status_code == 404
    assert result.content == b""


async def test_download_raise_on_http_error_404(monkeypatch):
    """image-proxy 语义：>=400 抛 FetchError（携带 http_status）"""
    _patch_client(monkeypatch, lambda request: httpx.Response(404, content=b""))
    with pytest.raises(fa.FetchError) as exc_info:
        await fa.MediaFetchAdapter().download(URL, raise_on_http_error=True)
    assert exc_info.value.http_status == 404
    assert exc_info.value.retryable is False


async def test_download_timeout_converted_to_fetch_error(monkeypatch):
    def handler(request):
        raise httpx.ReadTimeout("simulated timeout", request=request)

    _patch_client(monkeypatch, handler)
    with pytest.raises(fa.FetchError) as exc_info:
        await fa.MediaFetchAdapter().download(URL, timeout=1.0)
    assert exc_info.value.retryable is True


async def test_download_retries_5xx_then_succeeds(monkeypatch):
    """max_retries>0：5xx 指数退避重试后成功（with_retry 路径）"""
    _no_retry_sleep(monkeypatch)
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(503, content=b"busy")
        return httpx.Response(200, content=b"OK")

    _patch_client(monkeypatch, handler)
    result = await fa.MediaFetchAdapter().download(URL, max_retries=2)
    assert result.status_code == 200
    assert result.content == b"OK"
    assert calls["n"] == 3


async def test_download_retries_exhausted_5xx_raises_adapter_error(monkeypatch):
    """末次重试仍 5xx：with_retry 契约抛 AdapterError，绝不把失败响应当成功"""
    _no_retry_sleep(monkeypatch)
    _patch_client(monkeypatch, lambda request: httpx.Response(503, content=b"busy"))
    with pytest.raises(AdapterError):
        await fa.MediaFetchAdapter().download(URL, max_retries=1)


def test_singleton_get_and_reset():
    fa.reset_media_fetch_adapter()
    a = fa.get_media_fetch_adapter()
    assert fa.get_media_fetch_adapter() is a
    fa.reset_media_fetch_adapter()
    assert fa.get_media_fetch_adapter() is not a
