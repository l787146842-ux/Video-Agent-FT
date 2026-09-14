"""FC 工具执行段。

三段结构：
- 闸机裁决 = core/fc_gates.py（闸机链组合；判定实现唯一归 guard_pipeline）
- 执行 = 本文件（tool_calls 执行循环 + 过程时间线事件 + trace 记账）
- 批末对账 = core/fc_reconcile.py（客观账本为主、措辞兜底）

执行分桶（五项修法批 3，按工具声明 deny-by-default）：连续 `parallel_safe`
声明的调用进有界并行池（池上限 PARALLEL_POOL_LIMIT，asyncio 并发），
其余调用独占串行（自成屏障）。结果与 SSE 事件按模型顺序提交；
问即停（workflow_pause 永远独占）、批首 checkpoint、幂等账本、取消路径
（已启动的跑完，未启动的随取消上抛终止）、独占失败回滚-中止纪律
全部保持既有语义；并行组员均为只读，组内失败不级联。

execute() 返回 FCExecuteResult（结构化命名元组）：调用方按字段名取用，
位置解包仍兼容（历史调用/测试不破坏），新增字段不再是隐性破坏。
闸机裁决实现体 = core/fc_gates.py（本文件只组装 GateContext 并调 run_gate_chain），
回喂家族实现体 = core/fc_feedback.py；两者均由消费方直连，本文件不再设 re-export 壳。
"""
import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, NamedTuple, Optional

from loguru import logger

from src.video_agent.core.chat_port import ChatResponse
from src.video_agent.utils.cancel_token import GenerationCancelled
from src.video_agent.core import fc_gates, fc_reconcile, prompt_gates
from src.video_agent.core import batch_checkpoint
from src.video_agent.core import ports
from src.video_agent.core import provider_injection
from src.video_agent.core import workflow_runtime
from src.video_agent.core import pause_composer
from src.video_agent.core import tool_args_preview
from src.video_agent.core.gates_cards import PAUSE_SLOT_ASSERTION_NOTE
from src.video_agent.core.idempotency_ledger import IdempotencyLedger
from src.video_agent.core.sse_events import (
    SSE_ACTIONS_APPLIED, SSE_DOC_WRITTEN, SSE_TOOL_FINISHED, SSE_TOOL_STARTED,
)
from src.video_agent.core.tracer import AgentTracer
from src.video_agent.core import event_cards
from src.video_agent.skill_runtime.progress import emit_event_card
from src.video_agent.skill_runtime.registry import stage_label_for_tool
from src.video_agent.state import storyboard_ops as ops
from src.video_agent.state.manager import StateManager
from src.video_agent.tools.base import ProviderInjectionContext, ToolResult

from src.video_agent.core.fc_feedback import (
    compose_failure_feedback,
    describe_fc_tool,
)
from src.video_agent.utils.json_rescue import rescue_tool_arguments

# 单步并行池上限（五项修法批 3）：整组连续 parallel_safe 调用按本上限切片
# 并发执行（对齐 dsh 有界并行池思路，上限保守取 4）
PARALLEL_POOL_LIMIT = 4


class FCExecuteResult(NamedTuple):
    """execute() 结构化返回（杜绝位置解包：字段名即契约）。

    warnings：本批闸机拦截/豁免的用户可见文案，由 planner 并入
    loop_result.warnings —— FC 轨与文本轨拦截可见性对齐（§2.0/§2.4）；
    pause_overflow：三通道分离 B，模型 pause message 超长的原文（进正文通道）；
    pause_id：问即停发行点签发的暂停卡标识（未发行暂停为空串，
    尾部新增字段，位置解包兼容契约不变；决策史见 git tag adr-archive-20260901）。
    """

    applied: int
    confirmation: str
    image_urls: List[str]
    chat_inserts: List[Dict[str, Any]]
    action_log: List[str]
    confirmation_options: List[Dict[str, Any]]
    tool_results: List[Dict[str, Any]]
    docs_written: List[str]
    warnings: List[str]
    pause_overflow: str
    pause_id: str


@dataclass
class _CallCtx:
    """单调用上下文：PRE 段产物 + 执行结果。串行桶与并行桶统一经
    _commit_call 提交（语义逐字段对齐原内联实现）。"""

    index: int
    name: str
    args: Any
    tool_event_id: str
    args_preview: Any
    start_summary: str
    tool_t0: float
    idem_key: str = ""
    gate_error: Optional[str] = None
    result: Any = None
    # 组内同幂等键重复（五项修法批 3）：并发片内各员 PRE 均查不到彼此账本，
    # 延后到提交期串行补跑（首现者已记账，命中缓存），保 T4 去重语义不变
    cache_wait: bool = False


@dataclass
class _BatchState:
    """execute() 批级可变状态（原循环局部变量的聚合载体）：
    串行桶与并行桶共用同一提交路径，批末对账从本状态取值。"""

    ctx: Any
    ledger: Any
    scope_auto_pause: bool
    batch_cp: Any
    batch_tools: Any
    paused_this_batch: bool = False
    applied: int = 0
    confirmation: str = ""
    confirmation_options: List[Dict[str, Any]] = field(default_factory=list)
    pause_overflow: str = ""
    pause_fallback_message: str = ""
    pause_break: bool = False

    batch_tool_names: set = field(default_factory=set)
    last_stage_label: str = ""
    structure_created: bool = False
    structure_kinds: set = field(default_factory=set)
    image_urls: List[str] = field(default_factory=list)
    chat_inserts: List[Dict[str, Any]] = field(default_factory=list)
    action_log: List[str] = field(default_factory=list)
    tool_results: List[Dict[str, Any]] = field(default_factory=list)
    doc_written: bool = False
    docs_written: List[str] = field(default_factory=list)
    # 五项修法批 3：当前提交是否属于并行桶成员（组内失败不级联，
    # 不触发独占路径的回滚-中止判定）
    parallel_member: bool = False


class FCToolRunner:
    """执行 Function Calling 返回的 tool_calls（planner 的 FC 执行臂）"""

    def __init__(self, tool_manager) -> None:
        self.tool_manager = tool_manager
        # 当前对话使用的聊天供应商/模型（与主模型一致，
        # 由 chat_service/planner 注入）
        self.chat_provider: str = ""
        self.chat_model: str = ""
        # 用户坚持作用域（False / True / "all"）：覆盖对应闸机
        self.gate_override: Any = False
        # 本批闸机警告（随 execute 返回/时间线可见）
        self.gate_warnings: List[str] = []
        # 本轮同工具失败计数（结构化回喂升级用）
        self._tool_fail_counts: Dict[str, int] = {}
        # 本轮花钱生成（costly）工具失败登记（Q22 裁决 2026-09-01：
        # 轮末机械附重试选项卡，不依赖模型自觉上报）；跨批累积，
        # planner 每轮 handle_message 起始清空
        self.costly_failures: List[str] = []
        # 前端当前选中的草稿（对齐文本轨 "current" 语义）；execute 时按请求注入
        self._selected_draft_id = ""
        self._selected_type = ""
        # 闸机校准：(kind+原因签名) 连续相同拦截计数，用于升级重写指引文案
        self._gate_repeat: Dict[str, int] = {}
        # 幂等键轮内账本（T4）：同键重复提交去重，生命周期随轮、不持久化
        self._idempotency = IdempotencyLedger()
        # 正宗子代理启动器（run_subagent 控制流伪工具的执行体）：由 planner 轮始
        # 注入捕获本轮 context 的回调（依赖注入，本文件绝不 import planner/agent_loop，
        # 不成环）；None = 未装配/子级内（防递归），命中即明确不可用。
        self.subagent_launcher = None

    # ---------- 闸机上下文组装（判定实现体 = core/fc_gates.py） ----------

    @staticmethod
    def _raw_state() -> Dict[str, Any]:
        try:
            return StateManager.get_instance().state_dict
        except Exception:
            return {}

    def _gate_ctx(self, injected_skill: str = "") -> fc_gates.GateContext:
        """组装闸机上下文（warnings/gate_repeat 绑定本实例对象，写入即时可见；
        record_gen_log 经 core 端口委托 web 层日志面板，保住 core→web 分层）。
        非 __init__ 构造的实例（测试夹具 object.__new__）缺失属性回落默认值。"""
        return fc_gates.GateContext(
            injected_skill=injected_skill,
            gate_override=self.gate_override,
            selected_draft_id=getattr(self, "_selected_draft_id", ""),
            selected_type=getattr(self, "_selected_type", ""),
            warnings=self.gate_warnings,
            gate_repeat=getattr(self, "_gate_repeat", {}),
            state=self._raw_state,
            tool_risk_of=self._tool_risk_of,
            record_gen_log=self._record_gate_gen_log,
        )

    @staticmethod
    def _record_gate_gen_log(prompt: str, hard: List[str]) -> None:
        """闸机拦截写入生成日志（顶栏日志面板可见，经 task_log 端口）；
        记录失败/端口未装配不影响主链路。"""
        try:
            ports.task_log_port().record_gate_gen_log(prompt, hard)
        except Exception:  # 记录失败不影响主链路
            pass

    # ---------- 执行段 ----------

    def _tool_risk_of(self, name: str) -> str:
        """读取工具声明的风险分级；未注册/未声明一律 high（deny-by-default，§2.7）。"""
        try:
            tool = self.tool_manager.get_tool(name)
        except Exception:
            tool = None
        risk = str(getattr(tool, "risk", "") or "").strip().lower()
        return risk if risk in ("low", "medium", "high") else "high"

    def _is_parallel_safe(self, name: str) -> bool:
        """读取工具 parallel_safe 声明（五项修法批 3，deny-by-default）：
        未注册/未声明/声明非 True 一律独占串行。"""
        try:
            tool = self.tool_manager.get_tool(name)
        except Exception:
            return False
        return getattr(tool, "parallel_safe", False) is True

    def _has_tool(self, name: str) -> bool:
        """runner 实际装配的工具管理器判存（v4-2 解析层未注册拒收用）：
        管理器未提供 get_tool 成员查询（如最小执行桩）= 无法应答，
        返回 True 交闸机兜底（fail-closed 不前移）；get_tool 对缺失
        抛错 = 确定性不存在，返回 False 供解析层拒收。"""
        getter = getattr(self.tool_manager, "get_tool", None)
        if not callable(getter):
            return True
        try:
            getter(name)
            return True
        except Exception:
            return False

    async def _dispatch_tool(self, name: str, args: Dict[str, Any]) -> ToolResult:
        """闸机放行后的单调用派发（并行桶内亦经本路径）：
        含 read_skill 在内全部常规分发真执行（任务#12：短路已废）。

        run_subagent 属控制流伪工具（同 workflow_pause 在派发/提交段被 core 拦截）：
        经 planner 注入的 `subagent_launcher` 在隔离上下文跑完子循环、只回摘要，
        不走 `invoke_tool`（模型经 FC 发起、走同一闸机链，非机械执行器）。"""
        if name == "run_subagent":
            launcher = getattr(self, "subagent_launcher", None)
            if launcher is None:
                return ToolResult(
                    success=False,
                    error="子代理当前不可用（未装配或已达深度上限）。",
                    error_code="validation",
                )
            summary = await launcher(
                str((args or {}).get("task") or ""))
            text = str(summary or "").strip() or "（子代理未产出摘要）"
            # `detail` 是工具结果回喂给模型的既有专用通道（fc_feedback）：
            # 子代理的全部产出就是这段摘要，不带 detail 则父只看到
            # 「执行成功」一句话，委派信息全丢（委派本身失去意义）。
            return ToolResult(success=True, data={
                "summary": text, "result": text, "detail": text})
        return await self.tool_manager.invoke_tool(name, args)

    def _record_presented(self, name: str, args: Dict[str, Any]) -> None:
        """FC 轨记录本轮写入过提示词的草稿：patch_draft 带非空 prompt 成功时，
        解析实际 draft_id 记入 interaction.drafts_presented（用户回应时晋升已确认）"""
        if name != "storyboard_patch_draft":
            return
        patch = args.get("patch") if isinstance(args.get("patch"), dict) else {}
        if not str(patch.get("prompt") or "").strip():
            return
        try:
            found = ops.find_draft(
                self._raw_state(), str(args.get("draft_id") or ""),
                str(args.get("draft_type") or ""),
                selected_draft_id=self._selected_draft_id,
                selected_type=self._selected_type,
            )
            if not found:
                return
            _, draft = found
            draft_id = draft.get("id") or ""
            if not draft_id:
                return
            svc = StateManager.get_instance()
            workflow_runtime.reduce_drafts_presented(svc, draft_id=draft_id, flush=True)
        except Exception as e:  # 记录失败不影响主链路
            logger.debug(f"[FlowGate] drafts_presented 记录失败: {e}")

    def reset_turn_tracking(self) -> None:
        """轮始重置跨批跟踪（三通道分离 C）：阶段边界判定只认本轮执行。

        runner 为 Planner 级长存实例，不重置则上轮 script_analyze 等
        工具名泄漏到本轮边界判定，造成阶段中暂停误挂继续选项。
        """
        self._turn_tool_names = set()
        self._turn_stage_label = ""
        self._idempotency.reset()  # T4：幂等键账本随轮生命周期，轮始清空

    async def _prepare_call(
        self, call: Any, index: int, *, ctx: fc_gates.GateContext,
        image_provider: str, image_aspect_ratio: str,
        paused_this_batch: bool, on_event=None,
        group_keys: Optional[set] = None,
    ) -> _CallCtx:
        """PRE 段（原循环体内派发前的逐调用准备，语义逐行保持）：
        args 解析 → 引用解析 → started 事件 → 计时 → provider 注入 →
        幂等查账 → 结构纯净闸 → 闸机链。group_keys 非 None 时（并行桶片）
        另做组内同幂等键重复标记（cache_wait）。"""
        func = call.get("function", {}) if isinstance(call, dict) else {}
        name = func.get("name", "")
        args_raw = func.get("arguments", "{}")
        # 8888 事故批（对齐 dsh「数据不丢、错误可见」）：参数解析失败不再
        # 静默伪造 {} 继续调用——先本地抢救（控制字符转义），仍失败则结构化
        # 拒收并把真实拒因（出错位置+原文片段）回喂模型。原实现伪造 {} 后
        # 工具按「未携带非空 title」拒收，模型收到假拒因原样重发 15 轮。
        if isinstance(args_raw, str):
            args, _parse_err = rescue_tool_arguments(args_raw)
            if args is None:
                _tool_event_id = str(call.get("id") or f"fc-{index}") if isinstance(call, dict) else f"fc-{index}"
                _c = _CallCtx(
                    index=index, name=name, args={},
                    tool_event_id=_tool_event_id,
                    args_preview={}, start_summary=f"{name}（参数 JSON 解析失败）",
                    tool_t0=time.monotonic(),
                )
                if on_event is not None:
                    await on_event({
                        "type": SSE_TOOL_STARTED,
                        "id": _tool_event_id,
                        "name": name,
                        "summary": _c.start_summary,
                        "args": {},
                    })
                logger.warning(
                    f"[ToolRunner] 工具参数 JSON 解析失败（拒收）: {name}: {_parse_err[:200]}")
                _c.gate_error = _parse_err
                _c.result = ToolResult(success=False, error=_parse_err)
                return _c
        else:
            args = args_raw
        # current/空引用 → 真实 id（闸机与工具调用前，防命中错误卡片/绕过闸机）
        fc_gates.resolve_current_refs(ctx, name, args)

        # 过程时间线：工具开始（前端渲染运行态条目）
        tool_event_id = str(call.get("id") or f"fc-{index}") if isinstance(call, dict) else f"fc-{index}"
        start_summary = describe_fc_tool(name, args)
        # 输入参数预览（裁剪脱敏）：随 started 事件下发并同步
        # 落盘 trace（刷新重建后详情卡展开区不丢）
        args_preview = tool_args_preview.redact_tool_args(name, args)
        c = _CallCtx(
            index=index, name=name, args=args, tool_event_id=tool_event_id,
            args_preview=args_preview, start_summary=start_summary,
            tool_t0=time.monotonic(),
        )
        if on_event is not None:
            await on_event({
                "type": SSE_TOOL_STARTED,
                "id": tool_event_id,
                "name": name,
                "summary": start_summary,
                "args": args_preview,
            })

        # 未注册名解析层归位（v4-2）：闸机链之前直接结构化拒收，
        # 不经风险闸/注入/幂等；话术唯一源 = fc_gates.unknown_tool_error
        # （按 runner 实际装配的管理器判存，测试桩同形）。
        # 闸机层未注册兜底保留为最后防线（fail-closed 不变）。
        _unknown = fc_gates.unknown_tool_error(name, has_tool=self._has_tool)
        if _unknown is not None:
            logger.info(f"[ToolRunner] 未注册工具拒收（解析层）: {name}")
            c.gate_error = _unknown
            c.result = ToolResult(success=False, error=_unknown)
            return c

        # Provider 注入（I-3 声明驱动）：查工具 provider_kind 声明 → 走统一注入器
        # （core/provider_injection）；single/batch 等工具内部形态由工具自身消化，
        # 调度器不认具体工具名（消除 image_generate/generate_video 的 if/elif 特例）。
        provider_injection.inject(name, args, ProviderInjectionContext(
            state=self._raw_state(),
            image_provider=image_provider,
            image_aspect_ratio=image_aspect_ratio,
            selected_draft_id=self._selected_draft_id,
            selected_type=self._selected_type,
        ))

        # 幂等键轮内去重（T4）：同键命中直接用首次结果，跳过闸机链与实际执行；
        # 空键直通过不去重，判定语义唯一归 core/idempotency_ledger.py
        _idem_key = str(args.get("idempotency_key") or "").strip()
        c.idem_key = _idem_key
        _idem_cached = self._idempotency.check(_idem_key)
        if _idem_cached is not None:
            c.result, c.gate_error = _idem_cached, None
            return c
        # 闸机链（fc_gates.run_gate_chain）：轮内暂停纪律 → 工具风险 →
        # 生成确认 → 建组结构完整性 → 提示词结构 → 生图配额
        # （C1b 裁决 2026-08-31：阶段前置闸退役；结构纯净闸退役 2026-09-12——
        #  无阶段感知静默剥离 add_draft 内联 prompt 造成假成功空提示词卡，
        #  用户裁决删除：3333 项目实证）
        chain = fc_gates.run_gate_chain(
            ctx, name, args, paused_this_batch=paused_this_batch)
        c.gate_error = chain.error
        if c.gate_error is not None:
            c.result = ToolResult(success=False, error=c.gate_error)
        elif group_keys is not None:
            if _idem_key and _idem_key in group_keys:
                c.cache_wait = True
            if _idem_key:
                group_keys.add(_idem_key)
        return c

    async def _record_cancelled_call(self, c: _CallCtx, *, on_event=None,
                                     tracer=None) -> None:
        """取消留痕（原循环内 GenerationCancelled 处理的记账段）：
        本工具 SSE/trace 以取消态记录，不静默吞、不吞为失败结果；
        生成族账本登记由 _record_cancel_ledger 保持原记账顺序。"""
        _cancel_desc = describe_fc_tool(c.name, c.args)
        if on_event is not None:
            await on_event({
                "type": SSE_TOOL_FINISHED,
                "id": c.tool_event_id,
                "ok": False,
                "elapsed_ms": round((time.monotonic() - c.tool_t0) * 1000, 1),
                "result_summary": "已被用户取消",
            })
        tracer.record_action(
            name=c.name, summary=_cancel_desc,
            elapsed_ms=(time.monotonic() - c.tool_t0) * 1000, ok=False,
            stage=stage_label_for_tool(c.name),
            result_summary="已被用户取消", args=c.args_preview,
        )

    def _record_cancel_ledger(self, c: _CallCtx, st: _BatchState) -> None:
        """取消穿透前的生成族账本登记（保持原记账顺序：先账本后留痕）。"""
        if provider_injection.is_provider_tool(c.name):
            st.ledger.gen_failed_err = "生成任务已被取消"

    async def _commit_call(self, c: _CallCtx, st: _BatchState, *,
                           on_event=None, on_status=None, tracer=None) -> str:
        """单调用提交段（原 execute 循环内派发后的逐调用后处理，语义逐行保持）：
        幂等记账 → 暂停槽断言 → 生成族记账 → 成败分支（账本/事件/trace/回喂）。
        返回 "break"（问即停 / 回滚-中止）或 "continue"。"""
        name = c.name
        args = c.args
        result = c.result
        gate_error = c.gate_error
        _tool_ms = (time.monotonic() - c.tool_t0) * 1000
        # 幂等键记账（T4）：非空键的执行结果（含失败）入轮内账本；
        # 空键与闸机拒收不记账（拒收无副作用，待模型改参/用户确认后重新裁决）
        if gate_error is None:
            self._idempotency.record(c.idem_key, result)
        # 单一活跃暂停槽位：降级为防御性断言——已有未消费
        # 暂停时重复 workflow_pause 只告警 + trace 留痕（pause_slot_collision），
        # 旧卡作废 + 发行新卡 + 继续等待人工确认，不拒收（旧「执行后拒收」形态退役）
        if name == "workflow_pause" and result.success:
            try:
                _svc_pause = StateManager.get_instance()
                _active = ((_svc_pause.state_dict.get("interaction") or {})
                           .get("active_pause") or {})
                if _active.get("pause_id"):
                    logger.warning(
                        "[PauseSlot] 防御断言命中（旧 pause_id={}）：{}",
                        _active.get("pause_id"), PAUSE_SLOT_ASSERTION_NOTE,
                    )
                    tracer.record_control_flow(
                        "pause_slot_collision",
                        f"{PAUSE_SLOT_ASSERTION_NOTE}（旧 pause_id={_active.get('pause_id')}）")
            except Exception as _e:
                logger.debug("[fc_tool_runner] 忽略异常: {}", _e)
        # 生成类工具成败记录（批末对账用客观账本）
        if provider_injection.is_provider_tool(name):
            if result.success:
                st.ledger.gen_succeeded = True
            elif not st.ledger.gen_failed_err:
                st.ledger.gen_failed_err = str(result.error or "执行失败")
        if result.success:
            st.applied += 1
            self._record_presented(name, args)
            if name in ("storyboard_create_group", "storyboard_add_draft"):
                st.structure_created = True
                kind = prompt_gates.normalize_structure_kind(args.get("group_type") or "")
                if kind:
                    st.structure_kinds.add(kind)
                # 待确认标记即时置位（不等批结束）：同批后续的提示词写入
                # 会被提示词闸的 storyboard_pending 检查拦住（防 3+4 合并）
                if st.ledger.skill_strict:
                    try:
                        svc_now = StateManager.get_instance()
                        if not (svc_now.state_dict.get("interaction") or {}).get("storyboard_pending"):
                            workflow_runtime.reduce_interaction(
                                svc_now, set_flags={"storyboard_pending": True}, flush=True)
                    except Exception as _e:
                        logger.debug("[fc_tool_runner] 忽略异常: {}", _e)
            if name == "workflow_pause" and st.scope_auto_pause:
                # 子对话不发确认卡（用户裁决，二期子对话批 3）：scope 任务命中
                # workflow_pause 直接放行——不登记暂停三态、不组卡、不置问即停；
                # 回喂改写为「已自动确认」（见 tool_results 追加处），模型继续执行。
                # 主对话问即停语义不变（旗标缺省关）。
                tracer.record_control_flow(
                    "pause_auto_passed",
                    "scope 子对话内 workflow_pause 自动放行（不发起确认，直接执行）")
            elif name == "workflow_pause":
                st.paused_this_batch = True
                # workflow_pause 只提交审批事实——卡问句系统
                # 组装，模型原文一律进正文通道（无阈值补丁）
                st.confirmation, st.pause_overflow = pause_composer.split_pause_channels(
                    args.get("message", ""), st.last_stage_label)
                if st.pause_overflow:
                    logger.info(
                        "[FlowGate] pause 卡问句=系统模板，模型原文（{}字）进正文通道",
                        len(st.pause_overflow),
                    )
                # 候选选项（前端渲染为单选卡片，点击即发送选择；带 group 时分页向导）
                opts = args.get("options")
                if isinstance(opts, list):
                    for o in opts:
                        if isinstance(o, dict) and str(o.get("label") or "").strip():
                            item = {
                                "label": str(o.get("label")).strip(),
                                "description": str(o.get("description") or "").strip(),
                            }
                            if str(o.get("group") or "").strip():
                                item["group"] = str(o.get("group")).strip()
                            # 选项 value 机械消费
                            if str(o.get("value") or "").strip():
                                item["value"] = str(o.get("value")).strip()
                            st.confirmation_options.append(item)
                        elif isinstance(o, str) and o.strip():
                            st.confirmation_options.append({"label": o.strip(), "description": ""})
                # 验收缺失清单在场 → 暂停卡附「补拆/维持」结构化选项
                # （落实 Skill「先与用户确认是否修改」；附后清除登记）
                try:
                    _svc_m = StateManager.get_instance()
                    _inter_m = _svc_m.state_dict.get("interaction") or {}
                    _missing = _inter_m.get("pending_missing") or []
                    if _missing:
                        _n = len(_missing)
                        st.confirmation_options.append({
                            "label": f"补拆 {_n} 项缺失元素", "value": "补拆",
                            "description": "、".join(_missing[:6]) + ("等" if _n > 6 else "")})
                        st.confirmation_options.append({
                            "label": "维持现状继续", "value": "继续",
                            "description": "接受缺失，按流程推进下一阶段"})
                        _inter_m.pop("pending_missing", None)
                        _svc_m.save_debounced()
                except Exception as _e:
                    logger.debug("[fc_tool_runner] 忽略异常: {}", _e)
                # 选项面归一（Rule2 v6，pause_composer 唯一实现）：
                # 模型选项原样保留（阶段边界系统派生「继续」项已随阶段规则
                # 去代码化批退役——平台不再判阶段完成，无边界可派生）。
                st.confirmation, st.confirmation_options = pause_composer.normalize_option_surface(
                    self._raw_state(), st.ctx.injected_skill, st.confirmation,
                    st.confirmation_options)
                # 问即停：记下事务写入兜底文案（模型原文），
                # 置批末终止标记——本批后续调用不执行也不回喂拒因，
                # 悬挂调用留在 history 末尾，待暂停三态回应后统一消费
                st.pause_fallback_message = (
                    str(args.get("message") or "").strip()
                    or "请确认以上内容，确认后我将继续。")
                st.pause_break = True
            if name in ("document_write", "write_document"):
                st.doc_written = True
                # 即时同步进账本（与生成族记账同节拍）：循环中段的回滚判定读得到文档写标志，不留时序缺口；批末重复赋值同值无害
                st.ledger.doc_written = True
                doc_name = str(args.get("name") or args.get("key") or "").strip()
                if doc_name:
                    st.docs_written.append(doc_name)
                    st.ledger.docs_written = list(st.docs_written)
                    # 文档卡片即写即显，不等整轮 done。
                    # 前端按名称去重，done payload 的 documents_written 仍携带全量
                    # 供服务端持久化与刷新重建。
                    if on_event is not None:
                        await on_event({"type": SSE_DOC_WRITTEN, "name": doc_name})
            desc = describe_fc_tool(name, args)
            st.action_log.append(desc)
            # 推理过程可视化：每完成一个工具就推一条状态
            if on_status is not None:
                await on_status(f"已完成：{desc}", key="agent.opsDone", params={"ops": desc})
            # 边写边填（FC 轨）：每完成一个变动类工具就下发状态快照，
            # 草稿卡片逐张刷新，不等整批完成才一次性弹出
            if on_event is not None and name not in (
                "read_skill", "read_draft", "read_uploaded_doc", "read_project_doc",
                "read_state_group", "view_storyboard_media",
            ):
                await on_event({"type": SSE_ACTIONS_APPLIED, "count": 1})
            # 过程时间线：工具完成 + trace 记录
            if on_event is not None:
                _finished_ev = {
                    "type": SSE_TOOL_FINISHED,
                    "id": c.tool_event_id,
                    "ok": True,
                    "elapsed_ms": round(_tool_ms, 1),
                    "result_summary": desc,
                }
                await on_event(_finished_ev)
            tracer.record_action(name=name, summary=desc, elapsed_ms=_tool_ms, ok=True,
                                 stage=stage_label_for_tool(name),
                                 result_summary=desc,
                                 args=c.args_preview)
            st.batch_tool_names.add(name)
            _stage_lbl = stage_label_for_tool(name)
            if _stage_lbl:
                st.last_stage_label = _stage_lbl
                self._turn_stage_label = _stage_lbl
            st.tool_results.append({"name": name, "ok": True, "data": result.data,
                             "call_id": c.tool_event_id})
            # 子对话暂停放行（批 3）：回喂替换「已暂停」为「已自动确认」，
            # 防模型停在等待用户回应的语义上（子对话不发起确认）
            if name == "workflow_pause" and st.scope_auto_pause:
                st.tool_results[-1]["data"] = {
                    "auto_passed": True,
                    "note": "当前在微调子对话内：系统已自动确认并放行你的暂停请求"
                    "（子对话内不发起用户确认），请直接继续执行完成本次调整。",
                }
            # --- 收集生图工具产出的图片 URL ---
            data = result.data
            if data and "image_urls" in data:
                urls = data["image_urls"]
                if isinstance(urls, list):
                    st.image_urls.extend(urls)
            # --- 收集 storyboard_media_to_chat 产出的对话输入框插入项 ---
            if data and "chat_inserts" in data:
                inserts = data["chat_inserts"]
                if isinstance(inserts, list):
                    st.chat_inserts.extend(inserts)
            # --- 工具成功结果携带的警告（如建组闸机回喂清单）
            # 升级为轮末用户可见警告，不得只留在 trace（静默丢失禁令） ---
            if data and isinstance(data.get("warnings"), list):
                for _tw in data["warnings"]:
                    _tws = str(_tw or "").strip()
                    if _tws and _tws not in self.gate_warnings:
                        self.gate_warnings.append(_tws)
            # --- 批 2 · 插播报：产物落账即广播具名事件卡（触发时刻写死，
            # 逐卡唯一落点 = event_cards 映射表；读类卡只进时间线不进模型
            # 上下文防逐轮膨胀）
            _cards = event_cards.product_event_card(name, args, len(st.image_urls))
            for _card_name, _card_detail, _card_to_ctx, _card_md in _cards:
                await emit_event_card(
                    _card_name, _card_detail, detail_md=_card_md, emitter=on_event)
                if _card_to_ctx:
                    StateManager.get_instance().record_flow_event(
                        "event_card",
                        f"{_card_name}：{_card_detail}" if _card_detail else _card_name,
                    )
            # 问即停：暂停发行成功 = 立即结束本批（同批后续
            # tool_calls 不执行、不产生拒因回喂；发卡点正常收尾）
            if st.pause_break:
                return "break"
        else:
            logger.warning(f"[Planner] Tool '{name}' failed: {result.error}")
            # （规格静默拒收/接管已随用户裁决 2026-08-31 退役，D-08 清偿：
            # 规格写入不再被向导拒收，失败即普通失败（红×））
            # 止损计数可观测（Q22）：同工具累计失败次数随时间线条目可见，
            # 亦随结构化回喂供模型止损决策（二次升级见 compose_failure_feedback）
            self._tool_fail_counts[name] = self._tool_fail_counts.get(name, 0) + 1
            _fail_n = self._tool_fail_counts[name]
            if on_event is not None:
                _finished_ev = {
                    "type": SSE_TOOL_FINISHED,
                    "id": c.tool_event_id,
                    "ok": False,
                    "elapsed_ms": round(_tool_ms, 1),
                    "result_summary": str(result.error or "执行失败")[:120],
                }
                await on_event(_finished_ev)
            tracer.record_action(
                name=name, summary=f"{c.start_summary}（累计失败 {_fail_n} 次）",
                elapsed_ms=_tool_ms, ok=False,
                stage=stage_label_for_tool(name),
                result_summary=str(result.error or "执行失败")[:120],
                args=c.args_preview,
            )
            # 花钱生成失败不静默（Q22）：用户可见警告（随 gate_warnings
            # 并入轮末 warnings）+ 轮级登记（planner 轮末机械附重试选项卡）
            _is_costly = getattr(self.tool_manager, "is_costly_tool", None)
            if callable(_is_costly) and _is_costly(name):
                _cf_msg = (
                    f"花钱生成失败：{c.start_summary} —— "
                    f"{str(result.error or '执行失败')[:120]}。"
                    "可点「重试」重新执行，或调整提示词/模型后再试"
                )
                if _cf_msg not in self.gate_warnings:
                    self.gate_warnings.append(_cf_msg)
                self.costly_failures.append(name)
            # 结构化失败回喂（客观报告+单句建议，二次升级）
            st.tool_results.append({
                "name": name, "ok": False,
                "call_id": c.tool_event_id,
                "error": compose_failure_feedback(
                    name, result.error, _fail_n,
                    # T5 结构化错误轴：生产端已标注则透传分类码/可重试标志，
                    # 未标注回落文本分类（getattr 兼容测试 stub 返回非 ToolResult）
                    error_code=str(getattr(result, "error_code", "") or ""),
                    retryable=bool(getattr(result, "retryable", False)),
                ),
            })
            # 批级检查点（批 6）：回滚触发边界排除未执行型拒收（闸机拒收/入参校验拒收零副作用，判定在 core/batch_checkpoint.py）；
            # 仅确实执行过且失败的调用才过保守条件判定。回滚实际发生：失效轮内幂等账本（防同键命中陈旧成功缓存）
            # 并中止本批后续调用（仿问即停：不得在已恢复状态上继续执行产生矛盾回喂）；
            # 取消分支同理在穿透上抛前判定（见 _record_cancelled_call 接线点）。
            # 并行桶成员不进本回滚-中止判定（五项修法批 3：组员均为只读，组内失败不级联）
            if not st.parallel_member:
                if not batch_checkpoint.is_unexecuted_rejection(gate_error, result):
                    if batch_checkpoint.maybe_rollback_on_failure(
                            StateManager.get_instance(), st.batch_cp, failed_tool=name,
                            ledger=st.ledger, tool_names=st.batch_tools,
                            tool_manager=self.tool_manager):
                        self._idempotency.reset()
                        return "break"
        return "continue"

    async def _run_group_chunk(self, members: List[_CallCtx], st: _BatchState, *,
                               on_event=None, on_status=None, tracer=None) -> None:
        """并发执行一个并行桶片（≤PARALLEL_POOL_LIMIT 个 parallel_safe 调用），
        结果与 SSE 事件按模型顺序提交（逐成员走同一 _commit_call）。

        取消语义（对齐 dsh：已启动的跑完）：gather 等齐整片——已启动成员
        跑完者按真实结果提交，命中取消者记取消留痕，随后过保守回滚判定
        并穿透上抛（片外未启动调用随上抛终止，外层 while 不再续跑）。
        组内失败不级联（五项修法批 3：组员均为只读，失败只记失败回喂，
        不触发回滚-中止）。"""
        to_run = [m for m in members if m.result is None and m.gate_error is None
                  and not m.cache_wait]
        outcomes: Dict[int, Any] = {}
        if to_run:
            _outs = await asyncio.gather(
                *(self._dispatch_tool(m.name, m.args) for m in to_run),
                return_exceptions=True)
            outcomes = {id(m): o for m, o in zip(to_run, _outs)}
        _first_cancel_exc: Optional[GenerationCancelled] = None
        _first_cancel_member: Optional[_CallCtx] = None
        _first_exc: Optional[BaseException] = None
        st.parallel_member = True
        try:
            for m in members:
                if m.result is None and m.gate_error is None:
                    if m.cache_wait:
                        # 组内同键重复：此刻首现者已入账本，串行补跑命中缓存
                        _cached = self._idempotency.check(m.idem_key)
                        m.result = _cached if _cached is not None else (
                            await self._dispatch_tool(m.name, m.args))
                    else:
                        _out = outcomes.get(id(m))
                        if isinstance(_out, GenerationCancelled):
                            self._record_cancel_ledger(m, st)
                            await self._record_cancelled_call(
                                m, on_event=on_event, tracer=tracer)
                            if _first_cancel_exc is None:
                                _first_cancel_exc = _out
                                _first_cancel_member = m
                            continue
                        if isinstance(_out, BaseException):
                            # invoke_tool 兜底之外的非取消异常：记首例，提交完其余成员后上抛
                            if _first_exc is None:
                                _first_exc = _out
                            continue
                        m.result = _out
                _signal = await self._commit_call(
                    m, st, on_event=on_event, on_status=on_status, tracer=tracer)
                if _signal != "continue":
                    break
        finally:
            st.parallel_member = False
        if _first_cancel_exc is not None:
            # 取消穿透：过保守条件判定（同独占路径），已跑完成员的真实结果已提交
            if batch_checkpoint.maybe_rollback_on_cancel(
                    StateManager.get_instance(), st.batch_cp,
                    cancelled_tool=_first_cancel_member.name if _first_cancel_member else "",
                    ledger=st.ledger, tool_names=st.batch_tools,
                    tool_manager=self.tool_manager):
                self._idempotency.reset()
            raise _first_cancel_exc
        if _first_exc is not None:
            raise _first_exc

    async def execute(
        self, response: ChatResponse, image_provider: str = "", image_aspect_ratio: str = "",
        on_status=None, on_event=None, injected_skill: str = "",
        selected_draft_id: str = "", selected_type: str = "",
        gate_override: Any = False,
        scope_auto_pause: bool = False,
    ) -> FCExecuteResult:
        """执行 Function Calling 返回的 tool_calls。

        返回 FCExecuteResult（applied, confirmation, image_urls, chat_inserts,
        action_log, confirmation_options, tool_results, docs_written, warnings,
        pause_overflow, pause_id）——位置解包仍兼容，新调用方请按字段名取用。

        执行分桶（五项修法批 3）：连续 parallel_safe 声明的调用进有界并行池
        （池上限 PARALLEL_POOL_LIMIT），其余调用独占串行（自成屏障）。
        问即停（workflow_pause 永远独占）、批首 checkpoint、幂等账本、
        取消路径、独占失败回滚-中止纪律全部保持既有语义。
        """
        self._selected_draft_id = selected_draft_id or ""
        self._selected_type = selected_type or ""
        self.gate_override = gate_override
        self.gate_warnings = []
        # 闸机上下文（批级）：生图配额计数随 ctx 跨工具累计
        ctx = self._gate_ctx(injected_skill)
        # 批末对账账本（客观事实逐项记账，对账归 fc_reconcile）
        ledger = fc_reconcile.BatchLedger(
            injected_skill=injected_skill,
            # 暂停点归位 Skill 阶段边界——只快照批前是否为空，
            # 批末「故事板阶段完成且模型未暂停」才注入审阅卡（平台不再自加关键元素后暂停）
            skill_strict=bool(injected_skill) and prompt_gates.gate_mode() == "strict",
            storyboard_empty_before=prompt_gates.storyboard_is_empty(self._raw_state()),
        )
        # 三通道分离 C：批内成功执行的工具名/阶段标签（阶段边界判定用）；
        # 阶段标签跨批保留（实例属性）——分析工具与
        # workflow_pause 分属两个批，短问句仍需带上真实阶段名
        batch_tool_names: set = set(getattr(self, "_turn_tool_names", ()))
        last_stage_label = str(getattr(self, "_turn_stage_label", "") or "")
        # 批级检查点（批 6）：本批含写类/中高危工具时批首打快照，失败/取消回滚判定全在 core/batch_checkpoint.py
        _batch_cp = batch_checkpoint.take_checkpoint() if batch_checkpoint.batch_has_risky_tool(
            response, self.tool_manager) else None
        _batch_tools = batch_checkpoint.batch_tool_names(response)
        st = _BatchState(
            ctx=ctx, ledger=ledger, scope_auto_pause=scope_auto_pause,
            batch_cp=_batch_cp, batch_tools=_batch_tools,
            batch_tool_names=batch_tool_names, last_stage_label=last_stage_label,
        )
        self._turn_tool_names = st.batch_tool_names
        tracer = AgentTracer.get_instance()
        calls = list(response.tool_calls)
        ci = 0
        while ci < len(calls):
            call = calls[ci]
            func = call.get("function", {}) if isinstance(call, dict) else {}
            head_name = str(func.get("name") or "")
            if self._is_parallel_safe(head_name):
                # 分桶（五项修法批 3）：连续 parallel_safe 调用整组进有界并行池，
                # 超池上限按 PARALLEL_POOL_LIMIT 切片顺序并发
                _gs = ci
                j = ci
                while j < len(calls):
                    _f2 = calls[j].get("function", {}) if isinstance(calls[j], dict) else {}
                    if not self._is_parallel_safe(str(_f2.get("name") or "")):
                        break
                    j += 1
                _group = calls[_gs:j]
                ci = j
                for _cs in range(0, len(_group), PARALLEL_POOL_LIMIT):
                    _chunk = _group[_cs:_cs + PARALLEL_POOL_LIMIT]
                    _seen_keys: set = set()
                    members: List[_CallCtx] = []
                    for _k, _c in enumerate(_chunk):
                        members.append(await self._prepare_call(
                            _c, _gs + _cs + _k, ctx=ctx,
                            image_provider=image_provider,
                            image_aspect_ratio=image_aspect_ratio,
                            paused_this_batch=st.paused_this_batch,
                            on_event=on_event, group_keys=_seen_keys))
                    await self._run_group_chunk(
                        members, st, on_event=on_event, on_status=on_status,
                        tracer=tracer)
                    if st.pause_break:
                        break
                continue
            # 独占调用（屏障）：PRE → 派发 → 提交，语义逐行保持
            c = await self._prepare_call(
                call, ci, ctx=ctx, image_provider=image_provider,
                image_aspect_ratio=image_aspect_ratio,
                paused_this_batch=st.paused_this_batch, on_event=on_event)
            if c.result is None and c.gate_error is None:
                # 派发；取消穿透：先记本工具账本/trace（取消态）再上抛，
                # 任何中断都有痕迹（不静默吞，不吞为失败结果）
                try:
                    c.result = await self._dispatch_tool(c.name, c.args)
                except GenerationCancelled:
                    self._record_cancel_ledger(c, st)
                    await self._record_cancelled_call(c, on_event=on_event, tracer=tracer)
                    # 取消留半截态修复（批 6）：穿透上抛前过保守条件判定（不吞异常）；
                    # 回滚实际发生时失效轮内幂等账本（防同键重试命中陈旧成功缓存）
                    if batch_checkpoint.maybe_rollback_on_cancel(
                            StateManager.get_instance(), st.batch_cp, cancelled_tool=c.name,
                            ledger=st.ledger, tool_names=st.batch_tools,
                            tool_manager=self.tool_manager):
                        self._idempotency.reset()
                    raise
            _signal = await self._commit_call(
                c, st, on_event=on_event, on_status=on_status, tracer=tracer)
            if _signal != "continue":
                break
            ci += 1
        # 批末对账（fc_reconcile）：客观账本为主、措辞兜底
        ledger.doc_written = st.doc_written
        ledger.docs_written = st.docs_written
        ledger.structure_created = st.structure_created
        ledger.structure_kinds = st.structure_kinds
        ledger.confirmation = st.confirmation
        ledger.confirmation_options = st.confirmation_options
        ledger.tool_results = st.tool_results
        fc_reconcile.reconcile_batch(ledger, self._raw_state)
        # 问即停事务性写入：仅在发行确认后把暂停三态
        # awaiting_confirmation/confirmation_message/active_pause 经
        # reduce_interaction 一次原子写入（flush=True）；工具本体不写状态，
        # 防「状态已写但卡片未达用户」的半提交态。文案以批末对账后的
        # 最终口径为准（防虚报覆盖等同步改写在此一并生效）
        pause_id_issued = ""
        if st.paused_this_batch:
            _final_pause_message = (
                str(ledger.confirmation or "").strip() or st.pause_fallback_message)
            try:
                _svc_pw = StateManager.get_instance()
                pause_id_issued = uuid.uuid4().hex[:12]
                async with _svc_pw.lock:
                    workflow_runtime.reduce_interaction(_svc_pw, set_flags={
                        "awaiting_confirmation": True,
                        "confirmation_message": _final_pause_message,
                        "active_pause": {
                            "pause_id": pause_id_issued,
                            "message": _final_pause_message,
                            "options": list(ledger.confirmation_options or []),
                            # 发行轮次戳（批 C）：供轮始自愈对账计算卡龄，
                            # 超阈未消费的残留卡自动退役（防永远停在旧阶段）
                            "issued_turn_seq": int(
                                _svc_pw.state_dict.get("turn_seq") or 0),
                        },
                    }, flush=True)
                tracer.record_control_flow(
                    "pause_issued",
                    f"workflow_pause 发行成功（pause_id={pause_id_issued}）；"
                    "暂停三态经 reduce_interaction 事务写入完成")
            except Exception as _e:
                logger.warning("[PauseSlot] 暂停态事务写入失败（不影响本轮收尾）: {}", _e)
        return FCExecuteResult(
            applied=st.applied,
            confirmation=ledger.confirmation,
            image_urls=st.image_urls,
            chat_inserts=st.chat_inserts,
            action_log=st.action_log,
            confirmation_options=ledger.confirmation_options,
            tool_results=ledger.tool_results,
            docs_written=st.docs_written,
            warnings=list(self.gate_warnings),
            pause_overflow=st.pause_overflow,
            pause_id=pause_id_issued,
        )


# ---------- 三段结构落点（无 re-export 壳，消费方一律直连实现体） ----------
# 闸机裁决段实现体 = core/fc_gates.py（run_gate_chain；判定唯一归 guard_pipeline）
# 批末对账段实现体 = core/fc_reconcile.py（execute() 尾部 reconcile_batch 调用）
# 回喂家族实现体 = core/fc_feedback.py
