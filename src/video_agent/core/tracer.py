"""
轻量 Agent 执行链路追踪器。

每轮 agent_loop step 记录：
    {trace_id, step, timing_ms, token_usage, actions_applied, finish_reason}

通过 /api/agent/traces 端点暴露最近 50 条 trace（调试用）。
"""
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional


@dataclass
class StepTrace:
    """单步追踪记录"""
    step: int = 0
    timing_ms: float = 0.0
    token_usage: int = 0
    actions_applied: int = 0
    finish_reason: str = ""


@dataclass
class TraceRecord:
    """一次完整对话的追踪记录"""
    trace_id: str = ""
    timestamp: float = 0.0
    total_ms: float = 0.0
    steps: List[StepTrace] = field(default_factory=list)
    total_actions: int = 0
    user_message_preview: str = ""  # 前 80 字符

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "timestamp": self.timestamp,
            "total_ms": round(self.total_ms, 1),
            "total_actions": self.total_actions,
            "user_message_preview": self.user_message_preview,
            "steps": [
                {
                    "step": s.step,
                    "timing_ms": round(s.timing_ms, 1),
                    "token_usage": s.token_usage,
                    "actions_applied": s.actions_applied,
                    "finish_reason": s.finish_reason,
                }
                for s in self.steps
            ],
        }


class AgentTracer:
    """
    内存追踪器（单例）—— 保留最近 N 条 trace，无持久化开销。
    生产环境可通过配置关闭。
    """

    _instance: Optional["AgentTracer"] = None
    MAX_TRACES = 50

    def __init__(self):
        self._traces: Deque[TraceRecord] = deque(maxlen=self.MAX_TRACES)
        self._current: Optional[TraceRecord] = None
        self._step_start: float = 0.0

    @classmethod
    def get_instance(cls) -> "AgentTracer":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """测试用：重置单例"""
        cls._instance = None

    def start_trace(self, user_message: str = "") -> str:
        """开始一次新追踪，返回 trace_id"""
        trace_id = uuid.uuid4().hex[:12]
        self._current = TraceRecord(
            trace_id=trace_id,
            timestamp=time.time(),
            user_message_preview=user_message[:80],
        )
        self._step_start = time.monotonic()
        return trace_id

    def start_step(self) -> None:
        """标记一步的开始（计时起点）"""
        self._step_start = time.monotonic()

    def end_step(
        self,
        step: int,
        actions_applied: int = 0,
        finish_reason: str = "",
        token_usage: int = 0,
    ) -> None:
        """记录一步的完成"""
        if self._current is None:
            return
        timing_ms = (time.monotonic() - self._step_start) * 1000
        self._current.steps.append(StepTrace(
            step=step,
            timing_ms=timing_ms,
            token_usage=token_usage,
            actions_applied=actions_applied,
            finish_reason=finish_reason,
        ))

    def finish_trace(self, total_actions: int = 0) -> Dict[str, Any]:
        """完成追踪并存入历史，返回本次 trace 的 dict（供 done payload 下发前端展示）"""
        if self._current is None:
            return {}
        self._current.total_ms = (time.monotonic() - self._step_start) * 1000
        # 使用第一步开始到最后的总时间
        if self._current.steps:
            self._current.total_ms = sum(s.timing_ms for s in self._current.steps)
        self._current.total_actions = total_actions
        record = self._current.to_dict()
        self._traces.append(self._current)
        self._current = None
        return record

    def get_recent_traces(self, limit: int = 50) -> List[Dict[str, Any]]:
        """获取最近 N 条追踪记录"""
        traces = list(self._traces)[-limit:]
        return [t.to_dict() for t in reversed(traces)]
