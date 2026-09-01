"""FTDYB 追赶 P0：分镜新字段、删除语义、workflow_pause 门控
（Q2 裁决 2026-09-01：建组走 FC 工具，删除/分组 patch 走领域层 ops）"""
import asyncio

import pytest

from src.video_agent.core.agent_loop import run_agent_loop
from src.video_agent.state import storyboard_ops as ops
from src.video_agent.state.manager import StateManager


@pytest.fixture
def svc(tmp_path):
    return StateManager(str(tmp_path))


@pytest.fixture
def executor(svc):
    from src.video_agent.core.action_executor import StateOperationExecutor
    return StateOperationExecutor(svc)


@pytest.mark.asyncio
async def test_add_shot_with_ftdyb_fields(svc, monkeypatch):
    from src.video_agent.tools.storyboard_tools import (
        CreateGroupInput, StoryboardCreateGroupTool,
    )

    monkeypatch.setattr(StateManager, "get_instance", classmethod(lambda cls: svc))
    r = await StoryboardCreateGroupTool().aexecute(CreateGroupInput(
        group_type="shot",
        title="Shot_太空艇与宇航员坍缩",
        shot_type="长镜头",
        scene_refs=["Element_监视太空艇", "Element_二维空间平面"],
        duration="10s",
        rough_desc="起初(0-4s)：中景…然后切至(4-7s)：特写…最后切至(7-10s)：远景…",
        draft={"label": "分镜卡片", "prompt": "p"},
    ))
    assert r.success
    shot = svc.state_dict["shots"][-1]
    assert shot["shotType"] == "长镜头"
    assert shot["sceneRefs"] == ["Element_监视太空艇", "Element_二维空间平面"]
    assert "0-4s" in shot["roughDesc"]
    assert shot["duration"] == "10s"


def test_update_group_shot_fields(svc):
    shot = svc.state_dict["shots"][0]
    changed, _dropped = ops.patch_group(
        shot, {"shotType": "特写", "sceneRefs": ["Element_A"]})
    assert changed
    assert svc.state_dict["shots"][0]["shotType"] == "特写"
    assert svc.state_dict["shots"][0]["sceneRefs"] == ["Element_A"]


def test_delete_draft(svc):
    group = svc.state_dict["keyElements"][0]
    target = group["drafts"][0]["id"]
    before = len(group["drafts"])
    assert ops.delete_draft(svc.state_dict, target, "keyElement") == [target]
    assert len(group["drafts"]) == before - 1
    assert all(d["id"] != target for d in group["drafts"])


def test_delete_group(svc):
    gid = svc.state_dict["shots"][0]["id"]
    before = len(svc.state_dict["shots"])
    removed, hit = ops.delete_group(svc.state_dict, gid, "shot")  # 命中位与草稿列表分离（评审修补批）
    assert hit is True and isinstance(removed, list)
    assert len(svc.state_dict["shots"]) == before - 1


def test_delete_missing_returns_false(svc):
    assert ops.delete_draft(svc.state_dict, "no-such") == []
    assert ops.delete_group(svc.state_dict, "no-such") == ([], False)


async def test_workflow_pause_pauses_loop(svc, executor):
    """LLM 经 workflow_pause 工具请求确认后循环必须停下
    （audit-0819b：确认经第 5 元组结构化上抛，不再经文本块）"""
    calls = {"n": 0}

    async def llm(system, messages, stream_hook=None):
        calls["n"] += 1
        return ("拆解完成，请确认。", "stop", 1, 0.0, {
            "confirmation": "已拆解 1 个元素，确认后开始生成图片",
            "confirmation_options": [],
        })

    result = await run_agent_loop(
        "拆解", llm_call=llm, context_builder=lambda: "ctx", executor=executor, history=[],
    )
    assert calls["n"] == 1                      # 没有跑第二轮
    assert result.confirmation == "已拆解 1 个元素，确认后开始生成图片"
    assert result.applied_actions == 1          # 工具执行照计，确认不计数
