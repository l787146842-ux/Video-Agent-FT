"""P3-14(b) compaction token 驱动双条件触发单测。

覆盖：token 条件独立触发（少条数大内容）、条数条件独立触发（既有行为）、
双条件均未达不触发、模板含「未决事项清单 + 最近关键产物名」两节。
"""
from types import SimpleNamespace

import pytest

from src.video_agent.web import history_compact as chat_consume


class _FakeAdapter:
    def __init__(self):
        self.calls = 0

    async def chat(self, messages, **kwargs):
        self.calls += 1
        from src.video_agent.adapters.base_chat import ChatResponse

        return ChatResponse(content="摘要：用户要做短剧。\n未决事项清单：\n- 无", finish_reason="stop")


@pytest.mark.asyncio
async def test_token_condition_triggers_below_count_threshold(tmp_path, monkeypatch):
    """条数远未到阈值，但 token 超窗口 0.6 倍 → 仍触发 compaction"""
    from src.video_agent.state.manager import StateManager

    monkeypatch.setattr(
        chat_consume, "settings",
        SimpleNamespace(history_compact_threshold=100, llm_timeout=10),
    )
    svc = StateManager(str(tmp_path))
    # 6 条大消息：每条 3 万中文字 ≈ 2 万 token，总量远超 0.6×128000
    hist = [{"role": "user", "content": "稿" * 30000} for _ in range(6)]
    adapter = _FakeAdapter()
    out = await chat_consume._maybe_compact_history(hist, svc, adapter)
    assert adapter.calls == 1, "token 条件必须独立触发 compaction"
    # 任务#16：history 只留最近 KEEP 条，摘要经 system 专用段注入（active 标记）
    assert len(out) == chat_consume._HISTORY_COMPACT_KEEP
    cached = (svc.state_dict.get("interaction") or {}).get("session_summary") or {}
    assert cached.get("active") is True


@pytest.mark.asyncio
async def test_token_limit_follows_configured_window(tmp_path, monkeypatch):
    """token 阈值按配置窗口计算（小窗口下普通消息也能触发）"""
    from src.video_agent.state.manager import StateManager

    monkeypatch.setattr(
        chat_consume, "settings",
        SimpleNamespace(history_compact_threshold=100, llm_timeout=10,
                        context_window_size=100),
    )
    svc = StateManager(str(tmp_path))
    hist = [{"role": "user", "content": f"这是第 {i} 条普通对话消息，内容不算短" * 10}
            for i in range(6)]
    adapter = _FakeAdapter()
    out = await chat_consume._maybe_compact_history(hist, svc, adapter)
    assert adapter.calls == 1


@pytest.mark.asyncio
async def test_neither_condition_no_compact(tmp_path, monkeypatch):
    """条数与 token 均未达阈值 → 不触发（原 history 原样返回）"""
    from src.video_agent.state.manager import StateManager

    monkeypatch.setattr(
        chat_consume, "settings",
        SimpleNamespace(history_compact_threshold=100, llm_timeout=10),
    )
    svc = StateManager(str(tmp_path))
    hist = [{"role": "user", "content": f"m{i}"} for i in range(6)]
    adapter = _FakeAdapter()
    out = await chat_consume._maybe_compact_history(hist, svc, adapter)
    assert adapter.calls == 0
    assert out is hist


@pytest.mark.asyncio
async def test_threshold_zero_still_disables(tmp_path, monkeypatch):
    """阈值 0 = 整体关闭（token 条件一并关闭，既有开关语义不变）"""
    from src.video_agent.state.manager import StateManager

    monkeypatch.setattr(
        chat_consume, "settings",
        SimpleNamespace(history_compact_threshold=0, llm_timeout=10),
    )
    svc = StateManager(str(tmp_path))
    hist = [{"role": "user", "content": "稿" * 30000} for _ in range(6)]
    adapter = _FakeAdapter()
    out = await chat_consume._maybe_compact_history(hist, svc, adapter)
    assert adapter.calls == 0
    assert out is hist


def test_template_has_handoff_sections():
    """压缩指令唯一家 = feedback.md::COMPACTION_INSTRUCTION（2026-09-12 治理批：
    compaction.md 死模板删除，四段式交接语义并入活模板）"""
    from src.video_agent.utils.prompts import load_prompt_section

    tpl = load_prompt_section("planner/feedback.md", "COMPACTION_INSTRUCTION")
    assert tpl, "COMPACTION_INSTRUCTION 分节必须可加载"
    assert "未决事项" in tpl
    assert "最近关键产物名" in tpl


def test_template_must_keep_semantics_snapshot():
    """快照防漂移（Rule6）：记忆系统退役后，会话压缩是创作设定的唯一
    软性保护——锁定「必须保留」清单的关键语义（含批次 D 新增的
    角色/场景/音色设定要点行）与四段式交接结构，改动需同批更新本快照。
    （2026-09-12 治理批：断言对象自已删除的 compaction.md 迁至唯一活模板
    feedback.md::COMPACTION_INSTRUCTION。）"""
    from src.video_agent.utils.prompts import load_prompt_section

    tpl = load_prompt_section("planner/feedback.md", "COMPACTION_INSTRUCTION")
    # handoff 四段式结构
    assert "目标与现状" in tpl
    assert "已定约束" in tpl
    # 必须保留清单（逐条钉死关键语义）
    assert "用户的创作目标、已确认的规格与偏好" in tpl
    assert "已确认的角色/场景/音色设定要点（若尚未沉淀到故事板）" in tpl
    assert "已完成的阶段" in tpl
    assert "用户明确否决或要求修改过的内容" in tpl
    # 丢弃边界与输出格式锚点
    assert "已沉淀在工作台状态里" in tpl
