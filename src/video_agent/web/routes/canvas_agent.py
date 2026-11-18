"""画布 agent 协议端点（L2：本进程直接充当 canvas-agent）。

对端画布页以 EventSource 连接 /events，收 tool_call 执行后 POST /canvas/result
回传；本模块只做协议出入口，工具语义与快照缓存归 adapters.canvas_agent_session。
"""
from __future__ import annotations

import asyncio
import json
import secrets
import time
from typing import Any, AsyncIterator

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from loguru import logger

from src.video_agent.adapters.canvas_agent_session import (
    AGENT_PROTOCOL_VERSION,
    LOCAL_AGENT_TOKEN,
    agent_token_authorized,
    get_canvas_agent_session,
)

router = APIRouter()
_PING_SECONDS = 15.0


def _sse(event: str, payload: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _authorized(token: str) -> bool:
    return agent_token_authorized(token)


def _unauthorized() -> JSONResponse:
    return JSONResponse(status_code=401, content={"ok": False, "error": "token 无效"})


@router.get("/health", include_in_schema=False)
async def health():
    return get_canvas_agent_session().health()


@router.get("/config", include_in_schema=False)
async def config(request: Request):
    """画布页 discoverAgentConfig 探活入口（url 必须是绝对地址，画布侧会 new URL 校验）。"""
    origin = str(request.base_url).rstrip("/")
    return {
        "ok": True,
        "protocolVersion": AGENT_PROTOCOL_VERSION,
        "url": f"{origin}/api/canvas/agent",
        "token": LOCAL_AGENT_TOKEN,
        "hasToken": True,
    }


@router.get("/events", include_in_schema=False)
async def events(request: Request, token: str = Query(""), clientId: str = Query("")):
    if not _authorized(token):
        return _unauthorized()
    session = get_canvas_agent_session()
    client_id = clientId or secrets.token_hex(8)
    queue = session.connect(client_id)

    async def stream() -> AsyncIterator[str]:
        try:
            yield _sse("hello", session.hello(client_id))
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event, payload = await asyncio.wait_for(queue.get(), timeout=_PING_SECONDS)
                except asyncio.TimeoutError:
                    yield _sse("ping", {"time": int(time.time() * 1000)})
                    continue
                yield _sse(event, payload)
        except asyncio.CancelledError:
            raise
        finally:
            session.disconnect(client_id)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/canvas/state", include_in_schema=False)
async def post_state(request: Request, token: str = Query(""), clientId: str = Query("")):
    if not _authorized(token):
        return _unauthorized()
    try:
        body = await request.json()
    except ValueError:
        body = {}
    get_canvas_agent_session().update_state(clientId, body)
    return {"ok": True}


@router.post("/canvas/activate", include_in_schema=False)
async def activate(token: str = Query(""), clientId: str = Query("")):
    if not _authorized(token):
        return _unauthorized()
    get_canvas_agent_session().activate(clientId)
    return {"ok": True}


@router.post("/canvas/result", include_in_schema=False)
async def post_result(request: Request, token: str = Query(""), clientId: str = Query("")):
    if not _authorized(token):
        return _unauthorized()
    try:
        body = await request.json()
    except ValueError:
        body = {}
    resolved = get_canvas_agent_session().resolve(clientId, body if isinstance(body, dict) else {})
    if not resolved:
        logger.warning(f"[CanvasAgent] 丢弃未知或越权的工具回执: client={clientId}")
    return {"ok": resolved}


@router.post("/agent/codex/threads/reset", include_in_schema=False)
async def codex_threads_reset():
    """画布页连上后会做一次 Codex 会话重置探测；本项目无 Codex，返回空会话即停。"""
    return {
        "ok": True,
        "workspace": {"activeThreadId": ""},
        "conversation": {
            "revision": 1,
            "conversationId": "",
            "threadId": "",
            "status": "idle",
            "mcpStatuses": {},
        },
    }
