# -*- coding: utf-8 -*-
"""任务#36 护栏移植：建组结构完整性闸（_structure_integrity_gate）。

原 exec_common._apply_actions 三条机械校验随执行器退役下沉为通用工具级
校验，本文件逐条钉死同语义（与原实现对照）：
① 无标题 add_group 拒收（原：untitled 丢弃 + 警告）；
② 分镜 sceneRefs 完整度（原：非空且覆盖标题提及的关键元素，否则拒收）；
③ 分组类型边界（原：only_group_type 越界拒收；通用路径按当前阶段推导）。
"""
from types import SimpleNamespace

import pytest

from src.video_agent.core import prompt_gates
from src.video_agent.core.fc_tool_runner import FCToolRunner

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
    r = FCToolRunner(tool_manager=None)
    monkeypatch.setattr(FCToolRunner, "_raw_state",
                        staticmethod(lambda: STATE))
    # 边界判定按当前阶段：默认放行所有类别（structure 阶段语义）
    monkeypatch.setattr(
        "src.video_agent.core.fc_gates."
        "pipeline_orchestrator.current_stage",
        lambda state, skill: SimpleNamespace(key="structure", title="结构搭建"),
    )
    return r


def _args(group_type="shot", title="程心走过走廊", scene_refs=None):
    return {"group_type": group_type, "title": title,
            "scene_refs": scene_refs or []}


# ---------- ① 无标题 add_group 拒收 ----------


def test_untitled_group_rejected(strict, runner):
    err = runner._structure_integrity_gate(
        "storyboard_create_group", _args(title="  "), injected_skill="任意")
    assert err is not None and "title" in err


def test_untitled_passes_when_gate_off(monkeypatch, runner):
    monkeypatch.setattr(prompt_gates, "gate_mode", lambda: "off")
    assert runner._structure_integrity_gate(
        "storyboard_create_group", _args(title=""), injected_skill="任意") is None


def test_untitled_passes_without_skill(strict, runner):
    assert runner._structure_integrity_gate(
        "storyboard_create_group", _args(title=""), injected_skill="") is None


# ---------- ② 分镜 sceneRefs 完整度 ----------


def test_shot_empty_scene_refs_rejected(strict, runner):
    err = runner._structure_integrity_gate(
        "storyboard_create_group", _args(scene_refs=[]), injected_skill="任意")
    assert err is not None and "sceneRefs" in err


def test_shot_missing_title_mentioned_ke_rejected(strict, runner):
    # 标题点名「程心」但只引用了「走廊」→ 漏引拒收
    err = runner._structure_integrity_gate(
        "storyboard_create_group",
        _args(scene_refs=["走廊"]), injected_skill="任意")
    assert err is not None and "程心" in err


def test_shot_refs_by_id_or_title_pass(strict, runner):
    # 兼容关键元素 id 与标题两种写法（与 shot_refs_missing_element 同口径）
    assert runner._structure_integrity_gate(
        "storyboard_create_group",
        _args(scene_refs=["ke-1", "走廊"]), injected_skill="任意") is None
    assert runner._structure_integrity_gate(
        "storyboard_create_group",
        _args(scene_refs=["程心", "走廊"]), injected_skill="任意") is None


def test_shot_not_mentioned_ke_not_required(strict, runner):
    # 标题未点名的关键元素不强制引用（不误伤无关分镜）
    assert runner._structure_integrity_gate(
        "storyboard_create_group",
        _args(title="空镜远景", scene_refs=["走廊"]),
        injected_skill="任意") is None


# ---------- ③ 分组类型边界（当前阶段推导） ----------


def test_stage_boundary_rejects_offstage_kind(strict, runner, monkeypatch):
    monkeypatch.setattr(
        "src.video_agent.core.fc_gates."
        "pipeline_orchestrator.current_stage",
        lambda state, skill: SimpleNamespace(key="ke_media", title="元素图生成"),
    )
    err = runner._structure_integrity_gate(
        "storyboard_create_group", _args(group_type="shot"),
        injected_skill="任意")
    assert err is not None and "越界" in err
    # 元素图阶段补建关键元素放行
    assert runner._structure_integrity_gate(
        "storyboard_create_group",
        _args(group_type="keyElement", title="补漏元素"),
        injected_skill="任意") is None


def test_structure_stage_allows_all_kinds(strict, runner):
    for kind, title in (("keyElement", "程心"), ("audio", "旁白轨")):
        assert runner._structure_integrity_gate(
            "storyboard_create_group",
            _args(group_type=kind, title=title), injected_skill="任意") is None


# ---------- 边界：非建组工具不受本闸管辖 ----------


def test_non_create_group_tools_pass(strict, runner):
    assert runner._structure_integrity_gate(
        "storyboard_patch_draft", _args(title=""), injected_skill="任意") is None
