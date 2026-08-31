"""prompt_gates 承重分支补强（P1-11b）：只加测试不改生产代码。

钉死此前未覆盖分支：
① has_voice_reference / has_spec_document 的脏数据容忍分支；
③ resolve_kind_by_draft_id 空 ID / 未命中 / shot / audio 分档；
⑤ resolve_prompt_language 声明读取异常回落；
⑥ validate_prompt_write 内三处 registry 声明读取异常降级分支；
⑦ present_structure_kinds / storyboard_stage_complete 异常回落 /
   drafts_confirmed 空列表 / stage_tool_restrictions 规格向导在场裁剪。
（C1a 裁决 2026-08-31：② shot_references_missing_element_images 与
④ autofill_shot_duration 随技能级闸层删除退役；⑤ 的 cjk_min_ratio
调整轴退役，英文锁定只经 language 声明轴。）
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


# ---------- ⑤ resolve_prompt_language ----------

def test_resolve_language_registry_exception_falls_back_to_chinese(monkeypatch):
    """registry 声明读取抛异常：回落平台默认中文（不误拦）"""
    monkeypatch.setattr(pg.registry, "fallback_skill_from_state",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("registry 故障")))
    assert pg.resolve_prompt_language({}, skill_name="") == "中文"


# ---------- ⑥ validate_prompt_write registry 异常降级 ----------

_PROMPT_OK = (
    "清晨薄雾笼罩的旧街道上，主角背着帆布包缓步走向镜头，中景跟拍，"
    "光线柔和偏冷，环境音轻微带有远处鸟鸣，画面写实风格，细节丰富，"
    "整体氛围安静克制，色调低饱和，街道两侧的老建筑在雾中若隐若现"
)


def test_validate_write_fallback_skill_exception_degraded(monkeypatch):
    """当前 Skill 归属探测抛异常：吞掉照常校验（不误拦）"""
    monkeypatch.setattr(pg.registry, "fallback_skill_from_state",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    ok, hard, soft = pg.validate_prompt_write(_PROMPT_OK, "shot", {})
    assert ok is True


def test_validate_write_prompt_en_categories_exception_degraded(monkeypatch):
    """类别级语言豁免声明读取抛异常：吞掉回落现状判定"""
    monkeypatch.setattr(pg.registry, "fallback_skill_from_state", lambda *a, **k: "demo_skill")
    monkeypatch.setattr(pg.registry, "skill_prompt_en_categories",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    ok, hard, soft = pg.validate_prompt_write(_PROMPT_OK, "shot", {})
    assert ok is True


# ---------- ⑦ 结构/流程辅助函数 ----------

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


def test_stage_tool_restrictions_spec_wizard_active(monkeypatch):
    """规格向导在场且规格未定稿：全量裁剪且文案指向等待用户选定"""
    import src.video_agent.skill_runtime.registry as reg
    monkeypatch.setattr(reg, "spec_wizard_active", lambda *a, **k: True)
    excluded, note = pg.stage_tool_restrictions({"documents": []})
    assert "storyboard_create_group" in excluded
    assert "generate_video" in excluded
    assert "规格" in note
