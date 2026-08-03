# -*- coding: utf-8 -*-
"""画布（熊布）API 契约测试（修复计划书 P1-4）。

背景：CanvasAdapter 硬编码了熊布内部 schema（smart-image 的 images[]、viewport、
乐观锁 base_updated_at 等）。熊布是快速迭代的第三方项目，schema 漂移会让本项目
静默产生坏数据。本测试用录制的真实响应夹具（tests/fixtures/canvas/）守住契约：

- 夹具结构断言：adapter 依赖的字段必须存在且类型正确；
- adapter 读路径：用 httpx.MockTransport 重放夹具，验证解析逻辑；
- 写前校验：真实夹具节点必须能通过 _validate_write_payload，坏数据必须被拦截。

夹具刷新：对接新版熊布后，重新录制 GET /api/app-info、/api/canvases、
/api/canvases/{id}（智能画布）到 tests/fixtures/canvas/，diff 即风险清单。
本测试不需要熊布在线。
"""
import json
from pathlib import Path

import httpx
import pytest

from src.video_agent.adapters.canvas_adapter import (
    CanvasAdapter,
    _validate_write_payload,
)
from src.video_agent.exceptions import AdapterError

FIXTURES = Path(__file__).parent.parent / "fixtures" / "canvas"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def canvases_list() -> dict:
    return _load("canvases_list.json")


@pytest.fixture(scope="module")
def canvas_detail() -> dict:
    return _load("canvas_detail_smart.json")


@pytest.fixture(scope="module")
def app_info() -> dict:
    return _load("app_info.json")


# ---------- 夹具结构契约 ----------

class TestFixtureContract:
    """adapter 依赖的响应字段必须在真实夹具中存在"""

    def test_app_info_has_version(self, app_info):
        assert isinstance(app_info.get("version"), str) and app_info["version"]

    def test_canvases_list_fields(self, canvases_list):
        items = canvases_list.get("canvases")
        assert isinstance(items, list) and items, "夹具应至少含一个画布"
        # find_active_smart_canvas / find_active_canvas / routes 依赖的字段
        for c in items:
            for field in ("id", "title", "kind", "updated_at", "deleted_at"):
                assert field in c, f"画布列表项缺少字段: {field}"

    def test_canvas_detail_wrapper_and_fields(self, canvas_detail):
        # get_canvas 依赖 {"canvas": {...}} 包装层
        assert "canvas" in canvas_detail, "画布详情缺少 canvas 包装层"
        canvas = canvas_detail["canvas"]
        for field in ("id", "title", "nodes", "connections", "viewport", "updated_at"):
            assert field in canvas, f"画布详情缺少字段: {field}"
        assert isinstance(canvas["nodes"], list)
        assert isinstance(canvas["connections"], list)

    def test_viewport_schema(self, canvas_detail):
        viewport = canvas_detail["canvas"]["viewport"]
        for key in ("x", "y", "scale"):
            assert isinstance(viewport.get(key), (int, float)), f"viewport.{key} 应为数值"
        assert viewport["scale"] > 0

    def test_smart_image_node_schema(self, canvas_detail):
        nodes = canvas_detail["canvas"]["nodes"]
        smart = [n for n in nodes if n.get("type") == "smart-image"]
        assert smart, "夹具应至少含一个 smart-image 节点"
        for n in smart:
            # adapter 写入路径硬编码依赖的字段
            for field in ("id", "type", "x", "y", "scale", "images"):
                assert field in n, f"smart-image 节点缺少字段: {field}"
            assert isinstance(n["images"], list) and n["images"]
            for img in n["images"]:
                assert img.get("url"), "smart-image images[] 项缺少 url"


# ---------- adapter 读路径（MockTransport 重放夹具） ----------

def _adapter_with_fixtures(canvases_list: dict, canvas_detail: dict, app_info: dict) -> CanvasAdapter:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/canvases":
            return httpx.Response(200, json=canvases_list)
        if path.startswith("/api/canvases/"):
            return httpx.Response(200, json=canvas_detail)
        if path == "/api/app-info":
            return httpx.Response(200, json=app_info)
        return httpx.Response(404, json={"detail": "not found"})

    adapter = CanvasAdapter(base_url="http://fixture.local", timeout=5)
    adapter._client = lambda: httpx.AsyncClient(  # type: ignore[method-assign]
        base_url="http://fixture.local", transport=httpx.MockTransport(handler), timeout=5
    )
    return adapter


class TestAdapterReadPaths:
    @pytest.mark.asyncio
    async def test_list_canvases_parsing(self, canvases_list, canvas_detail, app_info):
        adapter = _adapter_with_fixtures(canvases_list, canvas_detail, app_info)
        canvases = await adapter.list_canvases()
        assert len(canvases) == len(canvases_list["canvases"])
        assert all("id" in c for c in canvases)

    @pytest.mark.asyncio
    async def test_get_canvas_unwraps_canvas_key(self, canvases_list, canvas_detail, app_info):
        adapter = _adapter_with_fixtures(canvases_list, canvas_detail, app_info)
        canvas = await adapter.get_canvas("any-id")
        assert "nodes" in canvas and "viewport" in canvas

    @pytest.mark.asyncio
    async def test_find_active_smart_canvas(self, canvases_list, canvas_detail, app_info):
        adapter = _adapter_with_fixtures(canvases_list, canvas_detail, app_info)
        active = await adapter.find_active_smart_canvas()
        expected = [
            c for c in canvases_list["canvases"]
            if not c.get("deleted_at") and str(c.get("kind") or "").strip().lower() == "smart"
        ]
        if expected:
            assert active is not None
            assert active["id"] == max(expected, key=lambda c: int(c.get("updated_at") or 0))["id"]
        else:
            assert active is None

    @pytest.mark.asyncio
    async def test_get_app_info_version(self, canvases_list, canvas_detail, app_info):
        adapter = _adapter_with_fixtures(canvases_list, canvas_detail, app_info)
        info = await adapter.get_app_info()
        assert info["version"] == app_info["version"]


# ---------- 写前校验（P1-5） ----------

class TestWriteValidation:
    def test_real_fixture_nodes_pass(self, canvas_detail):
        canvas = canvas_detail["canvas"]
        # 真实熊布数据必须能通过写前校验（否则说明校验规则与现网 schema 漂移）
        _validate_write_payload(canvas["nodes"], canvas["connections"], canvas["viewport"])

    def test_smart_image_without_images_rejected(self):
        with pytest.raises(AdapterError, match="images"):
            _validate_write_payload(
                [{"id": "n1", "type": "smart-image", "images": []}], [], {}
            )

    def test_smart_image_item_without_url_rejected(self):
        with pytest.raises(AdapterError, match="url"):
            _validate_write_payload(
                [{"id": "n1", "type": "smart-image", "images": [{"name": "x"}]}], [], {}
            )

    def test_node_without_id_or_type_rejected(self):
        with pytest.raises(AdapterError):
            _validate_write_payload([{"type": "image"}], [], {})
        with pytest.raises(AdapterError):
            _validate_write_payload([{"id": "n1"}], [], {})

    def test_bad_viewport_scale_rejected(self):
        with pytest.raises(AdapterError, match="scale"):
            _validate_write_payload([], [], {"x": 0, "y": 0, "scale": 0})
        with pytest.raises(AdapterError, match="viewport"):
            _validate_write_payload([], [], {"x": "left", "y": 0, "scale": 1})

    def test_empty_payload_passes(self):
        _validate_write_payload([], [], {})
