"""FTDYB 追赶 P0：分镜新字段、删除 action、workflow_pause 门控"""
import pytest

from src.video_agent.web.action_executor import StateOperationExecutor
from src.video_agent.core.agent_loop import run_agent_loop
from src.video_agent.state.manager import StateManager


@pytest.fixture
def svc(tmp_path):
    return StateManager(str(tmp_path))


@pytest.fixture
def executor(svc):
    return StateOperationExecutor(svc)


def test_add_shot_with_ftdyb_fields(svc, executor):
    applied = executor.execute([{
        "action": "add_group",
        "group_type": "shot",
        "title": "Shot_太空艇与宇航员坍缩",
        "shotType": "长镜头",
        "sceneRefs": ["Element_监视太空艇", "Element_二维空间平面"],
        "duration": "10s",
        "roughDesc": "起初(0-4s)：中景…然后切至(4-7s)：特写…最后切至(7-10s)：远景…",
        "draft": {"label": "分镜卡片", "prompt": "p"},
    }])
    assert applied == 1
    shot = svc.state_dict["shots"][-1]
    assert shot["shotType"] == "长镜头"
    assert shot["sceneRefs"] == ["Element_监视太空艇", "Element_二维空间平面"]
    assert "0-4s" in shot["roughDesc"]
    assert shot["duration"] == "10s"


def test_update_group_shot_fields(svc, executor):
    shot_id = svc.state_dict["shots"][0]["id"]
    applied = executor.execute([{
        "action": "update_group",
        "group_type": "shot",
        "group_id": shot_id,
        "patch": {"shotType": "特写", "sceneRefs": ["Element_A"]},
    }])
    assert applied == 1
    assert svc.state_dict["shots"][0]["shotType"] == "特写"
    assert svc.state_dict["shots"][0]["sceneRefs"] == ["Element_A"]


def test_delete_draft(svc, executor):
    group = svc.state_dict["keyElements"][0]
    target = group["drafts"][0]["id"]
    before = len(group["drafts"])
    assert executor.execute([{"action": "delete_draft", "draft_type": "keyElement", "draft_id": target}]) == 1
    assert len(group["drafts"]) == before - 1
    assert all(d["id"] != target for d in group["drafts"])


def test_delete_group(svc, executor):
    gid = svc.state_dict["shots"][0]["id"]
    before = len(svc.state_dict["shots"])
    assert executor.execute([{"action": "delete_group", "group_type": "shot", "group_id": gid}]) == 1
    assert len(svc.state_dict["shots"]) == before - 1


def test_delete_missing_returns_zero(executor):
    assert executor.execute([{"action": "delete_draft", "draft_id": "no-such"}]) == 0
    assert executor.execute([{"action": "delete_group", "group_id": "no-such"}]) == 0


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
