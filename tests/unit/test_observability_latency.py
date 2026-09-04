"""批 1/2 钉死回归：可观测性统一。

- 降级切换/机械写文档落转录（完成态可见）。
（执行器长等待心跳与 executor thinking=low 接线用例已随任务#36 B5
执行器一步退役删除：exec_common 不复存在。）
"""

# test_executor_thinking_low_wired / test_heartbeat_emits_on_long_wait 已随
# 任务#36 B5 执行器一步退役删除（被测对象 exec_common.executor_stream_text
# 与 _executor_thinking 不复存在；心跳/thinking 档位是执行器内部机制）。


def test_fallback_retired_and_spec_write_record_trace_action():
    """fallback 切换转录随裁决退役（2026-08-20）；规格机械写落转录随用户裁决 2026-08-31 退役（D-08 清偿）"""
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    cs = (root / "src/video_agent/web/chat_service.py").read_text(encoding="utf-8")
    assert '"model_fallback"' not in cs, "裁决：聊天链路不自动换模型，发射端已删"
    cc = (root / "src/video_agent/web/chat_consume.py").read_text(encoding="utf-8")
    assert '"write_document"' not in cc, "规格机械写落转录已随 D-08 清偿退役"

# test_prose_obligation_lint_warns_without_pause_declaration 已随 pause 声明
# 化石链整链删除（2026-09-05）：frontmatter pause 声明无运行时消费者，
# lint 建议作者补声明只会让提示闭嘴，运行时什么都不会发生。
