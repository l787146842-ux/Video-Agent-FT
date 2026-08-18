"""FC 工具执行与回喂（从 planner.py 拆出，批次5 文件瘦身；
八轮 B1 回喂家族切入 core/fc_feedback.py，本文件保留 re-export）。

承载：
- Function Calling tool_calls 的执行循环（含 read_skill 短路、生图参数注入、过程时间线事件）
- 工具结果回喂的格式化/压缩委托 fc_feedback（token 治理，C3 落点见该模块）

planner.py 对下列符号保留同名委托，既有调用/测试路径不变。
"""
import json
import time
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from src.video_agent.adapters.base_chat import ChatResponse
from src.video_agent.config import settings
from src.video_agent.core import guard_pipeline, prompt_gates
from src.video_agent.core.sse_events import SSE_ACTIONS_APPLIED, SSE_DOC_WRITTEN, SSE_TOOL_FINISHED, SSE_TOOL_STARTED
from src.video_agent.core.tracer import AgentTracer
from src.video_agent.skill_runtime.registry import stage_label_for_tool
from src.video_agent.state import storyboard_ops as ops
from src.video_agent.state.manager import StateManager
from src.video_agent.state.models import (
    ALL_CATEGORIES_TUPLE,
    CAT_KEY_ELEMENTS,
    CAT_SHOTS,
)

# 执行器工具名集合（skill_runtime 注册；FC 轨据此注入聊天供应商）
_EXECUTOR_TOOL_NAMES = frozenset({
    "script_analyze",
    "storyboard_key_elements",
    "storyboard_shots",
    "storyboard_audio",
    "write_media_prompt",
    "audio_generate",
    "video_assembler",
})
# 关键步骤工具（6666 事故）：这些失败时模型不得声称“已完成/已写入”
_CRITICAL_TOOL_NAMES = frozenset(_EXECUTOR_TOOL_NAMES | {"document_write"})
from src.video_agent.tools.base import ToolResult

# 回喂家族定义源 = core/fc_feedback.py；本文件顶层重新绑定全部符号，
# 既有 import 路径与测试 patch 目标不变（承重壳）。
from src.video_agent.core.fc_feedback import (
    FEEDBACK_COMPRESSED,  # noqa: F401
    FEEDBACK_FULL_TOOLS,  # noqa: F401
    FEEDBACK_IMAGE_TOOL,  # noqa: F401
    FEEDBACK_MARKER,  # noqa: F401
    FEEDBACK_MAX_TOTAL_CHARS,  # noqa: F401
    classify_tool_failure,  # noqa: F401
    compose_failure_feedback,
    compress_prior_feedback,  # noqa: F401
    describe_fc_tool,
    format_tool_results,  # noqa: F401
    render_read_result,  # noqa: F401
    should_compress_feedback,  # noqa: F401
    strip_prior_feedback_images,  # noqa: F401
)


class FCToolRunner:
    """执行 Function Calling 返回的 tool_calls（planner 的 FC 执行臂）"""

    def __init__(self, tool_manager) -> None:
        self.tool_manager = tool_manager
        # 当前对话使用的聊天供应商/模型（决策 E：与主模型一致，
        # 由 chat_service/planner 注入，执行器工具缺省时使用）
        self.chat_provider: str = ""
        self.chat_model: str = ""
        # 用户坚持作用域（False / True / "all" / "element_image"）：覆盖对应闸机
        self.gate_override: Any = False
        # 本批闸机警告（随 execute 返回/时间线可见）
        self.gate_warnings: List[str] = []
        # 0818-1111：本轮同工具失败计数（结构化回喂升级用）
        self._tool_fail_counts: Dict[str, int] = {}
        # 已完成阶段集合（script_analyze 等；总结/收集闸判定用）
        self.skill_stages_done: set = set()
        # Skill 可配置闸机规则（测试/执行器注入 parse_gate_rules 结果）
        self._gate_rules: Optional[Dict[str, Any]] = None
        # 前端当前选中的草稿（对齐文本轨 "current" 语义）；execute 时按请求注入
        self._selected_draft_id = ""
        self._selected_type = ""
        # 闸机校准：(kind+原因签名) 连续相同拦截计数，用于升级重写指引文案
        self._gate_repeat: Dict[str, int] = {}

    # ---------- 提示词结构闸机 ----------

    @staticmethod
    def _raw_state() -> Dict[str, Any]:
        try:
            return StateManager.get_instance().state_dict
        except Exception:
            return {}

    def _resolve_current_refs(self, name: str, args: Dict[str, Any]) -> None:
        """把 FC 工具参数里的 "current"/空 引用解析为真实 id（对齐文本轨语义）：
        前端选中草稿优先，未选中时回落第一个可用对象（与 ops.find_draft 兜底一致）。
        必须在闸机与工具调用之前执行，否则闸机/回写会命中错误的卡片。"""
        if name in ("storyboard_patch_draft", "storyboard_confirm_draft"):
            if str(args.get("draft_id") or "").strip() in ("", "current"):
                found = ops.find_draft(
                    self._raw_state(), "current", str(args.get("draft_type") or ""),
                    selected_draft_id=self._selected_draft_id,
                    selected_type=self._selected_type,
                )
                if found:
                    args["draft_id"] = found[1].get("id") or ""
        elif name == "storyboard_add_draft":
            if str(args.get("group_id") or "").strip() in ("", "current"):
                group = ops.find_group(
                    self._raw_state(), "current", str(args.get("group_type") or ""),
                    selected_draft_id=self._selected_draft_id,
                    selected_type=self._selected_type,
                )
                if group:
                    args["group_id"] = group.get("id") or ""
        elif name == "storyboard_media_to_chat":
            if str(args.get("target") or "").strip() == "current":
                found = ops.find_draft(
                    self._raw_state(), "current", "",
                    selected_draft_id=self._selected_draft_id,
                    selected_type=self._selected_type,
                )
                if found and found[1].get("id"):
                    ids = list(args.get("draft_ids") or [])
                    if found[1]["id"] not in ids:
                        ids.append(found[1]["id"])
                    args["draft_ids"] = ids
                    args["target"] = ""

    def _prompt_gate(self, name: str, args: Dict[str, Any], injected_skill: str) -> Optional[str]:
        """写入前闸机：Skill 流程激活时校验待写入的提示词结构。
        返回非 None = strict 模式硬拒绝（工具不执行，错误文案带回给模型重写）。"""
        if not injected_skill or prompt_gates.gate_mode() == "off":
            return None
        prompt, kind = "", ""
        if name == "storyboard_patch_draft":
            patch = args.get("patch") if isinstance(args.get("patch"), dict) else {}
            prompt = str(patch.get("prompt") or "").strip()
            kind = str(args.get("draft_type") or "").strip()
            if prompt and kind not in ("shot", "keyElement", "audio"):
                kind = prompt_gates.resolve_kind_by_draft_id(
                    self._raw_state(), str(args.get("draft_id") or ""),
                    str(args.get("draft_type") or ""),
                    self._selected_draft_id, self._selected_type,
                )
        elif name in ("storyboard_create_group", "storyboard_add_draft"):
            draft = args.get("draft")
            prompt = str(draft.get("prompt") or "").strip() if isinstance(draft, dict) else ""
            gt = str(args.get("group_type") or "").strip().lower()
            kind = {"keyelement": "keyElement", "shot": "shot", "audio": "audio"}.get(gt, "")
        else:
            return None
        # 客观补全（888 事故）：@引用与镜头时长可从 sceneRefs/duration 算出来，
        # 写入前按 Skill 声明的规则自动补印回待写入参数，不指望模型自觉
        if kind == "shot" and prompt:
            group: Optional[Dict[str, Any]] = None
            if name == "storyboard_patch_draft":
                found = ops.find_draft(
                    self._raw_state(), str(args.get("draft_id") or ""),
                    str(args.get("draft_type") or ""),
                    selected_draft_id=self._selected_draft_id,
                    selected_type=self._selected_type,
                )
                if found:
                    group = found[0]
            else:
                group = {
                    "id": str(args.get("group_id") or ""),
                    "title": str(args.get("title") or ""),
                    "sceneRefs": args.get("sceneRefs") or [],
                    "duration": str(args.get("duration") or ""),
                }
            if group is not None:
                target = patch if name == "storyboard_patch_draft" else draft
                if isinstance(target, dict):
                    filled_refs = prompt_gates.autofill_at_refs(
                        prompt, "shot", group, self._raw_state(), rules=self._gate_rules,
                    )
                    if filled_refs != prompt:
                        target["prompt"] = filled_refs
                        prompt = filled_refs
                    filled_dur = prompt_gates.autofill_shot_duration(
                        prompt, "shot", group, rules=self._gate_rules,
                    )
                    if filled_dur and filled_dur != prompt:
                        target["prompt"] = filled_dur
                        prompt = filled_dur
        if not prompt or kind not in ("shot", "keyElement"):
            return None
        # 故事板待确认窗口（步骤3→步骤4 分界）：流程闸，只警告不拦人
        if prompt_gates.gate_mode() == "strict" \
                and prompt_gates.storyboard_pending(self._raw_state()):
            self.gate_warnings.append(prompt_gates.STORYBOARD_PENDING_GATE_ERROR)
            logger.info("[FlowGate] 提示词写入时故事板待确认（警告，不拦人）")
        # 统一闸机管线（宪法 §2.0 单一组合实现；814R2 恢复接线，与文本轨同源判定）
        outcome = guard_pipeline.evaluate_prompt_write(
            prompt, kind, self._raw_state(),
            gate_rules=self._gate_rules,
            gate_override=self.gate_override,
            element_image_missing=prompt_gates.element_images_missing(self._raw_state()),
        )
        self.gate_warnings.extend(outcome.warnings)
        guard_pipeline.audit_verdicts(
            outcome.verdicts, skill_name=injected_skill, action=name,
            overridden=outcome.overridden,
        )
        if outcome.ok:
            return None
        hard = outcome.hard_errors
        logger.info(f"[PromptGate] 拦截不合格提示词写入（{kind}）: {hard}")
        # 错误日志入账：闸机拦截写入生成日志（顶栏日志面板可见，恢复错误日志可见性）
        try:
            from src.video_agent.web.task_manager import get_task_manager
            get_task_manager().record_gen_log(
                media_type="prompt", status="failed", prompt=prompt,
                error="; ".join(hard), source="agent",
            )
        except Exception:  # 记录失败不影响主链路
            pass
        # 闸机校准：连续相同拦截升级指引，防模型陷入「拦截-重写-再拦截」空转
        sig = f"{kind}|{'|'.join(sorted(hard))}"
        n = self._gate_repeat.get(sig, 0) + 1
        self._gate_repeat[sig] = n
        text = outcome.reject_message
        if n > 1:
            text += (
                f"\n[连续第 {n} 次因相同原因被拦截] 上一次重写未修正上述问题，"
                "请逐条对照原因彻底改写（不是换措辞：中文占比/字数/镜头语言标记必须实质达标），禁止再次提交相似文本。"
            )
        return text

    def _flow_gate(self, name: str, injected_skill: str) -> Optional[str]:
        """规格前置（S1，与文本轨对齐）：只对显式声明 flow.spec_gate 的 Skill
        生效，且不硬拦——规格未写入时追加一条可视线索到操作时间线，
        模型下一轮自行决定补写（用户指令优先）。返回恒 None（不再硬拒绝）。"""
        if not injected_skill or prompt_gates.gate_mode() != "strict":
            return None
        if name not in ("storyboard_create_group", "storyboard_add_draft"):
            return None
        if prompt_gates.has_spec_document(self._raw_state()):
            return None
        declared = False
        try:
            from src.video_agent.skill_runtime.registry import skill_flow_enabled

            declared = skill_flow_enabled(injected_skill, "spec_gate")
        except Exception:
            declared = False
        if not declared:
            return None
        # 814G5：执行侧强制已接管（ensure_spec_gate 拦截越阶工具调用），
        # 此处不再向用户追加 ⚠ 警告（只记日志，模型侧由拦截回喂知晓）
        logger.info(f"[FlowGate] {name}：规格文档未写入（Skill 声明 spec_gate，执行侧门禁生效）")
        return None

    def _strip_structure_prompt(self, name: str, args: Dict[str, Any], injected_skill: str) -> bool:
        """结构纯净闸（步骤3）：Skill 激活且 strict 时，create_group/add_draft 携带的
        内联草稿带提示词时，剥离 prompt 字段
        后放行建结构（不丢分组、不造成虚报），详细提示词留到用户确认后的步骤4。
        返回 True = 发生了剥离（回喂时附说明）。"""
        if not injected_skill or prompt_gates.gate_mode() != "strict":
            return False
        if name not in ("storyboard_create_group", "storyboard_add_draft"):
            return False
        draft = args.get("draft")
        if not isinstance(draft, dict):
            return False
        prompt = str(draft.get("prompt") or "").strip()
        if not prompt:
            return False
        draft["prompt"] = ""
        logger.info(f"[FlowGate] 剥离 {name} 内联详细提示词（{len(prompt)} 字，结构阶段只建骨架）")
        return True

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

    def _gen_confirm_gate(self, name: str, args: Dict[str, Any], injected_skill: str) -> Optional[str]:
        """生成确认闸（FC 轨，B4 双轨收敛一期）：判定唯一实现 =
        guard_pipeline.evaluate_gen_confirm（与文本轨逐字节一致）。"""
        if name != "image_generate":
            return None
        # 0817 一条龙：用户本条消息的显式指令作为本批生成同意（留痕），不弹确认闸
        if prompt_gates.flow_auto_continue(self._raw_state()):
            logger.info("[FlowDirective] 一条龙指令作为本批生成同意（留痕）")
            return None
        state = self._raw_state()
        target = str(args.get("target") or "all_keyElements").strip()
        targets: List[Dict[str, Any]] = []
        if target in ("all_keyElements", "all_keyelements"):
            for g in state.get(CAT_KEY_ELEMENTS, []):
                for d in g.get("drafts", []):
                    if (d.get("prompt") or "").strip():
                        targets.append(d)
        elif target in ("all_shots", "all_shot"):
            for g in state.get(CAT_SHOTS, []):
                for d in g.get("drafts", []):
                    if (d.get("prompt") or "").strip():
                        targets.append(d)
        else:
            for cat in ALL_CATEGORIES_TUPLE:
                for g in state.get(cat, []):
                    for d in g.get("drafts", []):
                        if d.get("id") == target and (d.get("prompt") or "").strip():
                            targets.append(d)
        if not targets:
            return None  # 无目标：交给工具自身报「未找到有提示词的草稿」
        err, warns = guard_pipeline.evaluate_gen_confirm(
            targets,
            active=bool(injected_skill) and prompt_gates.gate_mode() == "strict",
            override=self.gate_override,
            action=name,
        )
        for w in warns:
            if w not in self.gate_warnings:
                self.gate_warnings.append(w)
        if err:
            logger.info(f"[GenGate] 拦截 image_generate：{len(targets)} 个目标草稿存在未确认 Prompt Draft")
        return err

    async def execute(
        self, response: ChatResponse, image_provider: str = "", image_aspect_ratio: str = "",
        on_status=None, on_event=None, injected_skill: str = "",
        selected_draft_id: str = "", selected_type: str = "",
        gate_override: Any = False,
        flow_gates=None,
    ) -> Tuple[int, str, List[str], List[Dict[str, Any]], List[str], List[Dict[str, Any]], List[Dict[str, Any]], List[str], List[str]]:
        """执行 Function Calling 返回的 tool_calls。
        flow_gates（可选，814R3 复活）：Skill 声明式流程门禁，越阶工具调用直接拦截。
        返回 (applied_count, confirmation_message, image_urls, chat_inserts, action_log,
        confirmation_options, tool_results, docs_written, warnings)。
        warnings（B0/F3）：本批闸机拦截/豁免的用户可见文案，由 planner 并入
        loop_result.warnings —— FC 轨与文本轨拦截可见性对齐（§2.0/§2.4）。"""
        self._selected_draft_id = selected_draft_id or ""
        self._selected_type = selected_type or ""
        self.gate_override = gate_override
        self.gate_warnings = []
        # B1/F10-1：对话内单图工具每批调用次数（prose 禁令下沉工具层，13.6 审计清偿）
        self._gen_image_calls = 0
        applied = 0
        confirmation = ""
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
        prompt_stripped = False
        # 本批被提示词闸机拦截的写入次数（防虚报：拦截后暂停文案不得引导确认未写入的提示词）
        prompt_gate_blocked = 0
        # 0817：暂停点归位 Skill 阶段边界——只快照批前是否为空，
        # 批末「故事板阶段完成且模型未暂停」才注入审阅卡（平台不再自加关键元素后暂停）
        skill_strict = bool(injected_skill) and prompt_gates.gate_mode() == "strict"
        storyboard_empty_before = prompt_gates.storyboard_is_empty(self._raw_state())
        # 生成类工具本批成败跟踪（防虚报：同批失败后暂停文案不得声称已触发生成）
        gen_failed_err = ""
        gen_succeeded = False
        # 关键执行器/文档写入成败跟踪（6666：script_analyze/document_write 失败仍声称完成）
        key_tool_failed: List[str] = []
        key_tool_errors: Dict[str, str] = {}
        # 规格写入被向导拒收（8888：拒收后必须接管为规格向导卡，模型不得跳过规格交互）
        spec_write_rejected = False
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
            self._resolve_current_refs(name, args)

            # 执行器工具强制绑定主对话模型（决策 E：与主模型一致；6666 二轮：
            # 模型自行填写 chat_provider/chat_model 一律覆盖，防止串线到其他供应商
            # 导致 429/余额错误，也让「执行器与主模型一致」成为硬约束而非缺省兜底）
            if name in _EXECUTOR_TOOL_NAMES:
                if self.chat_provider:
                    args["chat_provider"] = self.chat_provider
                if self.chat_model:
                    args["chat_model"] = self.chat_model
                # 6666 事故：模型不带 skill_name 时，强制注入系统已确认的当前 Skill，
                # 否则执行器注册检查拿到空名 → 「未指定」未注册
                if not str(args.get("skill_name") or "").strip() and injected_skill:
                    args["skill_name"] = injected_skill

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

            # --- Skill 声明式流程门禁（814R3 复活；R2 收敛：判定经
            # guard_pipeline.evaluate_flow_gate 唯一实现）：拦截越阶工具调用（硬校验，不依赖模型自觉） ---
            if flow_gates is not None:
                gate_op = flow_gates.classify_fc(name, args)
                gate_verdict = guard_pipeline.evaluate_flow_gate(
                    flow_gates, gate_op, self._raw_state(),
                    action_name=name, skill_name=injected_skill,
                )
                if gate_verdict is not None:
                    reason = gate_verdict.message
                    logger.warning(f"[FlowGate] 拦截工具 '{name}': {reason}")
                    # 814G5：拦截对用户透明（结构化 chips 由 record_gate 入 trace，
                    # B2/F13 起不再重复写纯文本 warnings；「本次放行」按钮按结构挂载）
                    if on_event is not None:
                        await on_event({
                            "type": SSE_TOOL_FINISHED,
                            "id": tool_event_id,
                            "ok": False,
                            "elapsed_ms": 0.0,
                            "result_summary": "被流程门禁拦截",
                        })
                    tracer.record_action(name=name, summary="被流程门禁拦截", elapsed_ms=0.0, ok=False)
                    tool_results.append({"name": name, "ok": False, "error": reason})
                    flow_gates.mark_blocked(reason)
                    continue

            # --- 生图模型强制注入（B7）：草稿自身（中间面板直接选择）> 全局设置 > 平台默认 ---
            if name == "generate_image" and (
                "adapter_provider" not in args or args.get("adapter_provider") in ("mock", "", None)
            ):
                from src.video_agent.web.provider_config import spec_media_preference as _spec_pref
                _sp, _sm = _spec_pref(self._raw_state())
                # B7 用户裁决：模型能力参数唯一权威源 = 全局设置；优先级 =
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
            # B7 用户裁决：草稿自身（用户直接选择）> 全局设置 > 平台默认；
            # 防传空导致「供应商 '' 未配置」（8888 事故）---
            if name == "image_generate" and not str(args.get("provider_id") or "").strip():
                from src.video_agent.web.provider_config import spec_media_preference
                spec_pid, spec_model = spec_media_preference(self._raw_state())
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

            # read_skill 短路：选中 Skill 全文已硬注入 system prompt，重复 read 只是
            # 浪费一轮工具往返 + 全文回喂 token（prompt 里的「不要再 read」靠模型自觉，此处硬保障）
            if self._strip_structure_prompt(name, args, injected_skill):
                prompt_stripped = True
            # 闸机链：规格前置 → 生成确认 → 提示词结构/时序
            # （0817：首拆只允关键元素的平台自加警告已清除——流程以 Skill 为准，
            # 客观数据完整性（sceneRefs 引用存在性）由 exec_common 校验兜底）
            gate_error = self._flow_gate(name, injected_skill)
            if gate_error is None:
                gate_error = self._gen_confirm_gate(name, args, injected_skill)
                if gate_error is None:
                    pg_err = self._prompt_gate(name, args, injected_skill)
                    if pg_err:
                        prompt_gate_blocked += 1
                        gate_error = pg_err
            # B1/F10-1：对话内单图工具每批最多一次（prose 下沉工具层，13.6 审计清偿）。
            # 需要多张时模型改用 image_generate 批量工具（两者分工互斥，见 system_fc.md）
            if gate_error is None and name == "generate_image":
                self._gen_image_calls += 1
                if self._gen_image_calls > 1:
                    gate_error = (
                        "generate_image 每轮只调用一次；"
                        "需要多张图片时改用 image_generate 批量工具（明确 target 范围）。"
                    )
            if gate_error is not None:
                result = ToolResult(success=False, error=gate_error)
            elif name == "read_skill" and injected_skill:
                wanted_skill = str(args.get("name") or "").strip()
                if wanted_skill and wanted_skill == injected_skill.strip():
                    result = ToolResult(success=True, data={
                        "content": f"Skill「{wanted_skill}」全文已在本轮 system prompt 中注入，无需重复读取，直接遵循其中的规则即可。",
                        "already_injected": True,
                    })
                    logger.info(f"[Planner] read_skill 短路：「{wanted_skill}」已注入，跳过工具调用")
                else:
                    result = await self.tool_manager.invoke_tool(name, args)
            else:
                result = await self.tool_manager.invoke_tool(name, args)
            _tool_ms = (time.monotonic() - _tool_t0) * 1000
            # 生成类工具成败记录（批末防虚报校验用）
            if name in ("image_generate", "generate_image", "generate_video"):
                if result.success:
                    gen_succeeded = True
                elif not gen_failed_err:
                    gen_failed_err = str(result.error or "执行失败")
            if result.success:
                applied += 1
                self._record_presented(name, args)
                if name in ("storyboard_create_group", "storyboard_add_draft"):
                    structure_created = True
                    kind = prompt_gates.normalize_structure_kind(args.get("group_type") or "")
                    if kind:
                        structure_kinds.add(kind)
                    # 待确认标记即时置位（不等批结束）：同批后续的提示词写入
                    # 会被 _prompt_gate 的 storyboard_pending 检查拦住（防 3+4 合并）
                    if skill_strict:
                        try:
                            svc_now = StateManager.get_instance()
                            inter_now = svc_now.state_dict.setdefault("interaction", {})
                            if not inter_now.get("storyboard_pending"):
                                inter_now["storyboard_pending"] = True
                                svc_now.save()
                        except Exception as _e:
                            logger.debug("[fc_tool_runner] 忽略异常: {}", _e)
                if name == "workflow_pause":
                    confirmation = args.get("message", "请确认以上内容。")
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
                                # B2/F16：选项 value 机械消费
                                if str(o.get("value") or "").strip():
                                    item["value"] = str(o.get("value")).strip()
                                confirmation_options.append(item)
                            elif isinstance(o, str) and o.strip():
                                confirmation_options.append({"label": o.strip(), "description": ""})
                    # 1111 事故：模型自造「1K（更快）」式 label 无法机械落盘，
                    # 同 group 选项替换为标准「键：值」向导（系统永不没收模型的暂停文案）
                    try:
                        from src.video_agent.skill_runtime.registry import spec_wizard_active

                        if spec_wizard_active(injected_skill):
                            _m, _opts, _merged = prompt_gates.merge_spec_param_wizard(
                                self._raw_state(), confirmation, confirmation_options,
                            )
                            if _merged:
                                confirmation, confirmation_options = _m, _opts
                    except Exception as _e:
                        logger.debug("[fc_tool_runner] 忽略异常: {}", _e)
                if name in ("document_write", "write_document"):
                    doc_written = True
                    doc_name = str(args.get("name") or args.get("key") or "").strip()
                    if doc_name:
                        docs_written.append(doc_name)
                        # 3333 修复（B0/F1 恢复四段链）：文档卡片即写即显，不等整轮 done。
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
                    await on_event({
                        "type": SSE_TOOL_FINISHED,
                        "id": tool_event_id,
                        "ok": True,
                        "elapsed_ms": round(_tool_ms, 1),
                        "result_summary": desc,
                    })
                tracer.record_action(name=name, summary=desc, elapsed_ms=_tool_ms, ok=True,
                                     stage=stage_label_for_tool(name))
                tool_results.append({"name": name, "ok": True, "data": result.data})
                if name == "script_analyze":
                    self.skill_stages_done.add("script_analyze")
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
                # --- 0817 B16：执行器成功结果携带的警告（如补拆失败缺失清单）
                # 升级为轮末用户可见警告，不得只留在 trace（静默丢失禁令） ---
                if data and isinstance(data.get("warnings"), list):
                    for _tw in data["warnings"]:
                        _tws = str(_tw or "").strip()
                        if _tws and _tws not in self.gate_warnings:
                            self.gate_warnings.append(_tws)
            else:
                logger.warning(f"[Planner] Tool '{name}' failed: {result.error}")
                if name in _CRITICAL_TOOL_NAMES:
                    key_tool_failed.append(name)
                    key_tool_errors[name] = str(result.error or "执行失败")[:200]
                if name == "document_write" and prompt_gates.is_spec_doc_name(
                    str(args.get("name") or args.get("key") or "")
                ):
                    spec_write_rejected = True
                # 814G3：规格拒收静默——用户侧用中性系统提示（无失败红叉/⚠），
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
                    await on_event({
                        "type": SSE_TOOL_FINISHED,
                        "id": tool_event_id,
                        "ok": bool(spec_silent_summary),
                        "elapsed_ms": round(_tool_ms, 1),
                        "result_summary": spec_silent_summary or str(result.error or "执行失败")[:120],
                    })
                # 0817：trace 与 SSE 同一口径（规格静默拒收=中性 True，普通失败=红× False），
                # 防刷新后失败被重建为绿√
                tracer.record_action(
                    name=name, summary=spec_silent_summary or start_summary,
                    elapsed_ms=_tool_ms, ok=bool(spec_silent_summary),
                    stage=stage_label_for_tool(name),
                )
                # 0818-1111：结构化失败回喂（客观报告+单句建议，二次升级）
                self._tool_fail_counts[name] = self._tool_fail_counts.get(name, 0) + 1
                tool_results.append({
                    "name": name, "ok": False,
                    "error": compose_failure_feedback(
                        name, result.error, self._tool_fail_counts[name],
                    ),
                })
        # 阶段硬边界：写入了规格/阶段文档但模型未自行暂停时，由系统强制暂停等审阅，
        # 不给它顺手把后续阶段（拆结构/写提示词）也打包做完的机会；
        # 写入规格文档时用专属文案（带文档卡片提示与下一步指引）
        if doc_written and not confirmation:
            spec_hit = any(prompt_gates.is_spec_doc_name(n) for n in docs_written)
            if spec_hit:
                confirmation, confirmation_options = prompt_gates.spec_pause_card(self._raw_state())
        # 总结/规格收集闸（层9 兜底）：script_analyze 成功且无规格文档且模型未暂停
        if (
            "script_analyze" in self.skill_stages_done
            and not prompt_gates.has_spec_document(self._raw_state())
            and not confirmation
        ):
            if self.gate_override in ("all", True) or prompt_gates.flow_auto_continue(self._raw_state()):
                self.gate_warnings.append("用户已要求全速推进，已豁免规格收集暂停（仅附警告）")
            else:
                confirmation, confirmation_options = prompt_gates.spec_collect_card(self._raw_state())
                logger.info("[FlowGate] FC script_analyze 完成且无规格文档，注入规格收集向导")
        # 0817：暂停点归位 Skill 阶段边界（13.3/C6，用户裁决）：
        # 平台不再「关键元素首建后硬暂停」；仅当本批把故事板推进到阶段完成
        # （Skill 声明的组别齐）且模型未自行暂停时，注入审阅卡；
        # 模型自发暂停一律保留其文案与选项（平台不覆盖）。
        if (
            not confirmation
            and skill_strict
            and storyboard_empty_before
            and not prompt_gates.flow_auto_continue(self._raw_state())
            and prompt_gates.storyboard_stage_complete(self._raw_state(), injected_skill)
        ):
            confirmation, confirmation_options = prompt_gates.structure_paused_confirmation(
                structure_kinds or prompt_gates.present_structure_kinds(self._raw_state()))
            logger.info("[FlowGate] 故事板阶段完成且模型未暂停，注入审阅卡")
        # 结构阶段剥离了内联详细提示词：回喂中显式告知，防止模型虚报「提示词已写好」
        if prompt_stripped:
            tool_results.append({
                "name": "系统闸机",
                "ok": False,
                "error": (
                    "结构搭建阶段只建骨架：内联草稿中的详细提示词已被剥离，当前草稿无提示词（事实）。"
                    "请等用户确认故事板后，再用 storyboard_patch_draft 逐条编写提示词草案；"
                    "向用户陈述需与此一致。"
                ),
            })
        # 防虚报硬拦截（8888 事故）：同批生成类工具失败但模型暂停文案声称已触发/已生成
        # → 覆盖为诚实文案（对齐文本轨 gate_heal 的「拦截后不接受虚报」原则）
        if gen_failed_err and not gen_succeeded and confirmation:
            _claim_markers = (
                "已触发", "已为您触发", "开始生成", "正在生成", "生成中",
                "已生成", "已完成", "生成完毕", "出图进度",
            )
            if any(mk in confirmation for mk in _claim_markers):
                logger.warning("[Planner] 防虚报拦截：生成工具失败但暂停文案声称已触发，已覆盖为诚实文案")
                confirmation = (
                    "出图尚未执行：本次生成被系统闸机拦截（"
                    f"{gen_failed_err[:80]}）。提示词草案已就绪，请在左侧故事板审阅；"
                    "确认后我将按全局设置中的生成渠道触发生成。"
                )
                confirmation_options = [{
                    "label": "确认提示词草案，开始生成概念图",
                    "description": "将目标草稿标记为已确认并重新触发生成",
                }, {
                    "label": "先调整提示词",
                    "description": "告诉我需要修改的草稿与修改意见",
                }]
        # 暂停防虚报（问题2）：本批有提示词写入被质量闸拦截（未写入卡片），
        # 模型却仍暂停引导用户「确认提示词」→ 覆盖为诚实文案
        # （对齐生成失败防虚报闸；结构刚建立时已由上方结构暂停文案接管，不重复覆盖）
        if prompt_gate_blocked and confirmation and not structure_created:
            logger.warning(f"[Planner] 暂停防虚报：{prompt_gate_blocked} 条提示词写入被拦，覆盖暂停文案")
            confirmation = (
                f"部分提示词写入被系统质量闸拦截（{prompt_gate_blocked} 条未通过校验、未写入卡片），"
                "请先在左侧故事板审阅已成功写入的草案；确认后我将按 Skill 规范重写被拦截的提示词并再次请您确认。"
            )
            confirmation_options = [{
                "label": "确认已写入的草案，继续重写被拦截的提示词",
                "description": "把已审阅草案标记为已确认，并重写被闸机拦截的提示词",
            }, {
                "label": "先调整提示词",
                "description": "告诉我需要修改的草稿与修改意见",
            }]
        # 8888 事故：规格写入被向导拒收 → 系统接管为规格向导卡（与文本轨一致），
        # 模型不得用「请求阶段确认」跳过规格交互，也不得声称已生成规格
        if spec_write_rejected:
            _spec_state = self._raw_state()
            inter = _spec_state.setdefault("interaction", {})
            took_over = False
            if "script_analyze" in key_tool_failed:
                # 6666 二轮：剧本分析本身失败（如 API 余额不足/超时）时，
                # 不能装成已读完剧本弹规格向导，必须把失败原因明确交给用户
                _err = key_tool_errors.get("script_analyze", "执行失败")
                confirmation = (
                    f"剧本分析未完成（执行失败）：{_err}。"
                    "规格尚未交互与写入，请重试剧本分析；不要声称已完成或已生成规格。"
                )
                confirmation_options = [{
                    "label": "重试剧本分析",
                    "description": "重新执行 script_analyze（已绑定当前对话模型）",
                }]
                inter["pending_pause_kind"] = ""
                took_over = True
            elif prompt_gates.spec_doc_finalized(_spec_state):
                # 8888 二轮：规格已定稿时模型的冗余手写只拒收警告，
                # 不接管暂停卡——拆解阶段的阶段卡正常出现，不再叫用户确认规格
                logger.info("[Planner] 规格已定稿，模型冗余规格写入仅拒收警告，不接管暂停卡")
            else:
                confirmation, confirmation_options = prompt_gates.spec_pause_card(_spec_state)
                inter["pending_pause_kind"] = "spec"
                took_over = True
            if took_over:
                try:
                    # 8888 二轮：接管时必须同时洗掉 workflow_pause 写入的假完成文案，
                    # 否则下一轮会把「已完成…写入项目文档」当作暂停内容回喂给模型
                    inter["awaiting_confirmation"] = True
                    inter["confirmation_message"] = confirmation
                    StateManager.get_instance().save()
                except Exception as _e:
                    logger.warning("[Planner] 规格接管暂停态落盘失败（下轮可能重复接管）: {}", _e)
                logger.warning("[Planner] 规格写入被向导拒收，已接管为规格向导卡")

        # 6666/8888 事故：关键执行器/文档写入存在失败且模型带确认声称完成 → 覆盖为诚实文案
        # （部分成功、部分失败同样覆盖，堵住「script_analyze 成功就放行假规格文案」的盲区）
        if confirmation and key_tool_failed and not spec_write_rejected:
            # B2/F23：失败工具名映射为用户友好名（内部英文名不出现在用户文案）
            _failed = "、".join(
                dict.fromkeys(stage_label_for_tool(n) or n for n in key_tool_failed)
            )[:160]
            logger.warning(f"[Planner] 关键步骤防虚报：{_failed} 失败但模型声称完成，已覆盖")
            confirmation = (
                f"关键步骤未全部完成：{_failed} 执行失败，工作台状态未按预期更新；"
                "请按系统提示重试，不要声称已完成。"
            )
            confirmation_options = [{
                "label": "重试",
                "description": "重新执行未完成的关键步骤（Skill 绑定/执行器/规格向导已就绪）",
            }]
        return applied, confirmation, image_urls, chat_inserts, action_log, confirmation_options, tool_results, docs_written, list(self.gate_warnings)
