"""批 1/2 钉死回归：可观测性统一 + 时延治理。

- 降级切换/机械写文档落转录（完成态可见）；
- 执行器长等待心跳（>20s 后每 15s 下发进度，状态栏不静默）；
- executor 角色 thinking=low 接通执行器内部 LLM 调用（防思考吃光预算）。
"""
import asyncio
import inspect

import pytest

from src.video_agent.skill_runtime import exec_common, progress


def test_executor_thinking_low_wired():
    """model_policy executor 角色默认 low，且执行器取稿唯一出口携带 thinking_level"""
    assert exec_common._executor_thinking() == "low"
    src = inspect.getsource(exec_common.executor_stream_text)
    assert "thinking_level" in src


@pytest.mark.asyncio
async def test_heartbeat_emits_on_long_wait(monkeypatch):
    """长等待心跳：超过 AFTER 仍无结果即下发进度文案（黑箱等待不复现）"""
    monkeypatch.setattr(exec_common, "_HEARTBEAT_AFTER", 0.05)
    monkeypatch.setattr(exec_common, "_HEARTBEAT_EVERY", 0.05)
    seen = []

    async def collector(event):
        seen.append(event)

    async def slow_stream(provider, model, messages, **kw):
        await asyncio.sleep(0.2)
        return "ok", "stop"

    monkeypatch.setattr(
        exec_common._gen, "call_chat_completion_stream", slow_stream)
    token = progress.bind_progress_emitter(collector)
    try:
        out = await exec_common.executor_stream_text(
            "p", "m", [], max_tokens=16, timeout=5)
    finally:
        progress.unbind_progress_emitter(token)
    assert out == ("ok", "stop")
    texts = [str(e.get("text") or "") for e in seen]
    assert any("模型仍在生成" in t for t in texts), texts


def test_fallback_and_spec_write_record_trace_action():
    """降级切换与规格机械写均落 trace action（源码锁源）"""
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    cs = (root / "src/video_agent/web/chat_service.py").read_text(encoding="utf-8")
    assert 'record_action(\n                "model_fallback"' in cs or '"model_fallback"' in cs
    cc = (root / "src/video_agent/web/chat_consume.py").read_text(encoding="utf-8")
    assert '"write_document"' in cc and "写入文档" in cc


def test_prose_obligation_lint_warns_without_pause_declaration():
    """散文含对话义务而 sidecar 无 pause 声明 → lint 告警（只告警不阻断）"""
    from src.video_agent.web import skill_docs as sd

    # 用真实存量 Skill：AI-短剧一站式生成 的 sidecar 有 pause.stage_pause → 不告警
    ok_content = "<planner>\n每阶段完成后必须暂停，等待用户确认再继续。\n</planner>\n"
    assert sd._lint_prose_obligations(ok_content, "AI-短剧一站式生成") == []
    # 无 sidecar 文件的 slug → load_sidecar 空 → 告警
    warn = sd._lint_prose_obligations(ok_content, "__no_such_skill__")
    assert warn and "pause" in warn[0]
