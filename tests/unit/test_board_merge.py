# -*- coding: utf-8 -*-
"""G1 并行局部修改回归：故事板三向合并（board_merge）+ 合并端点。

外部标杆对齐：多镜头可同时细修；用户编辑与 Agent 写入并行时按元素粒度
检测冲突交面板定夺，取代整板 409 丢弃重做。
"""
import copy

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.video_agent.state import board_merge
from src.video_agent.state.manager import StateManager


def _group(gid, title="组", prompt="提示词", draft_id="d1"):
    return {"id": gid, "title": title,
            "drafts": [{"id": draft_id, "label": "草稿", "prompt": prompt}]}


def _board(groups):
    return {"keyElements": groups, "shots": [], "audioItems": [], "assets": []}


@pytest.fixture(autouse=True)
def _reset_history():
    board_merge.clear_history()
    yield
    board_merge.clear_history()


# ---------- 合并逻辑 ----------

def test_merge_single_side_edits_both_applied():
    """用户改分组 A、Agent 改分组 B：两改并存，零冲突。"""
    base = _board([_group("g1", "A", "原A"), _group("g2", "B", "原B")])
    mine = copy.deepcopy(base)
    mine["keyElements"][0]["drafts"][0]["prompt"] = "用户改A"
    theirs = copy.deepcopy(base)
    theirs["keyElements"][1]["drafts"][0]["prompt"] = "Agent改B"
    merged, conflicts = board_merge.merge_board(base, mine, theirs)
    assert conflicts == []
    prompts = {g["id"]: g["drafts"][0]["prompt"] for g in merged["keyElements"]}
    assert prompts == {"g1": "用户改A", "g2": "Agent改B"}


def test_merge_same_draft_both_edited_conflict():
    """双方同改同一草稿 → 冲突项（默认保留用户版进结果；归属带父组）。"""
    base = _board([_group("g1", "A", "原")])
    mine = copy.deepcopy(base)
    mine["keyElements"][0]["drafts"][0]["prompt"] = "用户版"
    theirs = copy.deepcopy(base)
    theirs["keyElements"][0]["drafts"][0]["prompt"] = "Agent版"
    merged, conflicts = board_merge.merge_board(base, mine, theirs)
    assert len(conflicts) == 1
    c = conflicts[0]
    assert c["kind"] == "draft" and c["category"] == "keyElements"
    assert c["mine"]["prompt"] == "用户版" and c["theirs"]["prompt"] == "Agent版"
    # 草稿级冲突带父组归属（前端面板按组展示/定位）
    assert c["group_id"] == "g1" and c["group_title"] == "A" and c["id"] == "d1"
    assert merged["keyElements"][0]["drafts"][0]["prompt"] == "用户版"


def test_merge_agent_adds_group_kept():
    """Agent 新增分组并入结果（追加末尾）。"""
    base = _board([_group("g1", "A")])
    mine = copy.deepcopy(base)
    theirs = copy.deepcopy(base)
    theirs["keyElements"].append(_group("g2", "Agent新组"))
    merged, conflicts = board_merge.merge_board(base, mine, theirs)
    assert conflicts == []
    assert [g["id"] for g in merged["keyElements"]] == ["g1", "g2"]


def test_merge_theirs_delete_mine_untouched_accepts_delete():
    """Agent 删组、用户未动 → 采纳删除。"""
    base = _board([_group("g1", "A"), _group("g2", "B")])
    mine = copy.deepcopy(base)
    theirs = _board([_group("g1", "A")])
    merged, conflicts = board_merge.merge_board(base, mine, theirs)
    assert conflicts == []
    assert [g["id"] for g in merged["keyElements"]] == ["g1"]


def test_merge_theirs_delete_mine_modified_conflict():
    """Agent 删组、用户改过 → 删改冲突进面板。"""
    base = _board([_group("g1", "A"), _group("g2", "B", "原")])
    mine = copy.deepcopy(base)
    mine["keyElements"][1]["drafts"][0]["prompt"] = "用户改过"
    theirs = _board([_group("g1", "A")])
    merged, conflicts = board_merge.merge_board(base, mine, theirs)
    assert len(conflicts) == 1 and conflicts[0]["kind"] == "delete_vs_modify"
    assert conflicts[0]["theirs"] is None


def test_merge_group_fields_conflict():
    """分组外壳字段（标题等）双方同改 → group 冲突，草稿仍按三向合并。"""
    base = _board([_group("g1", "原标题", "原")])
    mine = copy.deepcopy(base)
    mine["keyElements"][0]["title"] = "用户标题"
    theirs = copy.deepcopy(base)
    theirs["keyElements"][0]["title"] = "Agent标题"
    merged, conflicts = board_merge.merge_board(base, mine, theirs)
    assert len(conflicts) == 1 and conflicts[0]["kind"] == "group"
    assert merged["keyElements"][0]["title"] == "用户标题"


# ---------- 合并端点 ----------

@pytest.fixture
def svc(tmp_path):
    StateManager.reset_instance()
    instance = StateManager(str(tmp_path))
    StateManager._instance = instance
    yield instance
    StateManager.reset_instance()


@pytest.fixture
def client(svc):
    from src.video_agent.web.routes import project as project_routes
    from src.video_agent.web.app import video_agent_error_handler
    from src.video_agent.exceptions import VideoAgentError
    app = FastAPI()
    app.include_router(project_routes.router, prefix="/api")
    app.add_exception_handler(VideoAgentError, video_agent_error_handler)
    return TestClient(app)


def _seed_board(client, svc):
    """初始整板落盘，返回 (base_version, 初始分组集)。"""
    groups = [_group("g1", "A", "原A"), _group("g2", "B", "原B")]
    r = client.put("/api/project/state", json={
        "base_version": svc.board_version, "keyElements": groups})
    assert r.status_code == 200
    return r.json()["board_version"], groups


def test_merge_endpoint_applies_clean_merge(client, svc):
    """用户改 g1、Agent 改 g2：合并端点直接落盘，两改俱在。"""
    base_v, groups = _seed_board(client, svc)
    # Agent 写入（服务端状态前进）
    svc.state_dict["keyElements"][1]["drafts"][0]["prompt"] = "Agent改B"
    svc.save()
    assert svc.board_version > base_v
    # 用户携旧基线提交自己的改动
    mine = copy.deepcopy(groups)
    mine[0]["drafts"][0]["prompt"] = "用户改A"
    r = client.post("/api/project/state/merge", json={
        "base_version": base_v, "keyElements": mine})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and body["applied"] is True
    prompts = {g["id"]: g["drafts"][0]["prompt"]
               for g in svc.state_dict["keyElements"]}
    assert prompts == {"g1": "用户改A", "g2": "Agent改B"}
    assert body["board_version"] == svc.board_version


def test_merge_endpoint_returns_conflicts_without_apply(client, svc):
    """双方同改同一草稿：不落盘，回冲突清单 + 默认保留用户版的合并结果。"""
    base_v, groups = _seed_board(client, svc)
    svc.state_dict["keyElements"][0]["drafts"][0]["prompt"] = "Agent版"
    svc.save()
    mine = copy.deepcopy(groups)
    mine[0]["drafts"][0]["prompt"] = "用户版"
    r = client.post("/api/project/state/merge", json={
        "base_version": base_v, "keyElements": mine})
    body = r.json()
    assert r.status_code == 200
    assert body["ok"] is True and body["applied"] is False
    assert body["base_available"] is True
    assert len(body["conflicts"]) == 1
    assert body["conflicts"][0]["mine"]["prompt"] == "用户版"
    assert body["conflicts"][0]["theirs"]["prompt"] == "Agent版"
    # 服务端状态未被合并端点改写（等面板定夺后整板回提）
    assert svc.state_dict["keyElements"][0]["drafts"][0]["prompt"] == "Agent版"


def test_merge_endpoint_base_unavailable_falls_back(client, svc):
    """基线版号不可得（未记录/重启）：回落旧语义由前端处理。"""
    r = client.post("/api/project/state/merge", json={
        "base_version": 999999, "keyElements": []})
    body = r.json()
    assert body["ok"] is False and body["base_available"] is False


def test_merge_endpoint_rejects_cross_project_stale(client, svc):
    """跨项目陈旧写：同整板 PUT 口径直接 409。"""
    r = client.post("/api/project/state/merge", json={
        "project_id": "不存在的其他项目", "base_version": svc.board_version,
        "keyElements": []})
    assert r.status_code == 409
