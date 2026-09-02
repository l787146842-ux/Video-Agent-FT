"""错误翻译域。

上游错误人话翻译（friendly/raw 分层）+ 流式失败统一出口（持久化错误消息 +
发 error 事件）。消费方（chat_service 内部调用 _emit_stream_error、tests）直连本模块；
原 chat_service 尾部 re-export 承重壳已随批次E收敛删除（2026-09-02）。
"""
import re
from typing import Tuple

from src.video_agent.core.sse_events import SSE_ERROR
from src.video_agent.web.error_payload import classify_exception
from src.video_agent.web.stop_manager import retry_suggestion_if_user

__all__ = ["_emit_stream_error", "_friendly_stream_error"]


async def _emit_stream_error(svc, body, e: Exception, emit, use_studio_context: bool) -> None:
    """流式失败统一出口：持久化错误消息 + 发 error 事件。

    错误分层——气泡只展示一句人话（friendly），
    上游原始报文（raw）随 errorDetail 持久化 + payload raw 下发，前端折叠展示。
    """
    friendly, raw = _friendly_stream_error(e)
    # 结构化归类（kind/code）随事件下发，前端按映射表做动作，不再猜文案
    payload = classify_exception(e, message=friendly, raw=raw)
    if use_studio_context:
        async with svc.lock:
            # 错误前缀统一为 ⚠️（与前端 streamError 渲染一致，刷新后不跳变）；
            # 「继续刚才的任务」建议随错误消息落盘（刷新后可重建）
            svc.add_chat_message(
                "agent", f"⚠️ {friendly}", model_name=body.model or "",
                error_detail=raw,
                suggested_actions=retry_suggestion_if_user(svc),
            )
    await emit({
        "type": SSE_ERROR, "detail": friendly, "raw": raw,
        "error_code": getattr(e, "error_code", "INTERNAL_ERROR"),
        **payload.sse_fields(),
    })


def _friendly_stream_error(e: Exception) -> Tuple[str, str]:
    """上游错误人话翻译（反馈：裸 JSON 报错看不懂）。

    返回 (friendly, raw)：friendly = 一句可操作的人话；
    raw = 上游原始报文（未命中翻译时为空串，前端不渲染技术详情折叠）。
    """
    msg = str(e)
    if "insufficient_user_quota" in msg or "预扣费" in msg:
        m_remain = re.search(r"剩余额度[:：]\s*＄?\$?([\d.]+)", msg)
        m_need = re.search(r"需要预扣费额度[:：]\s*＄?\$?([\d.]+)", msg)
        detail = ""
        if m_remain and m_need:
            detail = f"（账户剩余 ${m_remain.group(1)}，本次需预扣 ${m_need.group(1)}）"
        return (
            f"上游供应商账户额度不足{detail}，无法预扣本次调用费用——这不是上下文超限。"
            "上下文越长预扣越高，故常在任务后半程触发。"
            "请为上游账户充值，或在 API 设置页切换其他供应商/模型后重试。",
            msg,
        )
    status = getattr(e, "http_status", None)
    # 中继拒收通知单（slow 队列等）优先翻译——须在 401/403 鉴权分支前，
    # 否则 403 被误译为「Key 过期」；裁决：不自动换模型，只提示手动
    low = msg.lower()
    if "10605" in msg or "queuetype" in low or "中继拒收通知单" in msg:
        return (
            "上游排队拒收（slow 队列瞬时不接客）：非 Key 或上下文问题。"
            "请稍后重试；如需可在选择器手动切换其他模型号再发。",
            msg,
        )
    if status in (401, 403):
        return (
            f"鉴权失败（HTTP {status}）：API Key 未配置、已过期或不正确。"
            "请到 API 设置页检查对应供应商的 Key 后重试。",
            msg,
        )
    if status == 429:
        return (
            "上游供应商限流或配额不足（HTTP 429）。请稍后重试，或切换其他供应商/模型。",
            msg,
        )
    if isinstance(status, int) and 500 <= status < 600:
        return (
            f"上游供应商瞬时故障（HTTP {status}）。请稍后重试；"
            "如需可在选择器手动切换其他供应商/模型。",
            msg,
        )
    low = msg.lower()
    if "timeout" in low or "timed out" in low or "connect" in low:
        return (
            "上游供应商连接超时或失败。请检查网络，或切换其他供应商/模型后重试。",
            msg,
        )
    return msg, ""
