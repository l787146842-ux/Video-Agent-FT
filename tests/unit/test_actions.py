"""StateOperationExecutor：别名、截断、选中态解析"""
import pytest

from src.video_agent.core.action_executor import StateOperationExecutor
from src.video_agent.state.manager import StateManager


@pytest.fixture
def svc(tmp_path):
    return StateManager(str(tmp_path))


@pytest.fixture
def executor(svc):
    return StateOperationExecutor(svc)


# test_parse_actions_block / test_parse_dict_with_actions_key /
# test_truncated_json_yields_no_actions 已随任务#27 文本轨残留退役删除：
# 被测对象（web/action_parser.py 文本块容错解析）整文件退役，
# 动作通道唯一 = FC 工具调用（ADR-0001）；mock 演示通道早已改结构化 dict 直达。


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
    executor = StateOperationExecutor(svc, selected_draft_id="ke-1-d2", selected_type="keyElement")
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
    executor = StateOperationExecutor(svc)
    applied = executor.execute([{
        "action": "update_draft",
        "draft_id": "current",
        "patch": {"tag": "兜底"},
    }])
    assert applied == 1
    assert svc.state_dict["keyElements"][0]["drafts"][0]["tag"] == "兜底"


def test_unknown_action_not_counted(executor):
    assert executor.execute([{"action": "no_such_action"}]) == 0
