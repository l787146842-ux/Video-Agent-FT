"""执行器进度上报（M6）：contextvar 绑定/解绑 + ETA 文案"""
import asyncio

from src.video_agent.skill_runtime.progress import (
    bind_progress_emitter, emit_progress, format_eta, unbind_progress_emitter,
)


def test_emit_progress_noop_without_binding():
    """未绑定事件通道时静默无操作（单测/CLI 场景不受影响）"""
    asyncio.run(emit_progress("任意文案"))  # 不抛异常即通过


def test_emit_progress_forwards_bound_event():
    events = []

    async def on_event(ev):
        events.append(ev)

    async def run():
        token = bind_progress_emitter(on_event)
        try:
            await emit_progress("第 1/3 批")
        finally:
            unbind_progress_emitter(token)

    asyncio.run(run())
    assert events == [{"type": "status", "text": "第 1/3 批"}]


def test_format_eta():
    assert format_eta(30) == "约 30 秒"
    assert format_eta(120) == "约 2 分钟"
    assert format_eta(150) == "约 2 分 30 秒"
    assert format_eta(-5) == "约 0 秒"
