"""
MediaFetchAdapter — 远程媒体资源下载统一入口（Rule4: 外部调用走 Adapter）。

收编 web 层两类 httpx 直调旁路：
- multimodal_builder 远程图片服务端代下载（失败静默降级为文本清单）
- routes/upload /api/image-proxy 代理下载（失败转 502）

设计（与既有 adapter 模式对齐）：
- 供应商无关的通用 HTTP GET 客户端，超时/重定向/代理策略全部参数化，
  调用方沿用各自原有取值（行为零变化）
- 默认不对非 2xx 抛异常，返回 status_code 由调用方决策（与原逻辑一致）；
  raise_on_http_error=True 时 >=400 抛 FetchError（image-proxy 的 raise_for_status 语义）
- max_retries>0 时复用 retry.with_retry（指数退避 + 前端状态栏可视化）；
  默认 0 = 单次尝试，与迁移前行为完全一致
"""
from typing import Optional

import httpx
from loguru import logger
from pydantic import BaseModel

from src.video_agent.adapters.retry import with_retry
from src.video_agent.exceptions import AdapterError


class FetchResult(BaseModel):
    """下载结果：HTTP 状态 + 原始字节 + Content-Type"""

    status_code: int = 0
    content: bytes = b""
    content_type: str = ""


class FetchError(AdapterError):
    """下载失败（网络异常或 HTTP 错误状态），路由层统一转 502"""

    status_code = 502
    error_code = "FETCH_ERROR"


class MediaFetchAdapter:
    """供应商无关的通用 HTTP 下载客户端（超时/重定向/代理策略按调用注入）"""

    async def download(
        self,
        url: str,
        *,
        timeout: float = 20.0,
        follow_redirects: bool = True,
        trust_env: bool = True,
        raise_on_http_error: bool = False,
        max_retries: int = 0,
        context: str = "media",
    ) -> FetchResult:
        """GET 下载 url，返回 FetchResult。

        Args:
            timeout: 请求超时（秒），各调用点沿用迁移前的原值
            follow_redirects: 是否跟随重定向
            trust_env: False 时禁用系统代理（本地回环场景）
            raise_on_http_error: True 时 >=400 抛 FetchError（raise_for_status 语义）
            max_retries: 最大重试次数（0 = 单次尝试，与迁移前行为一致）
            context: 日志/重试提示的上下文标识

        Raises:
            FetchError: 网络异常（超时/连接失败等），或开启 raise_on_http_error
                且响应状态 >=400；末次重试仍 5xx 时由 with_retry 抛 AdapterError
        """
        try:
            async with httpx.AsyncClient(
                timeout=timeout,
                follow_redirects=follow_redirects,
                trust_env=trust_env,
            ) as client:
                if max_retries > 0:
                    resp = await with_retry(
                        lambda: client.get(url),
                        max_retries=max_retries,
                        context=context,
                    )
                else:
                    resp = await client.get(url)
        except httpx.HTTPError as exc:
            logger.warning(
                f"[MediaFetch] {context} 下载失败: {url} ({type(exc).__name__}: {exc})"
            )
            raise FetchError(f"{type(exc).__name__}: {exc}", retryable=True) from exc

        if raise_on_http_error and resp.status_code >= 400:
            raise FetchError(
                f"HTTP {resp.status_code} for url {url}",
                retryable=resp.status_code >= 500,
                http_status=resp.status_code,
            )
        return FetchResult(
            status_code=resp.status_code,
            content=resp.content,
            content_type=resp.headers.get("content-type", ""),
        )


# ---------- 模块级单例 ----------

_instance: Optional[MediaFetchAdapter] = None


def get_media_fetch_adapter() -> MediaFetchAdapter:
    """获取全局 MediaFetchAdapter 单例"""
    global _instance
    if _instance is None:
        _instance = MediaFetchAdapter()
    return _instance


def reset_media_fetch_adapter() -> None:
    """重置单例（测试用）"""
    global _instance
    _instance = None
