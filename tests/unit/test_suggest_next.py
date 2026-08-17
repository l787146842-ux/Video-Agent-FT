"""八轮 B4 钉死回归：状态驱动下一步建议判定表（suggest_next_actions）。

确定性三问全中收归系统：答案可从状态算出、机器可判、无创作空间。
0817 B22：建议中性化——只报客观状态（待确认/停摆），不点名下一步流程。
"""
from src.video_agent.core.round_end_policies import suggest_next_actions


def _state(*drafts):
    return {"shots": [{"id": "g1", "title": "组一", "drafts": list(drafts)}]}


def _draft(tag="", prompt="", img="", video=""):
    return {"id": "d", "tag": tag, "prompt": prompt, "imgUrl": img, "videoUrl": video}


def test_empty_state_no_suggestion():
    assert suggest_next_actions({}) == []
    assert suggest_next_actions({"shots": []}) == []


def test_unconfirmed_drafts_suggest_confirm():
    out = suggest_next_actions(_state(_draft(tag="已确认"), _draft()))
    assert len(out) == 1 and out[0]["kind"] == "next"
    assert out[0]["label"] == "确认故事板草稿" and out[0]["value"]


def test_all_confirmed_missing_prompt_suggest_write():
    out = suggest_next_actions(_state(
        _draft(tag="已确认", prompt="完整提示词"),
        _draft(tag="已确认"),
    ))
    assert out[0]["label"] == "推进下一阶段"


def test_prompts_ready_suggest_generate():
    out = suggest_next_actions(_state(
        _draft(tag="已确认", prompt="完整提示词"),
        _draft(tag="已确认", prompt="另一条"),
    ))
    assert out[0]["label"] == "推进下一阶段"


def test_all_generated_no_suggestion():
    out = suggest_next_actions(_state(
        _draft(tag="已确认", prompt="完整提示词", img="http://x/1.png"),
        _draft(tag="已确认", prompt="另一条", video="http://x/1.mp4"),
    ))
    assert out == []


def test_staircase_priority_confirm_first():
    # 同时缺确认与缺提示词：只给最高阶梯的一条建议
    out = suggest_next_actions(_state(_draft(), _draft()))
    assert out[0]["label"] == "确认故事板草稿"


def test_malformed_state_never_raises():
    assert suggest_next_actions({"shots": [{"drafts": "不是列表"}]}) == []
    assert suggest_next_actions(None) == []
