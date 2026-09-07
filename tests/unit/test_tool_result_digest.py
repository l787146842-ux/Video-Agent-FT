"""P3-14(a) tool-result 消化单测。

覆盖：消化边界（超阈值才消化）、最近 2 轮回喂保留原文、开关关闭（=0）、
只消化已投影进状态 JSON 的写类工具行（read_* 全文/失败行不碰）、幂等。
B2：assistant tool_calls 大参数消化（report_markdown 等已落账全文）。
"""
import json

from src.video_agent.core.fc_feedback import (
    DIGEST_POINTER,
    FEEDBACK_MARKER,
    digest_projected_tool_args,
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


# ---------- B2：assistant tool_calls 大参数消化 ----------


def _asst(tool_name, args_str, call_id="call_1"):
    return {"role": "assistant", "content": "",
            "tool_calls": [{"id": call_id, "type": "function",
                            "function": {"name": tool_name, "arguments": args_str}}]}


LONG_REPORT = "# 分析报告 " + "细" * 400  # 远超默认阈值（不含换行，避开 JSON 转义干扰子串断言）


def test_args_digest_replaces_long_report():
    """超阈值的已投影工具大参数被替换为落账占位"""
    msgs = [
        _asst("script_analysis_report", json.dumps({
            "doc_name": "三体.md", "summary": "一句话",
            "report_markdown": LONG_REPORT}, ensure_ascii=False)),
        _asst("document_write", json.dumps({"x": "短"})),
        _asst("read_skill", json.dumps({"name": "s", "section": "c", "content": "正文"})),
        _asst("document_write", json.dumps({"x": "短"})),  # 最近 2 条保留区
        _asst("script_analysis_report", json.dumps({"summary": "最新"}, ensure_ascii=False)),
    ]
    n = digest_projected_tool_args(msgs, max_chars=200)
    assert n == 1
    sent_args = json.loads(msgs[0]["tool_calls"][0]["function"]["arguments"])
    assert "report_markdown" in sent_args
    assert LONG_REPORT not in sent_args["report_markdown"]
    assert "已落账" in sent_args["report_markdown"]
    # 短参数与同消息其他字段不动
    assert sent_args["summary"] == "一句话"
    assert sent_args["doc_name"] == "三体.md"


def test_args_digest_recent_two_kept():
    """最近 2 条含白名单调用的 assistant 消息保留原文"""
    long_args = json.dumps({"summary": "s", "report_markdown": LONG_REPORT}, ensure_ascii=False)
    msgs = [
        _asst("script_analysis_report", long_args, "call_1"),  # 消化
        _asst("script_analysis_report", long_args, "call_2"),  # 最近第 2 条
        _asst("script_analysis_report", long_args, "call_3"),  # 最近第 1 条
    ]
    assert digest_projected_tool_args(msgs, max_chars=200) == 1
    for i in (1, 2):
        assert LONG_REPORT in msgs[i]["tool_calls"][0]["function"]["arguments"]
    assert LONG_REPORT not in msgs[0]["tool_calls"][0]["function"]["arguments"]


def test_args_digest_skips_non_projected_and_short():
    """非白名单工具（read_skill 等）与未超阈值参数一律不动"""
    msgs = [
        _asst("read_skill", json.dumps({"name": "s", "section": "c",
                                        "content": "长" * 500}, ensure_ascii=False)),
        _asst("script_analysis_report", json.dumps({"summary": "短"})),
        _asst("document_write", json.dumps({"x": "短"})),
        _asst("document_write", json.dumps({"x": "短"})),
        _asst("script_analysis_report", json.dumps({"summary": "最新"}, ensure_ascii=False)),
    ]
    assert digest_projected_tool_args(msgs, max_chars=200) == 0
    assert "长" * 500 in msgs[0]["tool_calls"][0]["function"]["arguments"]


def test_args_digest_disabled_when_zero_and_idempotent():
    """max_chars=0 关闭；消化后占位短于阈值，二次调用不再命中"""
    msgs = [
        _asst("script_analysis_report", json.dumps({
            "summary": "s", "report_markdown": LONG_REPORT}, ensure_ascii=False)),
        _asst("document_write", json.dumps({"x": "短"})),
        _asst("script_analysis_report", json.dumps({"summary": "最新"}, ensure_ascii=False)),
    ]
    assert digest_projected_tool_args(msgs, max_chars=0) == 0
    assert LONG_REPORT in msgs[0]["tool_calls"][0]["function"]["arguments"]
    assert digest_projected_tool_args(msgs, max_chars=200) == 1
    assert digest_projected_tool_args(msgs, max_chars=200) == 0


def test_args_digest_wired_both_channels():
    """接线：流式/非流式两通道都在 truncate 前调用 tool_calls 参数消化"""
    import inspect

    from src.video_agent.core import turn_executor

    for fn in (turn_executor.TurnExecutor.call_llm, turn_executor.TurnExecutor.call_llm_stream):
        src = inspect.getsource(fn)
        assert "digest_projected_tool_args" in src
        assert src.index("digest_projected_tool_args") < src.index("truncate_messages")
