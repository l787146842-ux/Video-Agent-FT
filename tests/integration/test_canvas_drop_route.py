"""集成测试：POST /api/canvas/drop-image（FastAPI TestClient + mock CanvasAdapter）"""
import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch

from src.video_agent.web.app import app
from src.video_agent.adapters.canvas_adapter import CanvasAdapter, reset_canvas_adapter
from src.video_agent.exceptions import AdapterError


@pytest.fixture(autouse=True)
def _reset_adapter():
    reset_canvas_adapter()
    yield
    reset_canvas_adapter()


@pytest.fixture
def client():
    return TestClient(app)


class TestDropImageRoute:
    def test_missing_url_rejected(self, client):
        resp = client.post("/api/canvas/drop-image", json={})
        assert resp.status_code == 422

    def test_no_active_canvas_returns_404(self, client):
        # 路由现用 find_active_canvas（支持任意画布类型，不再仅限智能画布）
        with patch.object(
            CanvasAdapter, "find_active_canvas", new_callable=AsyncMock, return_value=None
        ), patch.object(
            CanvasAdapter, "upload_files", new_callable=AsyncMock, return_value=[]
        ):
            resp = client.post("/api/canvas/drop-image", json={
                "url": "https://example.com/x.png",
                "view": {"width": 1000, "height": 600},
            })
        assert resp.status_code == 404
        assert "画布" in resp.json()["detail"]

    def test_external_url_written_without_upload(self, client):
        """外部 URL：跳过上传，直接以绝对 URL 建节点"""
        with patch.object(
            CanvasAdapter, "find_active_canvas", new_callable=AsyncMock,
            return_value={"id": "c1", "title": "画布A"},
        ), patch.object(
            CanvasAdapter, "upload_files", new_callable=AsyncMock,
        ) as up, patch.object(
            CanvasAdapter, "add_image_node", new_callable=AsyncMock,
            return_value={"node_id": "smart-x", "canvas_id": "c1", "canvas_title": "画布A"},
        ) as add:
            resp = client.post("/api/canvas/drop-image", json={
                "url": "https://example.com/x.png",
                "name": "x.png",
                "drop": {"x": 500, "y": 300},
                "view": {"width": 1000, "height": 600},
            })
        assert resp.status_code == 200
        data = resp.json()
        assert data["node_id"] == "smart-x"
        assert data["image_url"] == "https://example.com/x.png"
        up.assert_not_called()
        _, kwargs = add.call_args
        assert kwargs["drop_point"] == (500.0, 300.0)
        assert kwargs["view_size"] == (1000.0, 600.0)

    def test_local_asset_uploaded_then_written(self, client, tmp_path, monkeypatch):
        """本站素材：读本地字节上传到画布素材库，以画布本地 URL 建节点"""
        import src.video_agent.web.routes.canvas as canvas_route

        assets = tmp_path / "assets"
        assets.mkdir()
        (assets / "gen-1.png").write_bytes(b"\x89PNG-fake")
        monkeypatch.setattr(canvas_route, "ASSETS_DIR", assets)

        with patch.object(
            CanvasAdapter, "upload_files", new_callable=AsyncMock,
            return_value=[{"url": "/assets/input/ai_ref_1.png", "name": "gen-1.png", "kind": "image"}],
        ) as up, patch.object(
            CanvasAdapter, "find_active_canvas", new_callable=AsyncMock,
            return_value={"id": "c1", "title": "画布A"},
        ), patch.object(
            CanvasAdapter, "add_image_node", new_callable=AsyncMock,
            return_value={"node_id": "smart-y", "canvas_id": "c1", "canvas_title": "画布A"},
        ) as add:
            resp = client.post("/api/canvas/drop-image", json={
                "url": "/workspace/assets/gen-1.png",
            })
        assert resp.status_code == 200
        data = resp.json()
        assert data["image_url"] == "/assets/input/ai_ref_1.png"
        # 上传的是本地文件字节
        args, _ = up.call_args
        (fname, content, mime), = args[0]
        assert fname == "gen-1.png"
        assert content == b"\x89PNG-fake"
        assert mime == "image/png"
        # 节点引用画布本地 URL
        _, kwargs = add.call_args
        assert kwargs["image"]["url"] == "/assets/input/ai_ref_1.png"

    def test_upload_failure_falls_back_to_absolute_url(self, client, tmp_path, monkeypatch):
        """上传失败：回退为本站绝对 URL，功能不中断"""
        import src.video_agent.web.routes.canvas as canvas_route

        assets = tmp_path / "assets"
        assets.mkdir()
        (assets / "gen-2.png").write_bytes(b"\x89PNG-fake")
        monkeypatch.setattr(canvas_route, "ASSETS_DIR", assets)

        with patch.object(
            CanvasAdapter, "upload_files", new_callable=AsyncMock,
            side_effect=AdapterError("画布服务响应超时"),
        ), patch.object(
            CanvasAdapter, "find_active_canvas", new_callable=AsyncMock,
            return_value={"id": "c1", "title": "画布A"},
        ), patch.object(
            CanvasAdapter, "add_image_node", new_callable=AsyncMock,
            return_value={"node_id": "smart-z", "canvas_id": "c1", "canvas_title": "画布A"},
        ) as add:
            resp = client.post("/api/canvas/drop-image", json={"url": "/workspace/assets/gen-2.png"})
        assert resp.status_code == 200
        _, kwargs = add.call_args
        assert kwargs["image"]["url"].endswith("/workspace/assets/gen-2.png")
        assert kwargs["image"]["url"].startswith("http")

    def test_path_traversal_rejected(self, client, tmp_path, monkeypatch):
        """/workspace/assets/ 之外的文件不得被读取上传"""
        import src.video_agent.web.routes.canvas as canvas_route
        monkeypatch.setattr(canvas_route, "ASSETS_DIR", tmp_path / "assets")

        with patch.object(
            CanvasAdapter, "upload_files", new_callable=AsyncMock,
        ) as up, patch.object(
            CanvasAdapter, "find_active_canvas", new_callable=AsyncMock,
            return_value={"id": "c1", "title": "画布A"},
        ), patch.object(
            CanvasAdapter, "add_image_node", new_callable=AsyncMock,
            return_value={"node_id": "smart-w", "canvas_id": "c1", "canvas_title": "画布A"},
        ):
            resp = client.post("/api/canvas/drop-image", json={
                "url": "/workspace/assets/../secrets.txt",
            })
        assert resp.status_code == 200
        up.assert_not_called()
