"""
ProviderProbeAdapter — 供应商连接探测 / 模型列表拉取（Rule4: 外部调用走 Adapter）。

覆盖场景：
- fetch-models / test-connection：GET {base_url}/models 拉取模型清单
- probe-async：探测 /models 端点原始响应（协议检测）

错误语义：
- 超时 → ProbeTimeoutError（路由层回「连接超时」类文案）
- HTTP 错误状态 → ProbeHTTPError（携带 status_code 与响应体前 200 字符）
- 探测端点非 200 不抛异常，返回 status_code + raw 由路由层决策

超时值：模型清单 15s / 协议探测 12s。
"""
from dataclasses import dataclass, field
import re
from typing import Any, List, Optional

import httpx

from src.video_agent.adapters.retry import with_retry
from src.video_agent.exceptions import AdapterError

# 超时值：fetch-models/test-connection 15s，probe-async 12s
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


# 已是版本段结尾（/v1、/api/v3 …）时不再补 /v1：
# 火山方舟 base_url=.../api/v3，补成 .../api/v3/v1/models 会 404。
_VERSION_SUFFIX_RE = re.compile(r"/(?:api/)?v\d+$", re.IGNORECASE)


def model_list_candidates(base_url: str) -> List[str]:
    """模型列表候选 base（按尝试顺序）。

    - 版本段结尾（/v1、/api/v3）：只试 {base}/models；
    - 主机名结尾：先试 {base}/v1/models（存量行为），再回落 {base}/models。
    """
    base = str(base_url or "").strip().rstrip("/")
    if not base:
        return []
    if _VERSION_SUFFIX_RE.search(base):
        return [base]
    return [f"{base}/v1", base]


# 非「Authorization: Bearer」鉴权的平台，集中在此（新增平台也只改这里或供应商配置）。
# ElevenLabs 用 ``xi-api-key: <key>``：用 Bearer 一律 401，模型列表拉不到就是这个原因。
_AUTH_STYLE_BY_HOST = {
    "elevenlabs.io": ("xi-api-key", ""),
}


def build_auth_headers(
    base_url: str,
    api_key: str,
    *,
    auth_header: str = "",
    auth_prefix: str = "",
) -> dict:
    """组装鉴权头：供应商显式声明 > 已知平台映射 > 默认 Bearer。

    auth_header/auth_prefix 来自供应商配置（ProviderBase），这样新平台不用改代码；
    只声明 ``auth_header``（如 xi-api-key）而未给前缀时按「无前缀」处理。
    """
    if not api_key:
        return {}
    header = str(auth_header or "").strip()
    if header:
        prefix = auth_prefix
        if header.lower() == "authorization" and not prefix:
            prefix = "Bearer "
    else:
        lowered = str(base_url or "").lower()
        for host, (host_header, host_prefix) in _AUTH_STYLE_BY_HOST.items():
            if host in lowered:
                header, prefix = host_header, host_prefix
                break
        else:
            header, prefix = "Authorization", "Bearer "
    return {header: f"{prefix}{api_key}"}


def _extract_model_ids(data: Any) -> List[str]:
    """从各家模型的响应里抽出模型名（兼容三种常见形状）。

    - OpenAI：``{"data": [{"id": "gpt-4o"}]}``
    - ElevenLabs：裸数组 ``[{"model_id": "eleven_v4"}]``
    - 其它：``{"models": [...]}`` / ``{"model_list": [...]}``
    条目也可能是纯字符串，字段名可能是 id/model_id/model/name。
    只抽名字不猜测用途，能力分类交给 classify_models。
    """
    items: List[Any] = []
    if isinstance(data, dict):
        for key in ("data", "models", "model_list"):
            value = data.get(key)
            if isinstance(value, list):
                items = value
                break
    elif isinstance(data, list):
        items = data
    ids: List[str] = []
    for item in items:
        if isinstance(item, str):
            if item.strip():
                ids.append(item.strip())
            continue
        if not isinstance(item, dict):
            continue
        for key in ("id", "model_id", "model", "name"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                ids.append(value.strip())
                break
    return sorted(set(ids))


class ProviderProbeAdapter:
    """OpenAI 兼容供应商探测客户端（/models 端点）"""

    async def fetch_model_list(
        self,
        base_url: str,
        api_key: str,
        *,
        timeout: float = PROBE_TIMEOUT_MODELS,
        max_retries: int = 0,
        auth_header: str = "",
        auth_prefix: str = "",
    ) -> List[str]:
        """GET {base_url}/models，返回排序后的模型 id 列表（OpenAI 兼容格式）。

        Raises:
            ProbeTimeoutError: 连接/读取超时
            ProbeHTTPError: 上游返回 4xx/5xx（携带状态码与响应体摘要）
            AdapterError: max_retries>0 且末次重试仍 5xx（with_retry 契约）
        """
        url_bases = model_list_candidates(base_url)
        if not url_bases:
            raise AdapterError("缺少 Base URL")
        headers = build_auth_headers(
            base_url, api_key, auth_header=auth_header, auth_prefix=auth_prefix)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                data: Any = {"data": []}
                for index, base in enumerate(url_bases):
                    try:
                        if max_retries > 0:
                            resp = await with_retry(
                                lambda base=base: client.get(f"{base}/models", headers=headers),
                                max_retries=max_retries,
                                context="probe",
                            )
                        else:
                            resp = await client.get(f"{base}/models", headers=headers)
                        resp.raise_for_status()
                        data = resp.json()
                        break
                    except httpx.HTTPStatusError as exc:
                        # 404 且还有候选：换下一个候选（兼容主机名与带版本段两种填法）
                        if exc.response.status_code == 404 and index < len(url_bases) - 1:
                            continue
                        raise
        except httpx.TimeoutException as exc:
            raise ProbeTimeoutError(
                f"供应商探测超时（{timeout:.0f}s）: {url_bases[0]}", retryable=True
            ) from exc
        except httpx.HTTPStatusError as exc:
            body = exc.response.text[:200]
            raise ProbeHTTPError(
                f"HTTP {exc.response.status_code}: {body}",
                http_status=exc.response.status_code,
                body_text=body,
                retryable=exc.response.status_code >= 500,
            ) from exc
        return _extract_model_ids(data)

    async def probe_models_endpoint(
        self,
        base_url: str,
        api_key: str,
        *,
        timeout: float = PROBE_TIMEOUT_DETECT,
        auth_header: str = "",
        auth_prefix: str = "",
    ) -> ProbeResult:
        """探测 /models 端点并返回原始结果（协议检测用）。

        非 200 不抛异常；content-type 为 JSON 时解析为对象，
        否则截取响应文本前 500 字符装入 {"text": ...}；JSON 解析失败原样上抛。

        Raises:
            ProbeTimeoutError: 连接/读取超时
        """
        headers = build_auth_headers(
            base_url, api_key, auth_header=auth_header, auth_prefix=auth_prefix)
        candidates = model_list_candidates(base_url)
        if not candidates:
            raise ProbeTimeoutError("缺少 Base URL")
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = None
                for index, base in enumerate(candidates):
                    resp = await client.get(f"{base}/models", headers=headers)
                    if resp.status_code == 404 and index < len(candidates) - 1:
                        continue
                    break
        except httpx.TimeoutException as exc:
            raise ProbeTimeoutError(f"供应商探测超时（{timeout:.0f}s）: {candidates[0]}", retryable=True) from exc
        status_code = resp.status_code  # type: ignore[union-attr]
        if resp.headers.get("content-type", "").startswith("application/json"):  # type: ignore[union-attr]
            raw: Any = resp.json()  # type: ignore[union-attr]
        else:
            raw = {"text": resp.text[:500]}  # type: ignore[union-attr]
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
