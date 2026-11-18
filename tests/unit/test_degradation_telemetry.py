"""承重接线降级遥测（整改计划批 8；814R 型断线防复发）。

五条承重接线的静默降级不再只进日志：异常回落时 record_degradation 计数，
经 /api/agent/degradations 端点可见（既有基建，零新增端点）。
钉死点位：豁免消费 / 暂停登记 / 会话压缩 / 事件通道 / 步间回收。
"""
import pytest

from src.video_agent.utils import live_metrics
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


async def test_gate_precheck_not_applied(monkeypatch, tmp_path):
    """闸预检已于 2026-11-12 宽权限批整体退役（计划 §5：删除
    `planner_triage.run_gate_precheck` 调用）——Planner 不再持有该入口，
    规格/原料前置闸归模型按 Skill 散文判断，平台只在工具调用点保留
    暂停纪律/风险/花钱确认三闸。

    本用例守卫「退役不复活」：Planner 一旦重新长出 `_run_gate_precheck`
    或 `planner_triage` 模块，说明有人在业务闸上回潮。"""
    from src.video_agent.core.planner import Planner

    assert not hasattr(Planner, "_run_gate_precheck"), (
        "闸预检入口回潮：2026-11-12 宽权限批已删除该业务型预检"
        "（规格/原料前置闸归模型按 Skill 散文判断）")
    try:
        import src.video_agent.core.planner_triage as _triage  # noqa: F401
    except ImportError:
        pass
    else:
        raise AssertionError(
            "planner_triage 模块回潮：其唯一函数 run_gate_precheck 已随"
            "2026-11-12 宽权限批退役，模块应保持删除状态")


@pytest.fixture
def svc_env(tmp_path):
    from src.video_agent.state.manager import StateManager

    StateManager.reset_instance()
    instance = StateManager(str(tmp_path))
    StateManager._instance = instance
    yield instance, None
    StateManager.reset_instance()
