"""上下文作用域取消令牌（端到端中断协议 · 跨切面基础设施）。

归属：本模块是 core / tools / adapters / web 共用的跨切面原语，下沉
utils/（与 stop_signal / provider_config_loader 同层），使各层单向依赖
utils 而非互相依赖（ARCHITECTURE_RULES §六：跨切面原语下沉 utils/）。

审核结论（取消令牌贯穿 adapters）：长工具调用（视频生成轮询可达
数十分钟）此前只能靠 task_manager 的 inflight 登记「事后告知」，
执行中不可协作式中断。引入 context-scoped cancellation token：

- agent_loop 在循环开始绑定本令牌（scope = stop_scope）；asyncio 任务
  与 asyncio.to_thread 都会拷贝 contextvars，FC 工具批 → tools →
  adapters 长任务全程无需显式传参即可经 current_cancel_token() 读到
  同一令牌（贯穿路径：run_agent_loop → llm_call → fc_tool_runner →
  generate_video 工具 → wait_until_complete 检查点）。
- cancelled 判定 = 显式 cancel() 或同 scope 的 stop_signal 标志命中：
  停止端点 request_stop(scope) 置标志后，长轮询的下一检查点立即
  协作退出（抛 GenerationCancelled），不必等 task.cancel() 硬取消先落。
- 纯 asyncio + contextvars 实现，不依赖 OS 信号/线程事件（Windows
  兼容：无 SIGTERM 语义依赖，无跨线程 Event 唤醒问题）。
- task_manager 的 inflight 登记保留为兜底：已提交到供应商侧、令牌
  也无法撤销的外部任务（提交成功后的远端生成）仍只登记 + 文案告知；
  令牌收敛的是「本进程内可中断的等待」，两者互补不是替代。

检查点协议（长任务实现方遵守）：轮询/重试循环每圈头部调
current_cancel_token() 判 cancelled，命中即抛 GenerationCancelled；
等待用 interruptible_sleep 替代 asyncio.sleep（切片睡 + 提前退出）。
"""
import asyncio
import time
from contextvars import ContextVar, Token
from typing import Optional

from src.video_agent.utils.stop_signal import is_stop_requested
from src.video_agent.exceptions import GenerationError

# 中断等待的切片粒度（秒）：睡够一片检查一次令牌，取消响应延迟有界
_CANCEL_SLEEP_SLICE = 0.5


class GenerationCancelled(GenerationError):
    """长生成任务被协作式取消（用户停止命中检查点）。

    语义：本进程内的等待已终止；供应商侧任务若已提交则可能仍在进行，
    由 web 层 inflight 登记兜底告知（第一版不撤销）。error_code 供
    前端区分「取消」与「失败」两种终态。
    """

    error_code = "GENERATION_CANCELLED"

    def __init__(self, message: str = "生成任务已被取消"):
        super().__init__(message)


class CancellationToken:
    """协作式取消令牌：作用域 = agent_loop 的 stop_scope。

    cancelled 双源合一：
    - 显式 cancel()（循环收尾/异常路径主动触发）；
    - 同 scope 停止标志（stop_signal.request_stop 置位）——停止端点
      置标志先于 task.cancel()，长任务检查点据此先于硬取消退出。
    """

    __slots__ = ("scope", "_cancelled")

    def __init__(self, scope: str = "chat"):
        self.scope = scope or "chat"
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    @property
    def cancelled(self) -> bool:
        return self._cancelled or is_stop_requested(self.scope)

    def check(self) -> None:
        """检查点：已取消时抛 GenerationCancelled（携带供应商侧提示）"""
        if self.cancelled:
            raise GenerationCancelled(
                "生成任务已被取消（供应商侧任务若已提交可能仍在进行，"
                "详见在途任务登记）"
            )


# 上下文作用域绑定：同一 asyncio 任务链（含 to_thread）共享同一令牌
_cancel_token_var: ContextVar[Optional[CancellationToken]] = ContextVar(
    "adapter_cancel_token", default=None,
)


def bind_cancel_token(token: CancellationToken) -> Token:
    """绑定令牌到当前上下文（agent_loop 循环开始调用），返回解绑凭证"""
    return _cancel_token_var.set(token)


def unbind_cancel_token(tk: Token) -> None:
    """解绑（agent_loop 各出口调用；异常路径 contextvar 随任务消亡兜底）"""
    try:
        _cancel_token_var.reset(tk)
    except (ValueError, LookupError):
        pass


def current_cancel_token() -> Optional[CancellationToken]:
    """当前上下文的取消令牌（未绑定返回 None：独立调用/测试路径不强制）"""
    return _cancel_token_var.get()


def check_cancelled() -> None:
    """便捷检查点：当前上下文令牌已取消时抛 GenerationCancelled；无令牌不抛"""
    tok = _cancel_token_var.get()
    if tok is not None:
        tok.check()


async def interruptible_sleep(
    seconds: float,
    token: Optional[CancellationToken] = None,
) -> bool:
    """可中断等待：切片睡眠，令牌取消时提前返回 False（协作式，不抛异常）。

    调用方在醒来后自行复检令牌决定退出路径——睡与判分离，
    检查点语义归调用方（与 asyncio.sleep 等价的替换点）。
    Windows 兼容：纯事件循环定时，无信号/线程事件依赖。
    """
    tok = token if token is not None else _cancel_token_var.get()
    if seconds <= 0:
        return not (tok is not None and tok.cancelled)
    deadline = time.monotonic() + seconds
    while True:
        if tok is not None and tok.cancelled:
            return False
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return True
        await asyncio.sleep(min(_CANCEL_SLEEP_SLICE, remaining))


__all__ = [
    "GenerationCancelled",
    "CancellationToken",
    "bind_cancel_token",
    "unbind_cancel_token",
    "current_cancel_token",
    "check_cancelled",
    "interruptible_sleep",
]
