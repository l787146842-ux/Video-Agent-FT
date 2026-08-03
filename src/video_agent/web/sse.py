"""
SSE 事件推送（从 chat_service.py 拆分，修复计划书 P1-6）。

职责：从 asyncio.Queue 消费事件并编码为 SSE 帧，检测客户端断连、
空闲心跳防代理切断、结束时取消后台 worker task。
"""
import asyncio
import json
from typing import AsyncGenerator

from fastapi import Request
from loguru import logger


async def sse_event_generator(queue: asyncio.Queue, task: asyncio.Task, request: Request) -> AsyncGenerator[str, None]:
    """SSE 事件生成器：从队列消费事件，检测客户端断连。

    空闲 15s 发送一次注释行心跳（`: heartbeat`），防止反向代理/浏览器在
    LLM 长时间无 delta 输出时静默切断连接（generate/workflow SSE 均有心跳，此处对齐）。
    """
    HEARTBEAT_AFTER = 15  # 秒
    idle_secs = 0
    try:
        while True:
            if await request.is_disconnected():
                logger.info("[SSE] 客户端已断开，终止流式响应")
                break
            try:
                event = await asyncio.wait_for(queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                idle_secs += 1
                if idle_secs >= HEARTBEAT_AFTER:
                    idle_secs = 0
                    yield ": heartbeat\n\n"
                continue
            idle_secs = 0
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            if event.get("type") in ("done", "error"):
                break
    finally:
        if not task.done():
            task.cancel()
            logger.debug("[SSE] worker task 已取消")
