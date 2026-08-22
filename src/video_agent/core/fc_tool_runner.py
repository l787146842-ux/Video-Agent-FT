"""FC 工具执行段（任务#23 D1：巨石三段拆分 2/3；回喂家族早已切入 fc_feedback.py）。

三段结构：
- 闸机裁决 = core/fc_gates.py（闸机链组合；判定实现唯一归 guard_pipeline）
- 执行 = 本文件（tool_calls 执行循环 + 过程时间线事件 + trace 记账）
- 批末对账 = core/fc_reconcile.py（客观账本为主、措辞兜底，见该模块 D2 说明）

execute() 返回 FCExecuteResult（结构化命名元组）：调用方按字段名取用，
位置解包仍兼容（历史调用/测试不破坏），新增字段不再是隐性破坏。
闸机方法对 fc_gates 保留同名承重壳（壳清单见文件尾部注释，13.7 惯例），
既有调用/测试 patch 路径不变。
"""
import json
import time
from typing import Any, Dict, List, NamedTuple, Optional

from loguru import logger

from src.video_agent.adapters.base_chat import ChatResponse
from src.video_agent.core import fc_gates, fc_reconcile, prompt_gates
from src.video_agent.core import ports
from src.video_agent.core import workflow_runtime
from src.video_agent.core import pause_composer
from src.video_agent.core.sse_events import (
    SSE_ACTIONS_APPLIED, SSE_DOC_WRITTEN, SSE_TOOL_FINISHED, SSE_TOOL_STARTED,
)
from src.video_agent.core.tracer import AgentTracer
from src.video_agent.skill_runtime.registry import stage_label_for_tool
from src.video_agent.state import storyboard_ops as ops
from src.video_agent.state.manager import StateManager
from src.video_agent.tools.base import ToolResult

# 回喂家族定义源 = core/fc_feedback.py；本文件顶层重新绑定全部符号，
# 既有 import 路径与测试 patch 目标不变（承重壳）。
from src.video_agent.core.fc_feedback import (
    FEEDBACK_COMPRESSED,  # noqa: 1
    FEEDBACK_FULL_TOOLS,  # noqa: 1
    FEEDBACK_IMAGE_TOOL,  # noqa: 1
    FEEDBACK_MARKER,  # noqa: 1
    FEEDBACK_MAX_TOTAL_CHARS,  # noqa: 1
    classify_tool_failure,  # noqa: 1
    compose_failure_feedback,
    compress_prior_feedback,  # noqa: 1
    describe_fc_tool,
    digest_projected_tool_results,  # noqa: 1
    format_tool_results,  # noqa: 1
    render_read_result,  # noqa: 1
    should_compress_feedback,  # noqa: 1
    strip_prior_feedback_images,  # noqa: 1
)

# 闸机常量定义源 = core/fc_gates.py；顶层重新绑定（承重壳，旧路径兼容）
_TOOL_RISK_CONFIRM_TOOLS = fc_gates.TOOL_RISK_CONFIRM_TOOLS  # noqa: 1
_PAUSE_WINDOW_READONLY = fc_gates.PAUSE_WINDOW_READONLY  # noqa: 1
_STAGE_ALLOWED_GROUP_KINDS = fc_gates.STAGE_ALLOWED_GROUP_KINDS  # noqa: 1


def _as_start(raw: Any) -> int:
    """read_skill 续读起点容错解析：非数字（模型偶发传「开头」等描述、
    None/缺失）一律归 0，不得抛 ValueError 中断整批工具执行。"""
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0


class FCExecuteResult(NamedTuple):
    """execute() 结构化返回（杜绝位置解包：字段名即契约）。

    warnings：本批闸机拦截/豁免的用户可见文案，由 planner 并入
    loop_result.warnings —— FC 轨与文本轨拦截可见性对齐（§2.0/§2.4）；
    pause_overflow：三通道分离 B，模型 pause message 超长的原文（进正文通道）。
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


class FCToolRunner:
    """执行 Function Calling 返回的 tool_calls（planner 的 FC 执行臂）"""

    def __init__(self, tool_manager) -> None:
        self.tool_manager = tool_manager
        # 当前对话使用的聊天供应商/模型（决策 E：与主模型一致，
        # 由 chat_service/planner 注入；执行器已随任务#36 B5 退役，
        # 属性保留仅为注入方兼容）
        self.chat_provider: str = ""
        self.chat_model: str = ""
        # 用户坚持作用域（False / True / "all" / "element_image"）：覆盖对应闸机
        self.gate_override: Any = False
        # 本批闸机警告（随 execute 返回/时间线可见）
        self.gate_warnings: List[str] = []
        # 本轮同工具失败计数（结构化回喂升级用）
        self._tool_fail_counts: Dict[str, int] = {}
        # Skill 可配置闸机规则（测试/执行器注入 parse_gate_rules 结果）
        self._gate_rules: Optional[Dict[str, Any]] = None
        # 前端当前选中的草稿（对齐文本轨 "current" 语义）；execute 时按请求注入
        self._selected_draft_id = ""
        self._selected_type = ""
        # 闸机校准：(kind+原因签名) 连续相同拦截计数，用于升级重写指引文案
        self._gate_repeat: Dict[str, int] = {}

    # ---------- 闸机裁决段承重壳（实现体 = core/fc_gates.py） ----------

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
            gate_rules=getattr(self, "_gate_rules", None),
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

    @staticmethod
    def _skill_full_text_injected(skill_name: str) -> bool:
        return fc_gates.skill_full_text_injected(skill_name)

    def _resolve_current_refs(self, name: str, args: Dict[str, Any]) -> None:
        fc_gates.resolve_current_refs(self._gate_ctx(), name, args)

    def _prompt_gate(self, name: str, args: Dict[str, Any], injected_skill: str) -> Optional[str]:
        return fc_gates.prompt_gate(self._gate_ctx(injected_skill), name, args)

    def _stage_precondition_gate(self, name: str, injected_skill: str) -> Optional[str]:
        return fc_gates.stage_precondition_gate(self._gate_ctx(injected_skill), name)

    def _flow_gate(self, name: str, injected_skill: str) -> Optional[str]:
        return fc_gates.flow_gate(self._gate_ctx(injected_skill), name)

    def _strip_structure_prompt(self, name: str, args: Dict[str, Any], injected_skill: str) -> bool:
        return fc_gates.strip_structure_prompt(self._gate_ctx(injected_skill), name, args)

    def _structure_integrity_gate(
        self, name: str, args: Dict[str, Any], injected_skill: str,
    ) -> Optional[str]:
        return fc_gates.structure_integrity_gate(
            self._gate_ctx(injected_skill), name, args)

    def _gen_confirm_gate(self, name: str, args: Dict[str, Any], injected_skill: str) -> Optional[str]:
        return fc_gates.gen_confirm_gate(self._gate_ctx(injected_skill), name, args)

    def _tool_risk_gate(self, name: str) -> Optional[str]:
        return fc_gates.tool_risk_gate(self._gate_ctx(), name)

    # ---------- 执行段 ----------

    def _tool_risk_of(self, name: str) -> str:
        """读取工具声明的风险分级；未注册/未声明一律 high（deny-by-default，§2.7）。"""
        try:
            tool = self.tool_manager.get_tool(name)
        except Exception:
            tool = None
        risk = str(getattr(tool, "risk", "") or "").strip().lower()
        return risk if risk in ("low", "medium", "high") else "high"

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

    async def execute(
        self, response: ChatResponse, image_provider: str = "", image_aspect_ratio: str = "",
        on_status=None, on_event=None, injected_skill: str = "",
        selected_draft_id: str = "", selected_type: str = "",
        gate_override: Any = False,
    ) -> FCExecuteResult:
        """执行 Function Calling 返回的 tool_calls。

        返回 FCExecuteResult（applied, confirmation, image_urls, chat_inserts,
        action_log, confirmation_options, tool_results, docs_written, warnings,
        pause_overflow）——位置解包仍兼容，新调用方请按字段名取用。
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
        # 轮内暂停纪律：workflow_pause 请求确认后同批拒续执行
        paused_this_batch = False
        applied = 0
        confirmation = ""
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
        # 结构纯净闸/故事板强制暂停用的批内标志
        structure_created = False
        structure_kinds: set = set()  # 本批搭建的结构类别（shot 优先决定暂停文案）
        prompt_gate_blocked = 0
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

            # 执行器供应商/模型绑定与 skill_name 强注已随任务#36 B5 退役
            # （执行器工具不再注册；通用路径工具无此参数）

            # 过程时间线：工具开始（前端渲染运行态条目）
            tool_event_id = str(call.get("id") or f"fc-{ci}") if isinstance(call, dict) else f"fc-{ci}"
            start_summary = describe_fc_tool(name, args)
            if on_event is not None:
                await on_event({
                    "type": SSE_TOOL_STARTED,
                    "id": tool_event_id,
                    "name": name,
                    "summary": start_summary,
                })
            _tool_t0 = time.monotonic()

            # --- 生图模型强制注入：草稿自身（中间面板直接选择）> 全局设置 > 平台默认 ---
            if name == "generate_image" and (
                "adapter_provider" not in args or args.get("adapter_provider") in ("mock", "", None)
            ):
                _sp, _sm = ports.provider_config_port().spec_media_preference(self._raw_state())
                # 用户裁决：模型能力参数唯一权威源 = 全局设置；优先级 =
                # 草稿自身（用户在中间面板的直接选择）> 全局设置 > 平台默认
                if image_provider:
                    args["adapter_provider"] = image_provider
                    logger.info("[Planner] Injected image gen provider from draft: %s",
                                image_provider)
                elif _sp:
                    args["adapter_provider"] = _sp
                    logger.info("[Planner] Injected image gen provider from global settings: %s", _sp)
            # --- 画面比例注入：用中间面板选中的比例 ---
            if name == "generate_image" and image_aspect_ratio:
                if not args.get("aspect_ratio"):
                    args["aspect_ratio"] = image_aspect_ratio
                    logger.info("[Planner] Injected image gen aspect ratio from draft: %s",
                                image_aspect_ratio)
            # --- image_generate（批量工具）同轨注入：LLM 未传 provider 时依次回退
            # 用户裁决：草稿自身（用户直接选择）> 全局设置 > 平台默认；
            # 防传空导致「供应商 '' 未配置」---
            if name == "image_generate" and not str(args.get("provider_id") or "").strip():
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

            # 结构纯净闸：内联详细提示词剥离（闸机链之前，回喂时附说明）
            if fc_gates.strip_structure_prompt(ctx, name, args):
                ledger.prompt_stripped = True
            # 闸机链（fc_gates.run_gate_chain）：轮内暂停纪律 → 阶段前置（平台不变量）
            # → 规格前置 → 工具风险 → 生成确认 → 建组结构完整性 → 提示词结构 → 生图配额
            chain = fc_gates.run_gate_chain(
                ctx, name, args, paused_this_batch=paused_this_batch)
            gate_error = chain.error
            prompt_gate_blocked += chain.prompt_gate_blocked
            if gate_error is not None:
                result = ToolResult(success=False, error=gate_error)
            elif name == "read_skill" and injected_skill:
                wanted_skill = str(args.get("name") or "").strip()
                same_skill = bool(wanted_skill) and wanted_skill == injected_skill.strip()
                # 续读参数（section/start）一律真读：分级注入时全文未全量注入，
                # 短路会断掉模型的章节续读能力（任务#36 B5）
                has_cont = bool(str(args.get("section") or "").strip()) \
                    or _as_start(args.get("start")) > 0
                if same_skill and not has_cont and fc_gates.skill_full_text_injected(wanted_skill):
                    result = ToolResult(success=True, data={
                        "content": f"Skill「{wanted_skill}」全文已在本轮 system prompt 中注入，无需重复读取，直接遵循其中的规则即可。",
                        "already_injected": True,
                    })
                    logger.info(f"[Planner] read_skill 短路：「{wanted_skill}」全文已直注，跳过工具调用")
                else:
                    # 未全量直注（分级注入/其他 Skill/续读）：按需真读全文或章节
                    result = await self.tool_manager.invoke_tool(name, args)
            else:
                result = await self.tool_manager.invoke_tool(name, args)
            _tool_ms = (time.monotonic() - _tool_t0) * 1000
            # 主体回归（ADR-0004）单一活跃暂停槽位互斥：已有未消费暂停时
            # 拒收重复 workflow_pause，结构化拒因回喂模型并进 trace（不静默吞掉）
            if name == "workflow_pause" and result.success:
                try:
                    _svc_pause = StateManager.get_instance()
                    _active = ((_svc_pause.state_dict.get("interaction") or {})
                               .get("active_pause") or {})
                    if _active.get("pause_id"):
                        result = ToolResult(success=False, error=(
                            "已有一张活跃暂停卡正在等待用户回应（单一活跃暂停槽位，"
                            "ADR-0004）。请勿重复发起暂停；等待用户回应现有暂停卡后，"
                            "再根据其回应决定下一步。"))
                        logger.info("[PauseSlot] workflow_pause 拒收：已有活跃暂停")
                except Exception as _e:
                    logger.debug("[fc_tool_runner] 忽略异常: {}", _e)
            # 生成类工具成败记录（批末对账用客观账本）
            if name in ("image_generate", "generate_image", "generate_video"):
                if result.success:
                    ledger.gen_succeeded = True
                elif not ledger.gen_failed_err:
                    ledger.gen_failed_err = str(result.error or "执行失败")
            if result.success:
                applied += 1
                # node_attempts 成败记账随执行器退役删除（任务#36 B5）：
                # 连失败重试引导归 gate_precheck，通用路径工具不再入账
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
                if name == "workflow_pause":
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
                if name in ("document_write", "write_document"):
                    doc_written = True
                    doc_name = str(args.get("name") or args.get("key") or "").strip()
                    if doc_name:
                        docs_written.append(doc_name)
                        # 修复（恢复四段链）：文档卡片即写即显，不等整轮 done。
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
                    "view_storyboard_media",
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
                                     result_summary=desc)
                batch_tool_names.add(name)
                _stage_lbl = stage_label_for_tool(name)
                if _stage_lbl:
                    last_stage_label = _stage_lbl
                    self._turn_stage_label = _stage_lbl
                tool_results.append({"name": name, "ok": True, "data": result.data})
                # --- 收集 generate_image 产出的图片 URL ---
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
                # --- ：工具成功结果携带的警告（如建组闸机回喂清单）
                # 升级为轮末用户可见警告，不得只留在 trace（静默丢失禁令） ---
                if data and isinstance(data.get("warnings"), list):
                    for _tw in data["warnings"]:
                        _tws = str(_tw or "").strip()
                        if _tws and _tws not in self.gate_warnings:
                            self.gate_warnings.append(_tws)
            else:
                logger.warning(f"[Planner] Tool '{name}' failed: {result.error}")
                # node_attempts 失败记账随执行器退役删除（任务#36 B5）
                if name == "document_write":
                    ledger.key_tool_failed.append(name)
                    ledger.key_tool_errors[name] = str(result.error or "执行失败")[:200]
                if name == "document_write" and prompt_gates.is_spec_doc_name(
                    str(args.get("name") or args.get("key") or "")
                ):
                    ledger.spec_write_rejected = True
                # 规格拒收静默——用户侧用中性系统提示（无失败红叉/⚠），
                # 拒收原因仍经 tool_results 回喂模型（模型知道未落盘）
                spec_silent_summary = ""
                if (
                    name == "document_write"
                    and prompt_gates.is_spec_doc_name(str(args.get("name") or args.get("key") or ""))
                ):
                    spec_silent_summary = (
                        "规格写入由系统向导接管（模型手写未落盘）"
                        if not prompt_gates.spec_doc_finalized(self._raw_state())
                        else "规格已定稿，冗余写入被拒收（未落盘）"
                    )
                if on_event is not None:
                    _finished_ev = {
                        "type": SSE_TOOL_FINISHED,
                        "id": tool_event_id,
                        "ok": bool(spec_silent_summary),
                        "elapsed_ms": round(_tool_ms, 1),
                        "result_summary": spec_silent_summary or str(result.error or "执行失败")[:120],
                    }
                    await on_event(_finished_ev)
                # trace 与 SSE 同一口径（规格静默拒收=中性 True，普通失败=红× False），
                # 防刷新后失败被重建为绿√；result_summary 与 SSE 同口径
                tracer.record_action(
                    name=name, summary=spec_silent_summary or start_summary,
                    elapsed_ms=_tool_ms, ok=bool(spec_silent_summary),
                    stage=stage_label_for_tool(name),
                    result_summary=spec_silent_summary or str(result.error or "执行失败")[:120],
                )
                # 结构化失败回喂（客观报告+单句建议，二次升级）
                self._tool_fail_counts[name] = self._tool_fail_counts.get(name, 0) + 1
                tool_results.append({
                    "name": name, "ok": False,
                    "error": compose_failure_feedback(
                        name, result.error, self._tool_fail_counts[name],
                    ),
                })
        # 批末对账（fc_reconcile）：客观账本为主、措辞兜底（D2）
        ledger.doc_written = doc_written
        ledger.docs_written = docs_written
        ledger.structure_created = structure_created
        ledger.structure_kinds = structure_kinds
        ledger.prompt_gate_blocked = prompt_gate_blocked
        ledger.confirmation = confirmation
        ledger.confirmation_options = confirmation_options
        ledger.tool_results = tool_results
        fc_reconcile.reconcile_batch(ledger, self._raw_state)
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
        )


# ---------- 承重壳清单（13.7 登记；测试 patch 目标与旧 import 路径不变） ----------
# 闸机裁决段承重壳（实现体 core/fc_gates.py）：
#   FCToolRunner._prompt_gate / _stage_precondition_gate / _flow_gate /
#   _structure_integrity_gate / _gen_confirm_gate / _tool_risk_gate /
#   _strip_structure_prompt / _resolve_current_refs / _skill_full_text_injected
# 批末对账段（实现体 core/fc_reconcile.py）：execute() 尾部 reconcile_batch 调用
# 回喂家族承重壳（实现体 core/fc_feedback.py）：本文件顶部 re-export 清单
