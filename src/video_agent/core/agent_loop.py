"""
Agent 多步执行循环（Rule2: 唯一实现）。

位于 core 层（-1 层级理顺：编排骨架属核心层，不再放 web/；
web/agent_loop.py 保留为 DEPRECATED 兼容 re-export）。

有界循环（最多 max_steps 轮）：FC 工具轮（tool_calls 在 llm_call 内执行，
finish 非 stop 或无可见正文时继续下一轮）与纯文本收尾轮（
单轨化，ADR-0001：文本动作块解析路径已退役；暂停确认经
llm_call 第 5 元组结构化上抛，不经文本块）。

llm_call / context_builder 以 callable 注入，便于单元测试。
"""
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Dict, List, Optional, Tuple, Union

import time

from loguru import logger

from src.video_agent.config import settings
from src.video_agent.core.sse_events import (
    SSE_ACTIONS_APPLIED,
    SSE_STATUS,
    SSE_STEP_STARTED,
    SSE_TOOL_FINISHED,
    SSE_TOOL_STARTED,
    status_event,
)
from src.video_agent.core.tracer import AgentTracer
from src.video_agent.skill_runtime.registry import fallback_skill_from_state
# （轮末闸机分支收敛为声明式策略表（层 9 唯一落点）
from src.video_agent.core.round_end_policies import (
    RoundEndContext,
    _claims_structure_done,  # noqa: 1 re-export 壳（测试导入路径不变，13.7 惯例）
    run_round_end_policies,
    suggest_next_actions,
)
from src.video_agent.core import live_metrics, prompt_gates
# （漂移进度通道绑定顶层化；spec_wizard_active 经模块属性访问
# （测试 patch 目标=registry 命名空间，顶层 from-import 会冻结绑定导致 patch 失效）
from src.video_agent.skill_runtime.progress import (
    bind_progress_emitter,
    unbind_progress_emitter,
)

if TYPE_CHECKING:
    # 仅类型标注用：执行器实现依赖 web 层生成管线，运行时不做硬依赖
    from src.video_agent.web.action_executor import StudioActionExecutor

MAX_STEPS = settings.max_steps

# llm_call(system_prompt, messages, stream_hook?) -> (content, finish_reason, fc_applied[, plan_ms])
# fc_applied: FC 路径已执行的 tool 数量（可选，默认 0）
# plan_ms: 纯模型规划耗时（可选；缺省 0，兼容旧 3 元组实现/测试桩）
# extra: 可选 dict：{confirmation, confirmation_options}——
# 本轮 FC 批经 workflow_pause 产生的结构化暂停确认（不经文本块）
# stream_hook: 可选流式增量回调，每段文本 await stream_hook(text)
LlmCall = Callable[..., Awaitable[Tuple[str, str, int, float]]]
# context_builder -> 最新的 system prompt（协议 + 实时状态）
ContextBuilder = Callable[[], str]


def _unpack_llm(ret: Tuple) -> Tuple[str, str, int, float, Dict[str, Any]]:
    """解包 llm_call 返回值：5 元组 (content, finish, fc_applied, plan_ms, extra)；
    旧 3/4 元组实现缺省补齐（plan_ms=0，extra={}；测试桩兼容）。"""
    plan = float(ret[3]) if len(ret) > 3 else 0.0
    extra = ret[4] if len(ret) > 4 and isinstance(ret[4], dict) else {}
    return str(ret[0]), str(ret[1]), int(ret[2]), plan, extra


def _bad_output_nudge(attempt: int) -> str:
    """空/畸形输出续写引导：重试时随 messages 附一句，
    明确要求本轮直接产出工具调用或可见回复（只临时附加，不入历史）。"""
    return (
        f"（系统）上一轮（第 {attempt} 次）未产出任何可见回复或工具调用。"
        "请直接发出本应执行的工具调用，或给出面向用户的回复；"
        "不要只输出思考过程。"
    )


@dataclass
class AgentLoopResult:
    text: str = ""
    applied_actions: int = 0
    steps: int = 0
    warnings: List[str] = field(default_factory=list)
    # LLM 通过 workflow_pause 工具请求用户确认时的说明文字（非空表示等待确认）
    confirmation: str = ""
    # 确认卡片的候选选项（每项 {label, description}，前端渲染为单选卡片）
    confirmation_options: List[Dict[str, Any]] = field(default_factory=list)
    # 执行轨迹（每轮 step/耗时/操作数/finish_reason），前端「执行轨迹」折叠区展示
    trace: Dict[str, Any] = field(default_factory=dict)
    # 建议动作按钮（确定性交互， 三问全中收归系统）：
    # retry=机械重发上一条用户消息（value 空，前端取历史原文）；
    # continue=发送固定文本推进新一轮
    suggested_actions: List[Dict[str, str]] = field(default_factory=list)


# split_actions / _extract_confirmation（文本动作别名归一）已删除
# （暂停确认唯一经 workflow_pause FC 工具结构化上抛，
# 不存在需归一的文本动作别名（对齐「只有一个 AskUserQuestion」）。

# 防虚报检测（_STRUCTURE_CLAIM_RE/_claims_structure_done） 随唯一消费点
# 迁入 round_end_policies；本文件顶部保留 re-export 壳，测试导入路径不变。


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
    user_id: str = "",
) -> AgentLoopResult:
    """on_event（可选）：async callable，接收 {"type": "step_started"/"actions_applied", ...}
    stream_hook（可选）：流式文本增量回调，每收到一段 LLM 文本就 await stream_hook(text)。
    user_text 可以是纯文本 str，也可以是多模态 content parts 列表（含 image_url）。
    """

    async def emit(event: Dict[str, Any]) -> None:
        if on_event:
            try:
                await on_event(event)
            except Exception as _e:
                # 承重接线遥测（批 8）：事件通道静默降级不再只进 debug 日志，
                # 断线经 /api/agent/degradations 可见（型防复发）
                live_metrics.record_degradation("agent_loop.event_emit")
                logger.debug("[agent_loop] 忽略异常: {}", _e)

    result = AgentLoopResult()
    messages: List[Dict[str, Any]] = list(history) + [{"role": "user", "content": user_text}]

    skill = str(getattr(executor, "skill_name", "") or "")
    if not skill:
        # 请求未携带 Skill 时回退项目 usedSkills 末位（单一实现）
        skill = fallback_skill_from_state(getattr(executor, "state", None) or {})

    # 链路追踪：记录本次对话执行过程
    tracer = AgentTracer.get_instance()
    user_preview = user_text if isinstance(user_text, str) else str(user_text)[:80]
    tracer.start_trace(user_preview, user_id=user_id)

    # 恢复：执行器进度通道双轨接线（统一循环级绑定，FC/文本轨同覆盖）。
    # 执行器内部批次边界（emit_timeline_note/emit_state_refresh/emit_progress）
    # 经此通道实时推时间线子项与故事板刷新——卡片一张张流式亮，不再结束才一把出现。
    # contextvar 任务级隔离：异常路径随任务消亡，正常路径在循环结束后解绑。
    _progress_token = bind_progress_emitter(emit)

    for step in range(1, max_steps + 1):
        result.steps = step
        tracer.start_step()
        if step == 1:
            # 前奏明细：读 Skill/文档等准备动作记入第一步时间线
            # （同时发 live 事件，运行中视图与持久化视图同条目）
            for pi, (name, summary) in enumerate(prelude_notes or []):
                tracer.record_action(str(name), str(summary), 0.0, True)
                pid = f"pre-{pi}"
                await emit({"type": SSE_TOOL_STARTED, "id": pid, "name": str(name), "summary": str(summary)})
                await emit({"type": SSE_TOOL_FINISHED, "id": pid, "ok": True, "elapsed_ms": 0.0, "result_summary": str(summary)})
        await emit({"type": SSE_STEP_STARTED, "step": step, "max_steps": max_steps})
        if step > 1:
            # 多轮循环"静默期"提示：上一轮工具执行完到本轮首 token 之间可能耗时数十秒，
            # 前端状态栏需明确告知正在进行第几轮思考（status 事件全链路已透传）
            await emit(status_event(
                "agent.roundThinking",
                f"第 {step - 1} 轮操作已完成，继续思考中（第 {step}/{max_steps} 轮）…",
                {"prev": step - 1, "step": step, "max": max_steps},
            ))
        # 轮间注入：任务执行期间收到的用户引导消息在上一轮操作完成、
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

        # 过程时间线：模型推理轮本身也作为操作条目可见（v6：仅创作型
        # 交接轮进入本循环，文案为节点内创作语义，非确定性阶段规划）
        await emit({
            "type": SSE_TOOL_STARTED,
            "id": f"llm-s{step}",
            "name": "model_reasoning",
            "summary": f"模型创作规划（节点内第 {step} 轮）",
        })
        # 规划条目先占位入 trace（保证持久化顺序 = live 顺序：规划→工具），
        # 耗时在 llm_call 返回后补填
        _plan_rec = tracer.record_action(
            "model_reasoning", f"模型创作规划（节点内第 {step} 轮）", 0.0, True,
        )
        content, finish_reason, fc_applied, plan_ms, fc_extra = _unpack_llm(
            await llm_call(system_prompt, messages, stream_hook)
        )
        plan_total = float(plan_ms or 0.0)

        # 空/畸形响应防护：空响应或 MALFORMED_FUNCTION_CALL 连续发生 → 重试至多 2 次，
        # 达到上限后以明确故障文案收尾（不再静默落为「没有返回可见回复」）。
        bad_retries = 0
        while not str(content or "").strip() and fc_applied == 0 and bad_retries < 2:
            bad_retries += 1
            logger.warning(f"[AgentLoop] 第 {step} 轮输出异常（空/畸形），重试 {bad_retries}/2")
            await emit(status_event("agent.badRetry", f"第 {step} 轮输出异常，重试中…", {"step": step}))
            tracer.record_action(
                name="bad_output_retry",
                summary=f"模型输出异常（空/畸形），自动重做（第 {bad_retries} 次）",
                elapsed_ms=0.0,
                ok=True,
            )
            content, finish_reason, fc_applied, plan_ms, fc_extra = _unpack_llm(
                await llm_call(
                    system_prompt,
                    messages + [{"role": "user", "content": _bad_output_nudge(bad_retries)}],
                    stream_hook,
                )
            )
            plan_total += float(plan_ms or 0.0)
        # 规划耗时只算纯模型规划（反馈）：FC 工具执行时间由各工具条目独立展示，
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
            # 一键重试按钮（机械重发上一条用户消息，零模型猜测）
            result.suggested_actions.append({"kind": "retry", "label": "重试", "value": ""})
            tracer.end_step(step, actions_applied=0, finish_reason="bad_output")
            break

        # Skill 声明式流程门禁已随 架构板正批退役（顺序归编排器）。

        if finish_reason == "length":
            result.warnings.append(
                f"第 {step} 轮回复被 max_tokens 截断，工具调用/正文可能不完整"
            )

        # 结构化暂停确认：本轮 FC 批经 workflow_pause 产生
        fc_confirmation = str((fc_extra or {}).get("confirmation") or "")
        fc_confirmation_options = list((fc_extra or {}).get("confirmation_options") or [])

        # FC 路径：tool_calls 已在 llm_call 内部执行；正文原样可见（单轨化后
        # 无文本动作块通道，ADR-0001，无需清洗）
        if fc_applied > 0 or fc_confirmation:
            result.applied_actions += fc_applied
            if fc_applied:
                await emit({"type": SSE_ACTIONS_APPLIED, "step": step, "count": fc_applied})
            visible = (content or "").strip()
            if visible:
                result.text = f"{result.text}\n\n{visible}".strip() if result.text else visible
            logger.info(
                f"[AgentLoop] step={step} fc_applied={fc_applied} "
                f"confirm={bool(fc_confirmation)} finish={finish_reason or '-'}"
            )
            if fc_confirmation:
                # 虚报审计（×）：FC 确认轮同样承重——声称拆完但故事板
                # 为空 → 只附警告不拦人（系统不没收模型暂停）；单轨化不豁免审计
                if (
                    _claims_structure_done(visible, fc_confirmation)
                    and prompt_gates.storyboard_is_empty(executor.state)
                ):
                    result.warnings.append(
                        "检测到虚报：正文声称已完成结构搭建，但故事板实际仍为空；"
                        "已按用户确认语义保留当前暂停（系统不没收模型暂停）。"
                    )
                # 暂停等待用户确认：终止循环，把确认请求（含候选选项）带回给前端
                result.confirmation = fc_confirmation
                result.confirmation_options = fc_confirmation_options
                # 三通道分离 B：超长 pause message 原文进正文通道
                # （成果展示归正文；判重内置，防与模型 prose 重复）
                _pause_overflow = str((fc_extra or {}).get("pause_overflow") or "").strip()
                if _pause_overflow and _pause_overflow not in (result.text or ""):
                    result.text = (
                        f"{result.text}\n\n{_pause_overflow}".strip()
                        if result.text else _pause_overflow
                    )
                tracer.end_step(
                    step, actions_applied=fc_applied,
                    finish_reason=finish_reason or "confirmation",
                )
                break
            # 6 提前终止：模型明确 stop 且已产出可见文本 → 任务已完成，
            # 不再固定追加 LLM 总结调用（finish=tool_calls 或无文本时保留多步链）
            if finish_reason in ("stop", "end_turn") and visible:
                # 状态驱动下一步建议：收尾且无既有建议时按客观状态下发
                if not result.suggested_actions:
                    result.suggested_actions.extend(suggest_next_actions(executor.state))
                tracer.end_step(step, actions_applied=fc_applied, finish_reason="fc_done")
                break
            if step == max_steps:
                result.warnings.append(f"已达到多步上限（{max_steps} 轮），循环终止")
                result.suggested_actions.append(
                    {"kind": "continue", "label": "继续完成", "value": "继续完成"})
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

        # 纯文本轮（FC 单轨， / ADR-0001）：模型本轮未发出工具调用，
        # 即本轮为面向用户的回复，循环进入收尾。文本动作块解析路径已随
        # 双轨退役删除；正文拼接收纳由轮末策略 false_claim_audit 单一执行
        # （与历史文本路径同源，防双处拼接重复；虚报/假停兜底等机械闸机
        # 与原文本路径同一策略表，零新增）。
        _re_ctx = RoundEndContext(
            step=step,
            executor=executor,
            content=content,
            skill=skill,
            confirmation="",
            confirmation_options=[],
            wants_continue=False,
            total_exec=0,
            applied=0,
            executable=[],
            gate_rejections=list(getattr(executor, "gate_rejections", None) or []),
            spec_wizard_pending=False,
            result_text=result.text,
        )
        await run_round_end_policies(_re_ctx, emit, tracer=tracer)
        if _re_ctx.result_warnings:
            result.warnings.extend(_re_ctx.result_warnings)
        result.text = _re_ctx.result_text
        # fakestop：轮末策略机械追加的建议动作（仅当无既有建议时生效）
        if _re_ctx.suggested_actions and not result.suggested_actions:
            result.suggested_actions.extend(_re_ctx.suggested_actions)
        if _re_ctx.confirmation or _re_ctx.hard_break:
            # 轮末策略注入的暂停卡（规格审阅/规格收集等）：带回前端
            result.confirmation = _re_ctx.confirmation
            result.confirmation_options = _re_ctx.confirmation_options
            tracer.end_step(
                step, actions_applied=0,
                finish_reason=_re_ctx.hard_break_finish or "confirmation",
            )
            break
        # 正常收尾：状态驱动下一步建议
        if not result.suggested_actions:
            result.suggested_actions.extend(suggest_next_actions(executor.state))
        tracer.end_step(step, actions_applied=0, finish_reason=finish_reason or "stop")
        break

    # 正常路径解绑进度通道（异常路径 contextvar 随任务消亡）
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
            # 用户腔兜底（空响应不是用户的错，给出明确下一步）
            result.text = (
                "这一轮没有生成可见回复（上游可能瞬时抖动）——请直接说「重试」，我再来一次；"
                "若连续出现可尝试切换模型。"
            )
            # 一键重试按钮替代手打「重试」（机械重发上一条用户消息）
            result.suggested_actions.append({"kind": "retry", "label": "重试", "value": ""})
    result.trace = tracer.finish_trace(total_actions=result.applied_actions)
    return result
