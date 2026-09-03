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
    mgr._batches[bid]["done"] = 1
    mgr._batches[bid]["failed"] = 1
    resumed = mgr.resume(bid)
    statuses = [s["status"] for s in resumed["shots"]]
    assert statuses == ["succeeded", "pending"]  # 成功镜跳过，失败镜重试
    assert resumed["status"] == "running"
    # 计数器按当前镜态重算：本轮口径 done=1 / failed=0（续跑全成功终态为 done）
    assert resumed["done"] == 1
    assert resumed["failed"] == 0


def test_b9_load_marks_running_batch_and_orphan_running_shots_interrupted(monkeypatch, tmp_path):
    """服务重启（真实 _load 读落盘文件）：running 批次 → interrupted，
    重启瞬间卡在 running 的镜 → interrupted（resume 可重试，不永久卡死）。"""
    import json

    import src.video_agent.web.video_batch as vb_mod

    persist = tmp_path / "video_batch_tasks.json"
    persist.write_text(json.dumps({"batches": [{
        "batch_id": "vb1", "project_id": "p1", "provider_id": "", "model": "",
        "resolution": "720p", "duration": 5, "status": "running",
        "created_at": 1.0, "updated_at": 1.0, "done": 1, "failed": 0,
        "shots": [
            {"group_id": "s1", "draft_id": "s1-d0", "title": "A",
             "status": "succeeded", "task_id": "t1", "error": ""},
            {"group_id": "s2", "draft_id": "s2-d0", "title": "B",
             "status": "running", "task_id": "", "error": ""},  # 重启瞬间正在提交
            {"group_id": "s3", "draft_id": "s3-d0", "title": "C",
             "status": "pending", "task_id": "", "error": ""},
        ],
    }]}, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(vb_mod, "_PERSIST_PATH", persist)

    mgr = VideoBatchManager.__new__(VideoBatchManager)
    mgr._batches = {}
    mgr._load()

    b = mgr._batches["vb1"]
    assert b["status"] == "interrupted"
    statuses = [s["status"] for s in b["shots"]]
    assert statuses == ["succeeded", "interrupted", "pending"]
    # 续跑：卡死的镜被重试
    resumed = mgr.resume("vb1")
    assert [s["status"] for s in resumed["shots"]] == ["succeeded", "pending", "pending"]
    assert resumed["done"] == 1
    assert resumed["failed"] == 0


def test_b9_cancel_normalizes_orphan_running_shot(monkeypatch):
    """取消时卡在 running 的镜（上一次崩溃遗留）→ interrupted，可再次续跑。"""
    mgr = _manager(monkeypatch, _state([_shot_group("s1", ("提示词A",))]))
    record = mgr.create("p1", "provV", "modelV")
    bid = record["batch_id"]
    mgr._batches[bid]["status"] = "running"
    mgr._batches[bid]["shots"][0]["status"] = "running"  # 模拟旧崩溃遗留
    assert mgr.cancel(bid) is True
    assert mgr._batches[bid]["status"] == "cancelled"
    assert mgr._batches[bid]["shots"][0]["status"] == "interrupted"
    resumed = mgr.resume(bid)
    assert resumed["shots"][0]["status"] == "pending"
    assert resumed["status"] == "running"


def test_b9_resume_then_full_success_ends_done(monkeypatch):
    """续跑后本轮全部提交成功：终态 done（修复计数器累计导致的 partial 误标）。"""

    async def run():
        mgr = _manager(monkeypatch, _state([_shot_group("s1", ("提示词A",))]))
        record = mgr.create("p1", "provV", "modelV")
        bid = record["batch_id"]
        mgr._batches[bid]["status"] = "interrupted"
        mgr._batches[bid]["shots"][0]["status"] = "failed"
        mgr._batches[bid]["failed"] = 1
        import src.video_agent.web.generation as gen_mod

        monkeypatch.setattr(
            gen_mod, "collect_shot_video_refs", lambda state, group, draft: ([], []))
        monkeypatch.setattr(
            gen_mod, "submit_video_task",
            lambda *a, **k: "task-new")
        # 走真实 resume 入口：归一卡死镜 + 重置计数 + status=running
        #（worker 只在 running 态工作；本测试同步上下文 _spawn_worker 静默跳过，
        # 由下方手动驱动 _run_worker 模拟后台执行）
        mgr.resume(bid)
        await mgr._run_worker(bid)
        b = mgr._batches[bid]
        assert b["shots"][0]["status"] == "succeeded"
        assert b["failed"] == 0
        assert b["status"] == "done"  # 非 partial

    asyncio.run(run())


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
