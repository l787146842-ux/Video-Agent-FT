"""动作语义钉死（Q2 裁决 2026-09-01：文本轨分派退役，建组走 FC 工具，
current 解析走领域层 ops）"""
import pytest

from src.video_agent.state import storyboard_ops as ops
from src.video_agent.state.manager import StateManager


@pytest.fixture
def svc(tmp_path):
    return StateManager(str(tmp_path))


# test_parse_actions_block / test_parse_dict_with_actions_key /
# test_truncated_json_yields_no_actions 已随任务#27 文本轨残留退役删除：
# 被测对象（web/action_parser.py 文本块容错解析）整文件退役，
# 动作通道唯一 = FC 工具调用（ADR-0001）。
# test_unknown_action_not_counted 已随 Q2 裁决 2026-09-01 退役删除：
# 文本轨未知动作计数随分派器退役；FC 轨未注册工具由 ToolManager
# deny-by-default 拒执行（注册闸另有钉死）。


@pytest.mark.asyncio
async def test_add_group_with_draft(svc, monkeypatch):
    from src.video_agent.tools.storyboard_tools import (
        CreateGroupInput, StoryboardCreateGroupTool,
    )

    monkeypatch.setattr(StateManager, "get_instance", classmethod(lambda cls: svc))
    before = len(svc.state_dict["keyElements"])
    r = await StoryboardCreateGroupTool().aexecute(CreateGroupInput(
        group_type="keyElement",
        title="测试元素",
        draft={"label": "概念图", "prompt": "test prompt"},
    ))
    assert r.success
    groups = svc.state_dict["keyElements"]
    assert len(groups) == before + 1
    assert groups[-1]["title"] == "测试元素"
    assert groups[-1]["drafts"][0]["prompt"] == "test prompt"


def test_current_resolves_to_selected_draft(svc):
    # demo 状态里 ke-1 有两个草稿；选中第二个后，"current" 必须命中它而非第一个
    found = ops.find_draft(
        svc.state_dict, "current", draft_type="keyElement",
        selected_draft_id="ke-1-d2", selected_type="keyElement")
    assert found is not None
    _group, draft = found
    assert draft["id"] == "ke-1-d2"


def test_current_without_selection_falls_back_to_first(svc):
    found = ops.find_draft(svc.state_dict, "current", draft_type="keyElement")
    assert found is not None
    _group, draft = found
    assert draft["id"] == svc.state_dict["keyElements"][0]["drafts"][0]["id"]
