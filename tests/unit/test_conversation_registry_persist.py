# -*- coding: utf-8 -*-
"""8888 委派失踪批 · 批 A：隐藏线程落盘不得静默丢弃（状态层，P0）。

事故现场：子代理已跑出 27KB 事件流，但 `create_scoped_conversation` 忽略
`save()` 返回值——版本闸命中时新建的线程只活在内存，盘上 `conversations`
只剩 `conv-main` → `GET /api/conversations/subagents` 返空 → 左栏「还没有子任务」。

钉死契约（save_ops.save docstring：破坏性写入路径不得静默放行）：
1. save() 返 True → 正常落盘、不触发重放；
2. 首次 False、重放后 True → 磁盘保留对手方新内容 **且** conversations 含新线程；
3. 重放仍 False → 抛 StateConflictError（调用点既有语义：委派降级 / 路由 409）；
4. 重放幂等（磁盘已有同 id 不重复追加）；
5. 追加前 flush_save 被调用（内存 = 磁盘 + 本次追加 成立，重载不丢在途增量）。
"""
import pytest

from src.video_agent.exceptions import StateConflictError
from src.video_agent.state import conversation_ops, save_ops
from src.video_agent.state.manager import StateManager


def _scope(draft_id: str, group_id: str = "grp-1") -> dict:
    return {
        "kind": "adjust", "cat": "shotGroups",
        "group_id": group_id, "draft_id": draft_id, "label": f"分镜 {draft_id}",
    }


@pytest.fixture
def svc(tmp_path):
    StateManager.reset_instance()
    instance = StateManager(str(tmp_path / "ws"))
    del instance.get_chat_messages()[:]
    instance.save()
    StateManager._instance = instance
    yield instance
    StateManager.reset_instance()


def _reload_conv_ids(svc, pid):
    """从磁盘另起实例读回 conversations id（验证落盘事实，非内存态）。"""
    fresh = StateManager(str(svc._workspace_dir))
    fresh.switch_project(pid)
    return [
        c.get("id") for c in (fresh._raw_state.get("conversations") or [])
        if isinstance(c, dict)
    ]


def _bump_disk_via_rival(svc, marker_key="rival_marker"):
    """对手方实例：另一实例在同项目落一次盘，把磁盘账本推高，令 svc 的
    _known_version 过期 → 后续 svc.save() 撞版本闸（复刻 8888 双实例并发写）。"""
    rival = StateManager(str(svc._workspace_dir))
    if rival.active_project_id != svc.active_project_id:
        rival.switch_project(svc.active_project_id)
    rival._raw_state[marker_key] = "opponent-new-content"
    assert rival.save() is True
    return rival


# ---------- ① 正常落盘：save True → 不触发重放 ----------

def test_save_true_persists_thread_no_replay(svc, monkeypatch):
    replayed = []
    monkeypatch.setattr(
        conversation_ops, "_replay_conversation",
        lambda *a, **k: replayed.append(a) or False)

    thread = conversation_ops.create_scoped_conversation(svc, _scope("draft-1"))

    assert replayed == [], "save 成功不得走重放"
    assert thread["id"] in _reload_conv_ids(svc, svc.active_project_id)


# ---------- ② 冲突后重放：磁盘保留对手方内容 **且** 含新线程 ----------

def test_conflict_replay_keeps_opponent_and_adds_thread(svc):
    _bump_disk_via_rival(svc)  # svc._known_version 就此过期

    thread = conversation_ops.create_scoped_conversation(svc, _scope("draft-1"))

    disk_ids = _reload_conv_ids(svc, svc.active_project_id)
    assert thread["id"] in disk_ids, "重放后新线程必须落盘（不得静默丢弃）"
    fresh = StateManager(str(svc._workspace_dir))
    fresh.switch_project(svc.active_project_id)
    assert fresh._raw_state.get("rival_marker") == "opponent-new-content", \
        "以磁盘为基重放，不得抹掉对手方刚写入的内容"


# ---------- ③ 重放仍失败 → StateConflictError ----------

def test_replay_failure_raises_state_conflict(svc, monkeypatch):
    # 所有 save 一律被拒（模拟磁盘持续领先，重放也追不上）
    monkeypatch.setattr(save_ops, "save", lambda _svc: False)

    with pytest.raises(StateConflictError):
        conversation_ops.create_scoped_conversation(svc, _scope("draft-1"))


# ---------- ④ 重放幂等：磁盘已有同 id 不重复追加 ----------

def test_replay_idempotent_no_duplicate(svc, monkeypatch):
    thread = conversation_ops.create_scoped_conversation(svc, _scope("draft-1"))
    pid = svc.active_project_id

    # 磁盘态已含同 id 线程（对手方已登记），重放不得再追加一份
    loaded = svc._repo.load_project(pid)
    existing_ids = [c.get("id") for c in (loaded.get("conversations") or [])
                    if isinstance(c, dict)]
    assert thread["id"] in existing_ids  # 上一步已落盘

    before = len(loaded.get("conversations") or [])
    monkeypatch.setattr(save_ops, "save", lambda _svc: True)  # 放行看合并结果
    ok = conversation_ops._replay_conversation(svc, thread)
    assert ok is True
    after = len(svc._raw_state.get("conversations") or [])
    assert after == before, "同 id 已存在时重放须幂等、不重复追加"


# ---------- ⑤ 追加前 flush_save 被调用 ----------

def test_flush_before_append(svc, monkeypatch):
    seen = {}

    def _spy_flush(_svc):
        # flush 发生时，本次新线程尚未追加（内存里不该已含目标 conv）
        seen["convs_at_flush"] = [
            c.get("id") for c in (
                conversation_ops.ensure_conversations(_svc) or [])
            if isinstance(c, dict)
        ]

    monkeypatch.setattr(save_ops, "flush_save", _spy_flush)
    thread = conversation_ops.create_scoped_conversation(svc, _scope("draft-1"))

    assert "convs_at_flush" in seen, "落盘前须先 flush_save 冲刷在途防抖写"
    assert thread["id"] not in seen["convs_at_flush"], \
        "flush 必须早于本次追加（否则重载会丢在途增量）"
