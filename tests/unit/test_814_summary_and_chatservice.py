"""814R4 钉死回归：总结强制入正文接线 + chat_service 修复（重复 pop/公共编排/compaction）。

事故背景：
- `_prepend_script_summary` 有定义有测试但无生产调用（1111 台账「总结强制入正文」断线）；
- chat_service._consume_pending_confirmation 重复 pop；流式/非流式开场编排双份复制；
- 会话级 compaction（session_compact.md）无人消费。
"""
import inspect

from src.video_agent.core.planner import Planner, _prepend_script_summary
from src.video_agent.web import chat_consume, chat_service


class TestScriptSummaryWiring:
    def test_fc_track_wired(self):
        """FC 轨 llm_call 在取回工具结果后调用 _prepend_script_summary"""
        src = inspect.getsource(Planner.handle_message)
        assert "_prepend_script_summary(content, tool_results)" in src

    def test_text_track_wired(self):
        """文本轨：执行过 script_analyze 且暂停时补拼总结"""
        src = inspect.getsource(Planner.handle_message)
        assert "skill_stages_done" in src and "_prepend_script_summary(loop_result.confirmation" in src

    def test_no_dup_when_already_shown(self):
        tr = [{"name": "script_analyze", "ok": True, "data": {"summary": "少年踏上复仇路"}}]
        # 正文已含总结 → 原样返回，不重复拼
        assert _prepend_script_summary("总结：少年踏上复仇路。", tr) == "总结：少年踏上复仇路。"

    def test_prepends_when_missing(self):
        tr = [{"name": "script_analyze", "ok": True, "data": {"summary": "少年踏上复仇路"}}]
        out = _prepend_script_summary("已读取剧本。", tr)
        assert out.startswith("**剧本一句话总结**：少年踏上复仇路")


class TestChatServiceFixes:
    def test_no_duplicate_pop(self):
        """_consume_pending_confirmation 的 pending_pause_kind 只允许 pop 一次"""
        src = inspect.getsource(chat_service._consume_pending_confirmation)
        assert src.count('interaction.pop("pending_pause_kind"') == 1

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
        # 摘要缓存到 interaction
        assert (svc.state_dict.get("interaction") or {}).get("session_summary", {}).get("count")

    async def test_cache_reuse_no_second_call(self, tmp_path, monkeypatch):
        from types import SimpleNamespace

        from src.video_agent.state.manager import StateManager

        monkeypatch.setattr(
            chat_consume, "settings",
            SimpleNamespace(history_compact_threshold=2, llm_timeout=10),
        )
        svc = StateManager(str(tmp_path))
        # 预置与当前消息数匹配的缓存摘要
        msg_count = len(svc.get_chat_messages())
        svc.state_dict.setdefault("interaction", {})["session_summary"] = {
            "count": msg_count, "text": "缓存摘要",
        }
        hist = [{"role": "user", "content": f"m{i}"} for i in range(6)]
        adapter = self._FakeAdapter()
        out = await chat_service._maybe_compact_history(hist, svc, adapter)
        assert adapter.calls == 0, "命中缓存不得再调模型"
        assert "缓存摘要" in out[0]["content"]


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
