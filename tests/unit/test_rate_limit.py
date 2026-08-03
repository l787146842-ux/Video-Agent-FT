"""P0-3 回归：限流不应误杀 GET 状态轮询，POST 提交仍受限"""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.video_agent.web.middleware.rate_limit import RateLimitMiddleware


def _build_app(rate: int = 10) -> FastAPI:
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware, rate=rate)

    @app.get("/api/generate/{task_id}/status")
    async def status(task_id: str):
        return {"task_id": task_id, "status": "processing"}

    @app.post("/api/generate/image")
    async def gen_image():
        return {"ok": True}

    @app.post("/api/agent/chat")
    async def chat():
        return {"ok": True}

    @app.get("/api/other")
    async def other():
        return {"ok": True}

    return app


class TestRateLimit:
    def test_get_polling_not_limited(self):
        """GET 状态轮询 12 次/分（前端 5s 间隔）不应触发 429"""
        client = TestClient(_build_app(rate=10))
        for _ in range(15):
            resp = client.get("/api/generate/task-1/status")
            assert resp.status_code == 200

    def test_post_still_limited(self):
        """POST 提交类端点超过配额后返回 429 + error_code"""
        client = TestClient(_build_app(rate=10))
        codes = [client.post("/api/generate/image", json={}).status_code for _ in range(12)]
        assert codes[:10] == [200] * 10
        assert 429 in codes[10:]
        # 验证 429 响应体带 error_code（供前端 i18n）
        resp429 = client.post("/api/generate/image", json={})
        assert resp429.status_code == 429
        assert resp429.json()["error_code"] == "RATE_LIMITED"

    def test_chat_post_limited(self):
        """聊天端点同样受限流保护"""
        client = TestClient(_build_app(rate=3))
        codes = [client.post("/api/agent/chat", json={}).status_code for _ in range(5)]
        assert 429 in codes

    def test_unlimited_prefix_get_passes(self):
        """非受限前缀的 GET 不受任何限制"""
        client = TestClient(_build_app(rate=1))
        for _ in range(5):
            assert client.get("/api/other").status_code == 200
