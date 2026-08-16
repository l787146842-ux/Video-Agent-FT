"""StudioActionExecutor：解析、别名、截断、选中态解析"""
import pytest

from src.video_agent.web.action_executor import StudioActionExecutor
from src.video_agent.state.manager import StateManager


@pytest.fixture
def svc(tmp_path):
    return StateManager(str(tmp_path))


@pytest.fixture
def executor(svc):
    return StudioActionExecutor(svc)


def test_parse_actions_block(executor):
    reply = '好的\n```studio-actions\n[{"action":"confirm_draft","draft_id":"ke-1-d1"}]\n```'
    actions = executor.parse_actions_from_reply(reply)
    assert len(actions) == 1
    assert actions[0]["action"] == "confirm_draft"


def test_parse_dict_with_actions_key(executor):
    reply = '```studio-actions\n{"actions":[{"action":"select_draft","draft_id":"x"}]}\n```'
    actions = executor.parse_actions_from_reply(reply)
    assert len(actions) == 1


def test_truncated_json_yields_no_actions_but_detected(executor):
    truncated = '```studio-actions\n[{"action":"add_group","title":"未闭合'
    # 未闭合的代码块解析不到 actions
    assert executor.parse_actions_from_reply(truncated + "\n```") == []
    # 但 has_action_block 能检测到，供上层发告警
    assert executor.has_action_block(truncated)


def test_strip_action_blocks(executor):
    reply = '前文\n```studio-actions\n[]\n```\n后文'
    assert executor.strip_action_blocks(reply) == "前文\n\n后文"


def test_add_group_with_draft(svc, executor):
    before = len(svc.state_dict["keyElements"])
    applied = executor.execute([{
        "action": "add_group",
        "group_type": "keyElement",
        "title": "测试元素",
        "draft": {"label": "概念图", "prompt": "test prompt"},
    }])
    assert applied == 1
    groups = svc.state_dict["keyElements"]
    assert len(groups) == before + 1
    assert groups[-1]["title"] == "测试元素"
    assert groups[-1]["drafts"][0]["prompt"] == "test prompt"


def test_current_resolves_to_selected_draft(svc):
    # demo 状态里 ke-1 有两个草稿；选中第二个后，"current" 必须命中它而非第一个
    executor = StudioActionExecutor(svc, selected_draft_id="ke-1-d2", selected_type="keyElement")
    applied = executor.execute([{
        "action": "update_draft",
        "draft_id": "current",
        "patch": {"tag": "选中测试"},
    }])
    assert applied == 1
    drafts = svc.state_dict["keyElements"][0]["drafts"]
    assert drafts[1]["tag"] == "选中测试"
    assert drafts[0]["tag"] != "选中测试"


def test_current_without_selection_falls_back_to_first(svc):
    executor = StudioActionExecutor(svc)
    applied = executor.execute([{
        "action": "update_draft",
        "draft_id": "current",
        "patch": {"tag": "兜底"},
    }])
    assert applied == 1
    assert svc.state_dict["keyElements"][0]["drafts"][0]["tag"] == "兜底"


def test_unknown_action_not_counted(executor):
    assert executor.execute([{"action": "no_such_action"}]) == 0
