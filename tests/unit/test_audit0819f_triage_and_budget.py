"""audit-0819f 钉死回归：分诊只认用户原话 + 执行器预算按任务定 + 截断重试可见。

1111 事故根治三件套：
1. 附件预览里的剧本对白问号不得参与提问判定（分诊认 raw_user_text）；
2. 初始预算下限 8192（消灭「先撞墙再扩额」的 79 秒白烧）；
3. 截断/空内容重试经 emit_progress 下发可见提示（长等待不再静默）。
"""
from pathlib import Path

import pytest

from src.video_agent.core.planner import Planner
from src.video_agent.skill_runtime import exec_common, exec_spec, progress
from src.video_agent.state.manager import StateManager

ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.fixture
def svc(tmp_path):
    return StateManager(str(tmp_path))


@pytest.fixture
def planner(svc):
    return Planner(state_manager=svc, llm_adapter=None, tool_manager=None)


# ---------- 阶段 1：分诊只认用户原话 ----------

def test_triage_attachment_question_mark_not_counted(planner, svc):
    """1111 现场：剧本预览含「？」。旧形态（多模态拼装）误判 handoff 的
    表面被钉住，新契约（原话）判 advance——两条都钉，防回退。"""
    svc.state_dict["uploadedDocs"] = [
        {"id": "d1", "name": "三体短篇集.md", "content": "AA：为什么木星城还没有回复？"}]
    parts = [
        {"type": "text", "text": "AI-短剧一站式生成"},
        {"type": "text", "text": "（用户上传了素材文档《三体短篇集.md》…AA：为什么木星城还没有回复？）"},
    ]
    # 旧 bug 表面：整条拼装消息含问号 → handoff（证明洞确实存在过）
    assert planner._triage_control(parts, "AI-短剧一站式生成") == "handoff"
    # 新契约：分诊认原话（Skill 名，无问号）+ 原料就位 → advance
    assert planner._triage_control(
        "AI-短剧一站式生成", "AI-短剧一站式生成") == "advance"


def test_triage_raw_question_still_handoff(planner, svc):
    """用户原话本身是提问 → 仍 handoff（原话语义不 regress）"""
    svc.state_dict["uploadedDocs"] = [{"id": "d1", "name": "a.md", "content": "x"}]
    assert planner._triage_control("为什么还没好？", "AI-短剧一站式生成") == "handoff"


def test_handle_message_triage_wired_to_raw_text():
    """钉死：handle_message 分诊取 context.raw_user_text（多模态拼装不得参与）"""
    src = (ROOT / "src/video_agent/core/planner.py").read_text(encoding="utf-8")
    assert "context.raw_user_text or user_message" in src


# ---------- 阶段 2：预算按任务定（C1） ----------

def test_budget_floor_8192():
    """1111 根因：4096 写死先撞墙。下限 8192 钉死"""
    assert exec_spec.initial_json_budget(1200, 4096, 16384) == 8192


def test_budget_sizing_by_input():
    assert exec_spec.initial_json_budget(20000, 4096, 65536) == 24096


def test_budget_caller_larger_wins():
    assert exec_spec.initial_json_budget(100, 30000, 65536) == 30000


def test_budget_ceiling_clamp():
    assert exec_spec.initial_json_budget(100000, 4096, 16384) == 16384


# ---------- 阶段 2：截断重试可见（B） ----------

@pytest.mark.asyncio
async def test_truncation_retry_emits_progress(monkeypatch):
    """截断重试必须下发可见进度（1111 的 79 秒静默不得复现）"""
    seen = []

    async def collector(event):
        seen.append(event)

    token = progress.bind_progress_emitter(collector)
    try:
        monkeypatch.setattr(
            exec_common, "_resolve_chat_provider", lambda p, m: ("prov", "model-x"))
        monkeypatch.setattr(exec_spec, "output_limit_for_model", lambda m: 32768)
        calls = {"n": 0}

        async def fake_stream(provider, model, messages, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                return "{", "length"  # 第一轮截断
            return '{"ok": 1}', "stop"

        monkeypatch.setattr(exec_common, "executor_stream_text", fake_stream)
        data = await exec_spec._llm_json_call("sys", "user" * 10, max_tokens=4096)
        assert data == {"ok": 1}
        assert calls["n"] == 2
    finally:
        progress.unbind_progress_emitter(token)
    texts = [str(e.get("text") or "") for e in seen]
    assert any("截断" in t and "重试" in t for t in texts), texts
