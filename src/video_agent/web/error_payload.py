"""
ErrorPayload — 统一错误语义契约（任务 #19）。

此前前端对错误文案做正则猜测（/401|403|token|鉴权/）决定交互动作，
与 SSE error_code 通道并存两套机制。本模块把错误语义结构化为单一契约，
后端 HTTP 错误响应与 SSE error 事件共用同一结构：

    { "code": "err.auth.invalid_key", "kind": "auth", "message": "...", "raw": "..." }

- kind（归类，封闭集合）：auth / quota / network / upstream / content / unknown
- code（命名空间 err.<kind>.<slug>，可扩展）：前端按 code/kind 做动作映射，
  不再猜测文案。
- message：面向用户的人话（中文），raw：上游原始报文（折叠展示，可空）。

SSE error 事件在既有字段（type/detail/error_code/raw）之上追加 code/kind/message，
不破坏既有事件格式；HTTP 错误响应体在 detail/error_code 之上追加同名字段。
前端镜像见 src/web/lib/error-payload.ts（两侧 kind 集合与 code 命名空间同批维护）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from src.video_agent.exceptions import AdapterError

# ---------- kind 归类（封闭集合；前端 error-payload.ts 镜像，改动需双侧同批） ----------
KIND_AUTH = "auth"        # 鉴权失败（401/403、Key 无效/过期）
KIND_QUOTA = "quota"      # 额度/限流（429、余额不足、预扣费失败）
KIND_NETWORK = "network"  # 网络层（超时、断连、DNS）
KIND_UPSTREAM = "upstream"  # 上游服务端故障（5xx、中继拒收）
KIND_CONTENT = "content"  # 内容策略拒答（审核/敏感/违规）
KIND_UNKNOWN = "unknown"  # 其余

ALL_KINDS = (KIND_AUTH, KIND_QUOTA, KIND_NETWORK, KIND_UPSTREAM, KIND_CONTENT, KIND_UNKNOWN)

# ---------- code 命名空间（err.<kind>.<slug>，简洁可读可扩展） ----------
CODE_AUTH_INVALID_KEY = "err.auth.invalid_key"        # 401
CODE_AUTH_FORBIDDEN = "err.auth.forbidden"            # 403
CODE_AUTH_FORBIDDEN_ORIGIN = "err.auth.forbidden_origin"  # 非本机来源写请求
CODE_QUOTA_RATE_LIMITED = "err.quota.rate_limited"    # 429 限流
CODE_QUOTA_INSUFFICIENT = "err.quota.insufficient"    # 余额/预扣费不足
CODE_NETWORK_TIMEOUT = "err.network.timeout"          # 超时
CODE_NETWORK_CONNECTION = "err.network.connection"    # 断连/连接失败
CODE_UPSTREAM_SERVER = "err.upstream.server_error"    # 5xx
CODE_UPSTREAM_RELAY_REJECTED = "err.upstream.relay_rejected"  # 中继拒收通知单
CODE_CONTENT_POLICY = "err.content.policy"            # 内容策略拒答
CODE_UNKNOWN = "err.unknown"                          # 兜底


@dataclass(frozen=True)
class ErrorPayload:
    """统一错误负载（HTTP 响应与 SSE 事件共用）"""

    code: str
    kind: str
    message: str
    raw: str = ""

    def sse_fields(self) -> dict:
        """SSE error 事件追加字段（与既有 detail/error_code/raw 并存不破坏）"""
        return {"code": self.code, "kind": self.kind, "message": self.message}

    def http_body(self, legacy_error_code: str = "") -> dict:
        """HTTP 错误响应体（detail/error_code 为既有兼容字段）"""
        body: dict = {
            "detail": self.message,
            "message": self.message,
            "code": self.code,
            "kind": self.kind,
        }
        if legacy_error_code:
            body["error_code"] = legacy_error_code
        if self.raw:
            body["raw"] = self.raw
        return body


# ---------- 既有（legacy）error_code → kind/code 映射 ----------
# 旧通道 error_code 未下线期间的归类桥接；未登记者归 unknown（code 附 slug 可读）
_LEGACY_CODE_MAP = {
    "UNAUTHORIZED": (KIND_AUTH, CODE_AUTH_INVALID_KEY),
    "FORBIDDEN_ORIGIN": (KIND_AUTH, CODE_AUTH_FORBIDDEN_ORIGIN),
    "RATE_LIMITED": (KIND_QUOTA, CODE_QUOTA_RATE_LIMITED),
    "TIMEOUT": (KIND_NETWORK, CODE_NETWORK_TIMEOUT),
    "PROBE_TIMEOUT": (KIND_NETWORK, CODE_NETWORK_TIMEOUT),
    "NETWORK_ERROR": (KIND_NETWORK, CODE_NETWORK_CONNECTION),
    "FETCH_ERROR": (KIND_NETWORK, CODE_NETWORK_CONNECTION),
    "VIDEO_CONNECT_ERROR": (KIND_NETWORK, CODE_NETWORK_CONNECTION),
    "VIDEO_TIMEOUT": (KIND_NETWORK, CODE_NETWORK_TIMEOUT),
    "ADAPTER_ERROR": (KIND_UPSTREAM, CODE_UPSTREAM_SERVER),
    "GENERATION_ERROR": (KIND_UPSTREAM, CODE_UPSTREAM_SERVER),
    "PROBE_HTTP_ERROR": (KIND_UPSTREAM, CODE_UPSTREAM_SERVER),
    "VIDEO_SUBMIT_FAILED": (KIND_UPSTREAM, CODE_UPSTREAM_SERVER),
    "VIDEO_HTTP_ERROR": (KIND_UPSTREAM, CODE_UPSTREAM_SERVER),
}

# 内容策略拒答特征（上游报文常见标记；先于状态码分支判定，防 400 被吞进 unknown）
_CONTENT_HINTS = (
    "content_filter", "data_inspection", "内容审核", "内容安全",
    "敏感", "违规", "moderation", "不当内容", "风险内容",
)

# 额度不足特征（与 _friendly_stream_error 的翻译触发词同源）
_QUOTA_HINTS = ("insufficient_user_quota", "预扣费", "余额不足", "额度不足")

# 中继拒收通知单特征（slow 队列等；须在 401/403 分支前，防 403 误归鉴权）
_RELAY_HINTS = ("10605", "queuetype", "中继拒收通知单")

_NETWORK_HINTS = ("timeout", "timed out", "connect", "connection", "network")


def _network_exception_code(exc: Exception) -> Optional[str]:
    """异常类型直接定网络子类（超时 vs 断连）；非网络异常返回 None"""
    name = type(exc).__name__
    if isinstance(exc, TimeoutError) or name.endswith(("TimeoutException", "ConnectTimeout", "ReadTimeout")):
        return CODE_NETWORK_TIMEOUT
    if isinstance(exc, ConnectionError) or name.endswith("ConnectError"):
        return CODE_NETWORK_CONNECTION
    return None


def _upstream_status(exc: Exception) -> Optional[int]:
    """取上游 HTTP 状态：http_status 优先；status_code 是本服务响应码，
    仅非 AdapterError 才有归类语义（AdapterError 默认 502 非上游事实）"""
    status = getattr(exc, "http_status", None)
    if isinstance(status, int):
        return status
    if isinstance(exc, AdapterError):
        return None
    sc = getattr(exc, "status_code", None)
    return sc if isinstance(sc, int) else None


def classify_legacy_code(legacy_code: str, message: str = "", raw: str = "") -> ErrorPayload:
    """仅凭既有 error_code 归类（DUPLICATE_REQUEST 等 worker 直发场景）"""
    code = (legacy_code or "").strip()
    if code in _LEGACY_CODE_MAP:
        kind, new_code = _LEGACY_CODE_MAP[code]
        return ErrorPayload(code=new_code, kind=kind, message=message, raw=raw)
    slug = code.lower() if code else "internal"
    return ErrorPayload(code=f"{CODE_UNKNOWN}.{slug}", kind=KIND_UNKNOWN, message=message, raw=raw)


def classify_exception(exc: Exception, *, message: Optional[str] = None, raw: str = "") -> ErrorPayload:
    """异常 → ErrorPayload（归类优先级与 _friendly_stream_error 的翻译顺序对齐）。

    message 缺省取 str(exc)；raw 缺省为空（调用方持有上游原文时显式传入）。
    """
    msg = message if message is not None else str(exc)
    low = msg.lower()
    status = _upstream_status(exc)
    legacy_code = str(getattr(exc, "error_code", "") or "")

    # 1) 额度不足（文案特征优先，上游常以 400 包裹）
    if any(h in msg or h in low for h in _QUOTA_HINTS):
        return ErrorPayload(CODE_QUOTA_INSUFFICIENT, KIND_QUOTA, msg, raw)
    # 2) 中继拒收（可在 403 状态上出现，须先于鉴权分支）
    if any(h in msg or h in low for h in _RELAY_HINTS):
        return ErrorPayload(CODE_UPSTREAM_RELAY_REJECTED, KIND_UPSTREAM, msg, raw)
    # 3) 上游 HTTP 状态归类
    if isinstance(status, int):
        if status in (401, 403):
            code = CODE_AUTH_INVALID_KEY if status == 401 else CODE_AUTH_FORBIDDEN
            return ErrorPayload(code, KIND_AUTH, msg, raw)
        if status == 429:
            return ErrorPayload(CODE_QUOTA_RATE_LIMITED, KIND_QUOTA, msg, raw)
        if 500 <= status < 600:
            return ErrorPayload(CODE_UPSTREAM_SERVER, KIND_UPSTREAM, msg, raw)
    # 4) 内容策略拒答
    if any(h in msg or h in low for h in _CONTENT_HINTS):
        return ErrorPayload(CODE_CONTENT_POLICY, KIND_CONTENT, msg, raw)
    # 5) 网络层（异常类型优先，文案关键词次之；须先于泛化 error_code 桥接，
    #    否则 AdapterError 默认 ADAPTER_ERROR 会把超时/断连吞进 upstream）
    _net = _network_exception_code(exc)
    if _net:
        return ErrorPayload(_net, KIND_NETWORK, msg, raw)
    if any(h in low for h in _NETWORK_HINTS):
        code = CODE_NETWORK_TIMEOUT if ("timeout" in low or "timed out" in low) else CODE_NETWORK_CONNECTION
        return ErrorPayload(code, KIND_NETWORK, msg, raw)
    # 6) 既有 error_code 桥接
    if legacy_code:
        return classify_legacy_code(legacy_code, msg, raw)
    # 7) 兜底
    return ErrorPayload(CODE_UNKNOWN, KIND_UNKNOWN, msg, raw)


def classify_http_status(status: int, message: str = "", raw: str = "") -> ErrorPayload:
    """仅凭 HTTP 状态码归类（中间件直发场景，如 API Key 校验 401）"""
    if status in (401, 403):
        code = CODE_AUTH_INVALID_KEY if status == 401 else CODE_AUTH_FORBIDDEN
        return ErrorPayload(code, KIND_AUTH, message, raw)
    if status == 429:
        return ErrorPayload(CODE_QUOTA_RATE_LIMITED, KIND_QUOTA, message, raw)
    if isinstance(status, int) and status >= 500:
        return ErrorPayload(CODE_UPSTREAM_SERVER, KIND_UPSTREAM, message, raw)
    return ErrorPayload(CODE_UNKNOWN, KIND_UNKNOWN, message, raw)
