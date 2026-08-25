"""814R4 钉死回归：chat_service 修复（重复 pop/公共编排/compaction）。

0818 架构板正批 B3：总结强制入正文接线随平台强注入退役删除。
"""
import inspect

from src.video_agent.core.planner import Planner
from src.video_agent.web import chat_consume, chat_service


class TestChatServiceFixes:
    def test_no_duplicate_pop(self):
        """pending_pause_kind 消费收敛 reducer（Rule2 v6）：
        散落直写/直 pop 清零，统一走 reduce_interaction pop_flags。"""
        src = inspect.getsource(chat_service._consume_pending_confirmation)
        assert src.count('interaction.pop("pending_pause_kind"') == 0
        assert 'pop_flags=("pending_pause_kind"' in src

    def test_single_opening_impl(self):
        """流式/非流式都走 _prepare_chat_opening（P1 单一实现）"""
        stream_src = inspect.getsource(chat_service._stream_worker_impl)
        non_stream_src = inspect.getsource(chat_service._non_stream_inner)
        assert "_prepare_chat_opening" in stream_src
        assert "_prepare_chat_opening" in non_stream_src
        # 双份内联复制已清除
        assert "_consume_spec_wizard(svc, user_text)" not in stream_src
        assert "_consume_spec_wizard(svc, user_text)" not in non_stream_src

    async def test_compaction_disabled_when_threshold_zero(self):
        """阈值 0 = 关闭（814G7 起默认 12 开启，此处显式置 0 验证关闭开关）"""
        from src.video_agent.config import settings

        old = settings.history_compact_threshold
        object.__setattr__(settings, "history_compact_threshold", 0)
        try:
            hist = [{"role": "user", "content": f"m{i}"} for i in range(30)]
            out = await chat_service._maybe_compact_history(hist, None, None)
            assert out is hist
        finally:
            object.__setattr__(settings, "history_compact_threshold", old)

    def test_compaction_default_on(self):
        """814G7：会话级 compaction 默认开（历史是上下文膨胀大头）"""
        from src.video_agent.config import settings

        assert settings.history_compact_threshold >= 12


class TestMaybeCompactHistory:
    class _FakeAdapter:
        def __init__(self):
            self.calls = 0

        async def chat(self, messages, **kwargs):
            self.calls += 1
            from src.video_agent.adapters.base_chat import ChatResponse

            return ChatResponse(content="摘要：用户要做短剧，已定规格。", finish_reason="stop")

    async def test_compacts_when_over_threshold(self, tmp_path, monkeypatch):
        from types import SimpleNamespace

        from src.video_agent.state.manager import StateManager

        monkeypatch.setattr(
            chat_consume, "settings",
            SimpleNamespace(history_compact_threshold=6, llm_timeout=10),
        )
        svc = StateManager(str(tmp_path))
        hist = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"m{i}"} for i in range(10)]
        adapter = self._FakeAdapter()
        out = await chat_service._maybe_compact_history(hist, svc, adapter)
        assert adapter.calls == 1
        # 摘要首条 + 最近 KEEP 条
        assert len(out) == 1 + chat_service._HISTORY_COMPACT_KEEP
        assert "会话摘要" in out[0]["content"]
        # 摘要缓存到 interaction（批 3.4：键 = 较早消息内容指纹 fp）
        cached = (svc.state_dict.get("interaction") or {}).get("session_summary") or {}
        assert cached.get("fp"), "内容指纹缓存键缺失"
        assert cached.get("text")

    async def test_cache_reuse_no_second_call(self, tmp_path, monkeypatch):
        from types import SimpleNamespace

        from src.video_agent.state.manager import StateManager
        from src.video_agent.web.chat_consume import (
            _HISTORY_COMPACT_KEEP,
            _history_fingerprint,
        )

        monkeypatch.setattr(
            chat_consume, "settings",
            SimpleNamespace(history_compact_threshold=2, llm_timeout=10),
        )
        svc = StateManager(str(tmp_path))
        hist = [{"role": "user", "content": f"m{i}"} for i in range(6)]
        # 预置与当前较早消息**内容指纹**匹配的缓存摘要（批 3.4：fp 键）
        older = hist[:-_HISTORY_COMPACT_KEEP]
        svc.state_dict.setdefault("interaction", {})["session_summary"] = {
            "fp": _history_fingerprint(older), "text": "缓存摘要",
        }
        adapter = self._FakeAdapter()
        out = await chat_service._maybe_compact_history(hist, svc, adapter)
        assert adapter.calls == 0, "命中缓存不得再调模型"
        assert "缓存摘要" in out[0]["content"]

    async def test_cache_invalidated_by_content_edit_not_just_count(
            self, tmp_path, monkeypatch):
        """批 3.4 指纹键语义：条数不变但内容被编辑重发 → 缓存必须失效重建。"""
        from types import SimpleNamespace

        from src.video_agent.state.manager import StateManager
        from src.video_agent.web.chat_consume import (
            _HISTORY_COMPACT_KEEP,
            _history_fingerprint,
        )

        monkeypatch.setattr(
            chat_consume, "settings",
            SimpleNamespace(history_compact_threshold=2, llm_timeout=10),
        )
        svc = StateManager(str(tmp_path))
        hist = [{"role": "user", "content": f"m{i}"} for i in range(6)]
        older = hist[:-_HISTORY_COMPACT_KEEP]
        stale_fp = _history_fingerprint(older)
        edited = [dict(m) for m in hist]
        edited[0]["content"] = "m0（已编辑重发）"      # 条数不变，内容变化
        edited_older = edited[:-_HISTORY_COMPACT_KEEP]
        assert _history_fingerprint(edited_older) != stale_fp
        svc.state_dict.setdefault("interaction", {})["session_summary"] = {
            "fp": stale_fp, "text": "陈旧摘要",
        }
        adapter = self._FakeAdapter()
        out = await chat_service._maybe_compact_history(edited, svc, adapter)
        assert adapter.calls == 1, "内容指纹变化必须失效重建，不得复用陈旧摘要"
        assert "陈旧摘要" not in out[0]["content"]


class TestGateOverridesStore:
    def test_store_gate_overrides_writes_interaction(self, tmp_path):
        """814F7：「本次放行」登记入 interaction，供 Planner 单次消费（§2.4 留痕）"""
        from src.video_agent.state.manager import StateManager

        svc = StateManager(str(tmp_path))
        chat_service._store_gate_overrides(svc, ["all", "  ", 123])
        inter = svc.state_dict.get("interaction") or {}
        assert inter.get("gate_overrides") == ["all"], "非法/空条目应被过滤"

    def test_store_gate_overrides_empty_noop(self, tmp_path):
        from src.video_agent.state.manager import StateManager

        svc = StateManager(str(tmp_path))
        chat_service._store_gate_overrides(svc, [])
        assert "gate_overrides" not in (svc.state_dict.get("interaction") or {})
