"""协作式停止信号注册表（端到端中断协议）。

目标不变式：**任何中断都有痕迹、都有出口**。

停止信号只经本模块（标志注册表）与任务注册表传递——闸机
（guard_pipeline/fc_tool_runner）不感知停止语义，避免触碰并行任务在改的文件。

职责：
- request_stop(scope)：停止端点（/agent/tasks/{id}/stop）在
  cancel asyncio.Task 之前先置标志，保证 CancelledError 先落时也能
  识别为「用户主动停止」而非异常取消。
- is_stop_requested(scope)：agent_loop 每步检查点读取（模型调用前 /
  工具批边界），命中即干净收尾退出循环并发 stopped 终态事件。
- clear_stop(scope, stop_id)：循环开始与收尾时清理，防先前轮次残留标志误杀新任务；
  代际 token（防与 in-flight cancel 竞态）：request_stop 返回单调递增的
  stop_id，带 id 的清理仅在当前代际匹配时生效——旧运行收尾不得误清
  快速重连后新发的停止请求；不带 id（循环开头残留清理）无条件清除。

scope 约定：任务式传输用 task_id（多任务并发互不串）；非流式用 "nonstream"。

阶段标记（stopped 事件 phase 字段，前端据此措辞）：
- thinking：思考阶段（模型调用前/间，尚未产生可见内容）
- tool_executing：工具执行阶段（FC 工具批边界）
- streaming：输出阶段（已产生流式正文）
"""
from typing import Dict, Optional

# 停止标志表（scope → 停止请求代际 token）；>0 = 已请求停止。
# 代际单调递增：每次 request_stop 换代，收尾清理按代匹配防误清新请求；
# 单进程内事件循环单线程访问，无需加锁
_STOP_FLAGS: Dict[str, int] = {}

# 停止阶段标记（stopped 事件 phase 字段取值，前后端契约）
STOP_PHASE_THINKING = "thinking"
STOP_PHASE_TOOL_EXECUTING = "tool_executing"
STOP_PHASE_STREAMING = "streaming"

_VALID_PHASES = frozenset({STOP_PHASE_THINKING, STOP_PHASE_TOOL_EXECUTING, STOP_PHASE_STREAMING})


def request_stop(scope: str = "chat") -> int:
    """请求停止指定作用域的运行循环（停止端点调用，须先于 task.cancel()）。

    返回本次停止请求的代际 token（单调递增）：观察方（agent_loop 检查点）
    携带该 id 收尾清理，快速重连后的新停止请求不会被旧运行收尾误清。
    """
    scope = scope or "chat"
    stop_id = int(_STOP_FLAGS.get(scope, 0)) + 1
    _STOP_FLAGS[scope] = stop_id
    return stop_id


def current_stop_id(scope: str = "chat") -> int:
    """当前停止请求的代际 token（0 = 无停止请求；检查点观察时快照用）。"""
    return int(_STOP_FLAGS.get(scope or "chat", 0) or 0)


def is_stop_requested(scope: str = "chat") -> bool:
    """检查点读取：该作用域是否已被请求停止"""
    return current_stop_id(scope) > 0


def clear_stop(scope: str = "chat", stop_id: Optional[int] = None) -> bool:
    """清除停止标志（循环开始/收尾调用；防残留误杀下一任务）。

    stop_id 非空 = 代际匹配清理：仅当当前代际与观察时快照一致才清除，
    新发的停止请求（代际已前进）不会被误清，返回 False；
    stop_id 缺省 = 无条件清除（循环开头清残留场景）。返回是否清除了。
    """
    scope = scope or "chat"
    if stop_id is not None and current_stop_id(scope) != int(stop_id):
        return False
    _STOP_FLAGS.pop(scope, None)
    return True


class AgentStoppedError(Exception):
    """协作式取消检查点命中时抛出：携带阶段标记，由 agent_loop 捕获后
    干净收尾（发 stopped 终态事件 + 清理退出），不当作故障处理。

    stop_id：观察方命中检查点时快照的停止代际 token，收尾清理按代匹配，
    防旧运行收尾误清快速重连后新发的停止请求。
    """

    def __init__(self, phase: str = STOP_PHASE_THINKING, step: int = 0,
                 stop_id: int = 0):
        self.phase = phase if phase in _VALID_PHASES else STOP_PHASE_THINKING
        self.step = int(step or 0)
        self.stop_id = int(stop_id or 0)
        super().__init__(f"agent stopped by user at phase={self.phase} step={self.step}")


__all__ = [
    "STOP_PHASE_THINKING",
    "STOP_PHASE_TOOL_EXECUTING",
    "STOP_PHASE_STREAMING",
    "request_stop",
    "current_stop_id",
    "is_stop_requested",
    "clear_stop",
    "AgentStoppedError",
]
