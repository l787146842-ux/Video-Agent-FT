"""统一闸机管线（宪法 §2.0）：单点判定 + FC/文本双轨一致性。"""
import pytest

from src.video_agent.core import prompt_gates
from src.video_agent.core.guard_pipeline import prompt_write_verdict
from src.video_agent.core.fc_tool_runner import FCToolRunner
from src.video_agent.state.manager import StateManager
from src.video_agent.web.action_executor import StudioActionExecutor

GOOD_SHOT = (
    "镜头总时长：15秒。缓慢推入中景，程心怀抱文物奔向舱门，背景冥王星冰原崩裂成二维平面，"
    "前景飘散的冰晶在冷光中闪烁，整体色调深青克制，Strong chiaroscuro contrast，"
    "<急促的呼吸声与远方空间坍缩的轰鸣>，no music，no subtitles。"
)


def test_verdict_short_prompt_rejected():
    v = prompt_write_verdict("敷衍短句", "shot", {}, gate_enabled=True)
    assert not v.ok
    assert v.rule_id == "skill.prompt_structure"
    assert "拦截" in v.message


def test_verdict_user_override_allows_with_warning():
    v = prompt_write_verdict(
        "敷衍短句", "shot", {}, gate_enabled=True, user_override=True,
    )
    assert v.ok
    assert v.layer == "skill"
    assert v.message  # 硬伤已降为警告文案（仍随结果展示）


def test_verdict_element_image_gate_warn_only():
    """4444 语义：元素概念图前置只警告不拦人（裁决权归用户）"""
    state = {"keyElements": [{"drafts": [{"imgUrl": ""}]}]}
    v = prompt_write_verdict(GOOD_SHOT, "shot", state, gate_enabled=True)
    assert v.ok, "元素图缺失不得硬拦截（4444：只警告不拦人）"
    assert prompt_gates.SHOT_SEQUENCE_GATE_ERROR in v.message


def test_verdict_audio_and_empty_skip():
    assert prompt_write_verdict("随便", "audio", {}).ok
    assert prompt_write_verdict("", "shot", {}).ok


def test_dual_track_same_verdict_for_bad_prompt(tmp_path):
    """FC 轨与文本轨对同一请求给出同一判定（宪法 Rule 2）。"""
    state = {"keyElements": [], "shots": [], "audioItems": []}
    svc = StateManager(str(tmp_path))
    svc.state_dict["keyElements"] = []
    svc.state_dict["shots"] = []
    svc.state_dict["audioItems"] = []
    ex = StudioActionExecutor(svc, gate_enabled=True)
    ex.structure_phase = True
    blocked = not ex._gate_check("敷衍短句", "shot")
    runner = FCToolRunner(tool_manager=None)
    runner._raw_state = staticmethod(lambda: state)
    err = runner._prompt_gate(
        "storyboard_patch_draft",
        {"draft_id": "1-1", "draft_type": "shot", "patch": {"prompt": "敷衍短句"}},
        injected_skill="任意 Skill",
    )
    assert blocked is (err is not None)


def test_dual_track_same_verdict_for_good_prompt(tmp_path):
    state = {"keyElements": [{"drafts": [{"imgUrl": "http://x/a.png"}]}],
             "shots": [], "audioItems": []}
    svc = StateManager(str(tmp_path))
    svc.state_dict.update(state)
    ex = StudioActionExecutor(svc, gate_enabled=True)
    assert ex._gate_check(GOOD_SHOT, "shot") is True
    runner = FCToolRunner(tool_manager=None)
    runner._raw_state = staticmethod(lambda: state)
    err = runner._prompt_gate(
        "storyboard_patch_draft",
        {"draft_id": "1-1", "draft_type": "shot", "patch": {"prompt": GOOD_SHOT}},
        injected_skill="任意 Skill",
    )
    assert err is None


def test_fc_flow_gate_s1_warning_only(tmp_path, monkeypatch):
    """814G5：规格前置从「只警告」升级为执行侧强制（拦 agent 不拦用户）。

    _flow_gate 本身不再追加用户警告；越阶拦截由 FlowGateSet.ensure_spec_gate
    在工具执行前完成，用户「本次放行」/坚持时 planner 不构建门禁。"""
    import src.video_agent.web.skill_docs as sd
    from src.video_agent.core.flow_gates import FlowGateSet
    from src.video_agent.skill_runtime import registry

    skill_dir = tmp_path / "skills"
    skill_dir.mkdir()
    monkeypatch.setattr(sd, "SKILL_DOCS_DIR", skill_dir)
    registry.reset_registry()
    sd.save_skill_doc(
        "有规格闸",
        '# A\n```json skill_manifest\n' '{"flow": {"spec_gate": true}}\n' "```\n正文",
    )
    try:
        runner = FCToolRunner(tool_manager=None)
        runner._raw_state = staticmethod(lambda: {})
        assert runner._flow_gate("storyboard_create_group", "有规格闸") is None
        assert not runner.gate_warnings  # 用户侧无 ⚠
        # 执行侧门禁客观生效：结构操作无规格被拦 / 执行器整包拆解同属结构操作
        fs = FlowGateSet.ensure_spec_gate(None)
        assert not fs.check_op(fs.classify_fc("storyboard_create_group", {}), {})[0]
        assert not fs.check_op(fs.classify_fc("storyboard_key_elements", {}), {})[0]
        assert fs.check_op(
            fs.classify_fc("storyboard_key_elements", {}),
            {"documents": [{"name": "Final_Video_Spec.md", "content": "x"}]},
        )[0]
    finally:
        registry.reset_registry()
