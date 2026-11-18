# -*- coding: utf-8 -*-
"""绑定媒体批（2026-10-26 用户裁决）单测。

钉死四条：
① `ops.enforce_single_bound`：同组同类型唯一（绑新卡解绑旧卡），异类型互不影响；
② `resolve_shot_refs` / `resolve_shot_audio_refs`：组内已有绑定卡时只取绑定卡，
   无绑定卡维持存量口径（存量项目零回归）；
③ `build_storyboard_media_map`：某种类已有绑定卡时未绑定卡不参与引用解析；
④ `task_manager.writeback_if_complete`：出片成功自动绑定 + 同组同类型解绑。
"""
from types import SimpleNamespace

from src.video_agent.state import storyboard_ops as ops
from src.video_agent.core.prompt_refs import build_storyboard_media_map
from src.video_agent.web import task_manager as tm


def _state_with_group(drafts):
    return {
        "keyElements": [{"id": "ke-1", "title": "Element_沈砚", "drafts": drafts}],
        "shots": [], "audioItems": [],
    }


def _shot(refs):
    return {"id": "s1", "shotRefs": refs, "drafts": []}


def test_enforce_single_bound_unbinds_same_kind_only():
    group = {"drafts": [
        {"id": "a", "mediaType": "image", "imgUrl": "/a.png", "bound": True},
        {"id": "b", "mediaType": "image", "imgUrl": "/b.png"},
        {"id": "c", "mediaType": "audio", "audioUrl": "/c.mp3", "bound": True},
    ]}
    new = group["drafts"][1]
    unbound = ops.enforce_single_bound(group, new)
    assert unbound == ["a"]
    assert new["bound"] is True
    assert group["drafts"][0]["bound"] is False
    assert group["drafts"][2]["bound"] is True, "异类型绑定不受影响"


def test_resolve_shot_refs_prefers_bound_image():
    state = _state_with_group([
        {"id": "d1", "label": "图1", "mediaType": "image", "imgUrl": "/1.png"},
        {"id": "d2", "label": "图2", "mediaType": "image", "imgUrl": "/2.png", "bound": True},
    ])
    refs = ops.resolve_shot_refs(state, _shot(["沈砚"]))
    assert refs == [{"url": "/2.png", "role": "reference"}]


def test_resolve_shot_refs_legacy_when_no_bound():
    state = _state_with_group([
        {"id": "d1", "label": "图1", "mediaType": "image", "imgUrl": "/1.png"},
        {"id": "d2", "label": "图2", "mediaType": "image", "imgUrl": "/2.png"},
    ])
    assert ops.resolve_shot_refs(state, _shot(["沈砚"]))[0]["url"] == "/1.png"


def test_resolve_shot_audio_refs_prefers_bound_audio():
    state = _state_with_group([
        {"id": "v1", "mediaType": "audio", "audioType": "voice", "audioUrl": "/v1.mp3"},
        {"id": "v2", "mediaType": "audio", "audioType": "voice", "audioUrl": "/v2.mp3", "bound": True},
    ])
    refs = ops.resolve_shot_audio_refs(state, _shot(["沈砚"]))
    assert refs == [{"url": "/v2.mp3", "role": "reference_audio"}]


def test_media_map_filters_unbound_when_group_has_bound():
    state = _state_with_group([
        {"id": "d1", "label": "图1", "mediaType": "image", "imgUrl": "/1.png"},
        {"id": "d2", "label": "图2", "mediaType": "image", "imgUrl": "/2.png", "bound": True},
    ])
    m = build_storyboard_media_map(state)
    assert m["沈砚"]["url"] == "/2.png"
    assert "图1" not in m, "同种类已有绑定卡时未绑定卡不登记（含 label）"


def test_media_map_legacy_when_no_bound():
    state = _state_with_group([
        {"id": "d1", "label": "图1", "mediaType": "image", "imgUrl": "/1.png"},
    ])
    m = build_storyboard_media_map(state)
    assert m["沈砚"]["url"] == "/1.png"
    assert m["图1"]["url"] == "/1.png"


class _FakeSvc:
    def __init__(self, state):
        self.state_dict = state
        self.saved = 0

    def find_draft(self, draft_id):
        for g in self.state_dict["keyElements"]:
            for d in g["drafts"]:
                if d.get("id") == draft_id:
                    return ("keyElements", g, d)
        return None

    def save(self):
        self.saved += 1


def test_writeback_auto_binds_and_unbinds_same_kind(monkeypatch):
    group = {"id": "ke-1", "drafts": [
        {"id": "d1", "mediaType": "image", "imgUrl": "/a.png", "bound": True},
        {"id": "d2", "mediaType": "image", "imgUrl": ""},
        {"id": "d3", "mediaType": "audio", "audioUrl": "/c.mp3", "audioType": "voice", "bound": True},
    ]}
    svc = _FakeSvc({"keyElements": [group]})
    task = {"status": "succeeded", "draft_id": "d2", "result": {"images": ["/b.png"]}}
    monkeypatch.setattr(tm, "StateManager", SimpleNamespace(get_instance=lambda: svc))
    monkeypatch.setattr(
        tm, "get_task_manager", lambda: SimpleNamespace(get_task=lambda tid: task))

    tm.writeback_if_complete("t1")

    assert group["drafts"][1]["imgUrl"] == "/b.png"
    assert group["drafts"][1]["bound"] is True, "出片成功自动绑定"
    assert group["drafts"][0]["bound"] is False, "同组同类型旧绑定自动解除"
    assert group["drafts"][2]["bound"] is True, "音频绑定不受影响"
    assert svc.saved == 1
