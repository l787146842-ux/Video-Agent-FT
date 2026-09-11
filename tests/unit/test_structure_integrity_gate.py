# -*- coding: utf-8 -*-
"""任务#36 护栏移植：建组结构完整性闸（_structure_integrity_gate）。

原 exec_common._apply_actions 机械校验随执行器退役下沉为通用工具级校验，
本文件逐条钉死同语义：
① 无标题 add_group 拒收；
② 分镜 sceneRefs 完整度（非空且覆盖标题提及的关键元素，否则拒收）。
（③ 分组类型边界已随 2026-09-10 阶段规则去代码化批退役：阶段类别边界闸
删除后按 group_type 声明推导，不再按「当前阶段」推导——对应用例同批删除。）
"""
import pytest

from src.video_agent.core import fc_gates, prompt_gates

STATE = {
    "keyElements": [
        {"id": "ke-1", "title": "程心", "drafts": []},
        {"id": "ke-2", "title": "走廊", "drafts": []},
    ],
    "shots": [],
    "audioItems": [],
}


@pytest.fixture
def strict(monkeypatch):
    monkeypatch.setattr(prompt_gates, "gate_mode", lambda: "strict")


@pytest.fixture
def runner(monkeypatch):
    """闸机上下文工厂：runner(injected_skill) → fc_gates.GateContext。
    （阶段类别边界闸退役后本闸不再读当前阶段，故无需 stage 桩。）"""

    def _ctx(injected_skill="任意"):
        return fc_gates.GateContext(state=lambda: STATE,
                                    injected_skill=injected_skill)

    return _ctx


def _args(group_type="shot", title="程心走过走廊", scene_refs=None):
    return {"group_type": group_type, "title": title,
            "scene_refs": scene_refs or []}


# ---------- ① 无标题 add_group 拒收 ----------


def test_untitled_group_rejected(strict, runner):
    err = fc_gates.structure_integrity_gate(
        runner(), "storyboard_create_group", _args(title="  "))
    assert err is not None and "title" in err


def test_untitled_passes_when_gate_off(monkeypatch, runner):
    monkeypatch.setattr(prompt_gates, "gate_mode", lambda: "off")
    assert fc_gates.structure_integrity_gate(
        runner(), "storyboard_create_group", _args(title="")) is None


def test_untitled_passes_without_skill(strict, runner):
    assert fc_gates.structure_integrity_gate(
        runner(""), "storyboard_create_group", _args(title="")) is None


# ---------- ② 分镜 sceneRefs 完整度 ----------


def test_shot_empty_scene_refs_rejected(strict, runner):
    err = fc_gates.structure_integrity_gate(
        runner(), "storyboard_create_group", _args(scene_refs=[]))
    assert err is not None and "sceneRefs" in err


def test_shot_missing_title_mentioned_ke_rejected(strict, runner):
    # 标题点名「程心」但只引用了「走廊」→ 漏引拒收
    err = fc_gates.structure_integrity_gate(
        runner(), "storyboard_create_group", _args(scene_refs=["走廊"]))
    assert err is not None and "程心" in err


def test_shot_refs_by_id_or_title_pass(strict, runner):
    # 兼容关键元素 id 与标题两种写法（与 shot_refs_missing_element 同口径）
    assert fc_gates.structure_integrity_gate(
        runner(), "storyboard_create_group",
        _args(scene_refs=["ke-1", "走廊"])) is None
    assert fc_gates.structure_integrity_gate(
        runner(), "storyboard_create_group",
        _args(scene_refs=["程心", "走廊"])) is None


def test_shot_not_mentioned_ke_not_required(strict, runner):
    # 标题未点名的关键元素不强制引用（不误伤无关分镜）
    assert fc_gates.structure_integrity_gate(
        runner(), "storyboard_create_group",
        _args(title="空镜远景", scene_refs=["走廊"])) is None


# ---------- ③ 各类别建组一律放行（阶段类别边界闸已退役） ----------


def test_all_group_kinds_pass_without_stage_boundary(strict, runner):
    """阶段类别边界闸退役（2026-09-10 计划 B2）：建组只看标题与引用完整度，
    不再按「当前阶段」限制 group_type。"""
    for kind, title in (("keyElement", "程心"), ("audio", "旁白轨")):
        assert fc_gates.structure_integrity_gate(
            runner(), "storyboard_create_group",
            _args(group_type=kind, title=title)) is None
    # 分镜类别同样不再按阶段限制（② sceneRefs 完整度仍守）
    assert fc_gates.structure_integrity_gate(
        runner(), "storyboard_create_group",
        _args(group_type="shot", title="程心走过走廊",
              scene_refs=["ke-1", "走廊"])) is None


# ---------- 边界：非建组工具不受本闸管辖 ----------


def test_non_create_group_tools_pass(strict, runner):
    assert fc_gates.structure_integrity_gate(
        runner(), "storyboard_patch_draft", _args(title="")) is None
