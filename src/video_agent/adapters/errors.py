"""
错误分类器 — 供应商故障按 transient/permanent 分流（任务 #26）。

分类规则表：
===========+===================================+===============================
 类别      | 触发条件                           | 处置
-----------+-----------------------------------+-------------------------------
 transient | 429（限流/配额）/ 5xx / 超时 /      | with_retry 指数退避重试
           | 连接错误 / 流中断（RemoteProtocol） | （上限与退避参数走 config）
-----------+-----------------------------------+-------------------------------
 permanent | 400/422 参数错误、401/403 鉴权失败、| 立即上抛结构化 AdapterError
           | 其他 4xx、模型明确拒答/中继拒收     | （kind 区分，不重试不 nudge）
===========+===================================+===============================

对齐说明：结构化错误字段（kind/retryable/http_status/message）按任务 #19 的
ErrorPayload 口径自定义（kind=upstream/auth/quota 等）；#19 落地后直接复用
该结构，不再另造并行口径。

设计原则：
- 未知异常一律 permanent（不盲目重试，避免重复计费请求反复提交）
- 分类是纯函数，不依赖网络/状态，便于单测钉死规则表
"""
from typing import Tuple

import httpx

from src.video_agent.exceptions import AdapterError

# ---------- 类别（category） ----------
TRANSIENT = "transient"  # 瞬时故障：指数退避重试
PERMANENT = "permanent"  # 永久故障：立即上抛，不重试

# ---------- kind（与任务 #19 ErrorPayload.kind 对齐） ----------
KIND_UPSTREAM = "upstream"  # 供应商侧 5xx / 通用服务故障
KIND_AUTH = "auth"          # 401/403 鉴权/授权失败
KIND_QUOTA = "quota"        # 429 限流/配额不足
KIND_PARAM = "param"        # 400/422 请求参数错误
KIND_REFUSAL = "refusal"    # 模型明确拒答 / 中继拒收通知单
KIND_TIMEOUT = "timeout"    # 请求超时
KIND_NETWORK = "network"    # 连接错误 / 流中断
KIND_UNKNOWN = "unknown"    # 未归类（按 permanent 处置）

# kind → 前端错误码（error_code，国际化锚点）
_KIND_ERROR_CODES = {
    KIND_UPSTREAM: "ADAPTER_UPSTREAM_ERROR",
    KIND_AUTH: "ADAPTER_AUTH_ERROR",
    KIND_QUOTA: "ADAPTER_QUOTA_ERROR",
    KIND_PARAM: "ADAPTER_PARAM_ERROR",
    KIND_REFUSAL: "ADAPTER_REFUSAL_ERROR",
    KIND_TIMEOUT: "ADAPTER_TIMEOUT_ERROR",
    KIND_NETWORK: "ADAPTER_NETWORK_ERROR",
}

# 瞬时故障对应的 httpx 异常类型（流中断=RemoteProtocolError）
_TRANSIENT_HTTPX_EXCEPTIONS = (
    httpx.TimeoutException,
    httpx.NetworkError,       # ConnectError/读写连接层故障
    httpx.RemoteProtocolError,  # 流中断（对端提前断开/SSE 协议破坏）
)


def classify_status(status_code: int) -> Tuple[str, str]:
    """按 HTTP 状态码分类 → (category, kind)。

    429/5xx = transient（可重试）；其余 4xx = permanent（按码细分 kind）。
    """
    if status_code == 429:
        return TRANSIENT, KIND_QUOTA
    if status_code >= 500:
        return TRANSIENT, KIND_UPSTREAM
    if status_code in (401, 403):
        return PERMANENT, KIND_AUTH
    if status_code in (400, 422):
        return PERMANENT, KIND_PARAM
    return PERMANENT, KIND_UPSTREAM


def classify_exception(exc: BaseException) -> Tuple[str, str]:
    """按异常类型分类 → (category, kind)。未知异常按 permanent 处置（不盲目重试）。"""
    if isinstance(exc, httpx.TimeoutException):
        return TRANSIENT, KIND_TIMEOUT
    if isinstance(exc, _TRANSIENT_HTTPX_EXCEPTIONS):
        return TRANSIENT, KIND_NETWORK
    if isinstance(exc, httpx.HTTPStatusError):
        return classify_status(exc.response.status_code)
    if isinstance(exc, AdapterError):
        # 已结构化的错误：优先按 http_status 细分，否则沿用 retryable/kind 标记
        if exc.http_status is not None:
            return classify_status(exc.http_status)
        category = TRANSIENT if exc.retryable else PERMANENT
        return category, (exc.kind or KIND_UNKNOWN)
    return PERMANENT, KIND_UNKNOWN


def is_transient_status(status_code: int) -> bool:
    """状态码是否属瞬时故障（429/5xx）"""
    return classify_status(status_code)[0] == TRANSIENT


def is_transient_error(exc: BaseException) -> bool:
    """异常是否属瞬时故障（重试判定唯一入口，替代文案匹配）"""
    return classify_exception(exc)[0] == TRANSIENT


def build_status_error(
    status_code: int,
    body: str = "",
    *,
    context: str = "",
    detail: str = "",
) -> AdapterError:
    """HTTP 错误状态 → 结构化 AdapterError（kind/retryable/http_status 齐备）。

    message 保持「LLM 返回 HTTP {code}」前缀（流式路径兼容探针按前缀识别 400）。
    """
    category, kind = classify_status(status_code)
    prefix = f"[{context}] " if context else ""
    suffix = f"（{detail}）" if detail else ""
    snippet = (body or "").strip()[:200]
    msg = f"{prefix}LLM 返回 HTTP {status_code}: {snippet}{suffix}"
    return AdapterError(
        msg.strip(),
        retryable=category == TRANSIENT,
        http_status=status_code,
        kind=kind,
        error_code=_KIND_ERROR_CODES.get(kind, "ADAPTER_ERROR"),
    )


def build_exception_error(exc: BaseException, *, context: str = "") -> AdapterError:
    """网络/超时等异常 → 结构化 AdapterError（分类由 classify_exception 决定）。"""
    category, kind = classify_exception(exc)
    prefix = f"[{context}] " if context else ""
    if isinstance(exc, httpx.TimeoutException):
        msg = f"{prefix}LLM 请求超时（{type(exc).__name__}），请检查网络或供应商状态"
    else:
        msg = f"{prefix}LLM 请求失败（{type(exc).__name__}）: {str(exc)[:200]}"
    return AdapterError(
        msg.strip(),
        retryable=category == TRANSIENT,
        http_status=getattr(getattr(exc, "response", None), "status_code", None),
        kind=kind,
        error_code=_KIND_ERROR_CODES.get(kind, "ADAPTER_ERROR"),
    )
