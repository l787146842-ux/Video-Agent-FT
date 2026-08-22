"""错误分类器单测（任务 #26）：钉死 transient/permanent 分类规则表。

规则表：
- transient = 429 / 5xx / 超时 / 连接错误 / 流中断 → 可重试
- permanent = 400/401/403/422/其他 4xx / 未知异常 → 立即上抛，不重试
"""
import httpx
import pytest

from src.video_agent.adapters import errors as er
from src.video_agent.exceptions import AdapterError


def _http_status_error(code: int) -> httpx.HTTPStatusError:
    req = httpx.Request("POST", "http://t/chat/completions")
    return httpx.HTTPStatusError(
        "err", request=req, response=httpx.Response(code, request=req),
    )


# ---------- 状态码分类 ----------

@pytest.mark.parametrize("code,cat,kind", [
    (429, er.TRANSIENT, er.KIND_QUOTA),
    (500, er.TRANSIENT, er.KIND_UPSTREAM),
    (502, er.TRANSIENT, er.KIND_UPSTREAM),
    (503, er.TRANSIENT, er.KIND_UPSTREAM),
    (504, er.TRANSIENT, er.KIND_UPSTREAM),
    (401, er.PERMANENT, er.KIND_AUTH),
    (403, er.PERMANENT, er.KIND_AUTH),
    (400, er.PERMANENT, er.KIND_PARAM),
    (422, er.PERMANENT, er.KIND_PARAM),
    (404, er.PERMANENT, er.KIND_UPSTREAM),
    (409, er.PERMANENT, er.KIND_UPSTREAM),
])
def test_classify_status_rule_table(code, cat, kind):
    assert er.classify_status(code) == (cat, kind)
    assert er.is_transient_status(code) is (cat == er.TRANSIENT)


# ---------- 异常分类 ----------

def test_classify_exception_timeout_is_transient():
    cat, kind = er.classify_exception(httpx.ReadTimeout("t"))
    assert cat == er.TRANSIENT and kind == er.KIND_TIMEOUT


def test_classify_exception_connect_and_stream_break_is_transient():
    cat, kind = er.classify_exception(httpx.ConnectError("refused"))
    assert cat == er.TRANSIENT and kind == er.KIND_NETWORK
    cat, kind = er.classify_exception(httpx.RemoteProtocolError("peer closed"))
    assert cat == er.TRANSIENT and kind == er.KIND_NETWORK


def test_classify_exception_http_status_delegates_to_status():
    assert er.classify_exception(_http_status_error(429)) == (er.TRANSIENT, er.KIND_QUOTA)
    assert er.classify_exception(_http_status_error(401)) == (er.PERMANENT, er.KIND_AUTH)
    assert er.is_transient_error(_http_status_error(503)) is True
    assert er.is_transient_error(_http_status_error(403)) is False


def test_classify_exception_adapter_error_respects_markers():
    # 已结构化：按 http_status 细分
    e = AdapterError("x", retryable=True, http_status=429, kind=er.KIND_QUOTA)
    assert er.classify_exception(e) == (er.TRANSIENT, er.KIND_QUOTA)
    # 无 http_status：沿用 retryable/kind 标记
    e2 = AdapterError("x", retryable=False, kind=er.KIND_REFUSAL)
    assert er.classify_exception(e2) == (er.PERMANENT, er.KIND_REFUSAL)
    assert er.is_transient_error(e2) is False


def test_classify_exception_unknown_is_permanent():
    """未知异常一律 permanent：不盲目重试，避免重复计费请求反复提交"""
    assert er.classify_exception(ValueError("boom")) == (er.PERMANENT, er.KIND_UNKNOWN)
    assert er.is_transient_error(ValueError("boom")) is False


# ---------- 结构化错误构造 ----------

def test_build_status_error_fields():
    err = er.build_status_error(429, "rate limited", context="chat")
    assert err.retryable is True
    assert err.http_status == 429
    assert err.kind == er.KIND_QUOTA
    assert err.error_code == "ADAPTER_QUOTA_ERROR"
    # message 保持「LLM 返回 HTTP {code}」前缀（流式探针前缀兼容契约）
    assert str(err).startswith("[chat] LLM 返回 HTTP 429")

    err2 = er.build_status_error(401, "Unauthorized")
    assert err2.retryable is False
    assert err2.kind == er.KIND_AUTH
    assert err2.error_code == "ADAPTER_AUTH_ERROR"
    assert str(err2).startswith("LLM 返回 HTTP 401")


def test_build_status_error_with_detail():
    err = er.build_status_error(500, "oops", context="chat", detail="已重试 2 次仍失败")
    assert err.kind == er.KIND_UPSTREAM
    assert err.retryable is True
    assert "已重试 2 次仍失败" in str(err)


def test_build_exception_error_fields():
    err = er.build_exception_error(httpx.ReadTimeout("timeout"), context="chat")
    assert err.retryable is True
    assert err.kind == er.KIND_TIMEOUT
    assert err.error_code == "ADAPTER_TIMEOUT_ERROR"
    assert "超时" in str(err)

    err2 = er.build_exception_error(httpx.ConnectError("refused"), context="chat")
    assert err2.retryable is True
    assert err2.kind == er.KIND_NETWORK
