# -*- coding: utf-8 -*-
"""资产只读盘点脚本（scripts/audit_assets.py，任务 #9 E-3）单测。

钉死契约：
- 引用判定以 /workspace/assets/<文件名> 出现在来源文本为准；
- 来源覆盖：workspace/projects/*/state.json、workspace/state.sqlite3
  （projects.state 与 kv['generation_tasks']）、data/generation_tasks.json、
  workspace/snapshots/**/*.json；
- 孤儿 = 无任何来源引用；
- 纯只读：盘点前后资产文件数量不变（dry-run 唯一模式）。
"""
import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "audit_assets.py"


@pytest.fixture(scope="module")
def audit_mod():
    spec = importlib.util.spec_from_file_location("audit_assets_under_test", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def fake_root(tmp_path):
    """构造工作区：3 个资产（a 被项目状态+任务表引用，c 被快照引用，b 孤儿）。"""
    assets = tmp_path / "workspace" / "assets"
    assets.mkdir(parents=True)
    (assets / "a.png").write_bytes(b"x" * 100)
    (assets / "b.png").write_bytes(b"y")
    (assets / "c.mp4").write_bytes(b"z" * 5000)

    proj = tmp_path / "workspace" / "projects" / "p1"
    proj.mkdir(parents=True)
    (proj / "state.json").write_text(
        json.dumps({"url": "/workspace/assets/a.png"}), encoding="utf-8")

    snap = tmp_path / "workspace" / "snapshots" / "p1"
    snap.mkdir(parents=True)
    (snap / "snap-1.json").write_text(
        json.dumps({"messages": [{"url": "/workspace/assets/c.mp4"}]}),
        encoding="utf-8")

    data = tmp_path / "data"
    data.mkdir()
    (data / "generation_tasks.json").write_text(
        json.dumps({"tasks": [{"result_url": "/workspace/assets/a.png"}]}),
        encoding="utf-8")
    return tmp_path


def test_audit_counts_refs_and_orphans(audit_mod, fake_root):
    report = audit_mod.audit(fake_root)
    assert report["total"] == 3
    assert report["orphans"] == ["b.png"]
    assert report["orphan_count"] == 1
    # a.png：项目状态 JSON 镜像 + 停写任务表两个来源
    assert sorted(report["ref_labels"]["a.png"]) == ["任务表", "项目状态"]
    # c.mp4：快照来源，按项目目录归类
    assert report["ref_labels"]["c.mp4"] == ["快照:p1"]
    assert report["proj_refs"] == {"p1": 1}


def test_audit_reads_sqlite_sources(audit_mod, tmp_path):
    """sqlite 事实源：projects.state 与 kv['generation_tasks'] 均计入引用。"""
    assets = tmp_path / "workspace" / "assets"
    assets.mkdir(parents=True)
    (assets / "s.png").write_bytes(b"x")
    (assets / "t.mp4").write_bytes(b"y")
    (assets / "orphan.png").write_bytes(b"z")

    db = tmp_path / "workspace" / "state.sqlite3"
    conn = sqlite3.connect(db)
    conn.executescript(
        "CREATE TABLE projects (id TEXT PRIMARY KEY, state TEXT, updated_at REAL);"
        "CREATE TABLE kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);")
    conn.execute(
        "INSERT INTO projects VALUES (?, ?, 0)",
        ("p9", json.dumps({"videoUrl": "/workspace/assets/s.png"})))
    conn.execute(
        "INSERT INTO kv VALUES (?, ?)",
        ("generation_tasks",
         json.dumps({"tasks": [{"video_url": "/workspace/assets/t.mp4"}]})))
    conn.commit()
    conn.close()

    report = audit_mod.audit(tmp_path)
    assert report["orphans"] == ["orphan.png"]
    assert report["ref_labels"]["s.png"] == ["项目状态:p9"]
    assert report["ref_labels"]["t.mp4"] == ["任务表"]


def test_audit_is_read_only(audit_mod, fake_root):
    before = sorted(p.name for p in (fake_root / "workspace" / "assets").iterdir())
    audit_mod.audit(fake_root)
    after = sorted(p.name for p in (fake_root / "workspace" / "assets").iterdir())
    assert before == after


def test_main_report_contains_summary(audit_mod, fake_root, capsys):
    code = audit_mod.main(["--root", str(fake_root)])
    assert code == 0
    out = capsys.readouterr().out
    assert "资产总数: 3" in out
    assert "孤儿资产（无任何引用）: 1" in out
    assert "b.png" in out


def test_audit_missing_dirs_is_safe(audit_mod, tmp_path):
    """空目录（无 workspace）：零资产零孤儿，不抛异常。"""
    report = audit_mod.audit(tmp_path)
    assert report["total"] == 0
    assert report["orphan_count"] == 0
