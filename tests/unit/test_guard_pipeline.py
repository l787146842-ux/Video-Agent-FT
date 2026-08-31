"""统一闸机管线（宪法 §2.0）：单点判定 + FC 轨一致性（Q2 后动作通道唯一 = FC）。"""
import pytest

from src.video_agent.core import prompt_gates
from src.video_agent.core.guard_pipeline import evaluate_prompt_write, prompt_write_verdict
from src.video_agent.core.fc_tool_runner import FCToolRunner

GOOD_SHOT = (
    "镜头总时长：15秒。缓慢推入中景，程心怀抱文物奔向舱门，背景冥王星冰原崩裂成二维平面，"
    "前景飘散的冰晶在冷光中闪烁，整体色调深青克制，Strong chiaroscuro contrast，"
    "<急促的呼吸声与远方空间坍缩的轰鸣>，no music，no subtitles。"
)


def test_verdict_short_prompt_rejected():
    v = prompt_write_verdict("敷衍短句", "shot", {}, gate_enabled=True)
    assert not v.ok
    assert v.rule_id == "platform.prompt_write"
    assert "拦截" in v.message


def test_verdict_user_override_allows_with_warning():
    v = prompt_write_verdict(
        "敷衍短句", "shot", {}, gate_enabled=True, user_override=True,
    )
    assert v.ok
    assert v.layer == "platform"
    assert v.message  # 硬伤已降为警告文案（仍随结果展示）


def test_verdict_audio_and_empty_skip():
    assert prompt_write_verdict("随便", "audio", {}).ok
    assert prompt_write_verdict("", "shot", {}).ok


def test_fc_track_same_verdict_for_bad_prompt():
    """FC 轨判定与唯一实现同源（宪法 Rule 2；Q2 裁决 2026-09-01 文本轨退役，
    原双轨对照收敛为单轨）。"""
    state = {"keyElements": [], "shots": [], "audioItems": []}
    runner = FCToolRunner(tool_manager=None)
    runner._raw_state = staticmethod(lambda: state)
    err = runner._prompt_gate(
        "storyboard_patch_draft",
        {"draft_id": "1-1", "draft_type": "shot", "patch": {"prompt": "敷衍短句"}},
        injected_skill="任意 Skill",
    )
    assert err is not None
    # 同源判定：唯一实现同输入同结论（拦截）
    out = evaluate_prompt_write("敷衍短句", "shot", state, gate_enabled=True)
    assert out.ok is False


def test_fc_track_same_verdict_for_good_prompt():
    state = {"keyElements": [{"drafts": [{"imgUrl": "http://x/a.png"}]}],
             "shots": [], "audioItems": []}
    runner = FCToolRunner(tool_manager=None)
    runner._raw_state = staticmethod(lambda: state)
    err = runner._prompt_gate(
        "storyboard_patch_draft",
        {"draft_id": "1-1", "draft_type": "shot", "patch": {"prompt": GOOD_SHOT}},
        injected_skill="任意 Skill",
    )
    assert err is None
    # 同源判定：唯一实现同输入同结论（放行）
    out = evaluate_prompt_write(GOOD_SHOT, "shot", state, gate_enabled=True)
    assert out.ok is True
