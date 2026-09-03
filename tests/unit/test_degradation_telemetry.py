"""承重接线降级遥测（整改计划批 8；814R 型断线防复发）。

五条承重接线的静默降级不再只进日志：异常回落时 record_degradation 计数，
经 /api/agent/degradations 端点可见（既有基建，零新增端点）。
钉死点位：豁免消费 / 暂停登记 / 会话压缩 / 事件通道 / 步间回收。
"""
import pytest

from src.video_agent.core import live_metrics
from src.video_agent.core.planner import Planner, PlannerResponse


@pytest.fixture(autouse=True)
def clean_counters():
    live_metrics.reset_degradations()
    yield
    live_metrics.reset_degradations()


def _points():
    return {r["point"] for r in live_metrics.get_degradations()}


class _BrokenState:
    """state_dict 即抛异常的假 StateManager（逼出 except 分支）"""

    @property
    def state_dict(self):
        raise RuntimeError("state broken")

    def save(self):
        raise RuntimeError("save broken")


def test_gate_override_consume_degradation_visible():
    from src.video_agent.core import planner_gate_session

    scope = planner_gate_session.consume_gate_overrides(_BrokenState(), "普通消息")
    assert scope is False or scope  # 回落兜底不抛异常
    assert "planner_gate_session.consume_gate_overrides" in _points()


def test_issue_pause_registration_degradation_visible():
    planner = Planner(state_manager=_BrokenState(), llm_adapter=None)
    resp = PlannerResponse(text="x", confirmation="请确认")
    planner._issue_pause(resp)  # 登记失败不阻断渲染
    assert resp.pause_id, "pause_id 签发不依赖登记成功"
    assert "planner._issue_pause" in _points()


async def test_session_compact_failure_degradation_visible(monkeypatch):
    from src.video_agent.config import settings
    from src.video_agent.web import history_compact as chat_consume

    original_threshold = settings.history_compact_threshold
    object.__setattr__(settings, "history_compact_threshold", 2)

    class _FailAdapter:
        async def chat(self, messages, **kw):
            raise RuntimeError("summary endpoint down")

    history = [{"role": "user", "content": f"m{i}"} for i in range(6)]

    class _Svc:
        state_dict = {"interaction": {}}

        def save_debounced(self):
            pass

        def get_chat_messages(self):
            return history

    try:
        out = await chat_consume._maybe_compact_history(history, _Svc(), _FailAdapter())
    finally:
        object.__setattr__(settings, "history_compact_threshold", original_threshold)
    assert out is history, "压缩失败必须回落原 history（优化不是前置条件）"
    assert "chat_consume.session_compact" in _points()


async def test_event_emit_degradation_visible(svc_env):
    """事件通道异常被吞时计数（loop 不中断，收尾正常）"""
    from src.video_agent.core.agent_loop import run_agent_loop
    from src.video_agent.core.action_executor import StateOperationExecutor

    svc, _ = svc_env
    executor = StateOperationExecutor(svc)

    async def llm_call(system_prompt, messages, stream_hook=None):
        return "好的", "stop", 0, 0.0, {}

    async def raising_event(ev):
        raise RuntimeError("frontend gone")

    result = await run_agent_loop(
        "x", llm_call=llm_call, context_builder=lambda: "ctx",
        executor=executor, history=[], on_event=raising_event,
    )
    assert result.text == "好的", "事件通道故障不得阻断对话收尾"
    assert "agent_loop.event_emit" in _points()


async def test_gate_precheck_degradation_visible(monkeypatch, tmp_path):
    """闸预检失败 fail-open：降级计数 + 交接模型循环（批 12 接替收权点）"""
    from src.video_agent.core.planner import Planner, PlannerContext
    from src.video_agent.adapters.base_chat import BaseChatAdapter, ChatResponse
    from src.video_agent.state.manager import StateManager

    class ProbeAdapter(BaseChatAdapter):
        def __init__(self):
            self.calls = 0

        @property
        def supports_function_calling(self):
            return False

        async def chat(self, messages, **kwargs):
            self.calls += 1
            return ChatResponse(content="ok", finish_reason="stop")

        async def chat_stream(self, messages, **kwargs):
            self.calls += 1
            yield ChatResponse(content="ok", finish_reason="stop")

    async def boom(self, context, user_message=""):
        raise RuntimeError("precheck down")

    monkeypatch.setattr(Planner, "_run_gate_precheck", boom)

    StateManager.reset_instance()
    svc = StateManager(str(tmp_path / "ws"))
    StateManager._instance = svc
    adapter = ProbeAdapter()
    planner = Planner(state_manager=svc, llm_adapter=adapter, tool_manager=None)
    await planner.handle_message("开始", PlannerContext(skill_name="AI-短剧一站式生成"))
    assert adapter.calls >= 1, "预检失败必须 fail-open 交接模型循环"
    assert "planner.gate_precheck" in _points()
    StateManager.reset_instance()


@pytest.fixture
def svc_env(tmp_path):
    from src.video_agent.state.manager import StateManager

    StateManager.reset_instance()
    instance = StateManager(str(tmp_path))
    StateManager._instance = instance
    yield instance, None
    StateManager.reset_instance()
