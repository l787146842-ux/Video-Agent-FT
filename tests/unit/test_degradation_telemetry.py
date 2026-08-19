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
    from src.video_agent.web import chat_consume

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

    out = await chat_consume._maybe_compact_history(history, _Svc(), _FailAdapter())
    assert out is history, "压缩失败必须回落原 history（优化不是前置条件）"
    assert "chat_consume.session_compact" in _points()


async def test_event_emit_degradation_visible(svc_env):
    """事件通道异常被吞时计数（loop 不中断，收尾正常）"""
    from src.video_agent.core.agent_loop import run_agent_loop
    from src.video_agent.web.action_executor import StudioActionExecutor

    svc, _ = svc_env
    executor = StudioActionExecutor(svc)

    async def llm_call(system_prompt, messages, stream_hook=None):
        return "好的", "stop", 0

    async def raising_event(ev):
        raise RuntimeError("frontend gone")

    result = await run_agent_loop(
        "x", llm_call=llm_call, context_builder=lambda: "ctx",
        executor=executor, history=[], on_event=raising_event,
    )
    assert result.text == "好的", "事件通道故障不得阻断对话收尾"
    assert "agent_loop.event_emit" in _points()


async def test_between_steps_reclaim_degradation_visible(monkeypatch):
    """步间回收评估失败 fail-open：钩子返 None（循环继续）且降级可见"""
    from src.video_agent.config import settings
    from src.video_agent.core import pipeline_orchestrator as po
    from src.video_agent.core import planner_triage

    object.__setattr__(settings, "pipeline_orchestrator_enabled", True)

    async def boom(state_manager, skill, user_message=""):
        raise RuntimeError("orchestrator down")

    monkeypatch.setattr(po, "orchestrate_turn", boom)

    hook = planner_triage.make_reclaim_hook(_BrokenState(), "AI-短剧一站式生成")
    reclaim = await hook(1)
    assert reclaim is None, "回收评估失败必须 fail-open（不劫持模型循环）"
    assert "planner.between_steps_reclaim" in _points()


@pytest.fixture
def svc_env(tmp_path):
    from src.video_agent.state.manager import StateManager

    StateManager.reset_instance()
    instance = StateManager(str(tmp_path))
    StateManager._instance = instance
    yield instance, None
    StateManager.reset_instance()
