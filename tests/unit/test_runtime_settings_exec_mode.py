# -*- coding: utf-8 -*-
"""执行模式四档路由测试（2026-09-06 Flova 对齐批）：/api/settings/runtime 的
execution_mode 字段——GET 恒下发、PUT 白名单清洗（非法值拒收）、
启动加载（合法应用/脏值回落/缺键不变）。照抄 execution_preference 三件套。
"""
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.video_agent.config import EXECUTION_MODE_DEFAULT, settings
from src.video_agent.web.routes import runtime_settings as rs


@pytest.fixture
def client(tmp_path, monkeypatch):
    """落盘文件隔离到临时目录；测试后还原 settings 原值（frozen 定点突破）。"""
    monkeypatch.setattr(rs, "RUNTIME_SETTINGS_FILE", tmp_path / "runtime_settings.json")
    app = FastAPI()
    app.include_router(rs.router, prefix="/api")
    original = settings.execution_mode
    yield TestClient(app)
    object.__setattr__(settings, "execution_mode", original)


def test_get_always_includes_mode_default(client):
    """GET 恒下发；未写过键时下发默认档（行为与现状一致）。"""
    r = client.get("/api/settings/runtime")
    assert r.status_code == 200
    assert r.json()["execution_mode"] == EXECUTION_MODE_DEFAULT == "ai_decide"


def test_put_valid_value_applies_and_persists(client, tmp_path):
    for value in ("auto_full", "key_steps_confirm", "pause_all", "ai_decide"):
        r = client.put("/api/settings/runtime", json={"execution_mode": value})
        assert r.status_code == 200
        assert r.json()["execution_mode"] == value
        assert settings.execution_mode == value
    # 持久化落盘：重启加载仍生效
    saved = json.loads((tmp_path / "runtime_settings.json").read_text(encoding="utf-8"))
    assert saved["execution_mode"] == "ai_decide"


def test_put_invalid_value_rejected_keeps_current(client, tmp_path):
    client.put("/api/settings/runtime", json={"execution_mode": "auto_full"})
    r = client.put("/api/settings/runtime", json={"execution_mode": "yolo"})
    assert r.status_code == 200  # 拒收 = 保持当前档，不报错
    assert r.json()["execution_mode"] == "auto_full"
    assert settings.execution_mode == "auto_full"
    saved = json.loads((tmp_path / "runtime_settings.json").read_text(encoding="utf-8"))
    assert saved.get("execution_mode") == "auto_full", "非法值不得落盘"


def test_load_applies_valid_value(tmp_path, monkeypatch):
    monkeypatch.setattr(rs, "RUNTIME_SETTINGS_FILE", tmp_path / "runtime_settings.json")
    (tmp_path / "runtime_settings.json").write_text(
        json.dumps({"execution_mode": "key_steps_confirm"}), encoding="utf-8")
    original = settings.execution_mode
    try:
        rs.load_runtime_settings()
        assert settings.execution_mode == "key_steps_confirm"
    finally:
        object.__setattr__(settings, "execution_mode", original)


def test_load_dirty_value_falls_back_to_default(tmp_path, monkeypatch):
    """迁移兼容：存量脏值加载后回落默认档（行为与现状一致）。"""
    monkeypatch.setattr(rs, "RUNTIME_SETTINGS_FILE", tmp_path / "runtime_settings.json")
    (tmp_path / "runtime_settings.json").write_text(
        json.dumps({"execution_mode": "turbo"}), encoding="utf-8")
    original = settings.execution_mode
    object.__setattr__(settings, "execution_mode", EXECUTION_MODE_DEFAULT)
    try:
        rs.load_runtime_settings()
        assert settings.execution_mode == EXECUTION_MODE_DEFAULT
    finally:
        object.__setattr__(settings, "execution_mode", original)


def test_load_missing_key_keeps_current(tmp_path, monkeypatch):
    """迁移兼容：不含该键的存量配置加载后行为不变。"""
    monkeypatch.setattr(rs, "RUNTIME_SETTINGS_FILE", tmp_path / "runtime_settings.json")
    (tmp_path / "runtime_settings.json").write_text(
        json.dumps({"model_fallback_enabled": True}), encoding="utf-8")
    original = settings.execution_mode
    object.__setattr__(settings, "execution_mode", EXECUTION_MODE_DEFAULT)
    try:
        rs.load_runtime_settings()
        assert settings.execution_mode == EXECUTION_MODE_DEFAULT
    finally:
        object.__setattr__(settings, "execution_mode", original)
