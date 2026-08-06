"""确认卡片候选选项：split_actions 选项解析（单选卡片数据链路起点）"""
from src.video_agent.core.agent_loop import split_actions


def test_options_dict_form():
    actions = [{
        "action": "request_confirmation",
        "message": "请选择成片规格",
        "options": [
            {"label": "60秒横版预告片", "description": "快节奏预告"},
            {"label": "90秒横版短片", "description": "完整叙事"},
        ],
    }]
    executable, cont, confirmation, options = split_actions(actions)
    assert executable == [] and cont is False
    assert confirmation == "请选择成片规格"
    assert [o["label"] for o in options] == ["60秒横版预告片", "90秒横版短片"]
    assert options[0]["description"] == "快节奏预告"


def test_options_string_form_and_filter():
    actions = [{
        "action": "request_confirmation",
        "message": "选择声音方向",
        "options": ["普通话旁白为主", "  ", {"label": "  ", "description": "x"}],
    }]
    _, _, _, options = split_actions(actions)
    assert options == [{"label": "普通话旁白为主", "description": ""}]


def test_no_options_defaults_empty():
    _, _, confirmation, options = split_actions(
        [{"action": "request_confirmation", "message": "请确认"}])
    assert confirmation == "请确认" and options == []
