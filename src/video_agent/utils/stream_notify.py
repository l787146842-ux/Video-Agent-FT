"""聊天链路实时状态通知（超时重试可视化）。

contextvar 绑定当前轮的「文本 → 前端状态栏」通道：chat_service 在轮开始时
绑定（把文本包成 SSE_STATUS 下发），Adapter 在等待上游响应与重试时刻调用
notify_stream(text)——首块产出前的漫长等待（最长 180s 超时 + 指数退避重试）
不再是静默无响应，用户实时看到"等待中/重试中"。

通知器签名是「文本 → 协程」，本模块不依赖 SSE 常量（保持 utils 底层纯净，
事件类型由绑定方负责包装）。未绑定时静默无操作（单测/CLI/无前端不受影响）。
"""
from loguru import logger
import contextvars
from typing import Awaitable, Callable, Optional

StreamNotifier = Callable[[str], Awaitable[None]]

_stream_notify_var: contextvars.ContextVar[Optional[StreamNotifier]] = contextvars.ContextVar(
    "stream_notifier", default=None
)


def bind_stream_notifier(notifier: Optional[StreamNotifier]):
    """绑定状态通知通道，返回解绑 token（与 unbind_stream_notifier 成对使用）。"""
    return _stream_notify_var.set(notifier)


def unbind_stream_notifier(token) -> None:
    """解绑状态通知通道。"""
    _stream_notify_var.reset(token)


async def notify_stream(text: str) -> None:
    """推送一条状态文案给前端（未绑定/空文案静默忽略，异常不阻断主链路）。"""
    notifier = _stream_notify_var.get()
    if notifier is None or not text:
        return
    try:
        await notifier(text)
    except Exception as _e:
        logger.debug("[stream_notify] 忽略异常: {}", _e)
