# -*- coding: utf-8 -*-
"""五项修法批 1 钉死回归：内部压缩撞输出帽 fail-closed。

摘要调用返回 finish_reason=length（半截摘要）时：
- round_compact：不入指纹缓存、不替换轮组，走既有失败回落（截断链兜底）；
- history_compact：不落 interaction.session_summary、保留原 history，
  走既有失败回落（含降级遥测）。
根因链治理：4444 项目「思考耗尽 8192 输出预算」同类风险在压缩链路的闭环。
"""
import pytest

from src.video_agent.adapters.base_chat import ChatResponse
from src.video_agent.core import round_compact
from src.video_agent.web import history_compact


class LengthAdapter:
    """摘要调用恒撞输出帽（finish_reason=length）的假 adapter"""

    def __init__(self):
        self.calls = 0

    async def chat(self, messages, **kwargs):
        self.calls += 1
        return ChatResponse(content="摘", finish_reason="length")


def _big_turns(n=3, size=600):
    """n 个真实用户轮组：真实用户消息 + assistant(tool_calls) + 系统回喂。"""
    msgs = []
    for i in range(n):
        msgs.append({"role": "user", "content": f"第{i}轮用户指令" + "长" * size})
        msgs.append({"role": "assistant", "content": "",
                     "tool_calls": [{"id": f"c{i}", "type": "function",
                                     "function": {"name": "read_draft", "arguments": "{}"}}]})
        msgs.append({"role": "user", "content": "（系统）本轮调用的工具已执行完毕，结果如下：\n- read_draft：执行成功" + "喂" * size})
    return msgs


@pytest.fixture(autouse=True)
def _clear_compact_cache():
    """模块级指纹缓存跨用例隔离。"""
    round_compact._COMPACT_CACHE.clear()
    yield
    round_compact._COMPACT_CACHE.clear()


@pytest.mark.asyncio
async def test_round_compact_truncated_summary_falls_back():
    """循环内摘要撞帽：False + 消息不变 + 半截摘要不入缓存。"""
    msgs = _big_turns(3)
    before = list(msgs)
    adapter = LengthAdapter()
    ok = await round_compact.compact_oldest_round(msgs, adapter, 800, 4)
    assert ok is False
    assert msgs == before
    assert adapter.calls == 1, "撞帽走失败回落，不得重试摘要调用"
    assert round_compact._COMPACT_CACHE == {}, "半截摘要不得入指纹缓存"


@pytest.mark.asyncio
async def test_round_compact_truncated_after_cached_success_is_isolated():
    """缓存链路隔离：正常摘要先入缓存，后续撞帽不污染既有缓存。"""
    class OkAdapter:
        def __init__(self):
            self.calls = 0

        async def chat(self, messages, **kwargs):
            self.calls += 1
            return ChatResponse(content="摘要：确定了风格", finish_reason="stop")

    msgs = _big_turns(3)
    ok_adapter = OkAdapter()
    assert await round_compact.compact_oldest_round(msgs, ok_adapter, 800, 4) is True
    assert len(round_compact._COMPACT_CACHE) == 1

    fresh = _big_turns(4, size=900)  # 新内容 → 新指纹 → 必须发摘要调用
    bad = LengthAdapter()
    before = list(fresh)
    assert await round_compact.compact_oldest_round(fresh, bad, 800, 4) is False
    assert len(round_compact._COMPACT_CACHE) == 1, "撞帽不得写入缓存"
    assert fresh == before


@pytest.mark.asyncio
@pytest.mark.allow_degradation
async def test_history_compact_truncated_summary_falls_back(tmp_path, monkeypatch):
    """会话 compaction 摘要撞帽：保留原 history + 不落 session_summary。"""
    from types import SimpleNamespace

    from src.video_agent.state.manager import StateManager

    monkeypatch.setattr(
        history_compact, "settings",
        SimpleNamespace(history_compact_threshold=6, llm_timeout=10),
    )
    svc = StateManager(str(tmp_path))
    hist = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"m{i}"}
            for i in range(10)]
    adapter = LengthAdapter()
    out = await history_compact._maybe_compact_history(hist, svc, adapter)
    assert out is hist, "撞帽回落保留原 history"
    assert adapter.calls == 1, "撞帽走失败回落，不得重试摘要调用"
    cached = (svc.state_dict.get("interaction") or {}).get("session_summary")
    assert not cached, "半截摘要不得落 interaction.session_summary"
