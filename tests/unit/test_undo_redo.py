"""单元测试：Undo/Redo 系统

覆盖：
- update() 后 undo 恢复前一步状态
- redo 重做已撤销的操作
- 新操作清空 redo 栈
- 栈上限（最多 20 步）
- 切换项目时清空栈
- can_undo / can_redo 属性
- 空栈时 undo/redo 返回 False
"""
import pytest

from src.video_agent.state.manager import StateManager


@pytest.fixture
def svc(tmp_path):
    StateManager.reset_instance()
    manager = StateManager(str(tmp_path))
    yield manager
    StateManager.reset_instance()


class TestUndoBasic:
    def test_undo_restores_previous_state(self, svc):
        """update 后 undo 应恢复前一步状态"""
        svc.update("status", "working")
        assert svc._raw_state["status"] == "working"

        ok = svc.undo()
        assert ok is True
        # 恢复为 demo 初始状态的 status（idle）
        assert svc._raw_state["status"] != "working"

    def test_undo_multiple_steps(self, svc):
        """多步 update 后逐步 undo"""
        svc.update("counter", 1)
        svc.update("counter", 2)
        svc.update("counter", 3)
        assert svc._raw_state["counter"] == 3

        svc.undo()
        assert svc._raw_state["counter"] == 2
        svc.undo()
        assert svc._raw_state["counter"] == 1

    def test_undo_empty_stack_returns_false(self, svc):
        """空栈 undo 返回 False"""
        assert svc.undo() is False

    def test_can_undo_property(self, svc):
        assert svc.can_undo is False
        svc.update("x", 1)
        assert svc.can_undo is True


class TestRedoBasic:
    def test_redo_after_undo(self, svc):
        """undo 后 redo 应恢复撤销前的状态"""
        svc.update("name", "Alice")
        svc.undo()
        assert svc._raw_state.get("name") != "Alice"

        ok = svc.redo()
        assert ok is True
        assert svc._raw_state["name"] == "Alice"

    def test_redo_empty_stack_returns_false(self, svc):
        """无撤销历史时 redo 返回 False"""
        assert svc.redo() is False

    def test_new_update_clears_redo_stack(self, svc):
        """新操作应清空 redo 栈"""
        svc.update("v", 1)
        svc.update("v", 2)
        svc.undo()  # v=1
        assert svc.can_redo is True

        svc.update("v", 99)  # 新操作
        assert svc.can_redo is False
        assert svc.redo() is False

    def test_can_redo_property(self, svc):
        assert svc.can_redo is False
        svc.update("x", 1)
        svc.undo()
        assert svc.can_redo is True


class TestUndoStackLimit:
    def test_max_20_undo_steps(self, svc):
        """undo 栈最多保留 20 步"""
        for i in range(25):
            svc.update("counter", i)

        # 只能 undo 20 次
        undo_count = 0
        while svc.undo():
            undo_count += 1
        assert undo_count == 20

    def test_oldest_entry_evicted(self, svc):
        """超过上限时最早的记录被淘汰"""
        svc.update("marker", "original")
        for i in range(25):
            svc.update("counter", i)

        # undo 20 次后，无法回到 "original"（已被淘汰）
        for _ in range(20):
            svc.undo()
        # 此时 counter 应为 4（最早的 0-3 已被淘汰）
        assert svc._raw_state.get("counter") == 4


class TestProjectSwitchClearsStack:
    def test_switch_project_clears_undo_redo(self, svc):
        """切换项目应清空 undo/redo 栈"""
        svc.update("data", "project-A")
        assert svc.can_undo is True

        # 创建并切换到新项目
        pid_b = svc.create_project("项目B")
        # create_project 内部会切换项目
        assert svc.can_undo is False
        assert svc.can_redo is False

    def test_undo_after_switch_does_not_affect_other_project(self, svc):
        """切换后 undo 不会跨项目影响"""
        svc.update("data", "A-data")
        pid_a = svc.active_project_id

        pid_b = svc.create_project("B")
        svc.update("data", "B-data")

        # 在 B 项目 undo
        svc.undo()
        assert svc._raw_state.get("data") != "B-data"

        # 切回 A，数据不受影响
        svc.switch_project(pid_a)
        assert svc._raw_state.get("data") == "A-data"
