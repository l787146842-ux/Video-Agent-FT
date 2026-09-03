"""八轮 B4 钉死回归：状态驱动下一步建议判定表（suggest_next_actions）。

确定性三问全中收归系统：答案可从状态算出、机器可判、无创作空间。
0817 B22：建议中性化——只报客观状态（待确认/停摆），不点名下一步流程。
任务 12：可判定 Skill 流程节点时 label 取节点标题；不可判定时回落
通用文案（缺提示词/缺媒体两分支拆分为可区分的 label/value）。
"""
import pytest

from src.video_agent.core import workflow_runtime as wr
from src.video_agent.core.round_end_policies import suggest_next_actions

SKILL = "AI-短剧一站式生成"


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
    assert out[0]["label"] == "补写提示词"


def test_prompts_ready_suggest_generate():
    out = suggest_next_actions(_state(
        _draft(tag="已确认", prompt="完整提示词"),
        _draft(tag="已确认", prompt="另一条"),
    ))
    assert out[0]["label"] == "补生成媒体"


def test_prompt_and_media_branches_distinguishable():
    """任务 12 阶段 C：两个分支不得再挂同一个按钮文案。"""
    a = suggest_next_actions(_state(_draft(tag="已确认", prompt="p"), _draft(tag="已确认")))
    b = suggest_next_actions(_state(_draft(tag="已确认", prompt="p")))
    assert a[0]["label"] != b[0]["label"]
    assert a[0]["value"] != b[0]["value"]


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


# ---------- 任务 12 阶段 B：Skill 流程节点标题附挂 ----------

@pytest.fixture
def _clean_cache():
    wr.clear_compile_cache()
    yield
    wr.clear_compile_cache()


def _state_with_run(current_node: str, *drafts) -> dict:
    definition = wr.compile_definition(SKILL)
    assert definition is not None, "测试前提：Skill 可编译"
    st = _state(*drafts) if drafts else {}
    st["workflow_run"] = {
        "run_id": "run_t12", "current_node": current_node,
        "definition_hash": definition["definition_hash"],
        "completed_nodes": [], "run_version": 0, "event_sequence": 0,
    }
    return st


def test_skill_node_title_used_as_label(_clean_cache):
    """可判定节点：label 取节点标题（DEFAULT_V2_NODE_TITLES），
    value 指向该节点。"""
    st = _state_with_run("storyboard_shots",
                         _draft(tag="已确认", prompt="p"))
    out = suggest_next_actions(st, SKILL)
    assert out[0]["label"] == "分镜设计"
    assert "分镜设计" in out[0]["value"]


def test_skill_node_title_stall_branch(_clean_cache):
    """停摆引导分支同样取节点标题。"""
    st = _state_with_run("storyboard_shots")
    st["keyElements"] = [{"id": "k", "drafts": []}]
    out = suggest_next_actions(st, SKILL)
    assert out[0]["label"] == "分镜设计"


def test_no_run_falls_back_to_generic(_clean_cache):
    """无 active run：回落通用文案（保持既有行为）。"""
    out = suggest_next_actions(
        _state(_draft(tag="已确认", prompt="p")), SKILL)
    assert out[0]["label"] == "补生成媒体"


def test_unknown_skill_falls_back_to_generic(_clean_cache):
    """未注册 Skill（无编译定义）：回落通用文案。"""
    st = _state_with_run("storyboard_shots", _draft(tag="已确认", prompt="p"))
    out = suggest_next_actions(st, "不存在的技能名")
    assert out[0]["label"] == "补生成媒体"
