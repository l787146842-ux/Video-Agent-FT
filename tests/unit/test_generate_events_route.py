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
from fastapi import FastAPI
from fastapi.testclient import TestClient

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
