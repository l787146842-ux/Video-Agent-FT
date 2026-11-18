# -*- coding: utf-8 -*-
"""进程内画布会话（L2 替代 canvas-agent）单元测试。

覆盖：连接/快照缓存、读工具直读、高层工具→canvas_apply_ops 翻译、
回执解析、超时与断连错误面。无需浏览器，全部在进程内完成。
"""
import asyncio

import pytest

import src.video_agent.adapters.canvas_agent_session as mod
from src.video_agent.adapters.canvas_agent_session import (
    AGENT_PROTOCOL_VERSION,
    CanvasAgentSession,
)
from src.video_agent.exceptions import AdapterError

STATE = {
    "projectId": "p1",
    "title": "测试画布",
    "nodes": [
        {"id": "n1", "type": "image", "title": "图1", "position": {"x": 0, "y": 0},
         "width": 100, "height": 100, "metadata": {"content": "http://x/a.png"}},
        {"id": "n2", "type": "text", "title": "文", "position": {"x": 200, "y": 0},
         "width": 100, "height": 100, "metadata": {"content": "长" * 400}},
    ],
    "connections": [],
    "selectedNodeIds": ["n2"],
    "viewport": {"x": 0, "y": 0, "k": 1},
}


def _connected_session():
    session = CanvasAgentSession()
    queue = session.connect("c1")
    session.update_state("c1", {**STATE, "hasCanvas": True})
    return session, queue


@pytest.mark.asyncio
async def test_hello_pins_protocol_version():
    session = CanvasAgentSession()
    hello = session.hello("c1")
    assert hello["protocolVersion"] == AGENT_PROTOCOL_VERSION
    assert hello["codex"]["busy"] is False


@pytest.mark.asyncio
async def test_call_tool_without_client_raises():
    session = CanvasAgentSession()
    with pytest.raises(AdapterError, match="没有已连接画布"):
        await session.call_tool("canvas_apply_ops", {"ops": []})


@pytest.mark.asyncio
async def test_get_state_compacts_long_content():
    session, _ = _connected_session()
    state = await session.call_tool("canvas_get_state")
    assert [n["id"] for n in state["nodes"]] == ["n1", "n2"]
    assert state["nodes"][1]["metadata"]["content"].endswith("...")
    assert len(state["nodes"][1]["metadata"]["content"]) < 400


@pytest.mark.asyncio
async def test_get_selection_filters_by_selected_ids():
    session, _ = _connected_session()
    selection = await session.call_tool("canvas_get_selection")
    assert [n["id"] for n in selection["nodes"]] == ["n2"]


@pytest.mark.asyncio
async def test_group_nodes_translated_to_apply_ops():
    session, queue = _connected_session()
    task = asyncio.create_task(session.call_tool("canvas_group_nodes", {"ids": ["n1", "n2"]}))
    event, payload = await asyncio.wait_for(queue.get(), 1)
    assert event == "tool_call"
    assert payload["name"] == "canvas_apply_ops"
    assert payload["input"]["ops"] == [{"type": "group_nodes", "ids": ["n1", "n2"]}]

    assert session.resolve("c1", {"requestId": payload["requestId"], "result": {"ok": True}})
    assert await task == {"ok": True}


@pytest.mark.asyncio
async def test_generate_image_builds_text_config_flow():
    session, queue = _connected_session()
    task = asyncio.create_task(
        session.call_tool("canvas_generate_image", {"prompt": "风景", "autoRun": True})
    )
    _, payload = await asyncio.wait_for(queue.get(), 1)
    ops = payload["input"]["ops"]
    kinds = [op["type"] for op in ops]
    assert kinds[:3] == ["add_node", "add_node", "connect_nodes"]
    assert ops[0]["nodeType"] == "text"
    assert ops[1]["nodeType"] == "config"
    assert ops[1]["metadata"]["generationMode"] == "image"
    assert kinds[-2:] == ["select_nodes", "run_generation"]

    session.resolve("c1", {"requestId": payload["requestId"], "result": {"ok": True}})
    await task


@pytest.mark.asyncio
async def test_site_tool_passes_through_untranslated():
    session, queue = _connected_session()
    task = asyncio.create_task(session.call_tool("canvas_list_projects", {"page": 1}))
    _, payload = await asyncio.wait_for(queue.get(), 1)
    assert payload["name"] == "canvas_list_projects"
    session.resolve("c1", {"requestId": payload["requestId"], "result": {"items": []}})
    assert await task == {"items": []}


@pytest.mark.asyncio
async def test_timeout_raises_adapter_error(monkeypatch):
    monkeypatch.setattr(mod, "TOOL_TIMEOUT_SECONDS", 0.05)
    session, _ = _connected_session()
    with pytest.raises(AdapterError, match="超时"):
        await session.call_tool("canvas_apply_ops", {"ops": []})


@pytest.mark.asyncio
async def test_disconnect_rejects_pending_call():
    session, _ = _connected_session()
    task = asyncio.create_task(session.call_tool("canvas_apply_ops", {"ops": []}))
    await asyncio.sleep(0.01)
    session.disconnect("c1")
    with pytest.raises(AdapterError, match="页面已断开"):
        await task


@pytest.mark.asyncio
async def test_unknown_tool_fails_closed():
    session, _ = _connected_session()
    with pytest.raises(AdapterError, match="未实现"):
        await session.call_tool("canvas_create_attachment_nodes", {"attachmentIds": ["a"]})
