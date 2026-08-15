"""
Agent 多步执行循环（Rule2: 唯一实现）。

位于 core 层（P1-1 层级理顺：编排骨架属核心层，不再放 web/；
web/agent_loop.py 保留为 DEPRECATED 兼容 re-export）。

单轮「LLM → 解析 actions → 执行」升级为有界循环（最多 max_steps 轮）：
LLM 可以在 studio-actions 末尾输出 {"action": "continue"} 请求下一轮，
系统执行本轮操作后刷新上下文再次调用，直到 LLM 不再请求继续或达到上限。

llm_call / context_builder 以 callable 注入，便于单元测试。
"""
from dataclasses import dataclass, field
import re
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Dict, List, Optional, Tuple, Union

import time

from loguru import logger

from src.video_agent.config import settings
from src.video_agent.core import prompt_gates
from src.video_agent.core.sse_events import (
    SSE_ACTIONS_APPLIED,
    SSE_DOC_WRITTEN,
    SSE_EXECUTING_ACTIONS,
    SSE_STATUS,
    SSE_STEP_STARTED,
    SSE_TOOL_FINISHED,
    SSE_TOOL_STARTED,
)
from src.video_agent.core.tracer import AgentTracer
from src.video_agent.skill_runtime.registry import fallback_skill_from_state, stage_label_for_tool

if TYPE_CHECKING:
    # 仅类型标注用：执行器实现依赖 web 层生成管线，运行时不做硬依赖
    from src.video_agent.web.action_executor import StudioActionExecutor

MAX_STEPS = settings.max_steps

# llm_call(system_prompt, messages, stream_hook?) -> (content, finish_reason, fc_applied[, plan_ms])
# fc_applied: FC 路径已执行的 tool 数量（可选，默认 0）
# plan_ms: 纯模型规划耗时（可选；缺省 0，兼容旧 3 元组实现/测试桩）
# stream_hook: 可选流式增量回调，每段文本 await stream_hook(text)
LlmCall = Callable[..., Awaitable[Tuple[str, str, int, float]]]
# context_builder() -> 最新的 system prompt（协议 + 实时状态）
ContextBuilder = Callable[[], str]


def _unpack_llm(ret: Tuple) -> Tuple[str, str, int, float]:
    """解包 llm_call 返回值：4 元组 (content, finish, fc_applied, plan_ms)；
    旧 3 元组实现 plan_ms 记 0（测试桩兼容）。"""
    plan = float(ret[3]) if len(ret) > 3 else 0.0
    return str(ret[0]), str(ret[1]), int(ret[2]), plan


@dataclass
class AgentLoopResult:
    text: str = ""
    applied_actions: int = 0
    steps: int = 0
    warnings: List[str] = field(default_factory=list)
    # LLM 通过 request_confirmation 请求用户确认时的说明文字（非空表示等待确认）
    confirmation: str = ""
    # 确认卡片的候选选项（每项 {label, description}，前端渲染为单选卡片）
    confirmation_options: List[Dict[str, Any]] = field(default_factory=list)
    # 执行轨迹（每轮 step/耗时/操作数/finish_reason），前端「执行轨迹」折叠区展示
    trace: Dict[str, Any] = field(default_factory=dict)


def split_actions(actions: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], bool, str, List[Dict[str, Any]]]:
    """分离流程信号，返回 (可执行的 actions, 是否请求下一轮, 确认请求文案, 确认候选选项)"""
    executable: List[Dict[str, Any]] = []
    wants_continue = False
    confirmation = ""
    confirmation_options: List[Dict[str, Any]] = []
    confirm_names = ("request_confirmation", "confirm", "confirmation", "pause", "workflow_pause")
    for a in actions:
        name = str(a.get("action") or a.get("tool") or a.get("type") or "").lower()
        if name == "continue":
            wants_continue = True
        elif name in confirm_names or "confirmation" in a or "request_confirmation" in a:
            confirmation = (
                _extract_confirmation(a)
                or str(a.get("confirmation") or a.get("request_confirmation") or "").strip()
                or "请确认以上内容，确认后我将继续。"
            )
            opts = a.get("options") or []
            if not isinstance(opts, list):
                opts = []
            for o in opts:
                if isinstance(o, dict) and str(o.get("label") or "").strip():
                    item = {
                        "label": str(o.get("label")).strip(),
                        "description": str(o.get("description") or "").strip(),
                    }
                    if str(o.get("group") or "").strip():
                        item["group"] = str(o.get("group")).strip()
                    # B2/F16：选项 value 机械消费（点击即发送 value，后端确定性处理）
                    if str(o.get("value") or "").strip():
                        item["value"] = str(o.get("value")).strip()
                    confirmation_options.append(item)
                elif isinstance(o, str) and o.strip():
                    confirmation_options.append({"label": o.strip(), "description": ""})
        else:
            executable.append(a)
    return executable, wants_continue, confirmation, confirmation_options


def _extract_confirmation(action: Dict[str, Any]) -> str:
    """从动作里提取暂停确认文案（兼容 tool/type 键与 message/confirmation 字段）。"""
    if not isinstance(action, dict):
        return ""
    name = str(action.get("action") or action.get("tool") or action.get("type") or "").lower()
    if name not in ("request_confirmation", "confirm", "confirmation", "pause", "workflow_pause"):
        return ""
    return str(action.get("message") or action.get("confirmation") or "").strip()


# 防虚报：模型在未真实执行结构操作时声称「已拆解/已建组/已写入故事板」。
# 每段独立判定（跨文本拼接不误报）；含未来/预告措辞（确认后/接下来/之后…）
# 一律不算声称（4444 误伤措辞豁免）。
_STRUCTURE_CLAIM_RE = re.compile(
    r"(?:已完成|完成|已创建|已拆解|已写入)\s*(?:关键元素)?(?:拆解|拆分|分组|故事板)"
    r"|(?:关键元素)?(?:拆解|拆分)完成|已创建\s*\d+\s*个分组并写入故事板",
)
_FUTURE_MARKER_RE = re.compile(r"确认后|接下来|之后|即将|下一步|先确认|先将")


def _claims_structure_done(*texts: str) -> bool:
    """判定文本是否声称已完成故事板结构搭建（防虚报闸的文本检测）。

    - 每个文本段独立判定（2222 事故：正文结尾与暂停文案开头跨文本拼接不得误报）；
    - 含未来/预告措辞的段落不算声称（4444 误伤措辞豁免）。
    """
    for t in texts:
        text = str(t or "")
        if _FUTURE_MARKER_RE.search(text):
            continue
        if _STRUCTURE_CLAIM_RE.search(text):
            return True
    return False


# 向后兼容别名
_split_actions = split_actions


# 自检回喂模板（888 事故：拆解覆盖完整性的表述源在铁律第 2 条）
SELF_CHECK_FEEDBACK = "（系统）自检提醒：拆解需覆盖完整（按《执行铁律》第 2 条自检核对）。"


def _compact_old_step_feedback(messages: List[Dict[str, Any]], keep_pairs: int = 2) -> int:
    """轮内 compaction（C3）：把超过最近 keep_pairs 轮的「工具已执行完毕」反馈
    折叠为摘要，旧 assistant 轮次原地压缩；用户消息与首条消息不碰。

    返回被折叠的反馈条数。
    """
    if not messages:
        return 0
    feedback_idx = [
        i for i, m in enumerate(messages)
        if isinstance(m.get("content"), str)
        and m.get("content", "").startswith("（系统）第")
        and "已执行完毕" in m.get("content", "")
    ]
    if len(feedback_idx) <= keep_pairs:
        return 0
    collapse = feedback_idx[:-keep_pairs]
    for i in collapse:
        # 压缩其紧邻的前一条 assistant 轮次（保留用户引导与首条用户消息）
        if i > 0 and messages[i - 1].get("role") == "assistant":
            messages[i - 1] = {
                **messages[i - 1],
                "content": "（历史轮次摘要：该轮工具反馈已折叠，详情以当前工作台状态为准）",
            }
    # 移除被折叠的反馈消息本身
    for i in sorted(collapse, reverse=True):
        messages.pop(i)
    return len(collapse)


async def run_agent_loop(
    user_text: Union[str, List[Dict[str, Any]]],
    *,
    llm_call: LlmCall,
    context_builder: ContextBuilder,
    executor: "StudioActionExecutor",
    history: List[Dict[str, Any]],
    max_steps: int = MAX_STEPS,
    on_event=None,
    stream_hook: Optional[Callable[[str], Awaitable[None]]] = None,
    prelude_notes: Optional[List[tuple]] = None,
    pending_injector: Optional[Callable[[], List[Dict[str, Any]]]] = None,
    flow_gates=None,
    user_id: str = "",
) -> AgentLoopResult:
    """on_event（可选）：async callable，接收 {"type": "step_started"/"actions_applied", ...}
    stream_hook（可选）：流式文本增量回调，每收到一段 LLM 文本就 await stream_hook(text)。
    user_text 可以是纯文本 str，也可以是多模态 content parts 列表（含 image_url）。
    flow_gates（可选，814R3 复活）：Skill 声明式流程门禁（FlowGateSet）；
    越阶操作被拦截后本轮强制补发确认暂停，不依赖模型自觉。
    """

    async def emit(event: Dict[str, Any]) -> None:
        if on_event:
            try:
                await on_event(event)
            except Exception:
                pass

    result = AgentLoopResult()
    messages: List[Dict[str, Any]] = list(history) + [{"role": "user", "content": user_text}]
    structure_self_check_pending = False
    structure_self_check_round = 0
    # B0/F1：文本轨已发射过 doc_written 的文档名（防重复发射；FC 轨在 fc_tool_runner 内发射）
    _emitted_docs: set = set()

    def _wizard_active() -> bool:
        """当前 Skill 是否启用规格向导（manifest/正文客观检测，S1 单一事实源）。"""
        try:
            from src.video_agent.skill_runtime.registry import spec_wizard_active

            return bool(spec_wizard_active(skill))
        except Exception:
            return False

    skill = str(getattr(executor, "skill_name", "") or "")
    if not skill:
        # 7777 事故：请求未携带 Skill 时回退项目 usedSkills 末位（单一实现）
        skill = fallback_skill_from_state(getattr(executor, "state", None) or {})
    selected_skills = list((getattr(executor, "state", None) or {}).get("usedSkills") or [])

    # 链路追踪：记录本次对话执行过程
    tracer = AgentTracer.get_instance()
    user_preview = user_text if isinstance(user_text, str) else str(user_text)[:80]
    tracer.start_trace(user_preview, user_id=user_id)

    # 814G8 恢复：执行器进度通道双轨接线（统一循环级绑定，FC/文本轨同覆盖）。
    # 执行器内部批次边界（emit_timeline_note/emit_state_refresh/emit_progress）
    # 经此通道实时推时间线子项与故事板刷新——卡片一张张流式亮，不再结束才一把出现。
    # contextvar 任务级隔离：异常路径随任务消亡，正常路径在循环结束后解绑。
    from src.video_agent.skill_runtime.progress import (
        bind_progress_emitter,
        unbind_progress_emitter,
    )
    _progress_token = bind_progress_emitter(emit)

    for step in range(1, max_steps + 1):
        result.steps = step
        tracer.start_step()
        if step == 1:
            # 前奏明细（Q8）：读 Skill/文档等准备动作记入第一步时间线
            # （814G2：同时发 live 事件，运行中视图与持久化视图同条目）
            for pi, (name, summary) in enumerate(prelude_notes or []):
                tracer.record_action(str(name), str(summary), 0.0, True)
                pid = f"pre-{pi}"
                await emit({"type": SSE_TOOL_STARTED, "id": pid, "name": str(name), "summary": str(summary)})
                await emit({"type": SSE_TOOL_FINISHED, "id": pid, "ok": True, "elapsed_ms": 0.0, "result_summary": str(summary)})
        await emit({"type": SSE_STEP_STARTED, "step": step, "max_steps": max_steps})
        if step > 1:
            # 多轮循环"静默期"提示：上一轮工具执行完到本轮首 token 之间可能耗时数十秒，
            # 前端状态栏需明确告知正在进行第几轮思考（status 事件全链路已透传）
            await emit({
                "type": SSE_STATUS,
                "text": f"第 {step - 1} 轮操作已完成，继续思考中（第 {step}/{max_steps} 轮）…",
            })
        # 轮间注入（7777 三轮）：任务执行期间收到的用户引导消息在上一轮操作完成、
        # 本轮 LLM 调用之前送达；首轮尚无操作可打断，一律不注入
        if step > 1 and pending_injector is not None:
            try:
                pending_items = pending_injector() or []
            except Exception:
                pending_items = []
            for item in pending_items:
                gid = str(item.get("id") or "")
                gtext = str(item.get("text") or "").strip()
                if not gtext:
                    continue
                messages.append({
                    "role": "user",
                    "content": (
                        f"（任务执行期间收到您的指令：{gtext}）"
                        "请优先处理；若为提问先回答，处理完继续原任务。"
                    ),
                })
                await emit({
                    "type": "guidance_injected",
                    "id": gid,
                    "text": gtext,
                })
        system_prompt = context_builder()  # 每轮刷新，让 LLM 看到上一轮执行后的最新状态

        # 过程时间线：模型推理轮本身也作为操作条目可见（读文档/调执行器之外的“思考”动作）
        await emit({
            "type": SSE_TOOL_STARTED,
            "id": f"llm-s{step}",
            "name": "model_reasoning",
            "summary": f"Agent 正在规划本步动作（第 {step} 轮）",
        })
        # 814G2：规划条目先占位入 trace（保证持久化顺序 = live 顺序：规划→工具），
        # 耗时在 llm_call 返回后补填
        _plan_rec = tracer.record_action(
            "model_reasoning", f"Agent 正在规划本步动作（第 {step} 轮）", 0.0, True,
        )
        content, finish_reason, fc_applied, plan_ms = _unpack_llm(
            await llm_call(system_prompt, messages, stream_hook)
        )
        plan_total = float(plan_ms or 0.0)

        # 空/畸形响应防护：空响应或 MALFORMED_FUNCTION_CALL 连续发生 → 重试至多 2 次，
        # 达到上限后以明确故障文案收尾（不再静默落为「没有返回可见回复」）。
        bad_retries = 0
        while not str(content or "").strip() and fc_applied == 0 and bad_retries < 2:
            bad_retries += 1
            logger.warning(f"[AgentLoop] 第 {step} 轮输出异常（空/畸形），重试 {bad_retries}/2")
            await emit({"type": SSE_STATUS, "text": f"第 {step} 轮输出异常，重试中…"})
            tracer.record_action(
                name="auto_retry",
                summary=f"模型输出异常（空/畸形），自动重做（第 {bad_retries} 次）",
                elapsed_ms=0.0,
                ok=True,
            )
            content, finish_reason, fc_applied, plan_ms = _unpack_llm(
                await llm_call(system_prompt, messages, stream_hook)
            )
            plan_total += float(plan_ms or 0.0)
        # 规划耗时只算纯模型规划（2222 反馈）：FC 工具执行时间由各工具条目独立展示，
        # 不再把工具耗时叠进规划行导致「规划很慢」的错觉
        await emit({
            "type": SSE_TOOL_FINISHED,
            "id": f"llm-s{step}",
            "ok": True,
            "elapsed_ms": round(plan_total, 1),
            "result_summary": f"Agent 规划完成（第 {step} 轮）",
        })
        _plan_rec["elapsed_ms"] = round(plan_total, 1)
        if bad_retries == 2 and not str(content or "").strip() and fc_applied == 0:
            result.text = "输出异常：模型连续返回空/畸形输出，已重试 2 次；请重试或检查模型配置。"
            result.warnings.append("模型连续 3 次输出异常（空/畸形），已终止本轮")
            tracer.end_step(step, actions_applied=0, finish_reason="bad_output")
            break

        # Skill 声明式流程门禁（814R3 复活，FC 轨）：本轮有越阶拦截 → 强制补发确认暂停
        if flow_gates is not None:
            fc_gate_blocked = flow_gates.consume_blocked()
            if fc_gate_blocked:
                result.confirmation = flow_gates.pause_message()
                visible_fc = str(content or "").strip()
                if visible_fc:
                    result.text = visible_fc
                await emit({"type": SSE_STATUS, "text": "越阶操作被流程门禁拦截，已强制暂停"})
                tracer.end_step(step, actions_applied=fc_applied, finish_reason="gate_pause")
                break

        if finish_reason == "length":
            result.warnings.append(
                f"第 {step} 轮回复被 max_tokens 截断，studio-actions 可能不完整"
            )

        # FC 路径：tool_calls 已在 llm_call 内部执行，跳过文本解析
        if fc_applied > 0:
            result.applied_actions += fc_applied
            await emit({"type": SSE_ACTIONS_APPLIED, "step": step, "count": fc_applied})
            visible = content.strip()
            if visible:
                result.text = f"{result.text}\n\n{visible}".strip() if result.text else visible
            logger.info(
                f"[AgentLoop] step={step} fc_applied={fc_applied} "
                f"confirm=False finish={finish_reason or '-'}"
            )
            # P2-6 提前终止：模型明确 stop 且已产出可见文本 → 任务已完成，
            # 不再固定追加一轮 LLM 总结调用（finish=tool_calls 或无文本时保留多步链）
            if finish_reason in ("stop", "end_turn") and visible:
                tracer.end_step(step, actions_applied=fc_applied, finish_reason="fc_done")
                break
            if step == max_steps:
                result.warnings.append(f"已达到多步上限（{max_steps} 轮），循环终止")
                tracer.end_step(step, actions_applied=fc_applied, finish_reason="max_steps")
                break
            tracer.end_step(step, actions_applied=fc_applied, finish_reason=finish_reason or "fc_continue")
            # 回喂：让下一轮 LLM 知道工具已执行
            messages.append({"role": "assistant", "content": content or f"（已执行 {fc_applied} 个工具调用）"})
            messages.append({
                "role": "user",
                "content": (
                    f"（系统）第 {step} 轮的 {fc_applied} 个 Tool 已执行完毕，工作台状态已刷新到 system prompt。"
                    "请继续完成任务；全部完成后直接回复文本即可。"
                ),
            })
            continue

        # 文本解析路径（非 FC 模型的 fallback）
        actions = executor.parse_actions_from_reply(content)
        if not actions and executor.has_action_block(content):
            result.warnings.append(
                f"第 {step} 轮的 studio-actions 块解析失败（JSON 无效或被截断），本轮操作已丢弃"
            )

        executable, wants_continue, confirmation, confirmation_options = _split_actions(actions)
        # Skill 声明式流程门禁（814R3 复活，文本轨）：执行前逐个校验，越阶操作直接剔除并记录拦截
        if executable and flow_gates is not None:
            _gate_state = getattr(executor, "state", None) or {}
            kept: List[Dict[str, Any]] = []
            for gi, action in enumerate(executable):
                gop = flow_gates.classify_action(action)
                gok, gmissing = flow_gates.check_op(gop, _gate_state)
                if gok:
                    kept.append(action)
                    continue
                greason = flow_gates.block_reason(gop, gmissing)
                # B2/F13：拦截原因已由 record_gate 入 trace（前端渲染结构化 chips），
                # 不再重复写入纯文本 warnings（避免同屏双显）
                flow_gates.mark_blocked(greason)
                tracer.record_action(
                    name=str(action.get("action", "")), summary="被流程门禁拦截",
                    elapsed_ms=0.0, ok=False,
                )
                tracer.record_gate(
                    "skill.flow.checkpoint", "skill", False,
                    action=str(action.get("action", "")), message=greason,
                )
                await emit({
                    "type": SSE_TOOL_FINISHED, "id": f"s{step}-gate{gi}",
                    "ok": False, "elapsed_ms": 0.0,
                    "result_summary": "被流程门禁拦截",
                })
            executable = kept
        # 模型自发暂停 + 规格参数未定稿：把模型自造 label 并入标准「键：值」向导
        # （1111 事故：自造「1K（更快）」无法机械落盘；系统永不没收模型的暂停文案）
        if confirmation and _wizard_active():
            try:
                _m, _opts, _merged = prompt_gates.merge_spec_param_wizard(
                    executor.state, confirmation, confirmation_options,
                )
                if _merged:
                    confirmation, confirmation_options = _m, _opts
            except Exception:
                pass
        # 规格向导闸机（S1）：声明 spec_wizard 的 Skill，规格文档由系统按向导
        # 拼装，模型手写规格一律不落盘，改为系统规格收集/审阅暂停卡
        spec_wizard_pending = False
        if executable:
            try:
                # 拒收仅对「真实选中」的 Skill 生效（4444）：无 usedSkills 时
                # 模型手写规格照常落盘，避免引擎预设流程误伤
                if _wizard_active() and skill in selected_skills:
                    spec_writes = [
                        a for a in executable
                        if str(a.get("action", "")).lower()
                        in ("write_document", "write_doc", "save_document", "document_write")
                        and prompt_gates.is_spec_doc_name(
                            str(a.get("name") or a.get("title") or "")
                        )
                    ]
                    if spec_writes:
                        executable = [a for a in executable if a not in spec_writes]
                        if prompt_gates.spec_doc_finalized(executor.state):
                            # 8888 二轮：规格已定稿 → 冗余手写只拒收，不接管暂停卡；
                            # 814G3：拒收只喂模型（下轮上下文），不再作为 ⚠ 展示给用户
                            messages.append({"role": "user", "content": (
                                "（系统）规格文档已定稿，你本次的冗余规格写入已被拒收（未落盘）；"
                                "如需调整规格请引导用户在文档面板修改，不要重复手写。")})
                        else:
                            spec_wizard_pending = True
                            # 814G3：接管静默——用户只看到随后的向导卡，不看报错
                            messages.append({"role": "user", "content": (
                                "（系统）规格文档由系统按向导拼装，你手写的规格未落盘；"
                                "请立即暂停，等待用户完成规格交互。向用户陈述需与此一致：本轮未写入规格。")})
            except Exception:
                spec_wizard_pending = False
        # 本轮全部可执行操作数（含流式已预执行部分）：gate_heal 判定用
        total_exec = len(executable)
        # 流式增量执行（边写边填）：planner 流式路径已逐条预执行的动作
        # 计入已应用并从待执行列表剔除，严禁重复执行（add_group 重复会建重分组）
        stream_consumed = int(getattr(executor, "stream_consumed", 0) or 0)
        stream_preapplied = int(getattr(executor, "stream_preapplied", 0) or 0)
        if stream_consumed:
            executable = executable[stream_consumed:]
            executor.stream_consumed = 0
            executor.stream_preapplied = 0
            logger.info(
                f"[AgentLoop] step={step} 流式边写边填已预执行 {stream_preapplied}/{stream_consumed} 个操作"
            )
        if executable:
            await emit({"type": SSE_EXECUTING_ACTIONS, "step": step, "count": len(executable)})
            # 过程时间线：逐个预告即将执行的操作（前端渲染运行态条目）
            for i, action in enumerate(executable):
                aname = str(action.get("action", "") or "")
                try:
                    preview = executor._describe_action(action)
                except Exception:
                    preview = aname
                await emit({
                    "type": SSE_TOOL_STARTED,
                    "id": f"s{step}-{i}",
                    "name": aname,
                    "summary": preview,
                })
        _log_before = len(executor.action_log)
        _t0 = time.monotonic()
        # 文本轨异步执行器动作（script_analyze/storyboard_* 等）走 execute_async
        # （独立 LLM 调用 + 结构化校验）；其余走同步 execute_locked
        if any(executor._is_async_action(a) for a in executable):
            applied = await executor.execute_async_locked(
                executable, accumulate=stream_consumed > 0,
            )
        else:
            applied = await executor.execute_locked(executable, accumulate=stream_consumed > 0)
        # 阶段账本：script_analyze 成功 → 标记已完成（总结/收集闸判定）
        if applied > 0 and any(
            str(a.get("action") or a.get("tool") or "").strip() == "script_analyze"
            for a in executable
        ):
            getattr(executor, "skill_stages_done", set()).add("script_analyze")
        applied += stream_preapplied  # 流式预执行成功数计入本轮应用量
        _batch_ms = (time.monotonic() - _t0) * 1000
        result.applied_actions += applied
        if applied:
            await emit({"type": SSE_ACTIONS_APPLIED, "step": step, "count": applied})
        # B0/F1：文本轨文档卡片即写即显（3333 修复四段链：发射 → planner 白名单 →
        # chat_service 透传 → 前端 handler；FC 轨由 fc_tool_runner 发射）
        for dn in (getattr(executor, "documents_written", None) or []):
            if dn and dn not in _emitted_docs:
                _emitted_docs.add(dn)
                await emit({"type": SSE_DOC_WRITTEN, "name": str(dn)})
        # 推理过程可视化：实时把本轮刚完成的操作描述推给前端状态栏 + 时间线
        new_logs = executor.action_log[_log_before:]
        if new_logs:
            await emit({"type": SSE_STATUS, "text": "已完成：" + "；".join(new_logs[-3:])})
        for i, desc in enumerate(new_logs):
            per_ms = _batch_ms / len(new_logs) if new_logs else 0.0
            # B2/F21：按动作实测耗时（文本轨此前均摊是白谎；执行器逐动作计时，
            # 缺失时回落均摊）
            _durations = getattr(executor, "last_action_durations", None) or []
            if i < len(_durations):
                per_ms = _durations[i]
            await emit({
                "type": SSE_TOOL_FINISHED,
                "id": f"s{step}-{i}",
                "ok": True,
                "elapsed_ms": round(per_ms, 1),
                "result_summary": desc,
            })
            tracer.record_action(
                name=str(executable[i].get("action", "")) if i < len(executable) else "",
                summary=desc, elapsed_ms=per_ms, ok=True,
                stage=stage_label_for_tool(str(executable[i].get("action", ""))) if i < len(executable) else "",
            )
        # 部分操作未成功（未匹配到目标/执行异常）：剩余条目补发失败态，
        # 避免前端时间线条目永远停在「运行中」
        if len(new_logs) < len(executable):
            for i in range(len(new_logs), len(executable)):
                action = executable[i]
                await emit({
                    "type": SSE_TOOL_FINISHED,
                    "id": f"s{step}-{i}",
                    "ok": False,
                    "elapsed_ms": 0.0,
                    "result_summary": "未匹配到目标或执行失败",
                })
                tracer.record_action(
                    name=str(action.get("action", "")),
                    summary="未匹配到目标或执行失败", elapsed_ms=0.0, ok=False,
                    stage=stage_label_for_tool(str(action.get("action", ""))),
                )
        gate_rejections = list(getattr(executor, "gate_rejections", None) or [])
        # Skill 声明式流程门禁（814R3 复活，文本轨）：本轮有拦截 → 强制补发确认暂停
        if flow_gates is not None:
            txt_gate_blocked = flow_gates.consume_blocked()
            if txt_gate_blocked:
                result.confirmation = confirmation or flow_gates.pause_message()
                result.confirmation_options = []
                visible_txt = executor.strip_action_blocks(content)
                if visible_txt:
                    result.text = f"{result.text}\n\n{visible_txt}".strip() if result.text else visible_txt
                await emit({"type": SSE_STATUS, "text": "越阶操作被流程门禁拦截，已强制暂停"})
                tracer.end_step(step, actions_applied=applied, finish_reason="gate_pause")
                break
        if total_exec and applied < total_exec:
            if gate_rejections:
                result.warnings.append(
                    f"第 {step} 轮有 {total_exec - applied} 个操作被流程闸机拦截"
                    f"（原因：{gate_rejections[0][:60]}…）"
                )
            elif stream_consumed == 0:
                failed_desc = ""
                try:
                    failed_desc = "；".join(
                        executor._describe_action(a) for a in executable[applied:][:3]
                    )
                except Exception:
                    failed_desc = ""
                result.warnings.append(
                    f"第 {step} 轮有 {total_exec - applied} 个操作未执行成功"
                    + (f"（{failed_desc}）" if failed_desc else "（目标不存在或执行失败）")
                )

        # 流程闸机自愈（对齐 Tool 模式错误回传闭环）：本轮有操作被闸机拦截（全部或
        # 部分）时，不接受本轮文本自带的暂停信号——模型常同时虚报「已写入/已创建 N 组」，
        # 直接暂停会把虚假成功展示给用户（8888 事故：9 条提示词写入 8 条被拦，
        # 却引导用户确认提示词）。丢弃本轮正文，把拦截原因回喂给模型，
        # 逼其补做正确操作（重写被拦的提示词）后再暂停。
        gate_heal = bool(gate_rejections) and total_exec > 0 and applied < total_exec
        if gate_heal:
            blocked_n = total_exec - applied
            confirmation = ""
            confirmation_options = []
            wants_continue = True
            result.warnings.append(
                f"第 {step} 轮 {blocked_n} 个操作被流程闸机拦截，已回喂模型修正"
            )
            await emit({
                "type": SSE_STATUS,
                "text": f"系统闸机拦截了本轮 {blocked_n} 个流程操作，正在要求模型按流程修正…",
            })

        # 阶段硬边界：写入规格/阶段文档后必须停下等审阅（9999 事故：写完规格
        # 输出 continue 想直冲下一步 → 系统强制停在规格审阅，无视 continue）
        doc_written_names = [
            str(a.get("name") or a.get("key") or "")
            for a in executable
            if str(a.get("action") or a.get("tool") or "").lower()
            in ("write_document", "write_doc", "save_document", "document_write")
        ]
        if doc_written_names and not confirmation and _wizard_active():
            spec_hit = any(prompt_gates.is_spec_doc_name(n) for n in doc_written_names)
            if spec_hit:
                confirmation, confirmation_options = prompt_gates.spec_pause_card(executor.state)
                interaction = executor.state.setdefault("interaction", {})
                interaction["pending_pause_kind"] = "spec"
                logger.info("[FlowGate] 规格文档已写入，强制暂停审阅")

        # 系统拼装规格已落盘待审阅（spec_review_pending）：轮末注入审阅卡
        interaction = executor.state.setdefault("interaction", {})
        if interaction.get("spec_review_pending") and not confirmation:
            interaction.pop("spec_review_pending", None)
            confirmation, confirmation_options = prompt_gates.spec_pause_card(executor.state)
            logger.info("[FlowGate] 系统拼装规格待审阅，注入审阅卡")

        # 规格向导激活：模型手写规格已被忽略，必须转系统向导暂停卡等用户选参
        if spec_wizard_pending and not confirmation:
            confirmation, confirmation_options = prompt_gates.spec_pause_card(executor.state)
            interaction = executor.state.setdefault("interaction", {})
            interaction["pending_pause_kind"] = "spec"
            logger.info("[FlowGate] 规格向导激活，模型手写规格已忽略，转系统规格向导暂停卡")

        # 总结/规格收集闸（层9 兜底，1111/6666 事故）：script_analyze 已成功
        # 且无规格文档且模型未自发暂停 → 注入规格收集向导；scope=all 豁免只附警告
        if (
            "script_analyze" in getattr(executor, "skill_stages_done", set())
            and not prompt_gates.has_spec_document(executor.state)
            and not any(
                prompt_gates.is_spec_doc_name(n)
                for n in getattr(executor, "documents_written", []) or []
            )
            and not confirmation
        ):
            if getattr(executor, "gate_override", False) in ("all", True):
                result.warnings.append("用户已要求全速推进，已豁免规格收集暂停（仅附警告）")
            else:
                confirmation, confirmation_options = prompt_gates.spec_collect_card(executor.state)
                interaction = executor.state.setdefault("interaction", {})
                interaction["pending_pause_kind"] = "collect"
                logger.info("[FlowGate] script_analyze 完成且无规格文档，注入规格收集向导")

        # 流程闸机硬边界（对齐 FC 轨）：本批刚搭建故事板结构时，确认卡片统一换成
        # 「审阅拆分方案」的系统文案——结构阶段闸机只建骨架不写详细提示词，
        # 模型自拟的「提示词已写好/开始生成」类文案属虚报，一律覆盖
        # （8888 事故：拆完分镜即引导「确认分镜与草案，开始生成视频」）。
        structure_kinds = set(getattr(executor, "structure_kinds_created", None) or set())
        if (
            not confirmation
            and structure_kinds
            and not structure_self_check_pending
            and getattr(executor, "gate_enabled", False)
            and prompt_gates.gate_mode() == "strict"
        ):
            # 结构首建后强制再跑一轮自检补漏（8888 事故）：不直接弹系统暂停卡，
            # 先让模型按铁律第 2 条自检；第二轮若模型仍未暂停，再落系统结构审阅卡
            structure_self_check_pending = True
            structure_self_check_round = step
            logger.info(f"[FlowGate] 结构首建，强制自检轮（kinds={sorted(structure_kinds)}）")
        if (
            not confirmation
            and structure_self_check_pending
            and step > structure_self_check_round
            and getattr(executor, "gate_enabled", False)
            and prompt_gates.gate_mode() == "strict"
        ):
            # 自检轮模型仍未暂停：系统落结构审阅卡，不再无限追加自检轮
            confirmation, confirmation_options = prompt_gates.structure_paused_confirmation(structure_kinds)
            structure_self_check_pending = False
            logger.info(f"[FlowGate] 自检轮后仍未暂停，注入结构审阅卡（kinds={sorted(structure_kinds)}）")
        # 8888 二轮：结构阶段模型自发暂停时文案保留、选项换成系统阶段卡
        if (
            confirmation
            and structure_kinds
            and getattr(executor, "gate_enabled", False)
            and prompt_gates.gate_mode() == "strict"
        ):
            _sys_msg, confirmation_options = prompt_gates.structure_paused_confirmation(structure_kinds)

        # 阶段完成引导兜底（5555 事故）：执行器跑完但模型没发确认卡时，
        # 系统客观补一张下一步引导卡（不覆盖模型自发的暂停）。
        # B4/F29：Skill 声明「何时暂停/阶段暂停」（pause.stage_pause）时同样消费——
        # 任何执行器批次完成后模型未自发暂停即补卡（声明驱动 + 平台兜底双语义）。
        _stage_pause_declared = False
        if skill:
            try:
                from src.video_agent.skill_runtime.guard import skill_requires_stage_pause

                _stage_pause_declared = skill_requires_stage_pause(skill)
            except Exception:
                _stage_pause_declared = False
        _executor_actions = (
            "script_analyze", "storyboard_key_elements", "storyboard_shots",
            "storyboard_audio", "write_media_prompt", "audio_generate", "video_assembler",
        )
        if (
            not confirmation
            and not gate_heal
            and applied > 0
            and (
                _stage_pause_declared
                or any(
                    str(a.get("action") or a.get("tool") or "").strip()
                    in ("storyboard_key_elements", "storyboard_shots", "storyboard_audio")
                    for a in executable
                )
            )
            and any(
                str(a.get("action") or a.get("tool") or "").strip() in _executor_actions
                for a in executable
            )
        ):
            confirmation = "阶段执行完成，请审阅左侧故事板结果"
            confirmation_options = [
                {"label": "继续下一步", "description": "确认当前阶段产出，推进到下一阶段"},
                {"label": "我要调整", "description": "告诉我需要增删改的内容"},
            ]
            logger.info("[FlowGate] 阶段执行完成且模型未暂停，注入下一步引导卡")

        visible = executor.strip_action_blocks(content)
        if visible and not gate_heal:
            # 虚报警告（7777 × 4444）：声称完成结构搭建但故事板实际为空 → 只警告不拦人
            if (
                confirmation
                and _claims_structure_done(visible)
                and prompt_gates.storyboard_is_empty(executor.state)
            ):
                result.warnings.append(
                    "检测到虚报：正文声称已完成结构搭建，但故事板实际仍为空；"
                    "已按用户确认语义保留当前暂停（系统不没收模型暂停）。"
                )
            # 8888 二轮：收集卡已内嵌一句话总结（spec_collect_card 模板），
            # 正文不再重复补拼，避免总结出现两遍
            # 结构纯净闸剥离了内联详细提示词：正文追加更正说明，
            # 避免持久化消息只剩模型「已编写提示词草案」的虚报文字
            result.text = f"{result.text}\n\n{visible}".strip() if result.text else visible

        logger.info(
            f"[AgentLoop] step={step} actions={applied}/{total_exec} "
            f"continue={wants_continue} confirm={bool(confirmation)} finish={finish_reason or '-'}"
        )

        if structure_self_check_pending and not confirmation:
            wants_continue = True

        if confirmation:
            # 暂停等待用户确认：终止循环，把确认请求（含候选选项）带回给前端
            result.confirmation = confirmation
            result.confirmation_options = confirmation_options
            tracer.end_step(step, actions_applied=applied, finish_reason=finish_reason or "confirmation")
            break

        if not wants_continue:
            tracer.end_step(step, actions_applied=applied, finish_reason=finish_reason or "stop")
            break
        if step == max_steps:
            result.warnings.append(f"已达到多步上限（{max_steps} 轮），循环终止")
            tracer.end_step(step, actions_applied=applied, finish_reason="max_steps")
            break

        tracer.end_step(step, actions_applied=applied, finish_reason=finish_reason or "continue")

        # 回喂：让下一轮 LLM 知道上一轮说了什么、执行结果如何
        messages.append({"role": "assistant", "content": content})
        if gate_heal:
            reasons = "\n".join(f"- {r}" for r in gate_rejections)
            blocked_n = total_exec - applied
            if applied:
                head = (
                    f"（系统）第 {step} 轮的 {total_exec} 个操作中有 {applied} 个成功、"
                    f"{blocked_n} 个被系统流程闸机拦截（被拦截的写入没有生效）。"
                )
            else:
                head = (
                    f"（系统）第 {step} 轮的 {total_exec} 个操作全部被系统流程闸机拦截（0 个成功），"
                    "本轮你声称已完成的写入/创建实际上都没有生效。"
                )
            feedback = (
                f"{head}\n拦截原因：\n{reasons}\n"
                "请严格按上述要求修正后重新执行被拦截的操作。"
                "操作未全部成功前，向用户陈述需与此一致：未写入的内容尚未完成，"
                "确认卡也只在全部成功后发出。"
            )
        else:
            feedback = (
                f"（系统）第 {step} 轮的 {applied} 个操作已执行，最新工作台状态已刷新到 system prompt。"
                "请继续完成任务；全部完成后直接结束本轮回复。"
            )
            if structure_self_check_pending:
                feedback += "\n" + SELF_CHECK_FEEDBACK
        messages.append({"role": "user", "content": feedback})

    # 814G8：正常路径解绑进度通道（异常路径 contextvar 随任务消亡）
    unbind_progress_emitter(_progress_token)
    if not result.text:
        if result.confirmation:
            # 暂停轮无正文兜底：用暂停说明作为可见回复，
            # 永远不向用户展示「模型返回了空内容」这类误导文案
            result.text = result.confirmation
        elif result.applied_actions:
            # 操作已在各轮实时写入工作台，只是模型没输出总结文字：
            # 明确告知操作数量，避免用户误以为什么都没发生。
            result.text = (
                f"已执行 {result.applied_actions} 个操作，故事板与当前预览已更新（模型未输出总结文字）。"
            )
        else:
            result.text = "（Agent 没有返回可见回复：模型返回了空内容，可能是上游瞬时抖动，请重试或换模型）"
    result.trace = tracer.finish_trace(total_actions=result.applied_actions)
    return result
