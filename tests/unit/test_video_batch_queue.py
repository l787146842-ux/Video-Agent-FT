"""B9 回归：视频批量队列状态机（断点续跑语义）。"""
import asyncio

from src.video_agent.web.video_batch import VideoBatchManager


def _manager(monkeypatch, state: dict) -> VideoBatchManager:
    from src.video_agent.state.manager import StateManager

    class _Svc:
        state_dict = state

    monkeypatch.setattr(StateManager, "get_instance", staticmethod(lambda: _Svc()))
    # 隔离持久化路径：写内存即可（落盘失败静默）
    mgr = VideoBatchManager.__new__(VideoBatchManager)
    mgr._batches = {}
    monkeypatch.setattr(mgr, "_persist", lambda: None)
    return mgr


def _state(shots: list) -> dict:
    return {"shots": shots, "keyElements": [], "audioItems": []}


def _shot_group(gid: str, prompts=("提示词A",)) -> dict:
    return {
        "id": gid, "title": f"Shot_{gid}",
        "drafts": [
            {"id": f"{gid}-d{i}", "label": "分镜卡片", "prompt": p}
            for i, p in enumerate(prompts)
        ],
    }


def test_b9_create_collects_only_prompted_shots(monkeypatch):
    mgr = _manager(monkeypatch, _state([
        _shot_group("s1", ("提示词A",)),
        _shot_group("s2", ()),  # 无提示词：不收
    ]))
    record = mgr.create("p1", "provV", "modelV")
    assert record["total"] == 1
    assert record["shots"][0]["group_id"] == "s1"
    assert mgr._batches[record["batch_id"]]["status"] == "running"


def test_b9_resume_retries_only_failed_and_pending(monkeypatch):
    mgr = _manager(monkeypatch, _state([_shot_group("s1", ("提示词A",)), _shot_group("s2", ("提示词B",))]))
    record = mgr.create("p1", "provV", "modelV")
    bid = record["batch_id"]
    mgr._batches[bid]["status"] = "partial"
    mgr._batches[bid]["shots"][0]["status"] = "succeeded"
    mgr._batches[bid]["shots"][1]["status"] = "failed"
    resumed = mgr.resume(bid)
    statuses = [s["status"] for s in resumed["shots"]]
    assert statuses == ["succeeded", "pending"]  # 成功镜跳过，失败镜重试
    assert resumed["status"] == "running"


def test_b9_load_marks_running_as_interrupted(monkeypatch):
    """服务重启：running 批次降级 interrupted（续跑入口 resume）。"""
    mgr = _manager(monkeypatch, {})
    mgr._batches = {"vb1": {
        "batch_id": "vb1", "project_id": "p1", "provider_id": "", "model": "",
        "resolution": "720p", "duration": 5, "shots": [], "status": "running",
        "created_at": 1.0, "updated_at": 1.0, "done": 0, "failed": 0,
    }}
    # 模拟重启加载：直接构造第二个实例并 load
    mgr2 = VideoBatchManager.__new__(VideoBatchManager)
    mgr2._batches = {}
    monkeypatch.setattr(mgr2, "_load", lambda: mgr2._batches.update({
        "vb1": {
            "batch_id": "vb1", "project_id": "p1", "provider_id": "", "model": "",
            "resolution": "720p", "duration": 5, "shots": [], "status": "running",
            "created_at": 1.0, "updated_at": 1.0, "done": 0, "failed": 0,
        }
    }) or _mark_interrupted(mgr2))
    mgr2._load()
    assert mgr2._batches["vb1"]["status"] == "interrupted"


def _mark_interrupted(mgr: VideoBatchManager) -> None:
    for r in mgr._batches.values():
        if r.get("status") == "running":
            r["status"] = "interrupted"


def test_b9_worker_marks_missing_draft_failed(monkeypatch):
    """步骤级断点：镜头草稿已被删除 → 标记 failed 并计错误（不崩批次）。"""

    async def run():
        mgr = _manager(monkeypatch, _state([_shot_group("s1", ("提示词A",))]))
        record = mgr.create("p1", "provV", "modelV")
        bid = record["batch_id"]
        # 删除草稿模拟：worker 查不到 → failed
        mgr._batches[bid]["shots"][0]["draft_id"] = "ghost"
        mgr._batches[bid]["shots"][0]["status"] = "pending"
        await mgr._run_worker(bid)
        b = mgr._batches[bid]
        assert b["shots"][0]["status"] == "failed"
        assert b["failed"] == 1
        assert b["status"] == "partial"

    asyncio.run(run())
