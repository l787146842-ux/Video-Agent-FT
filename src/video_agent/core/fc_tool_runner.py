"""FC 工具执行段。

三段结构：
- 闸机裁决 = core/fc_gates.py（闸机链组合；判定实现唯一归 guard_pipeline）
- 执行 = 本文件（tool_calls 执行循环 + 过程时间线事件 + trace 记账）
- 批末对账 = core/fc_reconcile.py（客观账本为主、措辞兜底）

execute() 返回 FCExecuteResult（结构化命名元组）：调用方按字段名取用，
位置解包仍兼容（历史调用/测试不破坏），新增字段不再是隐性破坏。
闸机裁决实现体 = core/fc_gates.py（本文件只组装 GateContext 并调 run_gate_chain），
回喂家族实现体 = core/fc_feedback.py；两者均由消费方直连，本文件不再设 re-export 壳。
"""
import json
import time
import uuid
from typing import Any, Dict, List, NamedTuple, Optional

from loguru import logger

from src.video_agent.adapters.base_chat import ChatResponse
from src.video_agent.adapters.cancel_token import GenerationCancelled
from src.video_agent.core import fc_gates, fc_reconcile, prompt_gates
from src.video_agent.core import batch_checkpoint
from src.video_agent.core import ports
from src.video_agent.core import readonly_parallel
from src.video_agent.core import workflow_runtime
from src.video_agent.core import pause_composer
from src.video_agent.core import tool_args_preview
from src.video_agent.core.gates_cards import PAUSE_SLOT_ASSERTION_NOTE
from src.video_agent.core.idempotency_ledger import IdempotencyLedger
from src.video_agent.core.sse_events import (
    SSE_ACTIONS_APPLIED, SSE_DOC_WRITTEN, SSE_TOOL_FINISHED, SSE_TOOL_STARTED,
)
from src.video_agent.core.tracer import AgentTracer
from src.video_agent.skill_runtime.registry import stage_label_for_tool
from src.video_agent.state import storyboard_ops as ops
from src.video_agent.state.manager import StateManager
from src.video_agent.tools.base import ToolResult

from src.video_agent.core.fc_feedback import (
    compose_failure_feedback,
    describe_fc_tool,
)


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

    async def _dispatch_tool(self, name: str, args: Dict[str, Any]) -> ToolResult:
        """闸机放行后的单调用派发（串行主循环与批 7 只读并行窗口共用同一派发面）：
        含 read_skill 在内全部常规分发真执行（任务#12：短路已废）。"""
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
            interaction = svc.state_dict.setdefault("interaction", {})
            presented = interaction.setdefault("drafts_presented", [])
            if draft_id not in presented:
                presented.append(draft_id)
                svc.save()
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
        # 轮内暂停纪律：workflow_pause 请求确认后同批不再续执行（问即停：
        # 发行成功即结束本批，悬挂调用不执行也不回喂拒因）
        paused_this_batch = False
        applied = 0
        confirmation = ""
        # 问即停：暂停发行后置的批末终止标记与事务写入兜底文案（批内赋值）
        _pause_break = False
        _pause_fallback_message = ""
        # 三通道分离 B：模型 pause message 超长的原文（进正文通道，不丢信息）
        pause_overflow = ""
        # 三通道分离 C：批内成功执行的工具名/阶段标签（阶段边界判定用）；
        # 阶段标签跨批保留（实例属性）——分析工具与
        # workflow_pause 分属两个批，短问句仍需带上真实阶段名
        batch_tool_names: set = set(getattr(self, "_turn_tool_names", ()))
        self._turn_tool_names = batch_tool_names
        last_stage_label = str(getattr(self, "_turn_stage_label", "") or "")
        confirmation_options: List[Dict[str, Any]] = []
        image_urls: List[str] = []
        chat_inserts: List[Dict[str, Any]] = []
        action_log: List[str] = []
        tool_results: List[Dict[str, Any]] = []
        doc_written = False
        docs_written: List[str] = []  # 本批写入的文档名（供前端渲染文档卡片）
        # 批级检查点（批 6）：本批含写类/中高危工具时批首打快照，失败/取消回滚判定全在 core/batch_checkpoint.py
        _batch_cp = batch_checkpoint.take_checkpoint() if batch_checkpoint.batch_has_risky_tool(
            response, self.tool_manager) else None
        _batch_tools = batch_checkpoint.batch_tool_names(response)
        # 只读受限并行（批 7，默认关）：识别连续 low 只读段；开关关/无窗口时返回空计划，
        # 执行路径与现状完全等价；段识别与窗口调度一律归 core/readonly_parallel.py
        _ro_plan, _ro_pre = readonly_parallel.plan_batch(response.tool_calls, self.tool_manager)
        # 结构纯净闸/故事板强制暂停用的批内标志
        structure_created = False
        structure_kinds: set = set()  # 本批搭建的结构类别（shot 优先决定暂停文案）
        tracer = AgentTracer.get_instance()
        for ci, call in enumerate(response.tool_calls):
            func = call.get("function", {}) if isinstance(call, dict) else {}
            name = func.get("name", "")
            args_raw = func.get("arguments", "{}")
            try:
                args = json.loads(args_raw) if isinstance(args_raw, str) else args_raw
            except json.JSONDecodeError:
                args = {}
            # current/空引用 → 真实 id（闸机与工具调用前，防命中错误卡片/绕过闸机）
            fc_gates.resolve_current_refs(ctx, name, args)

            # 批 7 只读并行窗口：命中窗口起点时整窗调度（闸机按序裁决 →
            # 全部放行后并行执行 → 结果按原序回填 _ro_pre）
            if ci in _ro_plan:
                await readonly_parallel.run_window(
                    self, ctx, ledger, response.tool_calls, _ro_plan[ci], _ro_pre,
                    paused_this_batch=paused_this_batch,
                    on_event=on_event, batch_cp=_batch_cp, batch_tools=_batch_tools)

            # 过程时间线：工具开始（前端渲染运行态条目）
            tool_event_id = str(call.get("id") or f"fc-{ci}") if isinstance(call, dict) else f"fc-{ci}"
            start_summary = describe_fc_tool(name, args)
            # 输入参数预览（裁剪脱敏）：随 started 事件下发并同步
            # 落盘 trace（刷新重建后详情卡展开区不丢）
            args_preview = tool_args_preview.redact_tool_args(name, args)
            if on_event is not None:
                await on_event({
                    "type": SSE_TOOL_STARTED,
                    "id": tool_event_id,
                    "name": name,
                    "summary": start_summary,
                    "args": args_preview,
                })
            _tool_t0 = time.monotonic()

            # --- image_generate（统一生图工具）同轨注入：按 mode 分流，
            # 优先级 = 草稿自身（中间面板直接选择）> 全局设置 > 平台默认；
            # single 模式补 adapter_provider/aspect_ratio，batch 模式补
            # provider_id/model；防传空导致「供应商 '' 未配置」---
            if name == "image_generate":
                _img_single = str(args.get("mode") or "batch").strip().lower() == "single"
                if _img_single:
                    if "adapter_provider" not in args or args.get("adapter_provider") in ("", None):
                        _sp, _sm = ports.provider_config_port().spec_media_preference(self._raw_state())
                        if image_provider:
                            args["adapter_provider"] = image_provider
                            logger.info("[Planner] Injected image_generate(single) provider from draft: %s",
                                        image_provider)
                        elif _sp:
                            args["adapter_provider"] = _sp
                            logger.info("[Planner] Injected image_generate(single) provider from global settings: %s", _sp)
                    if image_aspect_ratio and not args.get("aspect_ratio"):
                        args["aspect_ratio"] = image_aspect_ratio
                        logger.info("[Planner] Injected image_generate(single) aspect ratio from draft: %s",
                                    image_aspect_ratio)
                elif not str(args.get("provider_id") or "").strip():
                    spec_pid, spec_model = ports.provider_config_port().spec_media_preference(self._raw_state())
                    if image_provider:
                        args["provider_id"] = image_provider
                        logger.info("[Planner] Injected image_generate provider from draft: %s",
                                    image_provider)
                    elif spec_pid:
                        args["provider_id"] = spec_pid
                        if spec_model and not str(args.get("model") or "").strip():
                            args["model"] = spec_model
                        logger.info("[Planner] Injected image_generate provider from global settings: %s/%s",
                                    spec_pid, spec_model)

            # --- generate_video 同轨注入（任务 #20，与 image_generate 同模式）：
            # 优先级 = 模型显式指定 > 目标草稿卡自身的视频配置 > 全局默认渠道；
            # 按卡类型解析（分区内混有三类卡，禁止「分区 → 媒体类型」映射）---
            elif name == "generate_video":
                if not str(args.get("adapter_provider") or "").strip():
                    _vp, _vm = ports.provider_config_port().resolve_selected_draft_media_config(
                        self._raw_state(), self._selected_draft_id, self._selected_type,
                        kind="video")
                    if _vp:
                        args["adapter_provider"] = _vp
                        logger.info("[Planner] Injected generate_video provider from selected draft: %s/%s",
                                    _vp, _vm)

            # 幂等键轮内去重（T4）：同键命中直接用首次结果，跳过闸机链与实际执行；
            # 空键直通过不去重，判定语义唯一归 core/idempotency_ledger.py
            _idem_key = str(args.get("idempotency_key") or "").strip()
            _idem_cached = self._idempotency.check(_idem_key)
            _ro_hit = _ro_pre.pop(ci, None)
            if _ro_hit is not None:
                # 批 7 并行窗口预执行结果按原序回填（闸机裁决已在窗口内按序完成）
                result, gate_error = _ro_hit.result, _ro_hit.gate_error
            elif _idem_cached is not None:
                result, gate_error = _idem_cached, None
            else:
                # 结构纯净闸：内联详细提示词剥离（闸机链之前，回喂时附说明）
                fc_gates.strip_structure_prompt(ctx, name, args)
                # 闸机链（fc_gates.run_gate_chain）：轮内暂停纪律 → 工具风险 →
                # 生成确认 → 建组结构完整性 → 提示词结构 → 生图配额
                # （C1b 裁决 2026-08-31：阶段前置闸退役）
                chain = fc_gates.run_gate_chain(
                    ctx, name, args, paused_this_batch=paused_this_batch)
                gate_error = chain.error
                try:
                    if gate_error is not None:
                        result = ToolResult(success=False, error=gate_error)
                    else:
                        result = await self._dispatch_tool(name, args)
                except GenerationCancelled:
                    # 取消穿透：先记本工具账本/trace（取消态）再上抛，
                    # 任何中断都有痕迹（不静默吞，不吞为失败结果）
                    _cancel_desc = describe_fc_tool(name, args)
                    if name in ("image_generate", "generate_video"):
                        ledger.gen_failed_err = "生成任务已被取消"
                    if on_event is not None:
                        await on_event({
                            "type": SSE_TOOL_FINISHED,
                            "id": tool_event_id,
                            "ok": False,
                            "elapsed_ms": round((time.monotonic() - _tool_t0) * 1000, 1),
                            "result_summary": "已被用户取消",
                        })
                    tracer.record_action(
                        name=name, summary=_cancel_desc,
                        elapsed_ms=(time.monotonic() - _tool_t0) * 1000, ok=False,
                        stage=stage_label_for_tool(name),
                        result_summary="已被用户取消", args=args_preview,
                    )
                    # 取消留半截态修复（批 6）：穿透上抛前过保守条件判定（不吞异常）；
                    # 回滚实际发生时失效轮内幂等账本（防同键重试命中陈旧成功缓存）
                    if batch_checkpoint.maybe_rollback_on_cancel(
                            StateManager.get_instance(), _batch_cp, cancelled_tool=name,
                            ledger=ledger, tool_names=_batch_tools,
                            tool_manager=self.tool_manager):
                        self._idempotency.reset()
                    raise
            _tool_ms = _ro_hit.elapsed_ms if _ro_hit is not None else (time.monotonic() - _tool_t0) * 1000
            # 幂等键记账（T4）：非空键的执行结果（含失败）入轮内账本；
            # 空键与闸机拒收不记账（拒收无副作用，待模型改参/用户确认后重新裁决）
            if gate_error is None:
                self._idempotency.record(_idem_key, result)
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
            if name in ("image_generate", "generate_video"):
                if result.success:
                    ledger.gen_succeeded = True
                elif not ledger.gen_failed_err:
                    ledger.gen_failed_err = str(result.error or "执行失败")
            if result.success:
                applied += 1
                self._record_presented(name, args)
                if name in ("storyboard_create_group", "storyboard_add_draft"):
                    structure_created = True
                    kind = prompt_gates.normalize_structure_kind(args.get("group_type") or "")
                    if kind:
                        structure_kinds.add(kind)
                    # 待确认标记即时置位（不等批结束）：同批后续的提示词写入
                    # 会被提示词闸的 storyboard_pending 检查拦住（防 3+4 合并）
                    if ledger.skill_strict:
                        try:
                            svc_now = StateManager.get_instance()
                            if not (svc_now.state_dict.get("interaction") or {}).get("storyboard_pending"):
                                workflow_runtime.reduce_interaction(
                                    svc_now, set_flags={"storyboard_pending": True}, flush=True)
                        except Exception as _e:
                            logger.debug("[fc_tool_runner] 忽略异常: {}", _e)
                if name == "workflow_pause" and scope_auto_pause:
                    # 子对话不发确认卡（用户裁决，二期子对话批 3）：scope 任务命中
                    # workflow_pause 直接放行——不登记暂停三态、不组卡、不置问即停；
                    # 回喂改写为「已自动确认」（见 tool_results 追加处），模型继续执行。
                    # 主对话问即停语义不变（旗标缺省关）。
                    tracer.record_control_flow(
                        "pause_auto_passed",
                        "scope 子对话内 workflow_pause 自动放行（不发起确认，直接执行）")
                elif name == "workflow_pause":
                    paused_this_batch = True
                    # workflow_pause 只提交审批事实——卡问句系统
                    # 组装，模型原文一律进正文通道（无阈值补丁）
                    confirmation, pause_overflow = pause_composer.split_pause_channels(
                        args.get("message", ""), last_stage_label)
                    if pause_overflow:
                        logger.info(
                            "[FlowGate] pause message 超长（{}字）已压缩，原文进正文通道",
                            len(pause_overflow),
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
                                confirmation_options.append(item)
                            elif isinstance(o, str) and o.strip():
                                confirmation_options.append({"label": o.strip(), "description": ""})
                    # 验收缺失清单在场 → 暂停卡附「补拆/维持」结构化选项
                    # （落实 Skill「先与用户确认是否修改」；附后清除登记）
                    try:
                        _svc_m = StateManager.get_instance()
                        _inter_m = _svc_m.state_dict.get("interaction") or {}
                        _missing = _inter_m.get("pending_missing") or []
                        if _missing:
                            _n = len(_missing)
                            confirmation_options.append({
                                "label": f"补拆 {_n} 项缺失元素", "value": "补拆",
                                "description": "、".join(_missing[:6]) + ("等" if _n > 6 else "")})
                            confirmation_options.append({
                                "label": "维持现状继续", "value": "继续",
                                "description": "接受缺失，按流程推进下一阶段"})
                            _inter_m.pop("pending_missing", None)
                            _svc_m.save_debounced()
                    except Exception as _e:
                        logger.debug("[fc_tool_runner] 忽略异常: {}", _e)
                    # 选项面单一归一（Rule2 v6，pause_composer 唯一实现）：
                    # 模型自造规格类选项替换为标准向导；阶段边界剔除模型
                    # 继续类选项并前置系统派生项；调整类选项保留。
                    _boundary_hit = (
                        "script_analyze" in batch_tool_names
                        or (doc_written and prompt_gates.has_spec_document(
                            self._raw_state()))
                        or (structure_created and prompt_gates.storyboard_stage_complete(
                            self._raw_state(), injected_skill))
                    )
                    confirmation, confirmation_options = pause_composer.normalize_option_surface(
                        self._raw_state(), injected_skill, confirmation,
                        confirmation_options, boundary_hit=_boundary_hit)
                    # 问即停：记下事务写入兜底文案（模型原文），
                    # 置批末终止标记——本批后续调用不执行也不回喂拒因，
                    # 悬挂调用留在 history 末尾，待暂停三态回应后统一消费
                    _pause_fallback_message = (
                        str(args.get("message") or "").strip()
                        or "请确认以上内容，确认后我将继续。")
                    _pause_break = True
                if name in ("document_write", "write_document"):
                    doc_written = True
                    # 即时同步进账本（与生成族记账同节拍）：循环中段的回滚判定读得到文档写标志，不留时序缺口；批末重复赋值同值无害
                    ledger.doc_written = True
                    doc_name = str(args.get("name") or args.get("key") or "").strip()
                    if doc_name:
                        docs_written.append(doc_name)
                        ledger.docs_written = list(docs_written)
                        # 文档卡片即写即显，不等整轮 done。
                        # 前端按名称去重，done payload 的 documents_written 仍携带全量
                        # 供服务端持久化与刷新重建。
                        if on_event is not None:
                            await on_event({"type": SSE_DOC_WRITTEN, "name": doc_name})
                desc = describe_fc_tool(name, args)
                action_log.append(desc)
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
                        "id": tool_event_id,
                        "ok": True,
                        "elapsed_ms": round(_tool_ms, 1),
                        "result_summary": desc,
                    }
                    await on_event(_finished_ev)
                tracer.record_action(name=name, summary=desc, elapsed_ms=_tool_ms, ok=True,
                                     stage=stage_label_for_tool(name),
                                     result_summary=desc,
                                     args=args_preview)
                batch_tool_names.add(name)
                _stage_lbl = stage_label_for_tool(name)
                if _stage_lbl:
                    last_stage_label = _stage_lbl
                    self._turn_stage_label = _stage_lbl
                tool_results.append({"name": name, "ok": True, "data": result.data})
                # 子对话暂停放行（批 3）：回喂替换「已暂停」为「已自动确认」，
                # 防模型停在等待用户回应的语义上（子对话不发起确认）
                if name == "workflow_pause" and scope_auto_pause:
                    tool_results[-1]["data"] = {
                        "auto_passed": True,
                        "note": "当前在微调子对话内：系统已自动确认并放行你的暂停请求"
                        "（子对话内不发起用户确认），请直接继续执行完成本次调整。",
                    }
                # --- 收集 image_generate（single 模式）产出的图片 URL ---
                data = result.data
                if data and "image_urls" in data:
                    urls = data["image_urls"]
                    if isinstance(urls, list):
                        image_urls.extend(urls)
                # --- 收集 storyboard_media_to_chat 产出的对话输入框插入项 ---
                if data and "chat_inserts" in data:
                    inserts = data["chat_inserts"]
                    if isinstance(inserts, list):
                        chat_inserts.extend(inserts)
                # --- 工具成功结果携带的警告（如建组闸机回喂清单）
                # 升级为轮末用户可见警告，不得只留在 trace（静默丢失禁令） ---
                if data and isinstance(data.get("warnings"), list):
                    for _tw in data["warnings"]:
                        _tws = str(_tw or "").strip()
                        if _tws and _tws not in self.gate_warnings:
                            self.gate_warnings.append(_tws)
                # 问即停：暂停发行成功 = 立即结束本批（同批后续
                # tool_calls 不执行、不产生拒因回喂；发卡点正常收尾）
                if _pause_break:
                    break
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
                        "id": tool_event_id,
                        "ok": False,
                        "elapsed_ms": round(_tool_ms, 1),
                        "result_summary": str(result.error or "执行失败")[:120],
                    }
                    await on_event(_finished_ev)
                tracer.record_action(
                    name=name, summary=f"{start_summary}（累计失败 {_fail_n} 次）",
                    elapsed_ms=_tool_ms, ok=False,
                    stage=stage_label_for_tool(name),
                    result_summary=str(result.error or "执行失败")[:120],
                    args=args_preview,
                )
                # 花钱生成失败不静默（Q22）：用户可见警告（随 gate_warnings
                # 并入轮末 warnings）+ 轮级登记（planner 轮末机械附重试选项卡）
                _is_costly = getattr(self.tool_manager, "is_costly_tool", None)
                if callable(_is_costly) and _is_costly(name):
                    _cf_msg = (
                        f"花钱生成失败：{start_summary} —— "
                        f"{str(result.error or '执行失败')[:120]}。"
                        "可点「重试」重新执行，或调整提示词/模型后再试"
                    )
                    if _cf_msg not in self.gate_warnings:
                        self.gate_warnings.append(_cf_msg)
                    self.costly_failures.append(name)
                # 结构化失败回喂（客观报告+单句建议，二次升级）
                tool_results.append({
                    "name": name, "ok": False,
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
                # 并中止本批后续调用（仿 _pause_break：不得在已恢复状态上继续执行产生矛盾回喂）；
                # 取消分支同理在穿透上抛前判定（见本文件上方 GenerationCancelled 处）
                if not batch_checkpoint.is_unexecuted_rejection(gate_error, result):
                    if batch_checkpoint.maybe_rollback_on_failure(
                            StateManager.get_instance(), _batch_cp, failed_tool=name,
                            ledger=ledger, tool_names=_batch_tools,
                            tool_manager=self.tool_manager):
                        self._idempotency.reset()
                        break
        # 批末对账（fc_reconcile）：客观账本为主、措辞兜底
        ledger.doc_written = doc_written
        ledger.docs_written = docs_written
        ledger.structure_created = structure_created
        ledger.structure_kinds = structure_kinds
        ledger.confirmation = confirmation
        ledger.confirmation_options = confirmation_options
        ledger.tool_results = tool_results
        fc_reconcile.reconcile_batch(ledger, self._raw_state)
        # 问即停事务性写入：仅在发行确认后把暂停三态
        # awaiting_confirmation/confirmation_message/active_pause 经
        # reduce_interaction 一次原子写入（flush=True）；工具本体不写状态，
        # 防「状态已写但卡片未达用户」的半提交态。文案以批末对账后的
        # 最终口径为准（防虚报覆盖等同步改写在此一并生效）
        pause_id_issued = ""
        if paused_this_batch:
            _final_pause_message = (
                str(ledger.confirmation or "").strip() or _pause_fallback_message)
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
            applied=applied,
            confirmation=ledger.confirmation,
            image_urls=image_urls,
            chat_inserts=chat_inserts,
            action_log=action_log,
            confirmation_options=ledger.confirmation_options,
            tool_results=ledger.tool_results,
            docs_written=docs_written,
            warnings=list(self.gate_warnings),
            pause_overflow=pause_overflow,
            pause_id=pause_id_issued,
        )


# ---------- 三段结构落点（无 re-export 壳，消费方一律直连实现体） ----------
# 闸机裁决段实现体 = core/fc_gates.py（run_gate_chain；判定唯一归 guard_pipeline）
# 批末对账段实现体 = core/fc_reconcile.py（execute() 尾部 reconcile_batch 调用）
# 回喂家族实现体 = core/fc_feedback.py
