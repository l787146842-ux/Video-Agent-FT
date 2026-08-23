# -*- coding: utf-8 -*-
"""快照数量上限（任务 #9 E-3）：每项目快照超限后创建时淘汰最旧。

钉死契约：
- 上限可配（settings.snapshot_max_per_project，默认 20）；
- 超限时按 created_at 升序淘汰最旧，新创建的快照必保留；
- 损坏/缺 created_at 的快照视为最旧，优先被淘汰；
- 未超限不淘汰任何快照。
"""
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.video_agent.state.manager import StateManager


@pytest.fixture
def svc(tmp_path):
    StateManager.reset_instance()
    instance = StateManager(str(tmp_path / "ws"))
    del instance.get_chat_messages()[:]
    instance.save()
    StateManager._instance = instance
    yield instance
    StateManager.reset_instance()


@pytest.fixture
def snap_mod():
    import src.video_agent.web.routes.snapshots as snapshots_mod
    return snapshots_mod


@pytest.fixture
def client(svc, tmp_path, monkeypatch, snap_mod):
    import src.video_agent.web.routes.conversations as conv_mod

    monkeypatch.setattr(snap_mod, "WORKSPACE_DIR", tmp_path / "snaps")
    app = FastAPI()
    app.include_router(conv_mod.router, prefix="/api")
    app.include_router(snap_mod.router, prefix="/api")
    return TestClient(app)


def _seed_messages(svc, n=2):
    for i in range(n):
        svc.add_chat_message("user" if i % 2 == 0 else "agent", f"消息{i}")


def _snap_files(snap_mod, svc):
    return list(snap_mod._snap_dir(svc.active_project_id or "").glob("*.json"))


def _rewrite_created_at(files, base=1000.0):
    """按文件顺序赋递增 created_at，消除同秒创建的时间戳歧义。"""
    for i, f in enumerate(files):
        data = json.loads(f.read_text(encoding="utf-8"))
        data["created_at"] = base + i
        f.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_cap_evicts_oldest_keeps_newest(client, svc, snap_mod, set_global_setting):
    set_global_setting("snapshot_max_per_project", 3)
    _seed_messages(svc)
    for _ in range(5):
        assert client.post("/api/conversations/snapshot").status_code == 200
    _rewrite_created_at(sorted(_snap_files(snap_mod, svc),
                               key=lambda p: p.stat().st_mtime))

    # 第 6 个快照触发淘汰：5+1 → 保留最新 3 个
    r = client.post("/api/conversations/snapshot")
    assert r.status_code == 200
    new_id = r.json()["snap_id"]

    files = _snap_files(snap_mod, svc)
    assert len(files) == 3
    ids = {json.loads(f.read_text(encoding="utf-8"))["snap_id"] for f in files}
    assert new_id in ids  # 新快照永不被当次淘汰


def test_below_cap_evicts_nothing(client, svc, snap_mod, set_global_setting):
    set_global_setting("snapshot_max_per_project", 5)
    _seed_messages(svc)
    for _ in range(4):
        assert client.post("/api/conversations/snapshot").status_code == 200
    assert len(_snap_files(snap_mod, svc)) == 4


def test_prune_treats_corrupt_snapshot_as_oldest(svc, snap_mod, tmp_path, monkeypatch,
                                                 set_global_setting):
    monkeypatch.setattr(snap_mod, "WORKSPACE_DIR", tmp_path / "snaps")
    set_global_setting("snapshot_max_per_project", 2)
    d = snap_mod._snap_dir(svc.active_project_id or "")
    # 损坏快照（非法 JSON）+ 两个正常快照
    (d / "snap-broken.json").write_text("{not-json", encoding="utf-8")
    for i, sid in enumerate(("snap-old", "snap-new")):
        (d / f"{sid}.json").write_text(json.dumps(
            {"snap_id": sid, "created_at": 2000.0 + i}), encoding="utf-8")

    removed = snap_mod._prune_snapshots(svc.active_project_id or "")
    assert removed == 1
    left = {f.stem for f in d.glob("*.json")}
    assert left == {"snap-old", "snap-new"}  # 损坏文件被淘汰


def test_default_cap_is_20(snap_mod):
    from src.video_agent.config import settings
    assert settings.snapshot_max_per_project == 20
