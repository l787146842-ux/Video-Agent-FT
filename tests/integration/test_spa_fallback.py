"""集成测试：SPA fallback（814H8）——前端路由硬敲/刷新返回 index.html，未知接口保持 JSON 404。"""
import pytest
from fastapi.testclient import TestClient

from src.video_agent.web.app import app


@pytest.fixture()
def client():
    return TestClient(app)


def test_hard_nav_global_settings_returns_spa(client):
    """地址栏硬敲 /global-settings 不再 404：返回 SPA 入口由 JS 路由渲染"""
    resp = client.get("/global-settings")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")
    assert "<div" in resp.text


def test_unknown_frontend_path_returns_spa(client):
    """未来新增前端路由无需改后端：未识别非 api 路径一律递 index.html"""
    resp = client.get("/some/future/route")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")


def test_unknown_api_path_still_json_404(client):
    """/api 排除在兜底外：未知接口保持 JSON 404（前端 fetch 报错语义不被 HTML 200 污染）"""
    resp = client.get("/api/definitely-not-exist")
    assert resp.status_code == 404
    assert resp.headers.get("content-type", "").startswith("application/json")


def test_existing_spa_routes_unaffected(client):
    """既有页面路由不受 catch-all 影响"""
    assert client.get("/").status_code == 200
    assert client.get("/canvas").status_code == 200
    assert client.get("/settings").status_code == 200
