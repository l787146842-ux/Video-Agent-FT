# -*- coding: utf-8 -*-
"""快照数量上限（任务 #9 E-3）：每项目快照超限后创建时淘汰最旧。

钉死契约：
- 上限可配（settings.snapshot_max_per_project，默认 20）；
- 超限时按创建时间升序淘汰最旧，新创建的快照必保留；
- 创建时间优先文件名编码（snap-<ts>-<rand>），回落正文 created_at；
- 损坏/缺 created_at 的快照视为最旧，优先被淘汰；
- 未超限不淘汰任何快照；
- pinned 快照豁免淘汰（旁路索引 _pinned.json）；
- 创建响应带 pruned 清单（淘汰对用户可见，契约恒为列表）。
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


def test_cap_evicts_oldest_keeps_newest(client, svc, snap_mod, set_global_setting):
    set_global_setting("snapshot_max_per_project", 3)
    _seed_messages(svc)
    # 播种 5 个存量快照（文件名编码时间戳递增 = 旧→新）
    _seed_snap_files(snap_mod, svc,
                     [f"snap-{1000 + i}-{'%08x' % (0xa0000000 + i)}" for i in range(5)])

    # 新建快照（文件名时间戳 = 当前时间，必为最新）触发淘汰：6 → 保留最新 3 个
    r = client.post("/api/conversations/snapshot")
    assert r.status_code == 200
    new_id = r.json()["snap_id"]
    # 淘汰清单随响应带回：本次淘汰 3 个最旧
    assert r.json()["pruned"] == [f"snap-{1000 + i}-{'%08x' % (0xa0000000 + i)}"
                                    for i in range(3)]

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
    assert len(removed) == 1
    assert removed == ["snap-broken"]
    left = {f.stem for f in d.glob("*.json")}
    assert left == {"snap-old", "snap-new"}  # 损坏文件被淘汰


def test_default_cap_is_20(snap_mod):
    from src.video_agent.config import settings
    assert settings.snapshot_max_per_project == 20


def _seed_snap_files(snap_mod, svc, stems):
    """按给定文件名（含编码时间戳）播种快照文件，顺序 = 旧→新。"""
    d = snap_mod._snap_dir(svc.active_project_id or "")
    for i, stem in enumerate(stems):
        (d / f"{stem}.json").write_text(json.dumps(
            {"snap_id": stem, "created_at": 1000.0 + i}), encoding="utf-8")
    return d


def test_prune_returns_pruned_id_list(svc, snap_mod, monkeypatch, tmp_path,
                                      set_global_setting):
    """淘汰清单契约：_prune_snapshots 返回被淘汰的快照 id 列表。"""
    monkeypatch.setattr(snap_mod, "WORKSPACE_DIR", tmp_path / "snaps")
    set_global_setting("snapshot_max_per_project", 2)
    _seed_snap_files(snap_mod, svc,
                     ["snap-1000-aaaaaaa1", "snap-1001-bbbbbb22", "snap-1002-cccccc33"])
    removed = snap_mod._prune_snapshots(svc.active_project_id or "")
    assert removed == ["snap-1000-aaaaaaa1"]  # 文件名时间戳最旧者


def test_pinned_exempt_from_eviction(svc, snap_mod, monkeypatch, tmp_path,
                                     set_global_setting):
    """pinned 豁免：即使最旧也不被淘汰；淘汰穿透到次旧的非 pinned 快照。"""
    monkeypatch.setattr(snap_mod, "WORKSPACE_DIR", tmp_path / "snaps")
    set_global_setting("snapshot_max_per_project", 2)
    stems = ["snap-1000-pinned01", "snap-1001-bbbbbb22", "snap-1002-cccccc33",
             "snap-1003-dddddd44"]
    d = _seed_snap_files(snap_mod, svc, stems)
    snap_mod._save_pinned_index(d, {"snap-1000-pinned01"})
    removed = snap_mod._prune_snapshots(svc.active_project_id or "")
    assert "snap-1000-pinned01" not in removed
    left = {f.stem for f in snap_mod._snap_files(d)}
    assert "snap-1000-pinned01" in left  # pinned 最旧仍保留
    assert len(removed) == 2  # 4 个 → 上限 2，pinned 占一名额


def test_create_response_contract_pruned(client, svc, snap_mod, set_global_setting):
    """创建响应契约：pruned 恒为列表（未触发淘汰 = 空列表）。"""
    set_global_setting("snapshot_max_per_project", 5)
    _seed_messages(svc)
    r = client.post("/api/conversations/snapshot")
    assert r.status_code == 200
    body = r.json()
    assert set(body) >= {"snap_id", "title", "pruned"}
    assert body["pruned"] == []


def test_create_pinned_and_list_shows_pinned(client, svc, snap_mod,
                                             set_global_setting):
    """手动创建带 pinned：写入旁路索引，列表返回 pinned=true；
    删除后索引同步清理。"""
    set_global_setting("snapshot_max_per_project", 10)
    _seed_messages(svc)
    r = client.post("/api/conversations/snapshot", json={"pinned": True})
    assert r.status_code == 200
    snap_id = r.json()["snap_id"]
    d = snap_mod._snap_dir(svc.active_project_id or "")
    assert snap_id in snap_mod._pinned_index(d)
    listing = client.get("/api/conversations/snapshots").json()["snapshots"]
    entry = next(s for s in listing if s["snap_id"] == snap_id)
    assert entry["pinned"] is True
    # 删除快照 → 旁路索引同步移除
    assert client.delete(f"/api/conversations/snapshots/{snap_id}").status_code == 200
    assert snap_id not in snap_mod._pinned_index(d)


def test_filename_timestamp_beats_body_created_at(svc, snap_mod, monkeypatch,
                                                  tmp_path, set_global_setting):
    """排序优先文件名编码时间戳：正文 created_at 与文件名矛盾时以文件名为准。"""
    monkeypatch.setattr(snap_mod, "WORKSPACE_DIR", tmp_path / "snaps")
    set_global_setting("snapshot_max_per_project", 1)
    d = snap_mod._snap_dir(svc.active_project_id or "")
    # 文件名旧（999）但正文新；文件名新（2000）但正文旧 → 淘汰文件名旧者
    (d / "snap-999-aaaaaaa1.json").write_text(json.dumps(
        {"snap_id": "x", "created_at": 9999.0}), encoding="utf-8")
    (d / "snap-2000-bbbbbb22.json").write_text(json.dumps(
        {"snap_id": "y", "created_at": 1.0}), encoding="utf-8")
    removed = snap_mod._prune_snapshots(svc.active_project_id or "")
    assert removed == ["snap-999-aaaaaaa1"]
