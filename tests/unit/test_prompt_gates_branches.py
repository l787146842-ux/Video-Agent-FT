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
# 2026-11-12 宽权限批：`present_structure_kinds`（审阅卡文案用）随阶段审阅卡
# 一并退役，对应用例删除；`storyboard_stage_complete` 只保留「有没有结构」
# 这一条客观事实（音频完整性判定已删）。


def test_storyboard_stage_complete_ignores_audio():
    """结构齐即完成：音频做不做由模型按 Skill 散文判断，平台不查音频完整性
    （2026-11-12 宽权限批删去音频维度）。"""
    assert pg.storyboard_stage_complete(
        {"keyElements": [{}], "shots": [{}]}, skill_name="demo") is True
    # 缺分镜 → 未完成
    assert pg.storyboard_stage_complete(
        {"keyElements": [{}]}, skill_name="demo") is False
    # 有音频但缺结构 → 仍未完成（音频不参与判定）
    assert pg.storyboard_stage_complete(
        {"audioItems": [{}]}, skill_name="demo") is False


def test_drafts_confirmed_empty_is_false():
    assert pg.drafts_confirmed({}, []) is False
    assert pg.drafts_confirmed({}, [{"tag": "已确认"}]) is True


