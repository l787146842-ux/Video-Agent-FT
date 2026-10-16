# -*- coding: utf-8 -*-
"""9999 事故：子代理隐藏线程泄漏进主会话标签栏（可见性单点 + 活跃对话不变量）。

现场（9999 = proj-1790513490-8468602e）：18 条 `scope.kind='subagent'` 的隐藏
线程被渲染成右侧会话标签页，且 `activeConversationId` 指向其中一条隐藏线程
（主面板显示空线程、标签栏无对应高亮）。根因 = 「哪些对话对用户可见」这条
判据有两处分身：`conversations_meta_payload` 过滤了 scope，而
`build_full_snapshot`（前端标签栏的真实数据源 `/api/project/state`）没有。

钉死契约：
1. 可见性单点 `conversation_ops.is_visible_conversation` 是唯一判据，
   `visible_conversations` 是唯一取数面；
2. **快照面与 meta 面口径一致**：`build_full_snapshot().conversations` 与
   `conversations_meta_payload()['conversations']` 对任意状态给出同一组 id
   （回归本事故：此后任何一面漏过滤即 FAIL）；
3. 子代理线程照常经 `subagent_threads` 暴露（不得因修显示而丢清单/只读记录）；
4. `ensure_conversations` 不变量：活跃位落在隐藏线程时自愈回落到首个可见对话，
   `chatMessages` 随之重绑；全部对话都是隐藏线程时补建可见会话（不出现
   「无会话」态）；
5. `switch_conversation` 拒切隐藏线程（路由仍 404）、`delete_conversation`
   回落取首个**可见**对话（不把活跃位写回隐藏线程）。
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.video_agent.state import conversation_ops
from src.video_agent.state.manager import StateManager

_SUB_SCOPE = {
    "kind": "subagent", "parent_conversation": "conv-main",
    "subagent_kind": "stage:script_analyze", "label": "素材分析",
}
_ADJUST_SCOPE = {
    "kind": "adjust", "cat": "shotGroups",
    "group_id": "grp-1", "draft_id": "draft-1", "label": "分镜 1-2",
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


@pytest.fixture
def client(svc):
    import src.video_agent.web.routes.conversations as conv_mod
    from src.video_agent.exceptions import VideoAgentError
    from src.video_agent.web.app import video_agent_error_handler

    app = FastAPI()
    app.include_router(conv_mod.router, prefix="/api")
    app.add_exception_handler(VideoAgentError, video_agent_error_handler)
    return TestClient(app)


def _seed_threads(svc, n_sub=3):
    """建 n_sub 条子代理隐藏线程 + 1 条微调隐藏线程；返回子线程 id 清单。"""
    subs = [
        conversation_ops.create_scoped_conversation(
            svc, _SUB_SCOPE, title="子代理")["id"]
        for _ in range(n_sub)
    ]
    conversation_ops.create_scoped_conversation(svc, _ADJUST_SCOPE, title="微调 | 分镜 1-2")
    return subs


# ---------- 1. 单点判据本体 ----------

def test_is_visible_conversation_single_predicate():
    """唯一判据：不带 scope 键可见；带 scope（任意 kind，含空 dict 壳）不可见；
    非 dict 不可见。与 scoped_threads_payload / find_scoped_conversation 同源。"""
    assert conversation_ops.is_visible_conversation({"id": "c1", "title": "会话"}) is True
    assert conversation_ops.is_visible_conversation({"id": "c2", "scope": _SUB_SCOPE}) is False
    assert conversation_ops.is_visible_conversation({"id": "c3", "scope": _ADJUST_SCOPE}) is False
    # 空 dict scope（退化/空壳）同样视为隐藏线程：判据是「scope 是不是 dict」
    assert conversation_ops.is_visible_conversation({"id": "c4", "scope": {}}) is False
    assert conversation_ops.is_hidden_thread({"id": "c4", "scope": {}}) is True
    # 非 dict scope（存量脏值）不算线程，仍可见——两判据互补且不重叠
    assert conversation_ops.is_visible_conversation({"id": "c5", "scope": "x"}) is True
    assert conversation_ops.is_visible_conversation(None) is False
    assert conversation_ops.is_visible_conversation("c5") is False
    # is_hidden_thread / is_visible_conversation 互补（对 dict 输入恒真）
    for probe in ({"id": "a"}, {"id": "b", "scope": _SUB_SCOPE}, {"id": "c", "scope": {}}):
        assert (conversation_ops.is_hidden_thread(probe)
                != conversation_ops.is_visible_conversation(probe))


def test_visible_conversations_excludes_all_hidden_threads(svc):
    _seed_threads(svc)
    visible = conversation_ops.visible_conversations(svc)
    assert len(visible) == 1
    assert not visible[0].get("scope")
    assert all(not c.get("scope") for c in visible)


# ---------- 2. 快照面与 meta 面口径一致（本事故的回归钉） ----------

def _ids(payload_convs):
    return sorted(str(c.get("id") or "") for c in payload_convs)


def test_snapshot_and_meta_agree_on_visible_set(svc):
    """两个消费面必须给出同一组可见对话 id——任一面漏过滤即 FAIL。"""
    _seed_threads(svc)
    meta_ids = _ids(svc.conversations_meta_payload()["conversations"])
    snap_ids = _ids(svc.get_full_snapshot()["conversations"])
    assert snap_ids == meta_ids, (
        "快照面与 meta 面对「可见对话」口径不一致："
        f"meta={meta_ids} snapshot={snap_ids}")


def test_full_snapshot_has_no_subagent_threads(svc):
    """事故现场复现：子代理线程不得出现在快照 conversations 里。"""
    subs = _seed_threads(svc)
    snap_ids = _ids(svc.get_full_snapshot()["conversations"])
    for cid in subs:
        assert cid not in snap_ids, f"子代理线程 {cid} 泄漏进快照 conversations"
    # 真会话（无 scope）照常在快照里，且只留元信息（消息副本仍不上快照）
    assert len(snap_ids) == 1
    for c in svc.get_full_snapshot()["conversations"]:
        assert "messages" not in c


def test_visibility_filter_does_not_touch_raw_state(svc):
    """过滤只在投影层：raw state 的隐藏线程一条不少（子任务面板仍要读）。"""
    subs = _seed_threads(svc)
    svc.get_full_snapshot()
    svc.conversations_meta_payload()
    raw_ids = [c.get("id") for c in svc.state_dict["conversations"]]
    for cid in subs:
        assert cid in raw_ids


# ---------- 3. 隐藏线程的专用清单面不受影响 ----------

def test_subagent_threads_still_exposed(svc):
    """修显示不得顺手丢清单：子代理线程仍经 subagent_threads 暴露。"""
    subs = _seed_threads(svc)
    threads = svc.subagent_threads()
    assert sorted(t["conversation_id"] for t in threads) == sorted(subs)
    # 且每条仍带展示名与父会话（子任务面板卡面数据源）
    for t in threads:
        assert t["label"] == "素材分析"
        assert t["parent_conversation"] == "conv-main"


def test_scoped_threads_payload_still_exposed(svc):
    """微调线程同样不受影响（角标/浮窗重开数据源）。"""
    _seed_threads(svc)
    threads = svc.scoped_threads_payload()["threads"]
    assert len(threads) == 4  # 3 子代理 + 1 微调
    assert any(t["scope"].get("kind") == "adjust" for t in threads)


# ---------- 4. 活跃对话不变量（activeConversationId 落隐藏线程的自愈） ----------

def test_active_on_hidden_thread_heals_to_visible(svc):
    """活跃位落在子代理线程时（9999 现场）自愈回落到可见会话并重绑 chatMessages。"""
    subs = _seed_threads(svc)
    svc.state_dict["activeConversationId"] = subs[0]
    svc.state_dict["chatMessages"] = []
    conversation_ops.ensure_conversations(svc)
    active = svc.state_dict["activeConversationId"]
    assert active not in subs
    hit = next(c for c in svc.state_dict["conversations"] if c["id"] == active)
    assert not hit.get("scope")
    # 不变式 ① 仍成立：chatMessages 是活跃对话 messages 的同一引用
    assert svc.state_dict["chatMessages"] is hit["messages"]


def test_active_on_hidden_thread_heals_on_load(svc, tmp_path):
    """持久化态即脏（落盘的就是隐藏线程活跃位）时，重载同样自愈。"""
    subs = _seed_threads(svc)
    svc.state_dict["activeConversationId"] = subs[-1]
    svc.save()

    StateManager.reset_instance()
    reloaded = StateManager(str(tmp_path / "ws"))  # 同一 workspace 重载
    try:
        reloaded._ensure_conversations()
        assert reloaded.state_dict["activeConversationId"] not in subs
        assert reloaded.state_dict["chatMessages"] is not None
    finally:
        StateManager.reset_instance()


def test_all_hidden_threads_creates_visible_fallback(svc):
    """极端态：全部对话都是隐藏线程 → 补建可见会话（用户面板没有「无会话」态）。"""
    convs = svc.state_dict["conversations"]
    for c in convs:
        c["scope"] = dict(_SUB_SCOPE)
    svc.state_dict["activeConversationId"] = convs[0]["id"]
    conversation_ops.ensure_conversations(svc)
    visible = conversation_ops.visible_conversations(svc)
    assert len(visible) == 1
    assert svc.state_dict["activeConversationId"] == visible[0]["id"]


# ---------- 5. 切换/删除的可见性守卫 ----------

def test_switch_to_hidden_thread_rejected(svc):
    """隐藏线程不可成为活跃位；接口层仍 404（不暴露隐藏线程存在性）。"""
    subs = _seed_threads(svc)
    assert svc.switch_conversation(subs[0]) is None


def test_switch_endpoint_to_hidden_thread_404(client, svc):
    subs = _seed_threads(svc)
    assert client.post(f"/api/conversations/{subs[0]}/activate").status_code == 404


def test_delete_falls_back_to_visible_not_index_zero(svc):
    """删除活跃对话后的回落必须是**可见**对话：子代理线程占据数组第 0 位
    （9999 现场数组正是子线程在前）时，旧实现 `convs[0]` 会把活跃位写回隐藏线程。"""
    subs = _seed_threads(svc)
    # 让隐藏线程排在数组最前（9999 现场顺序）
    svc.state_dict["conversations"].sort(
        key=lambda c: 0 if c.get("id") in subs else 1)
    assert svc.state_dict["conversations"][0]["id"] in subs
    payload = svc.create_conversation("会话2")
    second = payload["active_conversation_id"]
    assert second not in subs
    # 删掉当前活跃的会话2 → 回落；第 0 位是子代理线程，不得回落上去
    svc.delete_conversation(second)
    active = svc.state_dict["activeConversationId"]
    assert active not in subs
    hit = next(c for c in svc.state_dict["conversations"] if c["id"] == active)
    assert not hit.get("scope")


def test_delete_hidden_thread_rejected(svc):
    """隐藏线程不走用户删除口（仅剩一个可见对话守卫同理不适用）。"""
    subs = _seed_threads(svc)
    assert svc.delete_conversation(subs[0]) is None
    assert subs[0] in [c.get("id") for c in svc.state_dict["conversations"]]


def test_delete_endpoint_hidden_thread_404(client, svc):
    subs = _seed_threads(svc)
    assert client.delete(f"/api/conversations/{subs[0]}").status_code == 404


def test_visible_delete_still_works_and_respects_min_one(svc):
    """既有语义不退化：可见对话可删；仅剩一个可见对话时拒删。"""
    subs = _seed_threads(svc)
    payload = svc.create_conversation("会话2")
    second = payload["active_conversation_id"]
    after = svc.delete_conversation(second)
    assert after is not None
    assert len(conversation_ops.visible_conversations(svc)) == 1
    # 仅剩一个可见对话：拒删（隐藏线程再多也不算「可删余量」）
    only = conversation_ops.visible_conversations(svc)[0]["id"]
    assert svc.delete_conversation(only) is None
