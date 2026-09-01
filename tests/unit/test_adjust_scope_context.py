# -*- coding: utf-8 -*-
"""批 S2 微调真子对话：作用域上下文裁剪（context_builder scope 档）。

钉死契约（对齐 Flova：子对话只应看到对应元素，任务 #19 收窄）：
1. scope 存在时：仅目标分组（group_id / draft_id 定位）注入全量草稿细节
   （含提示词全文）；同类别其余分组与其他类别整体不注入（连指针清单也不给）；
   documents（规格/剧本）/uploadedDocs/assets/analysis/interaction 一律不可见；
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
    raw["uploadedDocs"] = [{"id": "up-1", "name": "剧本.txt", "kind": "script", "char_count": 99}]
    raw["assets"] = [{"id": "a-1", "name": "参考图", "type": "image", "isBound": True, "url": "http://x/a.png"}]
    raw["analysis"] = {"summary": "剧本分析摘要不应可见", "key_points": ["k1"]}
    instance.save()
    StateManager._instance = instance
    yield instance
    StateManager.reset_instance()


def _parse(svc, scope):
    return json.loads(context_builder.build_agent_context(
        svc.state_dict, asset_mode="bound", cache=None, scope=scope))


# ---------- 1. 目标组全量 / 其余整体不注入 ----------

def test_scope_target_full_rest_invisible(svc):
    snap = _parse(svc, _SCOPE)
    shots = snap[CAT_SHOTS]
    # 目标类别只剩目标组（非目标组连指针也不给）
    assert [g.get("id") for g in shots] == ["grp-target"]
    target = shots[0]
    # 目标组：草稿细节全量（含提示词全文，渐进披露豁免）
    prompts = [d.get("prompt", "") for d in target["drafts"]]
    assert prompts == ["目标提示词全文A", "同组次卡提示词B"]
    assert target["title"] == "目标组" and target["index"] == 1
    # 其他类别整体不注入（空列表，连指针清单也不给）
    assert snap[CAT_KEY_ELEMENTS] == []
    assert snap[CAT_AUDIO_ITEMS] == []
    # documents（规格/剧本）/uploadedDocs/assets/analysis/interaction 不可见
    for key in ("documents", "uploadedDocs", "assets", "analysis", "interaction"):
        assert key not in snap
    # 非目标内容全文不外流（双保险：序列化面扫描）
    dumped = json.dumps(snap, ensure_ascii=False)
    assert "别组提示词不外流" not in dumped
    assert "主角提示词不外流" not in dumped
    assert "剧本分析摘要" not in dumped
    assert "剧本.txt" not in dumped
    # 裁剪解释在场（不嵌目标编号亦成立：字段存在性断言）
    assert snap.get("scopeNote")


def test_scope_locates_target_by_draft_id(svc):
    snap = _parse(svc, dict(_SCOPE, group_id="", draft_id="draft-9"))
    # draft_id 定位：目标切成 grp-other，全量注入；原 group_id 目标反不可见
    assert [g.get("id") for g in snap[CAT_SHOTS]] == ["grp-other"]
    assert [d.get("prompt", "") for d in snap[CAT_SHOTS][0]["drafts"]] == ["别组提示词不外流"]
    assert "目标提示词全文A" not in json.dumps(snap, ensure_ascii=False)


def test_scope_missing_target_falls_back_to_empty(svc):
    """目标缺失（组已删除）回落空注入，不阻断任务；非目标面仍不可见。"""
    snap = _parse(svc, dict(_SCOPE, group_id="grp-ghost", draft_id="draft-ghost"))
    assert snap[CAT_SHOTS] == []
    assert "documents" not in snap
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
