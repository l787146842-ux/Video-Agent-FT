"""上下文作用域取消令牌语义钉死（任务 #10 取消令牌贯穿 adapters）。

钉死：
1. cancelled 双源合一：显式 cancel() 或同 scope 停止标志命中；
2. contextvar 绑定/解绑（无令牌路径不强制，check_cancelled 不抛）；
3. interruptible_sleep 取消命中提前返回（不睡满全窗口）；
4. wait_until_complete 检查点：圈头命中即抛 GenerationCancelled，
   轮询中途取消有界响应（不空转到超时）。
"""
import asyncio
import time

import pytest

from src.video_agent.adapters import cancel_token as ct
from src.video_agent.adapters.base import VideoGenerationResponse
from src.video_agent.adapters.factory import wait_until_complete
from src.video_agent.core.stop_signal import clear_stop, request_stop


def test_token_explicit_cancel():
    tok = ct.CancellationToken(scope="ct-scope-1")
    assert not tok.cancelled
    tok.cancel()
    assert tok.cancelled


def test_token_observes_stop_signal():
    """停止端点 request_stop 置标志后，同 scope 令牌立即视为已取消"""
    scope = "ct-scope-2"
    tok = ct.CancellationToken(scope=scope)
    assert not tok.cancelled
    request_stop(scope)
    try:
        assert tok.cancelled
        with pytest.raises(ct.GenerationCancelled):
            tok.check()
    finally:
        clear_stop(scope)


def test_check_silent_when_not_cancelled():
    ct.CancellationToken(scope="ct-scope-3").check()  # 不抛


def test_token_created_after_stop_request_immediately_cancelled():
    """边界固化：父（停止端点）先置停止标志、子令牌晚注册——
    cancelled 实时读标志表而非注册时快照，迟到的令牌创建即命中，
    不存在「取消早于注册」的观察窗口漏报"""
    scope = "ct-scope-late"
    request_stop(scope)
    try:
        tok = ct.CancellationToken(scope=scope)
        assert tok.cancelled
        with pytest.raises(ct.GenerationCancelled):
            tok.check()
    finally:
        clear_stop(scope)


async def test_wait_until_complete_token_bound_after_stop_request():
    """同边界的轮询链路形态：停止标志先于令牌绑定存在，
    绑定后首次圈头检查即抛，不空转"""
    scope = "ct-scope-late-bind"
    request_stop(scope)
    try:
        tok = ct.CancellationToken(scope=scope)
        tk = ct.bind_cancel_token(tok)
        adapter = _ProcessingAdapter()
        try:
            with pytest.raises(ct.GenerationCancelled):
                await wait_until_complete(adapter, "task-late", timeout=30)
            assert adapter.polls == 0
        finally:
            ct.unbind_cancel_token(tk)
    finally:
        clear_stop(scope)


def test_bind_current_unbind_roundtrip():
    assert ct.current_cancel_token() is None
    tok = ct.CancellationToken(scope="ct-scope-4")
    tk = ct.bind_cancel_token(tok)
    try:
        assert ct.current_cancel_token() is tok
        ct.check_cancelled()  # 未取消：不抛
    finally:
        ct.unbind_cancel_token(tk)
    assert ct.current_cancel_token() is None


def test_check_cancelled_noop_without_token():
    ct.check_cancelled()  # 未绑定令牌：独立调用路径不强制


async def test_interruptible_sleep_full_duration():
    assert await ct.interruptible_sleep(0.05) is True


async def test_interruptible_sleep_early_exit_on_cancel():
    tok = ct.CancellationToken(scope="ct-scope-5")

    async def cancel_later():
        await asyncio.sleep(0.2)
        tok.cancel()

    task = asyncio.create_task(cancel_later())
    t0 = time.monotonic()
    ok = await ct.interruptible_sleep(30.0, tok)
    elapsed = time.monotonic() - t0
    await task
    assert ok is False
    assert elapsed < 5.0  # 取消响应有界，不睡满 30s


class _ProcessingAdapter:
    def __init__(self):
        self.polls = 0

    async def fetch_result(self, task_id):
        self.polls += 1
        return VideoGenerationResponse(task_id=task_id, status="processing")


class _CompletedAdapter:
    async def fetch_result(self, task_id):
        return VideoGenerationResponse(
            task_id=task_id, status="completed", video_url="/workspace/assets/x.mp4")


async def test_wait_until_complete_cancelled_before_first_poll():
    tok = ct.CancellationToken(scope="ct-scope-6")
    tok.cancel()
    tk = ct.bind_cancel_token(tok)
    adapter = _ProcessingAdapter()
    try:
        with pytest.raises(ct.GenerationCancelled):
            await wait_until_complete(adapter, "task-1", timeout=30)
        assert adapter.polls == 0  # 圈头检查点先于轮询生效
    finally:
        ct.unbind_cancel_token(tk)


async def test_wait_until_complete_cancelled_mid_polling():
    """轮询中途取消：有界响应退出，不空转到超时"""
    tok = ct.CancellationToken(scope="ct-scope-7")
    tk = ct.bind_cancel_token(tok)
    adapter = _ProcessingAdapter()

    async def cancel_later():
        await asyncio.sleep(0.3)
        tok.cancel()

    task = asyncio.create_task(cancel_later())
    try:
        t0 = time.monotonic()
        with pytest.raises(ct.GenerationCancelled):
            await wait_until_complete(adapter, "task-2", timeout=120)
        assert time.monotonic() - t0 < 10.0
        assert adapter.polls >= 1
    finally:
        await task
        ct.unbind_cancel_token(tk)


async def test_wait_until_complete_stop_signal_reaches_token():
    """停止端点置同 scope 标志 → 令牌观察命中 → 轮询协作退出"""
    scope = "ct-scope-8"
    tok = ct.CancellationToken(scope=scope)
    tk = ct.bind_cancel_token(tok)
    request_stop(scope)
    try:
        with pytest.raises(ct.GenerationCancelled):
            await wait_until_complete(_ProcessingAdapter(), "task-3", timeout=30)
    finally:
        clear_stop(scope)
        ct.unbind_cancel_token(tk)


async def test_wait_until_complete_normal_path_without_token():
    """未绑定令牌的独立调用路径：行为不回退，照常拿结果"""
    res = await wait_until_complete(_CompletedAdapter(), "task-4", timeout=5)
    assert res.status == "completed"
