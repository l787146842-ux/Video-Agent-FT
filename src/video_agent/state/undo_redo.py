"""
Undo/Redo Mixin — 从 StateManager 抽离。

提供 _push_undo / undo / redo / can_undo / can_redo 功能。
StateManager 通过继承此 Mixin 获得撤销/重做能力。
"""
import copy
from typing import Any, Dict, List


class UndoRedoMixin:
    """Undo/Redo 栈管理 Mixin。

    依赖宿主类提供：
    - self._raw_state: Dict[str, Any]
    - self._context_cache: Dict[str, str]
    - self.save() -> None
    """

    _undo_stack: List[Dict[str, Any]]
    _redo_stack: List[Dict[str, Any]]
    _max_undo: int

    def _init_undo_redo(self, max_undo: int = 20) -> None:
        """初始化 undo/redo 栈（在宿主 __init__ 中调用）"""
        self._undo_stack = []
        self._redo_stack = []
        self._max_undo = max_undo

    def _state_copy_for_stack(self) -> Dict[str, Any]:
        """压栈用深拷贝：排除 E1 快照区（指针化防嵌套膨胀）"""
        return copy.deepcopy(
            {k: v for k, v in self._raw_state.items() if k != "stateSnapshots"})

    def _apply_stack_state(self, state: Dict[str, Any]) -> None:
        """写回栈状态：快照区不在栈内，保留当前快照区（回退不丢版本列表）"""
        if "stateSnapshots" not in state and "stateSnapshots" in self._raw_state:
            state["stateSnapshots"] = self._raw_state["stateSnapshots"]
        self._raw_state = state

    def _push_undo(self) -> None:
        """在写入前保存当前状态到 undo 栈"""
        self._undo_stack.append(self._state_copy_for_stack())
        if len(self._undo_stack) > self._max_undo:
            self._undo_stack.pop(0)
        self._redo_stack.clear()

    def push_undo(self) -> None:
        """公开的 undo 快照入口（Web 路由做撤销检查点用，等价于 _push_undo）"""
        self._push_undo()

    def _discard_last_undo(self) -> None:
        """丢弃最近一次 _push_undo 的快照（预先压栈但实际无状态变更时调用）"""
        if self._undo_stack:
            self._undo_stack.pop()

    def discard_last_undo(self) -> None:
        """公开的丢弃快照入口（等价于 _discard_last_undo，供 executor 等外部调用）"""
        self._discard_last_undo()

    def undo(self) -> bool:
        """撤销上一步操作，返回是否成功"""
        if not self._undo_stack:
            return False
        self._redo_stack.append(self._state_copy_for_stack())
        self._apply_stack_state(self._undo_stack.pop())
        self._context_cache.clear()
        self.save()
        return True

    def redo(self) -> bool:
        """重做上一步撤销的操作，返回是否成功"""
        if not self._redo_stack:
            return False
        self._undo_stack.append(self._state_copy_for_stack())
        self._apply_stack_state(self._redo_stack.pop())
        self._context_cache.clear()
        self.save()
        return True

    @property
    def can_undo(self) -> bool:
        return len(self._undo_stack) > 0

    @property
    def can_redo(self) -> bool:
        return len(self._redo_stack) > 0

    def _clear_undo_redo(self) -> None:
        """清空栈（切换项目时调用）"""
        self._undo_stack.clear()
        self._redo_stack.clear()
