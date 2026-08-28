"""集成测试：画布路由（FastAPI TestClient + CanvasBackend 协议层打桩）。

打桩点在 CanvasBackend 协议层（路由只依赖协议）。
覆盖端点：/canvas/drop-image、/canvas/selection、/canvas/node-images、
/canvas/all-node-images、/canvas/list。
"""
import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock, patch

from src.video_agent.web.app import app
from src.video_agent.adapters.canvas_adapter import reset_canvas_adapter
from src.video_agent.exceptions import AdapterError


@pytest.fixture(autouse=True)
def _reset_adapter():
    reset_canvas_adapter()
    yield
    reset_canvas_adapter()


def _absolutize(public_base: str, url: str) -> str:
    if url.startswith(("http://", "https://", "data:", "blob:")):
        return url
    return f"{public_base.rstrip('/')}/{url.lstrip('/')}"


def _fake_backend() -> MagicMock:
    """CanvasBackend 协议桩：节点直接引用素材绝对 URL，无二次上传"""
    fake = MagicMock(name="CanvasBackend")
    fake.base_url = "http://canvas-fixture:3000"
    fake.is_online = AsyncMock(return_value=True)
    fake.list_canvases = AsyncMock(return_value=[
        {"id": "c1", "title": "画布A", "kind": "smart", "updated_at": 100, "deleted_at": None},
    ])
    fake.find_active_canvas = AsyncMock(
        return_value={"id": "c1", "title": "画布A", "kind": "smart"})
    fake.find_active_smart_canvas = AsyncMock(
        return_value={"id": "c1", "title": "画布A", "kind": "smart"})
    fake.add_image_node = AsyncMock(
        return_value={"node_id": "n-x", "canvas_id": "c1", "canvas_title": "画布A"})
    fake.get_selection = AsyncMock(return_value={
        "supported": True,
        "nodes": [{"id": "n1", "nodeType": "image"}],
    })
    fake.get_canvas = AsyncMock(return_value={"title": "画布A", "nodes": []})

    async def _prepare(*, url, name, local_path, mime, public_base):
        return {"url": _absolutize(public_base, url), "name": name}

    fake.prepare_drop_image = AsyncMock(side_effect=_prepare)
    return fake


@pytest.fixture
def fake():
    return _fake_backend()


@pytest.fixture
def client(fake):
    with patch("src.video_agent.web.routes.canvas.get_canvas_adapter", return_value=fake):
        yield TestClient(app)


class TestDropImageRoute:
    def test_missing_url_rejected(self, client):
        resp = client.post("/api/canvas/drop-image", json={})
        assert resp.status_code == 422

    def test_no_active_canvas_returns_404(self, client, fake):
        fake.find_active_canvas = AsyncMock(return_value=None)
        resp = client.post("/api/canvas/drop-image", json={
            "url": "https://example.com/x.png",
            "view": {"width": 1000, "height": 600},
        })
        assert resp.status_code == 404
        assert "画布" in resp.json()["detail"]

    def test_external_url_written_without_upload(self, client, fake):
        """外部 URL：不物化为本站资源，直接以绝对 URL 建节点"""
        resp = client.post("/api/canvas/drop-image", json={
            "url": "https://example.com/x.png",
            "name": "x.png",
            "drop": {"x": 500, "y": 300},
            "view": {"width": 1000, "height": 600},
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["node_id"] == "n-x"
        assert data["image_url"] == "https://example.com/x.png"
        _, kwargs = fake.add_image_node.call_args
        assert kwargs["drop_point"] == (500.0, 300.0)
        assert kwargs["view_size"] == (1000.0, 600.0)

    def test_local_asset_materialized_then_written(self, client, fake, tmp_path, monkeypatch):
        """本站素材：经协议 prepare_drop_image 物化后建节点（本站绝对 URL，无二次上传）"""
        import src.video_agent.web.routes.canvas as canvas_route

        assets = tmp_path / "assets"
        assets.mkdir()
        (assets / "gen-1.png").write_bytes(b"\x89PNG-fake")
        monkeypatch.setattr(canvas_route, "ASSETS_DIR", assets)

        resp = client.post("/api/canvas/drop-image", json={
            "url": "/workspace/assets/gen-1.png",
        })
        assert resp.status_code == 200
        data = resp.json()
        _, kwargs = fake.prepare_drop_image.call_args
        assert kwargs["local_path"] is not None  # 本站素材被识别
        assert data["image_url"].startswith("http")
        assert data["image_url"].endswith("/workspace/assets/gen-1.png")
        _, add_kwargs = fake.add_image_node.call_args
        assert add_kwargs["image"]["url"] == data["image_url"]

    def test_path_traversal_rejected(self, client, fake, tmp_path, monkeypatch):
        """/workspace/assets/ 之外的文件不得被识别为本站素材（防目录穿越）"""
        import src.video_agent.web.routes.canvas as canvas_route
        monkeypatch.setattr(canvas_route, "ASSETS_DIR", tmp_path / "assets")

        resp = client.post("/api/canvas/drop-image", json={
            "url": "/workspace/assets/../secrets.txt",
        })
        assert resp.status_code == 200
        _, kwargs = fake.prepare_drop_image.call_args
        assert kwargs["local_path"] is None


class TestSelectionRoute:
    def test_selection_forwarded(self, client):
        resp = client.get("/api/canvas/selection")
        assert resp.status_code == 200
        data = resp.json()
        assert data["canvas_online"] is True
        assert data["supported"] is True
        assert data["nodes"] == [{"id": "n1", "nodeType": "image"}]

    def test_selection_offline(self, client, fake):
        fake.is_online = AsyncMock(return_value=False)
        resp = client.get("/api/canvas/selection")
        assert resp.status_code == 200
        assert resp.json() == {"supported": False, "nodes": [], "canvas_online": False}

    def test_selection_adapter_error_returns_empty(self, client, fake):
        fake.get_selection = AsyncMock(side_effect=AdapterError("画布页未连接"))
        resp = client.get("/api/canvas/selection")
        assert resp.status_code == 200
        data = resp.json()
        assert data["supported"] is False
        assert data["nodes"] == []
        assert data["canvas_online"] is True


class TestNodeImagesRoutes:
    """node-images / all-node-images：节点图片引用提取（metadata.content）"""

    def test_node_images(self, client, fake):
        fake.get_canvas = AsyncMock(return_value={
            "title": "画布A",
            "nodes": [
                {"id": "n1", "type": "image", "title": "a.png",
                 "position": {"x": 0, "y": 0},
                 "metadata": {"content": "http://127.0.0.1:8080/workspace/assets/a.png"}},
                # text 节点 content 是正文，不得当图片提取
                {"id": "n2", "type": "text", "metadata": {"content": "正文文本"}},
            ],
        })
        resp = client.get("/api/canvas/node-images")
        assert resp.status_code == 200
        data = resp.json()
        assert data["canvas_online"] is True
        assert len(data["items"]) == 1
        assert data["items"][0]["url"] == "http://127.0.0.1:8080/workspace/assets/a.png"

    def test_node_images_offline(self, client, fake):
        fake.is_online = AsyncMock(return_value=False)
        resp = client.get("/api/canvas/node-images")
        assert resp.status_code == 200
        assert resp.json() == {"items": [], "canvas_online": False}

    def test_all_node_images_by_canvas_id(self, client, fake):
        fake.get_canvas = AsyncMock(return_value={
            "title": "画布A",
            "nodes": [{"id": "n1", "type": "image", "title": "b",
                       "metadata": {"content": "http://127.0.0.1:8080/workspace/assets/b.png"}}],
        })
        resp = client.get("/api/canvas/all-node-images", params={"canvas_id": "c1"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["canvas_online"] is True
        assert len(data["items"]) == 1
        assert data["items"][0]["url"].endswith("/b.png")


class TestCanvasListRoute:
    def test_list_with_online_flag(self, client):
        resp = client.get("/api/canvas/list")
        assert resp.status_code == 200
        data = resp.json()
        assert data["canvas_online"] is True
        assert data["canvases"][0]["id"] == "c1"
        assert data["canvases"][0]["kind"] == "smart"

    def test_list_offline(self, client, fake):
        fake.is_online = AsyncMock(return_value=False)
        resp = client.get("/api/canvas/list")
        assert resp.status_code == 200
        assert resp.json() == {"canvases": [], "canvas_online": False}
