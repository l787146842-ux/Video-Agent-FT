"""任务#16 钉死：压缩摘要注入形态对齐业界（system 专用段）+ 客观探针。

批 1：摘要不再伪装成 history 首条 user 消息——history 只留最近 KEEP 条，
摘要经 interaction.session_summary.active 标记由 prompt_builder 的
session_summary 段（P2-2 段序手术后位于全局设置段之后、状态 JSON 段之前）
注入；未触发/失败回落同步清除标记。
批 2：压缩结果客观探针（摘要长度/关键产物名命中率）拼入 compact
上下文事件 detail；探针只记录不阻断。
"""
from types import SimpleNamespace

import pytest

from src.video_agent.core import prompt_builder as pb_mod
from src.video_agent.web import chat_consume


# ---------- 批 1：注入形态 ----------

def test_session_summary_section_registered_before_state_json():
    """P2-2 段序手术：专用摘要段登记在全局设置段之后、状态 JSON 段之前
    （compaction 激活不再击穿稳定前缀）"""
    names = [s.name for s in pb_mod.PROMPT_SECTIONS]
    assert names.index("session_summary") == names.index("global_settings") + 1
    assert names.index("session_summary") < names.index("state_json")


def test_section_injects_when_active():
    state = {"interaction": {"session_summary": {"fp": "x", "text": "交接摘要正文", "active": True}}}
    pb = SimpleNamespace(_get_raw_state=lambda: state)
    out = pb_mod._sec_session_summary(pb, SimpleNamespace())
    assert "交接摘要正文" in out
    assert "== 会话摘要" in out


def test_section_skips_when_inactive_or_empty():
    for cached in (
        {"fp": "x", "text": "正文", "active": False},   # 未触发/失败回落已清标记
        {"fp": "x", "text": "", "active": True},        # 空摘要不注入
        {},                                              # 无缓存
    ):
        state = {"interaction": {"session_summary": cached}}
        pb = SimpleNamespace(_get_raw_state=lambda: state)
        assert pb_mod._sec_session_summary(pb, SimpleNamespace()) == ""


def test_section_skips_without_raw_state():
    pb = SimpleNamespace(_get_raw_state=None)
    assert pb_mod._sec_session_summary(pb, SimpleNamespace()) == ""


class _FakeAdapter:
    def __init__(self, reply="摘要：用户要做短剧。"):
        self.calls = 0
        self._reply = reply

    async def chat(self, messages, **kwargs):
        self.calls += 1
        from src.video_agent.adapters.base_chat import ChatResponse

        return ChatResponse(content=self._reply, finish_reason="stop")


class _SpyTracer:
    def __init__(self):
        self.events = []

    def record_context_event(self, kind, detail=""):
        self.events.append((kind, detail))


@pytest.mark.asyncio
async def test_compact_applies_active_and_drops_user_disguise(tmp_path, monkeypatch):
    """压缩生效：history 只留 KEEP 条（无 user 伪装首条）+ active 标记置位"""
    from src.video_agent.state.manager import StateManager

    monkeypatch.setattr(
        chat_consume, "settings",
        SimpleNamespace(history_compact_threshold=4, llm_timeout=10),
    )
    svc = StateManager(str(tmp_path))
    hist = [{"role": "user", "content": f"m{i}"} for i in range(8)]
    out = await chat_consume._maybe_compact_history(hist, svc, _FakeAdapter())
    assert out == hist[-chat_consume._HISTORY_COMPACT_KEEP:]
    assert not any("会话摘要" in str(m.get("content", "")) for m in out), \
        "摘要不得再伪装成 history 内的消息"
    cached = (svc.state_dict.get("interaction") or {}).get("session_summary") or {}
    assert cached.get("active") is True


@pytest.mark.asyncio
async def test_active_cleared_when_next_turn_not_triggered(tmp_path, monkeypatch):
    """压缩生效后下一轮未达阈值 → 标记必须清除（防陈旧摘要注入完整历史）"""
    from src.video_agent.state.manager import StateManager

    monkeypatch.setattr(
        chat_consume, "settings",
        SimpleNamespace(history_compact_threshold=4, llm_timeout=10),
    )
    svc = StateManager(str(tmp_path))
    long_hist = [{"role": "user", "content": f"m{i}"} for i in range(8)]
    await chat_consume._maybe_compact_history(long_hist, svc, _FakeAdapter())
    cached = (svc.state_dict.get("interaction") or {}).get("session_summary") or {}
    assert cached.get("active") is True
    short_hist = [{"role": "user", "content": f"s{i}"} for i in range(3)]
    out = await chat_consume._maybe_compact_history(short_hist, svc, _FakeAdapter())
    assert out is short_hist
    cached = (svc.state_dict.get("interaction") or {}).get("session_summary") or {}
    assert cached.get("active") is False


# ---------- 批 2：客观探针 ----------

def _state_with_artifacts():
    return {
        "documents": [{"name": "Final_Video_Spec.md"}],
        "uploadedDocs": [{"name": "原剧本.txt"}],
        "keyElements": [
            {"id": "g1", "title": "主角林晚", "drafts": [{"id": "d1", "label": "立绘-正面"}]},
        ],
        "shots": [],
        "audioItems": [],
    }


def test_extract_artifact_names_intersects_with_compressed_segment():
    """基线口径：工作台产物标识 ∩ 被压缩段正文（未谈论过的不进基线）"""
    state = _state_with_artifacts()
    older = [
        {"role": "assistant", "content": "已写入 Final_Video_Spec.md，主角林晚设定完成"},
        {"role": "user", "content": "好的"},
    ]
    names = chat_consume._extract_artifact_names(state, older)
    assert "Final_Video_Spec.md" in names
    assert "主角林晚" in names
    assert "原剧本.txt" not in names, "被压缩段未提及的产物不进基线"
    assert "立绘-正面" not in names


def test_probe_metrics_fields():
    state = _state_with_artifacts()
    older = [{"role": "assistant", "content": "已写入 Final_Video_Spec.md，主角林晚确认"}]
    summary = "摘要：已定 Final_Video_Spec.md 规格，主角林晚设定完成。"
    out = chat_consume._compact_probe_metrics(state, older, summary)
    assert f"summary_chars={len(summary)}" in out
    assert "summary_tokens≈" in out
    assert "artifact_name_hit=2/2" in out


def test_probe_metrics_no_baseline():
    out = chat_consume._compact_probe_metrics({}, [{"role": "user", "content": "hi"}], "摘要")
    assert "artifact_name_hit=无基线" in out


def test_probe_exception_returns_empty_not_blocking(monkeypatch):
    """探针内部异常只记录不阻断：返回空串"""
    def _boom(*a, **k):
        raise RuntimeError("probe broken")

    monkeypatch.setattr(chat_consume, "_extract_artifact_names", _boom)
    assert chat_consume._compact_probe_metrics({}, [], "摘要") == ""


@pytest.mark.asyncio
async def test_compact_event_detail_carries_probe(tmp_path, monkeypatch):
    """compact 上下文事件 detail 携带探针字段（经 record_context_event 入 trace）"""
    from src.video_agent.state.manager import StateManager

    monkeypatch.setattr(
        chat_consume, "settings",
        SimpleNamespace(history_compact_threshold=4, llm_timeout=10),
    )
    spy = _SpyTracer()
    monkeypatch.setattr(chat_consume, "AgentTracer",
                        SimpleNamespace(get_instance=lambda: spy))
    svc = StateManager(str(tmp_path))
    svc.state_dict["documents"] = [{"name": "Final_Video_Spec.md"}]
    hist = ([{"role": "assistant", "content": "已写入 Final_Video_Spec.md"}]
            + [{"role": "user", "content": f"m{i}"} for i in range(7)])
    await chat_consume._maybe_compact_history(
        hist, svc, _FakeAdapter("摘要：规格已写入 Final_Video_Spec.md。"))
    kinds = [k for k, _ in spy.events]
    assert "compact" in kinds
    detail = next(d for k, d in spy.events if k == "compact")
    assert "summary_chars=" in detail
    assert "summary_tokens≈" in detail
    assert "artifact_name_hit=1/1" in detail


@pytest.mark.asyncio
async def test_probe_failure_does_not_block_compaction(tmp_path, monkeypatch):
    """探针整体故障时压缩主流程照常完成（事件 detail 无探针后缀而已）"""
    from src.video_agent.state.manager import StateManager

    monkeypatch.setattr(
        chat_consume, "settings",
        SimpleNamespace(history_compact_threshold=4, llm_timeout=10),
    )
    monkeypatch.setattr(chat_consume, "_compact_probe_metrics",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    svc = StateManager(str(tmp_path))
    hist = [{"role": "user", "content": f"m{i}"} for i in range(8)]
    out = await chat_consume._maybe_compact_history(hist, svc, _FakeAdapter())
    assert len(out) == chat_consume._HISTORY_COMPACT_KEEP
