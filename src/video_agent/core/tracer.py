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
import json
from typing import Any, Deque, Dict, List, Optional

from loguru import logger

from src.video_agent.config import settings
from src.video_agent.utils.paths import DATA_DIR

# reasoning 文本持久化长度（仅展示用，防 trace 膨胀；D11：保留尾部，头部省略）
_REASONING_HEAD_NOTE = "…（前文思考已截断）"


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
    # 本轮闸机判定明细（814R2 恢复：rule_id/层/结果/是否被申诉放行），供审计与前端展示
    gates: List[Dict[str, Any]] = field(default_factory=list)
    # 本轮轮末卡片仲裁明细（四轮 R1/#4：候选策略/胜出者），供 /api/agent/traces 审计
    card_decisions: List[Dict[str, Any]] = field(default_factory=list)
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
    user_id: str = ""  # 多用户归属（814E6 基础，完整鉴权另行立项）
    llm_calls: int = 0  # N6：本 trace 含模型调用次数（成本看板口径用）

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "timestamp": self.timestamp,
            "total_ms": round(self.total_ms, 1),
            "total_actions": self.total_actions,
            "user_message_preview": self.user_message_preview,
            "user_id": self.user_id,
            "llm_calls": self.llm_calls,
            "steps": [
                {
                    "step": s.step,
                    "timing_ms": round(s.timing_ms, 1),
                    "token_usage": s.token_usage,
                    "actions_applied": s.actions_applied,
                    "finish_reason": s.finish_reason,
                    "actions": s.actions,
                    "gates": s.gates,
                    "card_decisions": s.card_decisions,
                    "reasoning": s.reasoning,
                }
                for s in self.steps
            ],
        }


class AgentTracer:
    """
    追踪器（单例）—— 内存保留最近 N 条 + JSONL 文件持久化（W22）。
    文件超限自动轮转（保留 trace_rotation_keep 份），重载按 trace_id 去重。
    """

    _instance: Optional["AgentTracer"] = None
    MAX_TRACES = 50

    def __init__(self):
        self._traces: Deque[TraceRecord] = deque(maxlen=self.MAX_TRACES)
        self._current: Optional[TraceRecord] = None
        self._step_start: float = 0.0
        # 全局闸机判定流（814R2 恢复审计）：不依附单次 trace，供 /api/agent/gates 调试端点
        self._recent_gates: Deque[Dict[str, Any]] = deque(maxlen=100)
        # B10：模型降级事件计数（fallback 频率指标；record_fallback 写入）
        self._fallback_events: Deque[Dict[str, Any]] = deque(maxlen=200)
        self._persist_path = DATA_DIR / "agent_traces.jsonl"

    @classmethod
    def get_instance(cls) -> "AgentTracer":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """测试用：重置单例"""
        cls._instance = None

    def start_trace(self, user_message: str = "", user_id: str = "") -> str:
        """开始一次新追踪，返回 trace_id"""
        trace_id = uuid.uuid4().hex[:12]
        self._current = TraceRecord(
            trace_id=trace_id,
            timestamp=time.time(),
            user_message_preview=user_message[:80],
            user_id=user_id or "",
        )
        self._step_start = time.monotonic()
        # 当前 step 期间收集的操作明细与 reasoning（end_step 时归档）
        self._pending_actions: List[Dict[str, Any]] = []
        self._pending_gates: List[Dict[str, Any]] = []
        self._pending_cards: List[Dict[str, Any]] = []
        self._pending_reasoning: List[str] = []
        # 执行器子步骤缓冲（814G2）：子步骤先于父工具完成时暂存，
        # 待父工具 record_action 时挂到父条目之后（持久化顺序 = live 顺序）
        self._pending_subs: List[Dict[str, Any]] = []
        return trace_id

    def start_step(self) -> None:
        """标记一步的开始（计时起点）"""
        self._step_start = time.monotonic()
        self._pending_actions = []
        self._pending_gates = []
        self._pending_cards = []
        self._pending_reasoning = []
        self._pending_subs = []

    def record_action(
        self,
        name: str,
        summary: str = "",
        elapsed_ms: float = 0.0,
        ok: bool = True,
        stage: str = "",
    ) -> Dict[str, Any]:
        """记录当前 step 内的一个操作/工具调用（供前端时间线逐条展示）。

        stage（B2/F15）：大阶段标签（后端权威下发，前端不再按工具名推断）。
        返回条目 dict（调用方可事后补填 elapsed_ms，如规划条目先占位后计时）；
        同时把缓冲的执行器子步骤挂到本条目之后（814G2 顺序一致性）。
        """
        entry = {
            "name": name,
            "summary": summary,
            "elapsed_ms": round(elapsed_ms, 1),
            "ok": ok,
        }
        if stage:
            entry["stage"] = stage
        if self._current is None:
            return entry
        self._pending_actions.append(entry)
        if self._pending_subs:
            self._pending_actions.extend(self._pending_subs)
            self._pending_subs = []
        return entry

    def record_subaction(
        self,
        name: str,
        summary: str = "",
        elapsed_ms: float = 0.0,
        ok: bool = True,
    ) -> None:
        """执行器子步骤（814G2）：缓冲到 _pending_subs，随下一个父 record_action
        挂到父条目之后；step 结束仍无父条目时由 end_step 兜底落盘。"""
        if self._current is None:
            return
        self._pending_subs.append({
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

    def record_gate(
        self,
        rule_id: str,
        layer: str,
        ok: bool,
        skill_name: str = "",
        action: str = "",
        draft_id: str = "",
        overridden: bool = False,
        message: str = "",
    ) -> None:
        """记录一条闸机判定（814R2 恢复审计）：归档到当前 step + 全局调试流"""
        entry = {
            "ts": time.time(),
            "rule_id": rule_id,
            "layer": layer,
            "ok": ok,
            "overridden": overridden,
            "skill_name": skill_name,
            "action": action,
            "draft_id": draft_id,
            "message": str(message or "")[:200],
        }
        self._recent_gates.append(entry)
        if self._current is not None:
            self._pending_gates.append(entry)

    def record_card_decision(
        self,
        step: int,
        candidates: List[str],
        winner: str,
    ) -> None:
        """四轮 R1（#4 仲裁可观测）：记录一次轮末卡片仲裁——
        全部命中候选策略 + 胜出者，随 step 归档，/api/agent/traces 可审计。"""
        if self._current is None:
            return
        self._pending_cards.append({
            "ts": time.time(),
            "step": step,
            "candidates": list(candidates or []),
            "winner": str(winner or ""),
        })

    def record_fallback(self, provider: str, model: str) -> None:
        """B10：记录一次模型降级切换（fallback 频率指标；内存滚动保留）。"""
        self._fallback_events.append({
            "ts": time.time(), "provider": provider, "model": model,
        })

    def record_llm_call(self) -> None:
        """N6（三轮审核）：当前 trace 模型调用 +1——成本看板平均耗时仅聚合含模型调用的轮。"""
        if self._current is not None:
            self._current.llm_calls += 1

    def metrics(self) -> Dict[str, Any]:
        """B10：成本看板聚合（内存 + 文件 trace，按 trace_id 去重）。

        N6：平均耗时仅聚合 llm_calls>0 的 trace（零模型调用的引导卡/直出卡
        不再拉低均值）；旧 trace 无 llm_calls 字段时回落全量口径。
        """
        traces = self.get_recent_traces(limit=200)
        llm_traces = [t for t in traces if int(t.get("llm_calls") or 0) > 0]
        scope = "llm_rounds" if llm_traces else "all"
        avg_base = llm_traces or traces
        avg_ms = (
            sum(float(t.get("total_ms") or 0) for t in avg_base) / len(avg_base)
            if avg_base else 0.0
        )
        steps = sum(len(t.get("steps") or []) for t in traces)
        actions = sum(int(t.get("total_actions") or 0) for t in traces)
        gates = [g for t in traces for s in (t.get("steps") or []) for g in (s.get("gates") or [])]
        intercepts = sum(1 for g in gates if not g.get("ok"))
        return {
            "traces_count": len(traces),
            "avg_turn_ms": round(avg_ms, 1),
            "avg_turn_scope": scope,
            "total_steps": steps,
            "total_actions": actions,
            "gate_total": len(gates),
            "gate_intercepts": intercepts,
            "gate_intercept_rate": round(intercepts / len(gates), 3) if gates else 0.0,
            "fallback_count": len(self._fallback_events),
            "recent_fallbacks": list(reversed(list(self._fallback_events)))[:10],
        }

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
        # D11：保留尾部（最新思考最有回看价值），头部省略
        max_chars = int(getattr(settings, "trace_reasoning_max_chars", 0) or 2000)
        if len(reasoning) > max_chars:
            reasoning = _REASONING_HEAD_NOTE + reasoning[-max_chars:]
        # 814G2：step 结束仍无父条目承接的子步骤兜底落盘（防丢）
        if self._pending_subs:
            self._pending_actions.extend(self._pending_subs)
            self._pending_subs = []
        self._current.steps.append(StepTrace(
            step=step,
            timing_ms=timing_ms,
            token_usage=token_usage,
            actions_applied=actions_applied,
            finish_reason=finish_reason,
            actions=list(self._pending_actions),
            gates=list(self._pending_gates),
            card_decisions=list(self._pending_cards),
            reasoning=reasoning,
        ))
        self._pending_actions = []
        self._pending_gates = []
        self._pending_cards = []
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
        self._persist_record(record)
        return record

    def _persist_record(self, record: Dict[str, Any]) -> None:
        """追加一条 trace 到 JSONL；文件超限时轮转（.1/.2…，超过保留份数丢弃最旧）。"""
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            line = json.dumps(record, ensure_ascii=False)
            self._rotate_if_needed()
            with open(self._persist_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception as e:
            logger.warning(f"[Tracer] trace 落盘失败（不影响主流程）: {e}")

    def _rotate_if_needed(self) -> None:
        max_bytes = int(getattr(settings, "trace_file_max_bytes", 2_000_000))
        keep = int(getattr(settings, "trace_rotation_keep", 3))
        try:
            if not self._persist_path.exists():
                return
            if self._persist_path.stat().st_size <= max_bytes:
                return
            # .N 依次后移；超过保留份数的最旧一份丢弃
            for n in range(keep - 1, 0, -1):
                src = self._persist_path.with_suffix(f".jsonl.{n}")
                dst = self._persist_path.with_suffix(f".jsonl.{n + 1}")
                if src.exists():
                    if dst.exists():
                        dst.unlink()
                    src.rename(dst)
            first = self._persist_path.with_suffix(".jsonl.1")
            if first.exists():
                first.unlink()
            self._persist_path.rename(first)
            # N6/L2：总容量上限——合计超 cap 时从编号最大（最旧）的 .N 丢弃
            cap = int(getattr(settings, "trace_total_max_bytes", 20_000_000))
            for n in range(keep + 1, 0, -1):
                files = [self._persist_path] + [
                    self._persist_path.with_suffix(f".jsonl.{i}") for i in range(1, keep + 2)
                ]
                total = sum(f.stat().st_size for f in files if f.exists())
                if total <= cap:
                    break
                oldest = self._persist_path.with_suffix(f".jsonl.{n}")
                if oldest.exists():
                    oldest.unlink()
        except Exception as e:
            logger.warning(f"[Tracer] trace 轮转失败（不影响主流程）: {e}")

    def get_recent_traces(self, limit: int = 50) -> List[Dict[str, Any]]:
        """获取最近 N 条追踪记录（内存 + 文件，按 trace_id 去重，新→旧）。"""
        by_id: Dict[str, Dict[str, Any]] = {}
        # 文件（重启恢复）在前，内存覆盖同 id（同 id 以新为准）
        try:
            if self._persist_path.exists():
                for line in self._persist_path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except Exception:
                        continue
                    if isinstance(rec, dict) and rec.get("trace_id"):
                        by_id[str(rec["trace_id"])] = rec
        except Exception as _e:
            logger.debug("[tracer] 忽略异常: {}", _e)
        for t in self._traces:
            by_id[t.trace_id] = t.to_dict()
        ordered = sorted(by_id.values(), key=lambda r: float(r.get("timestamp", 0) or 0), reverse=True)
        return ordered[:limit]

    def get_recent_gates(self, limit: int = 50) -> List[Dict[str, Any]]:
        """获取最近 N 条闸机判定（新→旧），供 /api/agent/gates 调试端点"""
        return list(reversed(list(self._recent_gates)))[:limit]
