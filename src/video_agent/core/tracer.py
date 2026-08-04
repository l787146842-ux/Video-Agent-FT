"""
轻量 Agent 执行链路追踪器。

每轮 agent_loop step 记录：
    {trace_id, step, timing_ms, token_usage, actions_applied, finish_reason,
     actions: [{name, summary, elapsed_ms, ok}], reasoning}

actions/reasoning 供前端「过程时间线」折叠面板展示（不进 LLM 上下文），
随消息 trace 字段持久化，刷新页面后可重建。
通过 /api/agent/traces 端点暴露最近 50 条 trace（调试用）。
"""
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional

# reasoning 文本持久化上限（仅展示用，防 trace 膨胀）
_REASONING_MAX_CHARS = 500


@dataclass
class StepTrace:
    """单步追踪记录"""
    step: int = 0
    timing_ms: float = 0.0
    token_usage: int = 0
    actions_applied: int = 0
    finish_reason: str = ""
    # 本轮执行的操作明细（工具/ studio-actions），供前端时间线逐条展示
    actions: List[Dict[str, Any]] = field(default_factory=list)
    # 本轮 reasoning（深度思考）文本摘要（截断后）
    reasoning: str = ""


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
                    "actions": s.actions,
                    "reasoning": s.reasoning,
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
        # 当前 step 期间收集的操作明细与 reasoning（end_step 时归档）
        self._pending_actions: List[Dict[str, Any]] = []
        self._pending_reasoning: List[str] = []
        return trace_id

    def start_step(self) -> None:
        """标记一步的开始（计时起点）"""
        self._step_start = time.monotonic()
        self._pending_actions = []
        self._pending_reasoning = []

    def record_action(
        self,
        name: str,
        summary: str = "",
        elapsed_ms: float = 0.0,
        ok: bool = True,
    ) -> None:
        """记录当前 step 内的一个操作/工具调用（供前端时间线逐条展示）"""
        if self._current is None:
            return
        self._pending_actions.append({
            "name": name,
            "summary": summary,
            "elapsed_ms": round(elapsed_ms, 1),
            "ok": ok,
        })

    def record_reasoning(self, text: str) -> None:
        """追加当前 step 的 reasoning（深度思考）文本"""
        if self._current is None or not text:
            return
        self._pending_reasoning.append(text)

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
        reasoning = "".join(self._pending_reasoning)
        if len(reasoning) > _REASONING_MAX_CHARS:
            reasoning = reasoning[:_REASONING_MAX_CHARS] + "…"
        self._current.steps.append(StepTrace(
            step=step,
            timing_ms=timing_ms,
            token_usage=token_usage,
            actions_applied=actions_applied,
            finish_reason=finish_reason,
            actions=list(self._pending_actions),
            reasoning=reasoning,
        ))
        self._pending_actions = []
        self._pending_reasoning = []

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
