# -*- coding: utf-8 -*-
"""选中态反向联动端点（/api/canvas/select-nodes）与嵌入配置下发（/api/config）测试。"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.video_agent.adapters.canvas_agent_session import LOCAL_AGENT_TOKEN
from src.video_agent.config import settings
from src.video_agent.web.routes import canvas as canvas_routes
from src.video_agent.web.routes import config as config_routes


def _patch_adapter(monkeypatch, adapter):
    monkeypatch.setattr(canvas_routes, "get_canvas_adapter", lambda: adapter)


def test_select_nodes_routes_supported_backend(monkeypatch):
    class _FakeAdapter:
        async def select_nodes(self, node_ids):
            return {"supported": True, "selected": len(node_ids)}

    _patch_adapter(monkeypatch, _FakeAdapter())
    app = FastAPI()
    app.include_router(canvas_routes.router, prefix="/api")
    client = TestClient(app)
    r = client.post("/api/canvas/select-nodes", json={"node_ids": ["n1", "n2"]})
    assert r.status_code == 200
    assert r.json() == {"supported": True, "selected": 2}


def test_select_nodes_routes_unsupported_backend_no_error(monkeypatch):
    """协议桩返回 supported=False 时路由原样透传，不报错（不 500）"""
    class _FakeAdapter:
        async def select_nodes(self, node_ids):
            return {"supported": False, "selected": 0, "reason": "画布页未连接"}

    _patch_adapter(monkeypatch, _FakeAdapter())
    app = FastAPI()
    app.include_router(canvas_routes.router, prefix="/api")
    client = TestClient(app)
    r = client.post("/api/canvas/select-nodes", json={"node_ids": ["n1"]})
    assert r.status_code == 200
    assert r.json()["supported"] is False


def _set_setting(name: str, value):
    """frozen dataclass 用 object.__setattr__ 绕过（与 test_config_fallback_switch 同口径）"""
    object.__setattr__(settings, name, value)


@pytest.fixture
def config_client(tmp_path, monkeypatch):
    monkeypatch.setattr(
        config_routes, "_RUNTIME_SETTINGS_FILE", tmp_path / "runtime_settings.json"
    )
    originals = {k: getattr(settings, k) for k in
                 ("canvas_agent_token", "infinite_canvas_url", "canvas_agent_url", "host")}
    _set_setting("canvas_agent_token", "tok-test")
    _set_setting("host", "127.0.0.1")  # 回环绑定：下发真实 token（环境无关）
    app = FastAPI()
    app.include_router(config_routes.router, prefix="/api")
    yield TestClient(app)
    for k, v in originals.items():
        _set_setting(k, v)


def test_config_embed_delivered(config_client):
    """L2：画布同域挂载（/canvas-app）+ 本进程 agent 端点（绝对地址）+ 本机令牌。"""
    r = config_client.get("/api/config")
    assert r.status_code == 200
    embed = r.json()["infinite_canvas_embed"]
    assert embed["canvas_url"] == "/canvas-app"
    assert embed["agent_url"].startswith("http")
    assert embed["agent_url"].endswith("/api/canvas/agent")
    assert embed["agent_token"] == LOCAL_AGENT_TOKEN
    # 基础下发字段不回归
    assert "canvas_url" in r.json() and "model_fallback_enabled" in r.json()


def test_config_embed_token_suppressed_on_non_loopback(config_client):
    """安全闸：非回环绑定（如 0.0.0.0）不下发真实 agent_token，返回空串"""
    _set_setting("host", "0.0.0.0")
    r = config_client.get("/api/config")
    assert r.status_code == 200
    assert r.json()["infinite_canvas_embed"]["agent_token"] == ""
