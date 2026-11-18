"""/api/generate/events/{task_id} 按任务定向 SSE 端点契约测试（任务7/P0）。

钉死：
- 终态任务立即回放快照并关流（晚到订阅不漏帧，消除连接前事件竞速）；
- 处理中任务仅转发本 task_id 帧（全局广播不得串扰），终态即关流并退订；
- 任务不存在（TTL 清理/从未创建）下发失败帧立即关流，不挂死等；
- 旧全局广播端点保留（待迁移，唯一消费方 generation-events 总线）。
"""
import asyncio
import json

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from src.video_agent.exceptions import VideoAgentError
from src.video_agent.web.error_payload import classify_exception
from src.video_agent.web.routes import generate as gen_routes


class _FakeTaskManager:
    """只实现端点消费的订阅面（subscribe/unsubscribe/get_task/notify）"""

    def __init__(self):
        self.tasks = {}
        self.subscribers = []

    def get_task(self, task_id):
        return self.tasks.get(task_id)

    def subscribe(self):
        q = asyncio.Queue(maxsize=100)
        self.subscribers.append(q)
        return q

    def unsubscribe(self, q):
        if q in self.subscribers:
            self.subscribers.remove(q)

    def notify(self, event):
        msg = json.dumps(event, ensure_ascii=False)
        for q in self.subscribers:
            q.put_nowait(msg)


@pytest.fixture()
def fake_tm(monkeypatch):
    tm = _FakeTaskManager()
    monkeypatch.setattr(gen_routes, "_tm", tm)
    return tm


@pytest.fixture()
def client(fake_tm):  # noqa: ARG001（fake_tm 经 monkeypatch 生效于路由模块）
    app = FastAPI()

    # 与生产 app.py 同形的业务异常转译（否则 VideoAgentError 会直穿成 500/抛错）
    @app.exception_handler(VideoAgentError)
    async def _video_agent_error_handler(request: Request, exc: VideoAgentError):
        payload = classify_exception(exc, raw=getattr(exc, "raw", "") or "")
        return JSONResponse(
            status_code=exc.status_code, content=payload.http_body(exc.error_code))

    app.include_router(gen_routes.router, prefix="/api")
    return TestClient(app)


def _data_frames(frames):
    return [json.loads(f.removeprefix("data: ").strip()) for f in frames]


@pytest.mark.asyncio
async def test_terminal_task_replays_snapshot_and_closes(fake_tm):
    """订阅时任务已终态：立即回放快照并关流（连接晚于完成也不漏帧）"""
    fake_tm.tasks["img-1"] = {
        "status": "succeeded", "created_at": 1000.0, "elapsed": 4.2,
        "result": {"images": ["http://u/1.png"]}, "draft_id": "d1",
    }
    resp = await gen_routes.generate_events_for_task("img-1")
    frames = [f async for f in resp.body_iterator]
    assert len(frames) == 1
    data = _data_frames(frames)[0]
    assert data["task_id"] == "img-1"
    assert data["status"] == "succeeded"
    assert data["result"] == {"images": ["http://u/1.png"]}
    assert data["elapsed"] == 4.2
    assert fake_tm.subscribers == []  # 关流即退订，不残留广播订阅者


@pytest.mark.asyncio
async def test_missing_task_emits_failed_frame_and_closes(fake_tm):
    """任务不存在：下发失败帧立即关流（前端降级轮询拿 not_found，不挂死等）"""
    resp = await gen_routes.generate_events_for_task("ghost")
    frames = [f async for f in resp.body_iterator]
    data = _data_frames(frames)[0]
    assert data["status"] == "failed"
    assert data["task_id"] == "ghost"
    assert fake_tm.subscribers == []


@pytest.mark.asyncio
async def test_processing_task_filters_by_task_id_and_closes_on_terminal(fake_tm):
    """处理中任务：只转发本任务帧（他任务广播被滤除），终态即关流退订"""
    fake_tm.tasks["vid-1"] = {"status": "processing", "created_at": 1.0}
    resp = await gen_routes.generate_events_for_task("vid-1")

    async def driver():
        await asyncio.sleep(0.05)  # 让生成器先进入等待
        fake_tm.notify({"task_id": "other-1", "status": "succeeded"})
        fake_tm.notify({"task_id": "vid-1", "status": "started"})
        fake_tm.notify({"task_id": "vid-1", "status": "succeeded", "video_url": "http://u/v.mp4"})

    driver_task = asyncio.create_task(driver())
    frames = [f async for f in resp.body_iterator]
    await driver_task

    datas = _data_frames(frames)
    assert [d["task_id"] for d in datas] == ["vid-1", "vid-1"]  # other-1 被滤除
    assert datas[-1]["status"] == "succeeded"
    assert datas[-1]["video_url"] == "http://u/v.mp4"
    assert fake_tm.subscribers == []


def test_routes_registered_and_global_endpoint_retained():
    """按任务端点注册；全局广播端点暂留（待 generation-events 总线迁移后退役）"""
    paths = {getattr(r, "path", "") for r in gen_routes.router.routes}
    assert "/generate/events/{task_id}" in paths
    assert "/generate/events" in paths


def test_per_task_endpoint_streams_event_content_type(client, fake_tm):
    """HTTP 层冒烟：text/event-stream + 终态快照正文可达"""
    fake_tm.tasks["img-2"] = {"status": "failed", "created_at": 1.0, "elapsed": 7.7, "error": "boom"}
    with client.stream("GET", "/api/generate/events/img-2") as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        body = resp.read().decode("utf-8")
    assert body.startswith("data: ")
    payload = json.loads(body.removeprefix("data: ").strip())
    assert payload == {
        "task_id": "img-2", "status": "failed", "kind": "image",
        "draft_id": "", "elapsed": 7.7, "error": "boom",
    }


# ---------- 音频端点（2026-10-28 M1-M3） ----------

@pytest.mark.asyncio
async def test_audio_terminal_snapshot_carries_kind_and_url(fake_tm):
    """音频终态快照：kind=audio + audio_url 随帧下发（前端按 kind 写回 audioUrl）"""
    fake_tm.tasks["aud-1"] = {
        "status": "succeeded", "created_at": 1000.0, "elapsed": 3.0,
        "media_kind": "audio", "draft_id": "a1",
        "audio_url": "/workspace/assets/audio-1.mp3",
        "result": {"audio": "/workspace/assets/audio-1.mp3", "voice_id": "v-1"},
    }
    resp = await gen_routes.generate_events_for_task("aud-1")
    frames = [f async for f in resp.body_iterator]
    data = _data_frames(frames)[0]
    assert data["kind"] == "audio"
    assert data["audio_url"] == "/workspace/assets/audio-1.mp3"
    assert data["result"]["voice_id"] == "v-1"


@pytest.mark.asyncio
async def test_active_tasks_reports_audio_kind(fake_tm):
    fake_tm.tasks["aud-2"] = {
        "status": "processing", "draft_id": "a2",
        "media_kind": "audio", "created_at": 1.0,
    }
    out = await gen_routes.get_active_tasks()
    assert out["tasks"][0]["kind"] == "audio"
    assert out["tasks"][0]["draft_id"] == "a2"


def test_audio_route_registered_and_validates(client):
    """音频路由注册；缺供应商/未知通道 → 400（不落任务、不猜模型）。

    FastAPI 对 include_router 使用惰性占位（_IncludedRouter），故不在
    router.routes 上取 path 断言，改用 HTTP 语义：400=已注册且校验生效，404=未注册。
    """
    bad_channel = client.post("/api/generate/audio", json={
        "channel": "podcast", "provider_id": "custom-api-8", "model": "fun-music-v1",
    })
    assert bad_channel.status_code == 400
    assert "未知音频通道" in bad_channel.text

    no_provider = client.post("/api/generate/audio", json={
        "channel": "music", "provider_id": "", "model": "fun-music-v1",
    })
    assert no_provider.status_code == 400
    assert no_provider.json().get("error_code") == "PROVIDER_NOT_CONFIGURED", no_provider.text

    no_model = client.post("/api/generate/audio", json={
        "channel": "music", "provider_id": "custom-api-8", "model": "",
    })
    assert no_model.status_code == 400

