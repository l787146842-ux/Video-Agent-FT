# -*- coding: utf-8 -*-
"""GET /health 端点单测（任务 #28 全局健康层）：
- 复用既有根路径端点（不进 /api 前缀 → 生产免 API Key，前端心跳可直接探测）；
- 契约钉死：status=ok + canvas_online 字段（前端 api/health.ts 据此映射 ok/canvas）。
"""
from fastapi.testclient import TestClient

from src.video_agent.web.app import app


def test_health_returns_ok_without_api_key():
    """健康探测不得要求鉴权（断连恢复期前端可能尚无有效 Key）"""
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"


def test_health_contract_fields():
    """前端契约字段：canvas_online 必须存在（bool/None），version 非空"""
    client = TestClient(app)
    body = client.get("/health").json()
    assert "canvas_online" in body
    assert body["canvas_online"] is None or isinstance(body["canvas_online"], bool)
    assert body.get("version")
    assert "canvas_enabled" in body


def test_health_not_swallowed_by_spa_fallback():
    """/health 必须返回 JSON 而非 SPA index.html（catch-all 注册顺序回归防护）"""
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.headers.get("content-type", "").startswith("application/json")
