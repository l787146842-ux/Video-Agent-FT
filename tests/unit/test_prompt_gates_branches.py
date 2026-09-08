"""prompt_gates 承重分支补强（P1-11b）：只加测试不改生产代码。

钉死此前未覆盖分支：
① has_voice_reference / has_spec_document 的脏数据容忍分支；
③ resolve_kind_by_draft_id 空 ID / 未命中 / shot / audio 分档；
⑦ present_structure_kinds / storyboard_stage_complete 异常回落 /
   drafts_confirmed 空列表（stage_tool_restrictions 规格向导在场裁剪
   已随批 B2 工具全量常驻退役，2026-09-09）。
（C1a 裁决 2026-08-31：② shot_references_missing_element_images 与
④ autofill_shot_duration 随技能级闸层删除退役；2026-09-06 用户裁决：
语言闸私设推导整体退役，⑤ resolve_prompt_language 与 ⑥ 的 registry
声明读取降级分支随之删除——提示词语言归文档层，不属闸机执法面。）
"""
import pytest

from src.video_agent.core import prompt_gates as pg


# ---------- ① 原料探测的脏数据容忍 ----------

def test_has_voice_reference_audio_draft_url():
    """音频草稿带音源即判定存在音色参考"""
    state = {"audioItems": [{"drafts": [{"audioUrl": "voice_01.mp3"}]}]}
    assert pg.has_voice_reference(state) is True


def test_has_voice_reference_empty_state_false():
    assert pg.has_voice_reference({}) is False


def test_has_spec_document_skips_non_dict_entries():
    """documents 混入非 dict 条目不炸，名称命中且正文非空才算数"""
    state = {
        "documents": [
            "脏数据",
            {"name": "随便一个文档", "content": "正文"},
            {"name": "制片规格.md", "content": "规格正文"},
        ]
    }
    assert pg.has_spec_document(state) is True
    # 空正文不算（防空文档绕闸）
    state2 = {"documents": [{"name": "制片规格.md", "content": "  "}]}
    assert pg.has_spec_document(state2) is False


# ---------- ③ resolve_kind_by_draft_id ----------

_STATE_KINDS = {
    "keyElements": [{"id": "ke-1", "drafts": [{"id": "d-ke"}]}],
    "shots": [{"id": "shot-1", "drafts": [{"id": "d-shot"}]}],
    "audioItems": [{"id": "audio-1", "drafts": [{"id": "d-audio"}]}],
}


def test_resolve_kind_empty_draft_id_returns_empty():
    assert pg.resolve_kind_by_draft_id(_STATE_KINDS, "") == ""


def test_resolve_kind_not_found_returns_empty():
    assert pg.resolve_kind_by_draft_id(_STATE_KINDS, "d-nope") == ""


def test_resolve_kind_shot_and_audio_prefixes():
    assert pg.resolve_kind_by_draft_id(_STATE_KINDS, "d-shot") == "shot"
    assert pg.resolve_kind_by_draft_id(_STATE_KINDS, "d-audio") == "audio"
    assert pg.resolve_kind_by_draft_id(_STATE_KINDS, "d-ke") == "keyElement"


# ---------- ⑥/⑤ 已随语言闸退役删除（2026-09-06 用户裁决，见模块 docstring） ----------


def test_present_structure_kinds_full():
    state = {"keyElements": [{}], "shots": [{}], "audioItems": [{}]}
    assert pg.present_structure_kinds(state) == ["keyElement", "shot", "audio"]


def test_storyboard_stage_complete_registry_exception_degraded(monkeypatch):
    """registry.resolve_entry 抛异常：音频需求判定回落 False，不阻断"""
    import src.video_agent.skill_runtime.registry as reg
    monkeypatch.setattr(reg, "resolve_entry",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    state = {"keyElements": [{}], "shots": [{}]}
    assert pg.storyboard_stage_complete(state, skill_name="demo") is True


def test_drafts_confirmed_empty_is_false():
    assert pg.drafts_confirmed({}, []) is False
    assert pg.drafts_confirmed({}, [{"tag": "已确认"}]) is True


