# -*- coding: utf-8 -*-
"""E1 回档三件套钉死测试：消息级快照（指针化）+ 版本列表 + 回档/分叉。

口径：消息存 snapshotId 指针、本体存 stateSnapshots（媒体只有 URL 指针，
不落二进制）；回档经 restore_snapshot 受控写面（自动压 undo 栈 → 可 Redo）；
生成中禁回退由 API 层非终态任务判定（409）。
"""
import pytest

from src.video_agent.state.manager import StateManager
from src.video_agent.state.models import CAT_SHOTS


@pytest.fixture
def svc(tmp_path):
    StateManager.reset_instance()
    s = StateManager(str(tmp_path / "ws"))
    yield s
    StateManager.reset_instance()


def _add_msg(svc, sender, text):
    svc.add_chat_message(sender, text)


def test_take_and_list_and_get_snapshot(svc):
    svc.state_dict[CAT_SHOTS] = [{"id": "g1", "drafts": []}]
    sid = svc.take_snapshot("v1")
    assert sid and len(sid) == 12
    lst = svc.list_snapshots()
    assert lst[0]["id"] == sid and lst[0]["label"] == "v1" and lst[0]["ts"]
    snap = svc.get_snapshot(sid)
    assert snap[CAT_SHOTS][0]["id"] == "g1"
    assert svc.get_snapshot("不存在") is None
    assert svc.get_snapshot("") is None


def test_snapshot_cap_evicts_oldest(svc):
    ids = [svc.take_snapshot(f"v{i}") for i in range(svc._MAX_SNAPSHOTS + 5)]
    lst = svc.list_snapshots()
    assert len(lst) == svc._MAX_SNAPSHOTS
    assert lst[0]["id"] == ids[5] and lst[-1]["id"] == ids[-1]


def test_attach_snapshot_to_last_agent_message(svc):
    _add_msg(svc, "user", "你好")
    _add_msg(svc, "agent", "第一轮回复")
    _add_msg(svc, "agent", "第二轮卡片")
    sid = svc.attach_snapshot_to_last_agent_message("轮次完成")
    msgs = svc.state_dict["chatMessages"]
    # 只挂最后一条 agent 消息，其余不挂
    assert msgs[-1]["snapshotId"] == sid
    assert "snapshotId" not in msgs[1]
    assert "snapshotId" not in msgs[0]


def test_restore_snapshot_roundtrip(svc):
    svc.state_dict[CAT_SHOTS] = [{"id": "g1", "drafts": []}]
    sid = svc.take_snapshot("回档点")
    svc.state_dict[CAT_SHOTS] = []  # 之后清空（模拟误删）
    assert svc.restore_snapshot(svc.get_snapshot(sid))
    assert svc.state_dict[CAT_SHOTS][0]["id"] == "g1"
    # 回档本身可撤销（恢复前压了 undo 栈）
    assert svc.can_undo


def test_fork_from_snapshot(svc):
    svc.state_dict[CAT_SHOTS] = [{"id": "g1", "drafts": []}]
    sid = svc.take_snapshot("分叉点")
    svc.state_dict[CAT_SHOTS] = []
    before = len(svc.list_projects()["projects"])
    pid = svc.fork_from_snapshot(sid, "分叉测试")
    assert pid and len(svc.list_projects()["projects"]) == before + 1
    # 新项目状态 = 快照时刻
    assert svc.state_dict[CAT_SHOTS][0]["id"] == "g1"
    assert svc.fork_from_snapshot("不存在") is None


def test_forbid_restore_while_generating(svc, monkeypatch):
    """E1 生成中禁回退：非终态任务在场 → 409 语义。"""
    from src.video_agent.web.routes import project as proj

    class _TM:
        def list_tasks(self, limit=50):
            return [{"status": "running"}]

    monkeypatch.setattr(proj, "get_task_manager", lambda: _TM())
    with pytest.raises(Exception) as exc:
        proj._forbid_restore_while_generating()
    assert getattr(exc.value, "status_code", None) == 409

    class _TMDone:
        def list_tasks(self, limit=50):
            return [{"status": "succeeded"}, {"status": "failed"}]

    monkeypatch.setattr(proj, "get_task_manager", lambda: _TMDone())
    proj._forbid_restore_while_generating()  # 全终态：不抛
