"""
画布拖放（对话栏图片 -> 画布节点）单元测试 — mock httpx 响应。
覆盖：upload_files / find_active_smart_canvas / add_image_node / _resolve_drop_world_point。
"""
import pytest
import httpx
from unittest.mock import AsyncMock, patch, MagicMock

from src.video_agent.adapters.canvas_adapter import (
    CanvasAdapter,
    _resolve_drop_world_point,
    reset_canvas_adapter,
)


@pytest.fixture(autouse=True)
def _reset_singleton():
    reset_canvas_adapter()
    yield
    reset_canvas_adapter()


@pytest.fixture
def adapter():
    return CanvasAdapter(base_url="http://test-canvas:8000", timeout=5)


def _mock_response(json_data, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=MagicMock(), response=resp
        )
        resp.text = str(json_data)
    return resp


class TestUploadFiles:
    @pytest.mark.asyncio
    async def test_success(self, adapter):
        mock_resp = _mock_response({"files": [{"url": "/assets/input/ai_ref_a.png", "name": "a.png", "kind": "image"}]})
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp) as post:
            result = await adapter.upload_files([("a.png", b"\x89PNG", "image/png")])
        assert len(result) == 1
        assert result[0]["url"] == "/assets/input/ai_ref_a.png"
        # multipart 字段名为 files
        _, kwargs = post.call_args
        assert kwargs["files"][0][0] == "files"

    @pytest.mark.asyncio
    async def test_empty_list(self, adapter):
        assert await adapter.upload_files([]) == []

    @pytest.mark.asyncio
    async def test_filters_entries_without_url(self, adapter):
        mock_resp = _mock_response({"files": [{"name": "bad"}, {"url": "/assets/input/ok.png"}]})
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp):
            result = await adapter.upload_files([("a.png", b"x", "image/png")])
        assert [f["url"] for f in result] == ["/assets/input/ok.png"]


class TestFindActiveSmartCanvas:
    @pytest.mark.asyncio
    async def test_picks_latest_updated_smart(self, adapter):
        canvases = [
            {"id": "c1", "kind": "smart", "updated_at": 100},
            {"id": "c2", "kind": "smart", "updated_at": 300},
            {"id": "c3", "kind": "classic", "updated_at": 999},
            {"id": "c4", "kind": "smart", "updated_at": 200, "deleted_at": 1},
        ]
        mock_resp = _mock_response({"canvases": canvases})
        with patch("httpx.AsyncClient.request", new_callable=AsyncMock, return_value=mock_resp):
            result = await adapter.find_active_smart_canvas()
        assert result["id"] == "c2"

    @pytest.mark.asyncio
    async def test_no_smart_canvas_returns_none(self, adapter):
        mock_resp = _mock_response({"canvases": [{"id": "c3", "kind": "classic", "updated_at": 1}]})
        with patch("httpx.AsyncClient.request", new_callable=AsyncMock, return_value=mock_resp):
            assert await adapter.find_active_smart_canvas() is None


class TestResolveDropWorldPoint:
    def _canvas(self, viewport):
        return {"viewport": viewport}

    def test_no_drop_point_returns_viewport_center(self):
        canvas = self._canvas({"x": 0, "y": 0, "scale": 1})
        wx, wy = _resolve_drop_world_point(canvas, None, (1000, 600))
        assert (wx, wy) == (500, 300)

    def test_drop_point_with_shell_offset(self):
        canvas = self._canvas({"x": 0, "y": 0, "scale": 1})
        wx, wy = _resolve_drop_world_point(canvas, (596, 216), (1000, 600))
        # 默认外壳偏移 (96, 16)：world = drop - offset
        assert (wx, wy) == (500, 200)

    def test_scale_and_viewport(self):
        canvas = self._canvas({"x": 100, "y": 50, "scale": 2})
        wx, wy = _resolve_drop_world_point(canvas, (496, 266), (1000, 600))
        # world = (drop - offset - viewport) / scale
        assert wx == (496 - 96 - 100) / 2
        assert wy == (266 - 16 - 50) / 2

    def test_out_of_view_clamped_into_visible_rect(self):
        canvas = self._canvas({"x": 0, "y": 0, "scale": 1})
        # 落点远超可视区（偏移估计失效场景）→ 夹取回可视世界矩形内
        wx, wy = _resolve_drop_world_point(canvas, (-5000, 99999), (1000, 600))
        assert 80 <= wx <= 920
        assert 80 <= wy <= 520

    def test_zero_scale_falls_back_to_one(self):
        canvas = self._canvas({"x": 0, "y": 0, "scale": 0})
        wx, wy = _resolve_drop_world_point(canvas, None, (1000, 600))
        assert (wx, wy) == (500, 300)


class TestAddImageNode:
    def _canvas_payload(self):
        return {
            "id": "c1",
            "title": "测试画布",
            "icon": "sparkles",
            "kind": "smart",
            "updated_at": 100,
            # n0 显式远离视口中心（无坐标节点会被避让算法视为占据原点，
            # 导致新节点被挤开，无法验证「默认放视口中心」语义）
            "nodes": [{"id": "n0", "type": "smart-image", "x": -2000, "y": -2000,
                      "images": [{"url": "https://example.com/n0.png", "name": "n0.png"}]}],
            "connections": [],
            "viewport": {"x": 0, "y": 0, "scale": 1},
            "logs": [],
            "settings": {"engine": "api"},
        }

    @pytest.mark.asyncio
    async def test_appends_smart_image_node_and_saves(self, adapter):
        canvas = self._canvas_payload()

        async def fake_request(self, method, path, **kwargs):
            if method == "GET":
                return {"canvas": canvas}
            if method == "PUT":
                self._last_put = kwargs["json"]
                return {"canvas": {**canvas, "updated_at": 200}}
            raise AssertionError(method)

        with patch.object(CanvasAdapter, "_request", autospec=True) as m:
            m.side_effect = fake_request
            result = await adapter.add_image_node(
                "c1",
                image={"url": "/assets/input/x.png", "name": "x.png", "kind": "image"},
                view_size=(1000, 600),
            )

        assert result["canvas_id"] == "c1"
        assert result["canvas_title"] == "测试画布"
        put = adapter._last_put
        new_nodes = [n for n in put["nodes"] if n["id"] != "n0"]
        assert len(new_nodes) == 1
        node = new_nodes[0]
        assert node["type"] == "smart-image"
        assert node["scale"] == 2
        assert node["images"] == [{"url": "/assets/input/x.png", "name": "x.png", "kind": "image"}]
        # 原节点保留 + 基底版本号传递（乐观锁）
        assert put["nodes"][0]["id"] == "n0"
        assert put["base_updated_at"] == 100
        assert put["settings"] == {"engine": "api"}
        # 默认放视口中心（1000x600 视口，节点半宽 224）
        assert node["x"] == round(500 - 224)
        assert node["y"] == round(300 - 224)
