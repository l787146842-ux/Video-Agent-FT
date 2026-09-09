"""plan_write 计划清单工具单测（细案 docs/计划清单工具细案.md §七）。

校验矩阵（空/超上限/空 content/重复/双 in_progress/非法状态/正常覆盖）、
last-write-wins 整表替换、错误信封三字段、state 落盘形状、
注入面（空清单不注入 / 紧凑两键）、轮首裁剪表不受影响。
"""
import pytest

from src.video_agent.state.context_builder import _build_snapshot_dict
from src.video_agent.state.manager import StateManager
from src.video_agent.tools.manager import ToolManager
from src.video_agent.tools.plan_tools import (
    MAX_ITEMS,
    PlanWriteTool,
    register_plan_tools,
    validate_plan_items,
)


@pytest.fixture(autouse=True)
def _reset_tools():
    ToolManager.reset()
    register_plan_tools()
    yield
    ToolManager.reset()


@pytest.fixture
def svc(tmp_path):
    StateManager.reset_instance()
    instance = StateManager(str(tmp_path))
    StateManager._instance = instance
    yield instance
    StateManager.reset_instance()


def _items(n, status="pending", start=0):
    return [{"content": f"步骤{i}", "status": status}
            for i in range(start, start + n)]


class TestValidatePlanItems:
    """校验纯函数矩阵：通过 = ("", "")，失败 = (原因码, 话术≤3句)"""

    def test_empty_rejected(self):
        code, msg = validate_plan_items([])
        assert code == "empty" and msg

    def test_over_limit_rejected(self):
        code, _ = validate_plan_items(_items(MAX_ITEMS + 1))
        assert code == "too_many"

    def test_blank_content_rejected(self):
        code, _ = validate_plan_items([{"content": "  ", "status": "pending"}])
        assert code == "blank"

    def test_duplicate_rejected(self):
        code, _ = validate_plan_items(_items(1) + _items(1))
        assert code == "duplicate"

    def test_bad_status_rejected(self):
        code, _ = validate_plan_items(
            [{"content": "a", "status": "doing"}])
        assert code == "bad_status"

    def test_multi_in_progress_rejected(self):
        code, msg = validate_plan_items(
            _items(1, "in_progress") + _items(1, "in_progress", 1))
        assert code == "multi_active" and "2 个 in_progress" in msg

    def test_single_active_ok(self):
        assert validate_plan_items(
            _items(1, "in_progress") + _items(2, "pending", 1)) == ("", "")

    def test_error_prose_at_most_three_sentences(self):
        # v4-1 口径：回喂话术单条 ≤3 句
        for bad in ([], _items(MAX_ITEMS + 1), [{"content": "", "status": "x"}],
                    _items(1, "in_progress") + _items(1, "in_progress", 1)):
            _, msg = validate_plan_items(bad)
            assert msg.count("。") <= 3


class TestPlanWriteTool:
    async def _write(self, todos):
        return await ToolManager.invoke_tool("plan_write", {"todos": todos})

    async def test_success_lands_state(self, svc):
        result = await self._write(_items(3, "in_progress", 0)[:1]
                                   + _items(2, "pending", 1))
        assert result.success is True, result.error
        assert result.data == {"items": 3, "open": 3}
        plan = svc.state_dict["plan"]
        assert len(plan["items"]) == 3
        assert plan["items"][0]["status"] == "in_progress"
        assert "updated_turn" in plan

    async def test_last_write_wins_full_replace(self, svc):
        await self._write(_items(5))
        result = await self._write(_items(2))
        assert result.success is True
        assert len(svc.state_dict["plan"]["items"]) == 2

    async def test_validation_failure_keeps_old_plan(self, svc):
        await self._write(_items(3))
        result = await self._write(
            _items(1, "in_progress") + _items(1, "in_progress", 1))
        assert result.success is False
        assert result.error_code == "validation"
        assert result.retryable is False
        assert len(svc.state_dict["plan"]["items"]) == 3  # 旧清单保留

    async def test_unknown_field_rejected_by_strict_schema(self, svc):
        result = await self._write(
            [{"content": "a", "status": "pending", "extra": 1}])
        assert result.success is False
        assert result.error_code == "validation"

    async def test_registered_declarations(self):
        tool = ToolManager.get_tool("plan_write")
        assert tool.risk == "low"
        assert tool.detail_tier == "expand"
        assert tool.parallel_safe is False
        assert tool.costly is False


class TestPlanInjectionSurface:
    """注入面（细案 §四/§五）：空清单不注入；有清单只带 content/status 两键"""

    def _snapshot(self, raw):
        return _build_snapshot_dict(raw, "bound")

    def test_empty_plan_injects_nothing(self):
        assert self._snapshot({}).get("plan") == {}
        assert self._snapshot({"plan": {"items": []}}).get("plan") == {}

    def test_plan_compact_two_keys(self):
        snap = self._snapshot({"plan": {
            "items": [{"content": "拆镜", "status": "in_progress",
                       "noise": "x"}],
            "updated_turn": 7}})
        assert snap["plan"] == [{"content": "拆镜", "status": "in_progress"}]

    def test_plan_write_in_pause_window_readonly_set(self):
        from src.video_agent.core.fc_gates import PAUSE_WINDOW_READONLY
        assert "plan_write" in PAUSE_WINDOW_READONLY

    def test_plan_write_in_studio_state_tools(self):
        from src.video_agent.core.planner import _STUDIO_STATE_TOOLS
        assert "plan_write" in _STUDIO_STATE_TOOLS

    def test_projection_keys_include_plan(self):
        from src.video_agent.state.context_builder import _BOARD_PROJECTION_KEYS
        assert "plan" in _BOARD_PROJECTION_KEYS
