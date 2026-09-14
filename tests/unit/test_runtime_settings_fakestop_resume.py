# -*- coding: utf-8 -*-
"""假停机械续跑开关路由测试（2026-09-14 词表退役批）：/api/settings/runtime 的
fakestop_auto_resume_enabled 字段——GET 恒下发（结构性判定，默认 True）、
PUT 生效落盘、启动加载回放/缺键不变。照抄 execution_mode 三件套。
词表键 fakestop_promise_patterns 已整体退役（接口面不再存在）。"""
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.video_agent.config import settings
from src.video_agent.web.routes import runtime_settings as rs


@pytest.fixture
def client(tmp_path, monkeypatch):
    """落盘文件隔离到临时目录；测试后还原 settings 原值（frozen 定点突破）。"""
    monkeypatch.setattr(rs, "RUNTIME_SETTINGS_FILE", tmp_path / "runtime_settings.json")
    app = FastAPI()
    app.include_router(rs.router, prefix="/api")
    original_toggle = settings.fakestop_auto_resume_enabled
    yield TestClient(app)
    object.__setattr__(settings, "fakestop_auto_resume_enabled", original_toggle)


def test_get_default_on(client):
    """GET 恒下发；未写过键时下发默认开（结构性机械续跑为默认主防线）。"""
    r = client.get("/api/settings/runtime")
    assert r.status_code == 200
    assert r.json()["fakestop_auto_resume_enabled"] is True


def test_put_applies_and_persists(client, tmp_path):
    r = client.put("/api/settings/runtime", json={"fakestop_auto_resume_enabled": False})
    assert r.status_code == 200
    assert r.json()["fakestop_auto_resume_enabled"] is False
    # 运行时生效：agent_loop 据此决定假停轮是否机械续跑
    assert settings.fakestop_auto_resume_enabled is False
    # 持久化落盘：重启加载仍生效
    saved = json.loads((tmp_path / "runtime_settings.json").read_text(encoding="utf-8"))
    assert saved["fakestop_auto_resume_enabled"] is False


def test_load_replays_persisted_value(tmp_path, monkeypatch):
    monkeypatch.setattr(rs, "RUNTIME_SETTINGS_FILE", tmp_path / "runtime_settings.json")
    (tmp_path / "runtime_settings.json").write_text(
        json.dumps({"fakestop_auto_resume_enabled": False}), encoding="utf-8")
    original = settings.fakestop_auto_resume_enabled
    try:
        rs.load_runtime_settings()
        assert settings.fakestop_auto_resume_enabled is False
    finally:
        object.__setattr__(settings, "fakestop_auto_resume_enabled", original)


def test_load_missing_key_keeps_current(tmp_path, monkeypatch):
    """迁移兼容：不含该键的存量配置加载后行为不变。"""
    monkeypatch.setattr(rs, "RUNTIME_SETTINGS_FILE", tmp_path / "runtime_settings.json")
    (tmp_path / "runtime_settings.json").write_text(
        json.dumps({"model_fallback_enabled": True}), encoding="utf-8")
    original = settings.fakestop_auto_resume_enabled
    object.__setattr__(settings, "fakestop_auto_resume_enabled", True)
    try:
        rs.load_runtime_settings()
        assert settings.fakestop_auto_resume_enabled is True
    finally:
        object.__setattr__(settings, "fakestop_auto_resume_enabled", original)


# ---------- 词表键退役（2026-09-14 批）：接口面不再存在，PUT 传入被忽略 ----------

def test_patterns_key_retired_from_contract(client, tmp_path):
    """GET 不再下发词表键；PUT 携带旧词表键被静默忽略（未知键不校验不落盘）。"""
    r = client.get("/api/settings/runtime")
    assert r.status_code == 200
    assert "fakestop_promise_patterns" not in r.json()

    r2 = client.put("/api/settings/runtime", json={
        "fakestop_promise_patterns": "马上继续\n继续第[批：\n"})
    assert r2.status_code == 200  # 未知键不校验、不拒收、不生效
    assert "fakestop_promise_patterns" not in r2.json()
    saved = json.loads((tmp_path / "runtime_settings.json").read_text(encoding="utf-8"))
    assert "fakestop_promise_patterns" not in saved
