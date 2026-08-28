# -*- coding: utf-8 -*-
"""模型降级开关 API 测试（/api/config/model-fallback）。

需求：顶部导航栏开关控制「主模型打不通时是否自动切 API 配置里的其他模型」；
关闭时打不通直接报错停止。开关状态持久化，重启后仍生效。
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.video_agent.config import settings
from src.video_agent.web.routes import config as config_routes


@pytest.fixture
def client(tmp_path, monkeypatch):
    """隔离持久化文件到临时目录，测试后还原 settings 原值（frozen dataclass 用 setattr 绕过）。"""
    monkeypatch.setattr(
        config_routes, "_RUNTIME_SETTINGS_FILE", tmp_path / "runtime_settings.json"
    )
    app = FastAPI()
    app.include_router(config_routes.router, prefix="/api")
    original = settings.model_fallback_enabled
    yield TestClient(app)
    object.__setattr__(settings, "model_fallback_enabled", original)


def test_get_config_includes_fallback_flag(client):
    r = client.get("/api/config")
    assert r.status_code == 200
    assert "model_fallback_enabled" in r.json()


def test_toggle_off_applies_and_persists(client, tmp_path):
    r = client.post("/api/config/model-fallback", json={"enabled": False})
    assert r.status_code == 200
    assert r.json()["model_fallback_enabled"] is False
    # 运行时生效：chat_service 据此决定候选链只有主模型
    assert settings.model_fallback_enabled is False
    # 持久化落盘：重启后仍生效
    assert (tmp_path / "runtime_settings.json").exists()
    assert "false" in (tmp_path / "runtime_settings.json").read_text(encoding="utf-8")


def test_toggle_on_restores(client):
    client.post("/api/config/model-fallback", json={"enabled": False})
    r = client.post("/api/config/model-fallback", json={"enabled": True})
    assert r.status_code == 200
    assert settings.model_fallback_enabled is True


# ---------- 退役画布环境变量启动期检测（小修 3） ----------

def test_stale_canvas_env_keys_warn_not_raise(monkeypatch, caplog):
    """旧画布键残留：只警告不 raise（仿 SKILL_RUNTIME 显式处置，
    但旧键已无读取方，硬拒会阻断正常启动），警告指明新键名。"""
    import logging

    from src.video_agent.config import Settings

    monkeypatch.delenv("SKILL_RUNTIME_MODE", raising=False)
    monkeypatch.delenv("SKILL_RUNTIME", raising=False)
    monkeypatch.setenv("CANVAS_BASE_URL", "http://legacy")
    monkeypatch.setenv("CANVAS_PROVIDERS_FILE", "legacy.json")
    with caplog.at_level(logging.WARNING):
        Settings()  # 不抛异常即通过（与 SKILL_RUNTIME fail-hard 的区分点）
    warns = [r.getMessage() for r in caplog.records if "已退役" in r.getMessage()]
    assert any("CANVAS_BASE_URL" in w for w in warns)
    assert any("CANVAS_PROVIDERS_FILE" in w for w in warns)
    # 警告必须指明新键名（不留「静默失效」死角）
    assert any("CANVAS_AGENT_URL" in w for w in warns)
    # 未设置的旧键不告警（无残留零噪声）
    assert not any("CANVAS_ENV_FILE" in w for w in warns)
