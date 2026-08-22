"""
ProviderProbeAdapter — 供应商连接探测 / 模型列表拉取（Rule4: 外部调用走 Adapter）。

收编 web/routes/providers.py 的 httpx 直调旁路：
- fetch-models / test-connection：GET {base_url}/models 拉取模型清单
- probe-async：探测 /models 端点原始响应（协议检测）

错误语义与迁移前完全一致：
- 超时 → ProbeTimeoutError（路由层回「连接超时」类文案）
- HTTP 错误状态 → ProbeHTTPError（携带 status_code 与响应体前 200 字符）
- 探测端点非 200 不抛异常，返回 status_code + raw 由路由层决策（与原逻辑一致）

超时值沿用迁移前原值：模型清单 15s / 协议探测 12s。
"""
from dataclasses import dataclass, field
from typing import Any, List, Optional

import httpx

from src.video_agent.adapters.retry import with_retry
from src.video_agent.exceptions import AdapterError

# 迁移前沿用值：fetch-models/test-connection 15s，probe-async 12s
PROBE_TIMEOUT_MODELS = 15.0
PROBE_TIMEOUT_DETECT = 12.0


class ProbeTimeoutError(AdapterError):
    """供应商探测超时（路由层转「连接超时（15s）」类文案）"""

    status_code = 504
    error_code = "PROBE_TIMEOUT"


class ProbeHTTPError(AdapterError):
    """供应商返回 HTTP 错误状态（携带状态码与响应体摘要，供路由层组装文案）"""

    error_code = "PROBE_HTTP_ERROR"

    def __init__(
        self,
        message: str,
        *,
        http_status: int,
        body_text: str = "",
        retryable: Optional[bool] = None,
    ):
        super().__init__(
            message,
            status_code=http_status,
            retryable=retryable,
            http_status=http_status,
        )
        self.body_text = body_text


@dataclass
class ProbeResult:
    """探测端点原始结果（非 200 不视为异常，由调用方按 status_code 决策）"""

    status_code: int = 0
    raw: Any = field(default_factory=dict)


def normalize_openai_base_url(base_url: str) -> str:
    """与画布保持一致：若 base_url 未以 /v1 结尾则自动补全，避免用户手填时漏掉路径段。"""
    url = base_url.rstrip("/")
    if not url.endswith("/v1"):
        url += "/v1"
    return url


class ProviderProbeAdapter:
    """OpenAI 兼容供应商探测客户端（/models 端点）"""

    async def fetch_model_list(
        self,
        base_url: str,
        api_key: str,
        *,
        timeout: float = PROBE_TIMEOUT_MODELS,
        max_retries: int = 0,
    ) -> List[str]:
        """GET {base_url}/models，返回排序后的模型 id 列表（OpenAI 兼容格式）。

        Raises:
            ProbeTimeoutError: 连接/读取超时
            ProbeHTTPError: 上游返回 4xx/5xx（携带状态码与响应体摘要）
            AdapterError: max_retries>0 且末次重试仍 5xx（with_retry 契约）
        """
        url = normalize_openai_base_url(base_url)
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                if max_retries > 0:
                    resp = await with_retry(
                        lambda: client.get(f"{url}/models", headers=headers),
                        max_retries=max_retries,
                        context="probe",
                    )
                else:
                    resp = await client.get(f"{url}/models", headers=headers)
                resp.raise_for_status()
                data = resp.json()
        except httpx.TimeoutException as exc:
            raise ProbeTimeoutError(
                f"供应商探测超时（{timeout:.0f}s）: {url}", retryable=True
            ) from exc
        except httpx.HTTPStatusError as exc:
            body = exc.response.text[:200]
            raise ProbeHTTPError(
                f"HTTP {exc.response.status_code}: {body}",
                http_status=exc.response.status_code,
                body_text=body,
                retryable=exc.response.status_code >= 500,
            ) from exc
        models_data = data.get("data", [])
        return sorted(m.get("id", "") for m in models_data if m.get("id"))

    async def probe_models_endpoint(
        self,
        base_url: str,
        api_key: str,
        *,
        timeout: float = PROBE_TIMEOUT_DETECT,
    ) -> ProbeResult:
        """探测 /models 端点并返回原始结果（协议检测用）。

        与迁移前行为一致：非 200 不抛异常；content-type 为 JSON 时解析为对象，
        否则截取响应文本前 500 字符装入 {"text": ...}；JSON 解析失败原样上抛。

        Raises:
            ProbeTimeoutError: 连接/读取超时
        """
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        probe_url = normalize_openai_base_url(base_url)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.get(f"{probe_url}/models", headers=headers)
        except httpx.TimeoutException as exc:
            raise ProbeTimeoutError(f"供应商探测超时（{timeout:.0f}s）: {probe_url}", retryable=True) from exc
        status_code = resp.status_code
        if resp.headers.get("content-type", "").startswith("application/json"):
            raw: Any = resp.json()
        else:
            raw = {"text": resp.text[:500]}
        return ProbeResult(status_code=status_code, raw=raw)


# ---------- 模块级单例 ----------

_instance: Optional[ProviderProbeAdapter] = None


def get_provider_probe_adapter() -> ProviderProbeAdapter:
    """获取全局 ProviderProbeAdapter 单例"""
    global _instance
    if _instance is None:
        _instance = ProviderProbeAdapter()
    return _instance


def reset_provider_probe_adapter() -> None:
    """重置单例（测试用）"""
    global _instance
    _instance = None
