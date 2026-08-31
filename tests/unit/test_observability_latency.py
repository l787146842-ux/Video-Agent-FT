"""批 1/2 钉死回归：可观测性统一。

- 降级切换/机械写文档落转录（完成态可见）。
（执行器长等待心跳与 executor thinking=low 接线用例已随任务#36 B5
执行器一步退役删除：exec_common 不复存在。）
"""

# test_executor_thinking_low_wired / test_heartbeat_emits_on_long_wait 已随
# 任务#36 B5 执行器一步退役删除（被测对象 exec_common.executor_stream_text
# 与 _executor_thinking 不复存在；心跳/thinking 档位是执行器内部机制）。


def test_fallback_retired_and_spec_write_record_trace_action():
    """规格机械写落转录（源码锁源）；fallback 切换转录随裁决退役（2026-08-20）"""
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    cs = (root / "src/video_agent/web/chat_service.py").read_text(encoding="utf-8")
    assert '"model_fallback"' not in cs, "裁决：聊天链路不自动换模型，发射端已删"
    cc = (root / "src/video_agent/web/chat_consume.py").read_text(encoding="utf-8")
    assert '"write_document"' in cc and "写入文档" in cc


def test_prose_obligation_lint_warns_without_pause_declaration():
    """散文含对话义务而 frontmatter 无 pause 声明 → lint 告警（只告警不阻断）"""
    from src.video_agent.web import skill_docs as sd

    # 2026-08-31 用户裁决 Flova 对齐：存量包 frontmatter 不再声明 pause，
    # 散文含对话义务即告警（只告警不阻断）；无义务散文不告警
    ok_content = "<planner>\n先分析素材再搭建故事板。\n</planner>\n"
    assert sd._lint_prose_obligations(ok_content, "AI-短剧一站式生成") == []
    warn = sd._lint_prose_obligations(
        "<planner>\n每阶段完成后必须暂停，等待用户确认再继续。\n</planner>\n",
        "AI-短剧一站式生成")
    assert warn and "pause" in warn[0]
