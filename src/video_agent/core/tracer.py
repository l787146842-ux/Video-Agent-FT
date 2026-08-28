"""
轻量 Agent 执行链路追踪器。

每轮 agent_loop step 记录：
    {trace_id, step, timing_ms, token_usage, actions_applied, finish_reason,
     actions: [{name, summary, elapsed_ms, ok}], reasoning}

actions/reasoning 供前端「过程时间线」折叠面板展示（不进 LLM 上下文），
随消息 trace 字段持久化，刷新页面后可重建。
通过 /api/agent/traces 端点暴露最近 50 条 trace（调试用）。
"""
import hashlib
import time
import uuid
from collections import deque
from contextvars import ContextVar
from dataclasses import dataclass, field
import json
from typing import Any, Deque, Dict, List, Optional

from loguru import logger

from src.video_agent.config import settings
from src.video_agent.utils.paths import DATA_DIR

# reasoning 文本持久化长度（仅展示用，防 trace 膨胀；保留尾部，头部省略）
_REASONING_HEAD_NOTE = "…（前文思考已截断）"
# 多模态非文本段归一后各段的连接符（整条消息再经 json 序列化，无歧义）
_FP_PART_SEP = "\u0001"


def fingerprint_messages(messages: List[Dict[str, Any]], prev: str = "") -> str:
    """P2-6 模型可见指纹链：对可见消息计算确定性指纹（sha256 前 16 hex）。

    链式：prev（上一条指纹）参与哈希，篡改任一环即后续全链对不上。
    规范化口径：每条消息无歧义序列化（json.dumps([role, content])，
    content 内任何字符均被转义），再以 "," 连接——content 内伪造分隔符
    无法构造跨消息碰撞；content 为多模态列表时文本段保留、
    非文本段归一为 [类型] 占位（审计口径 = 模型实际看到了什么）。
    """
    norm: List[str] = []
    for m in messages or []:
        role = str(m.get("role", "") if isinstance(m, dict) else "")
        content = m.get("content", "") if isinstance(m, dict) else ""
        if isinstance(content, list):
            parts: List[str] = []
            for p in content:
                if isinstance(p, dict):
                    ptype = str(p.get("type", "") or "")
                    parts.append(str(p.get("text", "") or "") if ptype == "text" else f"[{ptype}]")
                else:
                    parts.append(str(p))
            content = _FP_PART_SEP.join(parts)
        if not isinstance(content, str):
            content = str(content)
        norm.append(json.dumps([role, content], ensure_ascii=True))
    payload = f"{prev}|" + ",".join(norm)
    return hashlib.sha256(payload.encode("utf-8", errors="replace")).hexdigest()[:16]


@dataclass
class _TraceContextState:
    """单任务上下文的追踪态（ContextVar 持有，并行任务各持一份互不串线）。

    asyncio 任务创建时自动拷贝上下文，后台 worker 与新会话各写各的。
    """
    current: Optional["TraceRecord"] = None  # 本上下文当前 trace
    step_start: float = 0.0  # 当前 step 计时起点
    # 当前 step 期间收集的操作/闸机/仲裁/reasoning 明细（end_step 归档）
    pending_actions: List[Dict[str, Any]] = field(default_factory=list)
    pending_gates: List[Dict[str, Any]] = field(default_factory=list)
    pending_cards: List[Dict[str, Any]] = field(default_factory=list)
    pending_reasoning: List[str] = field(default_factory=list)
    # 执行器子步骤缓冲：先于父工具完成时暂存，随下一个 record_action 挂接
    pending_subs: List[Dict[str, Any]] = field(default_factory=list)
    # 轮前机械动作缓冲（先于 start_trace，start_trace 时收养进当轮时间线）
    pre_actions: List[Dict[str, Any]] = field(default_factory=list)
    # 上下文治理事件（降级事件化：truncate/degrade/compact/prune）——
    # 内存采集、end_trace 随 step 落盘；热路径零磁盘 IO。
    # pending 不在 start_step 重置（跨步累积，end_step 归档）；
    # pre_* 缓冲轮前事件（如 compaction 先于 start_trace），随 start_trace 收养
    pending_context_events: List[Dict[str, Any]] = field(default_factory=list)
    pre_context_events: List[Dict[str, Any]] = field(default_factory=list)
    # P2-6 可见指纹链：当前 step 已录指纹（end_step 归档）+ 链上一条指纹
    # （start_trace 新建态自然重置为 ""，链头无前驱）
    pending_prompt_fps: List[Dict[str, Any]] = field(default_factory=list)
    last_prompt_fp: str = ""


# 每任务上下文独立持有追踪态；未显式绑定时 _ctx() 惰性建档
_trace_ctx_var: ContextVar[Optional[_TraceContextState]] = ContextVar(
    "agent_trace_current", default=None,
)


@dataclass
class StepTrace:
    """单步追踪记录"""
    step: int = 0
    timing_ms: float = 0.0
    token_usage: int = 0
    # P2-1 KV-cache 遥测：本轮供应商前缀缓存命中 token（0 = 未命中/端点未返回）
    cached_tokens: int = 0
    actions_applied: int = 0
    finish_reason: str = ""
    # 本轮执行的操作明细（工具/ studio-actions），供前端时间线逐条展示
    actions: List[Dict[str, Any]] = field(default_factory=list)
    # 本轮闸机判定明细（rule_id/层/结果/是否被申诉放行），供审计与前端展示
    gates: List[Dict[str, Any]] = field(default_factory=list)
    # 本轮轮末卡片仲裁明细（候选策略/胜出者），供 /api/agent/traces 审计
    card_decisions: List[Dict[str, Any]] = field(default_factory=list)
    # 本轮上下文治理事件（truncate/degrade/compact/prune，无则不落盘省体积）
    context_events: List[Dict[str, Any]] = field(default_factory=list)
    # 本轮模型可见消息指纹链（P2-6，无则不落盘省体积）
    prompt_fingerprints: List[Dict[str, Any]] = field(default_factory=list)
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
    user_id: str = ""  # 多用户归属（基础，完整鉴权另行立项）
    llm_calls: int = 0  # 本 trace 含模型调用次数（成本看板口径用）
    # 失败现场摘要（仅失败轮非空）：异常上抛路径的 partial trace 归档，
    # 重试带上下文续跑（web/chat_retry_context）据此还原「在何处失败」
    error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        steps: List[Dict[str, Any]] = []
        for s in self.steps:
            sd = {
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
            # 无事件不写键：历史 trace 格式不变，单条体积不增
            if s.context_events:
                sd["context_events"] = s.context_events
            # 同口径：缓存命中为 0 不写键（历史格式不变，体积不增）
            if s.cached_tokens:
                sd["cached_tokens"] = s.cached_tokens
            # 同口径：无指纹不写键（历史格式不变）
            if s.prompt_fingerprints:
                sd["prompt_fingerprints"] = s.prompt_fingerprints
            steps.append(sd)
        d = {
            "trace_id": self.trace_id,
            "timestamp": self.timestamp,
            "total_ms": round(self.total_ms, 1),
            "total_actions": self.total_actions,
            "user_message_preview": self.user_message_preview,
            "user_id": self.user_id,
            "llm_calls": self.llm_calls,
            "steps": steps,
        }
        # 失败现场：无错误不写键（历史成功 trace 格式不变，体积不增）
        if self.error:
            d["error"] = self.error
        return d


class AgentTracer:
    """
    追踪器（单例）—— 内存保留最近 N 条 + JSONL 文件持久化。
    文件超限自动轮转（保留 trace_rotation_keep 份），重载按 trace_id 去重。

    并发隔离：「当前 trace」及各 step 缓冲随 contextvar 按上下文持有，
    后台任务转续与新会话并行时 span 归属各自正确（全局流：traces/gates/
    control_flow/fallback 仍实例共享，属进程级审计口径，与任务归属无关）。
    """

    _instance: Optional["AgentTracer"] = None
    MAX_TRACES = 50

    def __init__(self):
        self._traces: Deque[TraceRecord] = deque(maxlen=self.MAX_TRACES)
        # 全局闸机判定流（审计）：不依附单次 trace，供 /api/agent/gates 调试端点
        self._recent_gates: Deque[Dict[str, Any]] = deque(maxlen=100)
        # 控制流结构化事件流（分诊/阶段批/交接/回收）——控制流必须可观测
        self._control_flow: Deque[Dict[str, Any]] = deque(maxlen=200)
        # 模型降级事件计数（fallback 频率指标；record_fallback 写入）
        self._fallback_events: Deque[Dict[str, Any]] = deque(maxlen=200)
        # P2-6 断言审计：模型调用无在场 trace 的累计次数（理想恒 0）
        self._unlogged_llm_calls = 0
        self._persist_path = DATA_DIR / "agent_traces.jsonl"

    @staticmethod
    def _ctx() -> _TraceContextState:
        """取当前上下文的追踪态（无则惰性建档）。

        asyncio 每个 Task 创建时拷贝上下文：首次 set 只影响本任务副本，
        后台 worker 与前台会话天然各持一份 _TraceContextState，不串写。
        """
        state = _trace_ctx_var.get()
        if state is None:
            state = _TraceContextState()
            _trace_ctx_var.set(state)
        return state

    # 兼容入口（测试/旧调用直访实例属性）：代理到当前上下文态
    @property
    def _current(self) -> Optional[TraceRecord]:
        return self._ctx().current

    @property
    def _pending_actions(self) -> List[Dict[str, Any]]:
        return self._ctx().pending_actions

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
        """开始一次新追踪，返回 trace_id（绑定到调用方所在上下文）。

        每次新建追踪态并 set 进当前上下文：即使本上下文从创建方继承来
        共享状态对象（create_task 拷贝上下文），新 trace 也与原对象彻底
        切割，并行任务间零串写；同上下文轮前缓冲随新态收养不丢。
        """
        inherited = _trace_ctx_var.get()
        ctx = _TraceContextState()
        if inherited is not None and inherited.pre_actions:
            # 轮前机械动作收养（向导机械写文档等）：完成态/运行态同一条目
            ctx.pre_actions = list(inherited.pre_actions)
            inherited.pre_actions = []
        if inherited is not None and inherited.pre_context_events:
            # 轮前上下文事件收养（compaction 先于 start_trace 等）
            ctx.pre_context_events = list(inherited.pre_context_events)
            inherited.pre_context_events = []
        _trace_ctx_var.set(ctx)
        trace_id = uuid.uuid4().hex[:12]
        ctx.current = TraceRecord(
            trace_id=trace_id,
            timestamp=time.time(),
            user_message_preview=user_message[:80],
            user_id=user_id or "",
        )
        ctx.step_start = time.monotonic()
        # 当前 step 期间收集的操作明细与 reasoning（end_step 时归档）
        ctx.pending_actions = []
        if ctx.pre_actions:
            ctx.pending_actions.extend(ctx.pre_actions)
            ctx.pre_actions = []
        # 轮前上下文事件收养进本轮 pending（随首个 end_step 归档落盘）
        if ctx.pre_context_events:
            ctx.pending_context_events = list(ctx.pre_context_events)
            ctx.pre_context_events = []
        # 执行器子步骤缓冲：子步骤先于父工具完成时暂存，
        # 待父工具 record_action 时挂到父条目之后（持久化顺序 = live 顺序）
        return trace_id

    def start_step(self) -> None:
        """标记一步的开始（计时起点，按当前上下文取值）"""
        ctx = self._ctx()
        ctx.step_start = time.monotonic()
        ctx.pending_actions = []
        ctx.pending_gates = []
        ctx.pending_cards = []
        ctx.pending_reasoning = []
        ctx.pending_subs = []

    def record_action(
        self,
        name: str,
        summary: str = "",
        elapsed_ms: float = 0.0,
        ok: bool = True,
        stage: str = "",
        result_summary: str = "",
        planning: bool = False,
        args: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """记录当前 step 内的一个操作/工具调用（供前端时间线逐条展示）。

        stage：大阶段标签（后端权威下发，前端不再按工具名推断）。
        planning：规划级执行器标记（源自 skill_runtime/capability 注册表）。
        result_summary：工具执行结果一句话摘要（透明度兑现：持久化后
        刷新重建的时间线不再丢失结果细节；与 SSE tool_finished 同口径）。
        args：工具输入参数预览（必须已经 core/tool_args_preview 裁剪脱敏；
        与 result_summary 同口径落盘——刷新重建后详情卡展开区不丢输入细节）。
        返回条目 dict（调用方可事后补填 elapsed_ms，如规划条目先占位后计时）；
        同时把缓冲的执行器子步骤挂到本条目之后（顺序一致性）。
        """
        entry = {
            "name": name,
            "summary": summary,
            "elapsed_ms": round(elapsed_ms, 1),
            "ok": ok,
        }
        if stage:
            entry["stage"] = stage
        if result_summary:
            entry["result_summary"] = result_summary
        if planning:
            entry["planning"] = True
        if args:
            entry["args"] = args
        ctx = self._ctx()
        if ctx.current is None:
            return entry
        ctx.pending_actions.append(entry)
        if ctx.pending_subs:
            ctx.pending_actions.extend(ctx.pending_subs)
            ctx.pending_subs = []
        return entry

    def record_subaction(
        self,
        name: str,
        summary: str = "",
        elapsed_ms: float = 0.0,
        ok: bool = True,
    ) -> None:
        """执行器子步骤：缓冲到 pending_subs，随下一个父 record_action
        挂到父条目之后；step 结束仍无父条目时由 end_step 兜底落盘。"""
        ctx = self._ctx()
        if ctx.current is None:
            return
        ctx.pending_subs.append({
            "name": name,
            "summary": summary,
            "elapsed_ms": round(elapsed_ms, 1),
            "ok": ok,
        })

    def record_pre_turn(
        self, name: str, summary: str = "", elapsed_ms: float = 0.0, ok: bool = True,
    ) -> None:
        """轮前机械动作登记：缓冲待 start_trace 收养。

        开场编排（向导机械落盘等）先于 agent_loop.start_trace 发生，
        直记 record_action 会落进先前轮次残迹被清空——轮前缓冲根治。"""
        self._ctx().pre_actions.append({
            "name": name, "summary": summary,
            "elapsed_ms": round(elapsed_ms, 1), "ok": ok,
        })

    def record_reasoning(self, text: str) -> None:
        """追加当前 step 的 reasoning（深度思考）文本"""
        ctx = self._ctx()
        if ctx.current is None or not text:
            return
        ctx.pending_reasoning.append(text)

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
        scope: str = "",
    ) -> None:
        """记录一条闸机判定（审计）：归档到当前 step + 全局调试流"""
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
        if scope:
            entry["scope"] = scope
        self._recent_gates.append(entry)
        ctx = self._ctx()
        if ctx.current is not None:
            ctx.pending_gates.append(entry)

    def record_control_flow(self, event: str, detail: str = "", skill_name: str = "") -> None:
        """控制流结构化事件（分诊 triage / 阶段批 stage_batch /
        交接 handoff / 回收 reclaim / 发卡 card）——滚动保留，调用方同步打日志，
        控制流决策永不无据可查。"""
        self._control_flow.append({
            "ts": time.time(),
            "event": str(event or ""),
            "detail": str(detail or "")[:200],
            "skill_name": str(skill_name or ""),
        })

    def control_flow_events(self) -> List[Dict[str, Any]]:
        """控制流事件流（调试端点/审计用，新→旧）"""
        return list(reversed(self._control_flow))

    def record_card_decision(
        self,
        step: int,
        candidates: List[str],
        winner: str,
    ) -> None:
        """记录一次轮末卡片仲裁——
        全部命中候选策略 + 胜出者，随 step 归档，/api/agent/traces 可审计。"""
        ctx = self._ctx()
        if ctx.current is None:
            return
        ctx.pending_cards.append({
            "ts": time.time(),
            "step": step,
            "candidates": list(candidates or []),
            "winner": str(winner or ""),
        })

    def record_context_event(self, kind: str, detail: str = "") -> None:
        """记录一次上下文治理事件：
        kind ∈ truncate（轮组截断）/ degrade（system 降级保险丝）/
        compact（会话 compaction）/ prune（回喂剪枝）。

        只内存采集（当前 trace 在场入 pending，否则入轮前缓冲待
        start_trace 收养），随 end_trace 落盘——截断热路径零磁盘 IO。
        失败仅 log，绝不干扰主链路。"""
        try:
            if kind not in ("truncate", "degrade", "compact", "prune"):
                return
            entry = {
                "ts": time.time(),
                "kind": kind,
                "detail": str(detail or "")[:200],
            }
            ctx = self._ctx()
            if ctx.current is None:
                ctx.pre_context_events.append(entry)
            else:
                ctx.pending_context_events.append(entry)
        except Exception as e:
            logger.debug(f"[Tracer] context event 记录失败（忽略）: {e}")

    def record_fallback(self, provider: str, model: str) -> None:
        """记录一次模型降级切换（fallback 频率指标；内存滚动保留）。"""
        self._fallback_events.append({
            "ts": time.time(), "provider": provider, "model": model,
        })

    def record_llm_call(self) -> None:
        """当前 trace 模型调用 +1——成本看板平均耗时仅聚合含模型调用的轮。"""
        current = self._ctx().current
        if current is not None:
            current.llm_calls += 1

    def record_error(self, summary: str) -> None:
        """登记本轮失败现场摘要（异常上抛路径归档前调用）。

        无在场 trace（异常先于 start_trace）时静默跳过；
        失败仅 log，绝不干扰主链路。"""
        try:
            current = self._ctx().current
            if current is not None and summary:
                current.error = str(summary)[:500]
        except Exception as e:
            logger.debug(f"[Tracer] 失败现场登记失败（忽略）: {e}")

    def record_prompt_fingerprint(self, messages: List[Dict[str, Any]]) -> bool:
        """P2-6 可见指纹链：模型调用前对可见消息录指纹（链式入当前 step）。

        断言口径「凡入 llm_call 必入 trace」（Model-visible means logged）：
        无在场 trace 时告警 + 计数（不中断主链），返回 False；已入链返回 True。
        失败仅 log，绝不干扰主链路。
        """
        try:
            ctx = self._ctx()
            if ctx.current is None:
                self._unlogged_llm_calls += 1
                logger.warning(
                    "[Tracer] 模型调用无在场 trace，指纹未落盘"
                    "（违反「凡入 llm_call 必入 trace」，累计 %d 次）", self._unlogged_llm_calls)
                return False
            fp = fingerprint_messages(messages, prev=ctx.last_prompt_fp)
            ctx.pending_prompt_fps.append({
                "fp": fp,
                "prev": ctx.last_prompt_fp,
                "msgs": len(messages or []),
            })
            ctx.last_prompt_fp = fp
            return True
        except Exception as e:
            logger.debug(f"[Tracer] 指纹记录失败（忽略）: {e}")
            return False

    def metrics(self) -> Dict[str, Any]:
        """成本看板聚合（内存 + 文件 trace，按 trace_id 去重）。

        平均耗时仅聚合 llm_calls>0 的 trace（零模型调用的引导卡/直出卡
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
            # P2-6 断言审计：理想恒 0，非 0 即有模型调用未入 trace
            "unlogged_llm_calls": self._unlogged_llm_calls,
        }

    def end_step(
        self,
        step: int,
        actions_applied: int = 0,
        finish_reason: str = "",
        token_usage: int = 0,
        cached_tokens: int = 0,
    ) -> None:
        """记录一步的完成（cached_tokens：P2-1 KV-cache 命中遥测）"""
        ctx = self._ctx()
        if ctx.current is None:
            return
        timing_ms = (time.monotonic() - ctx.step_start) * 1000
        reasoning = "".join(ctx.pending_reasoning)
        # 保留尾部（最新思考最有回看价值），头部省略
        max_chars = int(getattr(settings, "trace_reasoning_max_chars", 0) or 2000)
        if len(reasoning) > max_chars:
            reasoning = _REASONING_HEAD_NOTE + reasoning[-max_chars:]
        # step 结束仍无父条目承接的子步骤兜底落盘（防丢）
        if ctx.pending_subs:
            ctx.pending_actions.extend(ctx.pending_subs)
            ctx.pending_subs = []
        ctx.current.steps.append(StepTrace(
            step=step,
            timing_ms=timing_ms,
            token_usage=token_usage,
            cached_tokens=cached_tokens,
            actions_applied=actions_applied,
            finish_reason=finish_reason,
            actions=list(ctx.pending_actions),
            gates=list(ctx.pending_gates),
            card_decisions=list(ctx.pending_cards),
            reasoning=reasoning,
            context_events=list(ctx.pending_context_events),
            prompt_fingerprints=list(ctx.pending_prompt_fps),
        ))
        ctx.pending_actions = []
        ctx.pending_gates = []
        ctx.pending_cards = []
        ctx.pending_reasoning = []
        ctx.pending_context_events = []
        ctx.pending_prompt_fps = []

    def finish_trace(self, total_actions: int = 0) -> Dict[str, Any]:
        """完成追踪并存入历史，返回本次 trace 的 dict（供 done payload 下发前端展示）"""
        ctx = self._ctx()
        if ctx.current is None:
            return {}
        ctx.current.total_ms = (time.monotonic() - ctx.step_start) * 1000
        # 使用第一步开始到最后的总时间
        if ctx.current.steps:
            ctx.current.total_ms = sum(s.timing_ms for s in ctx.current.steps)
        ctx.current.total_actions = total_actions
        record = ctx.current.to_dict()
        self._traces.append(ctx.current)
        ctx.current = None
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
        # 运行时残留策略：保留份数收紧为 2 份——
        # trace 仅供近期审计/重建，历史归档归文件备份，不留过多残留
        keep = int(getattr(settings, "trace_rotation_keep", 2))
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
            # 总容量上限——合计超 cap 时从编号最大（最旧）的 .N 丢弃
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
