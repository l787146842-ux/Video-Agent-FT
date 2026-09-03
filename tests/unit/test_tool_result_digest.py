"""P3-14(a) tool-result 消化单测。

覆盖：消化边界（超阈值才消化）、最近 2 轮回喂保留原文、开关关闭（=0）、
只消化已投影进状态 JSON 的写类工具行（read_* 全文/失败行不碰）、幂等。
"""
from src.video_agent.core.fc_feedback import (
    DIGEST_POINTER,
    FEEDBACK_MARKER,
    digest_projected_tool_results,
)


def _fb(lines):
    """构造一条 FC 工具结果回喂消息（与 format_tool_results 行格式一致）"""
    return {"role": "user", "content": "\n".join([FEEDBACK_MARKER] + lines)}


LONG_DETAIL = "已更新草稿明细：" + "x" * 300  # 远超默认阈值


def test_long_projected_line_digested():
    """超阈值的已投影写类工具行被替换为「摘要 + 状态 JSON」指针"""
    msgs = [
        _fb([f"- storyboard_patch_draft：执行成功，{LONG_DETAIL}"]),
        _fb(["- storyboard_add_draft：执行成功"]),  # 最近两条保留
        _fb(["- document_write：执行成功"]),
    ]
    n = digest_projected_tool_results(msgs, max_chars=200)
    assert n == 1
    assert "storyboard_patch_draft" in msgs[0]["content"]
    assert DIGEST_POINTER.format(name="storyboard_patch_draft").split("（")[0] in msgs[0]["content"]
    assert LONG_DETAIL not in msgs[0]["content"]
    # 首行 marker 与其余行保留
    assert msgs[0]["content"].startswith(FEEDBACK_MARKER)


def test_short_line_not_digested():
    """未超阈值的行保留原文（消化边界）"""
    line = "- document_write：执行成功，已写入文档 Final_Video_Spec.md"
    msgs = [_fb([line]), _fb(["- a：执行成功"]), _fb(["- b：执行成功"])]
    assert digest_projected_tool_results(msgs, max_chars=200) == 0
    assert line in msgs[0]["content"]


def test_recent_two_feedback_kept():
    """最近 2 条回喂消息无论多长都保留原文"""
    msgs = [
        {"role": "user", "content": "普通用户消息"},
        _fb([f"- storyboard_patch_draft：执行成功，{LONG_DETAIL}"]),  # 消化
        _fb([f"- storyboard_patch_draft：执行成功，{LONG_DETAIL}"]),  # 最近第 2 条
        _fb([f"- storyboard_patch_draft：执行成功，{LONG_DETAIL}"]),  # 最近第 1 条
    ]
    assert digest_projected_tool_results(msgs, max_chars=200) == 1
    assert LONG_DETAIL in msgs[2]["content"]
    assert LONG_DETAIL in msgs[3]["content"]
    assert LONG_DETAIL not in msgs[1]["content"]


def test_disabled_when_zero():
    """max_chars=0 一键关闭（settings.tool_result_digest_chars=0 同效）"""
    msgs = [_fb([f"- storyboard_patch_draft：执行成功，{LONG_DETAIL}"]),
            _fb(["- x：执行成功"]), _fb(["- y：执行成功"])]
    assert digest_projected_tool_results(msgs, max_chars=0) == 0
    assert LONG_DETAIL in msgs[0]["content"]


def test_non_projected_lines_never_digested():
    """硬约束：read_* 全文行、失败行、非白名单工具行一律不消化"""
    read_line = f"- read_project_doc 执行成功，全文如下：\n{'y' * 500}"
    fail_line = f"- storyboard_patch_draft：执行失败 —— {'e' * 300}"
    other_line = f"- script_analyze：执行成功，{'z' * 300}"
    msgs = [
        _fb([read_line, fail_line, other_line]),
        _fb(["- a：执行成功"]),
        _fb(["- b：执行成功"]),
    ]
    assert digest_projected_tool_results(msgs, max_chars=200) == 0
    assert read_line in msgs[0]["content"]
    assert fail_line in msgs[0]["content"]
    assert other_line in msgs[0]["content"]


def test_idempotent():
    """已消化行短于阈值，二次调用不再命中"""
    msgs = [
        _fb([f"- storyboard_patch_draft：执行成功，{LONG_DETAIL}"]),
        _fb(["- a：执行成功"]),
        _fb(["- b：执行成功"]),
    ]
    assert digest_projected_tool_results(msgs, max_chars=200) == 1
    assert digest_projected_tool_results(msgs, max_chars=200) == 0


def test_planner_wires_digest_before_truncate():
    """接线：LLM 调用点在构建 full_messages 后先消化再截断
    （D-02 拆分：实现体迁 core/turn_executor.py）"""
    import inspect

    from src.video_agent.core import turn_executor

    assert hasattr(turn_executor, "digest_projected_tool_results")
    for fn in (turn_executor.TurnExecutor.call_llm, turn_executor.TurnExecutor.call_llm_stream):
        src = inspect.getsource(fn)
        assert "digest_projected_tool_results" in src
        assert src.index("digest_projected_tool_results") < src.index("truncate_messages")
