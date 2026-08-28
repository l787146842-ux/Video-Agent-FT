"""
画布拖放（对话栏图片 -> 画布节点）单元测试。

InfiniteCanvasBackend：MockTransport 重放夹具 + 协议层打桩。覆盖
add_image_node / add_nodes_batch（一次批量提交）/ update_node / delete_node /
get_selection / _resolve_drop_point / prepare_drop_image（无二次上传）。
"""
import json
from pathlib import Path

import pytest
import httpx
from unittest.mock import AsyncMock, patch

from src.video_agent.adapters.canvas_adapter import reset_canvas_adapter
from src.video_agent.adapters.infinite_canvas_backend import (
    InfiniteCanvasBackend,
    _resolve_drop_point,
)

FIXTURES = Path(__file__).parent.parent / "fixtures" / "infinite_canvas"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def _reset_singleton():
    reset_canvas_adapter()
    yield
    reset_canvas_adapter()


def _ic_backend_with_recorder():
    """MockTransport 重放夹具，并记录 /api/tools 请求体"""
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/tools":
            body = json.loads(request.content)
            calls.append(body)
            name = body.get("name") or ""
            if name == "canvas_apply_ops":
                op_type = ((body.get("input") or {}).get("ops") or [{}])[0].get("type", "")
                fx = f"tools/canvas_apply_ops_{op_type}.json"
            else:
                fx = f"tools/{name}.json"
            return httpx.Response(200, json=_load(fx)["response"])
        return httpx.Response(404, json={"ok": False, "error": "not found"})

    backend = InfiniteCanvasBackend(base_url="http://fixture.local", token="t", timeout=5)
    backend.client = lambda: httpx.AsyncClient(  # type: ignore[method-assign]
        base_url="http://fixture.local", transport=httpx.MockTransport(handler), timeout=5
    )
    return backend, calls


# update/delete 用的带节点状态（夹具 canvas_get_state 为空画布，此处协议层打桩）
_IC_STATE_WITH_NODES = {
    "projectId": "c1", "title": "测试画布", "hasCanvas": True,
    "nodes": [
        {"id": "img1", "type": "image", "title": "pic", "width": 320, "height": 320,
         "position": {"x": 10, "y": 20}, "metadata": {"content": "http://a/x.png"}},
        {"id": "txt1", "type": "text", "title": "note",
         "position": {"x": 400, "y": 20}, "metadata": {"content": "hello"}},
    ],
    "connections": [{"id": "conn1", "fromNodeId": "txt1", "toNodeId": "img1"}],
    "viewport": {"x": 0, "y": 0, "k": 1},
}


def _ic_backend_stubbed():
    """带节点状态的协议层打桩实例（_get_state/_apply_ops）"""
    backend = InfiniteCanvasBackend(base_url="http://fixture.local", token="t", timeout=5)
    backend._get_state = AsyncMock(return_value=json.loads(json.dumps(_IC_STATE_WITH_NODES)))  # type: ignore[method-assign]
    backend._apply_ops = AsyncMock(return_value=[])  # type: ignore[method-assign]
    return backend


class TestResolveDropPointInfinite:
    """落点换算：屏幕坐标 → 画布世界坐标"""

    def _state(self, viewport):
        return {"viewport": viewport}

    def test_no_drop_point_returns_viewport_center(self):
        wx, wy = _resolve_drop_point(self._state({"x": 0, "y": 0, "k": 1}), None, (1000, 600))
        assert (wx, wy) == (500, 300)

    def test_drop_point_with_shell_offset(self):
        wx, wy = _resolve_drop_point(self._state({"x": 0, "y": 0, "k": 1}), (596, 216), (1000, 600))
        assert (wx, wy) == (500, 200)

    def test_scale_and_viewport(self):
        wx, wy = _resolve_drop_point(self._state({"x": 100, "y": 50, "k": 2}), (496, 266), (1000, 600))
        assert wx == (496 - 96 - 100) / 2
        assert wy == (266 - 16 - 50) / 2

    def test_out_of_view_clamped(self):
        wx, wy = _resolve_drop_point(self._state({"x": 0, "y": 0, "k": 1}), (-5000, 99999), (1000, 600))
        assert 80 <= wx <= 920
        assert 80 <= wy <= 520

    def test_zero_k_falls_back_to_one(self):
        wx, wy = _resolve_drop_point(self._state({"x": 0, "y": 0, "k": 0}), None, (1000, 600))
        assert (wx, wy) == (500, 300)


class TestInfiniteCanvasDrop:
    @pytest.mark.asyncio
    async def test_add_image_node_emits_add_op(self):
        """拖放图片：单条 add_node op 直发，URL 绝对化存 metadata.content"""
        backend, calls = _ic_backend_with_recorder()
        result = await backend.add_image_node(
            _load("tools/canvas_get_state.json")["response"]["result"]["projectId"],
            image={"url": "/workspace/assets/x.png", "name": "x.png", "kind": "image"},
            view_size=(1000, 600),
        )
        assert result["canvas_id"]
        assert result["node_id"]
        apply_calls = [c for c in calls if c["name"] == "canvas_apply_ops"]
        assert len(apply_calls) == 1
        op = apply_calls[0]["input"]["ops"][0]
        assert op["type"] == "add_node"
        assert op["nodeType"] == "image"
        url = op["metadata"]["content"]
        assert url.startswith("http") and url.endswith("/workspace/assets/x.png")

    @pytest.mark.asyncio
    async def test_add_nodes_batch_single_apply_call(self):
        """批量追加：一次 canvas_apply_ops 提交全部 add_node op"""
        backend, calls = _ic_backend_with_recorder()
        nodes = [
            {"id": f"b{i}", "type": "smart-image", "title": f"图{i}",
             "x": 100 + (i % 4) * 400, "y": 100 + (i // 4) * 300,
             "images": [{"url": f"http://a/{i}.png", "name": f"{i}.png"}]}
            for i in range(3)
        ]
        ids = await backend.add_nodes_batch("", nodes=nodes)
        assert ids == ["b0", "b1", "b2"]
        apply_calls = [c for c in calls if c["name"] == "canvas_apply_ops"]
        assert len(apply_calls) == 1  # 一次批量提交（≤ APPLY_OPS_BATCH_SIZE）
        ops = apply_calls[0]["input"]["ops"]
        assert [o["type"] for o in ops] == ["add_node"] * 3
        assert ops[2]["position"] == {"x": 100 + (2 % 4) * 400, "y": 100 + (2 // 4) * 300}

    @pytest.mark.asyncio
    async def test_update_node_existing_emits_update_op(self):
        backend = _ic_backend_stubbed()
        ok = await backend.update_node(
            "c1", node_id="img1",
            patch={"title": "新图", "x": 100, "y": None, "prompt": None,
                   "image_url": "/workspace/assets/new.png", "content": None},
        )
        assert ok is True
        ops = backend._apply_ops.call_args[0][0]
        assert len(ops) == 1
        op = ops[0]
        assert op["type"] == "update_node" and op["id"] == "img1"
        assert op["patch"]["position"] == {"x": 100.0, "y": 20.0}  # y 未传，保持原值
        assert op["patch"]["title"] == "新图"
        assert op["metadata"]["content"].endswith("/workspace/assets/new.png")

    @pytest.mark.asyncio
    async def test_update_node_text_content(self):
        backend = _ic_backend_stubbed()
        ok = await backend.update_node(
            "c1", node_id="txt1",
            patch={"title": None, "x": None, "y": None, "prompt": "新提示词",
                   "image_url": None, "content": None},
        )
        assert ok is True
        op = backend._apply_ops.call_args[0][0][0]
        assert op["metadata"]["content"] == "新提示词"
        assert "title" not in op["patch"]

    @pytest.mark.asyncio
    async def test_update_node_missing_returns_false(self):
        backend = _ic_backend_stubbed()
        ok = await backend.update_node("c1", node_id="ghost", patch={"title": "x"})
        assert ok is False
        backend._apply_ops.assert_not_called()

    @pytest.mark.asyncio
    async def test_delete_node_cleans_connections(self):
        backend = _ic_backend_stubbed()
        ok = await backend.delete_node("c1", node_id="txt1")
        assert ok is True
        ops = backend._apply_ops.call_args[0][0]
        assert ops[0] == {"type": "delete_node", "ids": ["txt1"]}
        assert ops[1] == {"type": "delete_connections", "ids": ["conn1"]}

    @pytest.mark.asyncio
    async def test_delete_node_missing_returns_false(self):
        backend = _ic_backend_stubbed()
        assert await backend.delete_node("c1", node_id="ghost") is False
        backend._apply_ops.assert_not_called()

    @pytest.mark.asyncio
    async def test_add_node_single_op(self):
        backend = _ic_backend_stubbed()
        result = await backend.add_node(
            "c1",
            node={"id": "txt-new", "type": "text", "title": "T", "x": 10, "y": 20, "content": "hi"},
        )
        assert result == {"node_id": "txt-new", "canvas_id": "c1"}
        op = backend._apply_ops.call_args[0][0][0]
        assert op["type"] == "add_node"
        assert op["nodeType"] == "text"
        assert op["metadata"]["content"] == "hi"

    @pytest.mark.asyncio
    async def test_get_selection_replay(self):
        backend, _ = _ic_backend_with_recorder()
        sel = await backend.get_selection()
        assert sel["supported"] is True
        assert sel["nodes"] == _load("tools/canvas_get_selection.json")["response"]["result"]["nodes"]

    @pytest.mark.asyncio
    async def test_select_nodes_replay(self):
        """反向选中：canvas_select_nodes 工具调用，空列表短路不发请求"""
        backend, calls = _ic_backend_with_recorder()
        out = await backend.select_nodes(["n1", "n2"])
        assert out == {"supported": True, "selected": 2}
        assert calls[-1] == {"name": "canvas_select_nodes", "input": {"ids": ["n1", "n2"]}}
        empty = await backend.select_nodes([])
        assert empty == {"supported": True, "selected": 0}
        assert len(calls) == 1  # 空列表未发新请求

    @pytest.mark.asyncio
    async def test_find_active_canvas_current_page(self):
        backend, _ = _ic_backend_with_recorder()
        active = await backend.find_active_canvas()
        assert active is not None
        assert active["id"] == _load("tools/canvas_get_state.json")["response"]["result"]["projectId"]


class TestPrepareDropImageInfinite:
    """拖放物化：直接引用本站绝对 URL，无二次上传"""

    @pytest.mark.asyncio
    async def test_external_url_passthrough(self):
        backend = InfiniteCanvasBackend(base_url="http://fixture.local", token="t", timeout=5)
        out = await backend.prepare_drop_image(
            url="https://example.com/a.png", name="a.png",
            local_path=None, mime="image/png", public_base="http://testserver/",
        )
        assert out["url"] == "https://example.com/a.png"

    @pytest.mark.asyncio
    async def test_local_asset_referenced_without_upload(self, tmp_path):
        backend = InfiniteCanvasBackend(base_url="http://fixture.local", token="t", timeout=5)
        f = tmp_path / "gen-1.png"
        f.write_bytes(b"\x89PNG-fake")
        with patch.object(
            InfiniteCanvasBackend, "upload_files", new_callable=AsyncMock
        ) as up:
            out = await backend.prepare_drop_image(
                url="/workspace/assets/gen-1.png", name="gen-1.png",
                local_path=f, mime="image/png", public_base="http://testserver/",
            )
        up.assert_not_called()  # 无二次上传：节点直接引用素材绝对 URL
        assert out["url"] == "http://testserver/workspace/assets/gen-1.png"
