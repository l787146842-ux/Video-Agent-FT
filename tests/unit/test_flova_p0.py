"""Flova 追赶 P0：分镜新字段、删除 action、request_confirmation 门控"""
import pytest

from src.video_agent.web.actions import StudioActionExecutor
from src.video_agent.web.agent_loop import run_agent_loop
from src.video_agent.web.state_service import StudioStateService


@pytest.fixture
def svc(tmp_path):
    return StudioStateService(base_dir=tmp_path)


@pytest.fixture
def executor(svc):
    return StudioActionExecutor(svc)


def test_add_shot_with_flova_fields(svc, executor):
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
    shot = svc.state["shots"][-1]
    assert shot["shotType"] == "长镜头"
    assert shot["sceneRefs"] == ["Element_监视太空艇", "Element_二维空间平面"]
    assert "0-4s" in shot["roughDesc"]
    assert shot["duration"] == "10s"


def test_update_group_shot_fields(svc, executor):
    shot_id = svc.state["shots"][0]["id"]
    applied = executor.execute([{
        "action": "update_group",
        "group_type": "shot",
        "group_id": shot_id,
        "patch": {"shotType": "特写", "sceneRefs": ["Element_A"]},
    }])
    assert applied == 1
    assert svc.state["shots"][0]["shotType"] == "特写"
    assert svc.state["shots"][0]["sceneRefs"] == ["Element_A"]


def test_delete_draft(svc, executor):
    group = svc.state["keyElements"][0]
    target = group["drafts"][0]["id"]
    before = len(group["drafts"])
    assert executor.execute([{"action": "delete_draft", "draft_type": "keyElement", "draft_id": target}]) == 1
    assert len(group["drafts"]) == before - 1
    assert all(d["id"] != target for d in group["drafts"])


def test_delete_group(svc, executor):
    gid = svc.state["shots"][0]["id"]
    before = len(svc.state["shots"])
    assert executor.execute([{"action": "delete_group", "group_type": "shot", "group_id": gid}]) == 1
    assert len(svc.state["shots"]) == before - 1


def test_delete_missing_returns_zero(executor):
    assert executor.execute([{"action": "delete_draft", "draft_id": "no-such"}]) == 0
    assert executor.execute([{"action": "delete_group", "group_id": "no-such"}]) == 0


async def test_request_confirmation_pauses_loop(svc, executor):
    """LLM 请求确认后循环必须停下，即使同时带了 continue 也不再跑下一轮"""
    reply = ('拆解完成，请确认。\n```studio-actions\n'
             '[{"action":"add_group","group_type":"keyElement","title":"Element_X","draft":{"label":"d","prompt":"p"}},'
             '{"action":"request_confirmation","message":"已拆解 1 个元素，确认后开始生成图片"},'
             '{"action":"continue","reason":"should be ignored"}]\n```', "stop")
    calls = {"n": 0}

    async def llm(system, messages):
        calls["n"] += 1
        return reply

    result = await run_agent_loop(
        "拆解", llm_call=llm, context_builder=lambda: "ctx", executor=executor, history=[],
    )
    assert calls["n"] == 1                      # 没有跑第二轮
    assert result.confirmation == "已拆解 1 个元素，确认后开始生成图片"
    assert result.applied_actions == 1          # 确认/continue 不计数
