# -*- coding: utf-8 -*-
"""批 S2 微调真子对话：作用域上下文裁剪（context_builder scope 档）。

钉死契约：
1. scope 存在时：目标分组（group_id / draft_id 定位）注入全量草稿细节
   （含提示词全文），同类别非目标分组与其他类别一律组级指针；
2. 无 scope 时行为零变化（渐进披露：仅 prompt_chars，无 prompt 全文）；
3. 缓存键扩 scope：同 scope 命中复用、不同 scope 不互串、未命中回落重建。
"""
import json

import pytest

from src.video_agent.state import context_builder
from src.video_agent.state.manager import StateManager
from src.video_agent.state.models import CAT_AUDIO_ITEMS, CAT_KEY_ELEMENTS, CAT_SHOTS

_SCOPE = {
    "kind": "adjust", "cat": CAT_SHOTS,
    "group_id": "grp-target", "draft_id": "draft-1", "label": "分镜 1-1",
}


# ---------- 夹具 ----------

@pytest.fixture
def svc(tmp_path):
    StateManager.reset_instance()
    instance = StateManager(str(tmp_path / "ws"))
    raw = instance.state_dict
    raw[CAT_SHOTS] = [
        {"id": "grp-target", "title": "目标组", "duration": "3s", "drafts": [
            {"id": "draft-1", "label": "1-1", "prompt": "目标提示词全文A"},
            {"id": "draft-2", "label": "1-2", "prompt": "同组次卡提示词B"},
        ]},
        {"id": "grp-other", "title": "非目标组", "drafts": [
            {"id": "draft-9", "label": "2-1", "prompt": "别组提示词不外流"},
        ]},
    ]
    raw[CAT_KEY_ELEMENTS] = [
        {"id": "ke-1", "title": "主角", "drafts": [
            {"id": "kd-1", "label": "主角-1", "prompt": "主角提示词不外流"},
        ]},
    ]
    raw[CAT_AUDIO_ITEMS] = []
    raw["documents"] = [{"name": "规格", "content": "正文不进注入面" * 40}]
    instance.save()
    StateManager._instance = instance
    yield instance
    StateManager.reset_instance()


def _parse(svc, scope):
    return json.loads(context_builder.build_agent_context(
        svc.state_dict, asset_mode="bound", cache=None, scope=scope))


# ---------- 1. 目标组全量 / 其余指针 ----------

def test_scope_target_full_others_pointers(svc):
    snap = _parse(svc, _SCOPE)
    shots = snap[CAT_SHOTS]
    target = next(g for g in shots if g.get("id") == "grp-target")
    other = next(g for g in shots if g.get("id") == "grp-other")
    # 目标组：草稿细节全量（含提示词全文，渐进披露豁免）
    prompts = [d.get("prompt", "") for d in target["drafts"]]
    assert prompts == ["目标提示词全文A", "同组次卡提示词B"]
    assert target["title"] == "目标组" and target["index"] == 1
    # 同类别非目标组：仅组级指针
    assert "drafts" not in other and other.get("draft_count") == 1
    assert "别组提示词不外流" not in json.dumps(snap, ensure_ascii=False)
    # 其他类别一律指针
    ke = snap[CAT_KEY_ELEMENTS][0]
    assert "drafts" not in ke and ke.get("draft_count") == 1
    assert "主角提示词不外流" not in json.dumps(snap, ensure_ascii=False)
    # 裁剪解释在场（不嵌目标编号亦成立：字段存在性断言）
    assert snap.get("scopeNote")
    # documents 保持既有清单形态（名称/字数/前 200 字预览，全文不注入）
    doc = snap["documents"][0]
    assert "content" not in doc and doc["char_count"] == len("正文不进注入面" * 40)
    assert len(doc.get("preview", "")) <= 200


def test_scope_locates_target_by_draft_id(svc):
    snap = _parse(svc, dict(_SCOPE, group_id="", draft_id="draft-9"))
    other = next(g for g in snap[CAT_SHOTS] if g.get("id") == "grp-other")
    target = next(g for g in snap[CAT_SHOTS] if g.get("id") == "grp-target")
    assert [d.get("prompt", "") for d in other["drafts"]] == ["别组提示词不外流"]
    assert "drafts" not in target  # 反成指针


def test_scope_missing_target_falls_back_to_pointers(svc):
    snap = _parse(svc, dict(_SCOPE, group_id="grp-ghost", draft_id="draft-ghost"))
    assert all("drafts" not in g for g in snap[CAT_SHOTS])
    assert snap.get("scopeNote")


def test_no_scope_behavior_unchanged(svc):
    snap = _parse(svc, None)
    assert "scopeNote" not in snap
    target = next(g for g in snap[CAT_SHOTS] if g.get("id") == "grp-target")
    d0 = target["drafts"][0]
    assert "prompt" not in d0 and d0.get("prompt_chars") == len("目标提示词全文A")
    # 无 scope 时其他类别照常全量结构（不裁剪）
    assert "drafts" in snap[CAT_KEY_ELEMENTS][0]


# ---------- 2. 缓存：命中复用 / 不互串 / 未命中回落 ----------

def test_scope_cache_hit_miss_semantics(svc):
    cache: dict = {}
    first = context_builder.build_agent_context(
        svc.state_dict, cache=cache, scope=_SCOPE)
    second = context_builder.build_agent_context(
        svc.state_dict, cache=cache, scope=_SCOPE)
    assert second is first  # 命中：同键复用同一对象
    # 不同 scope 不互串（独立键）
    context_builder.build_agent_context(
        svc.state_dict, cache=cache, scope=dict(_SCOPE, draft_id="draft-9"))
    context_builder.build_agent_context(svc.state_dict, cache=cache)  # 无 scope 旧形态
    assert len(cache) == 3
    # 命中语义：状态已变但缓存未清时仍返回旧结果（清缓存职责在写入方）
    svc.state_dict[CAT_SHOTS][0]["drafts"][0]["prompt"] = "改后提示词"
    assert context_builder.build_agent_context(
        svc.state_dict, cache=cache, scope=_SCOPE) is first
    # 未命中回落：新缓存字典重建，反映最新状态
    fresh = json.loads(context_builder.build_agent_context(
        svc.state_dict, cache={}, scope=_SCOPE))
    target = next(g for g in fresh[CAT_SHOTS] if g.get("id") == "grp-target")
    assert target["drafts"][0]["prompt"] == "改后提示词"


def test_manager_build_agent_context_scope_passthrough(svc):
    """StateManager 委托层 scope 透传（与模块函数同口径）。"""
    snap = json.loads(svc.build_agent_context("bound", scope=_SCOPE))
    assert snap.get("scopeNote")
    plain = json.loads(svc.build_agent_context("bound"))
    assert "scopeNote" not in plain
