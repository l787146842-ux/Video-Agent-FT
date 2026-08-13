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
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Dict, List, Optional, Tuple, Union

import time

from loguru import logger

from src.video_agent.config import settings
from src.video_agent.core import prompt_gates
from src.video_agent.core.sse_events import (
    SSE_ACTIONS_APPLIED,
    SSE_EXECUTING_ACTIONS,
    SSE_STATUS,
    SSE_STEP_STARTED,
    SSE_TOOL_FINISHED,
    SSE_TOOL_STARTED,
)
from src.video_agent.core.tracer import AgentTracer

if TYPE_CHECKING:
    # 仅类型标注用：执行器实现依赖 web 层生成管线，运行时不做硬依赖
    from src.video_agent.web.action_executor import StudioActionExecutor

MAX_STEPS = settings.max_steps

# llm_call(system_prompt, messages, stream_hook?) -> (content, finish_reason, fc_applied)
# fc_applied: FC 路径已执行的 tool 数量（可选，默认 0）
# stream_hook: 可选流式增量回调，每段文本 await stream_hook(text)
LlmCall = Callable[..., Awaitable[Tuple[str, str, int]]]
# context_builder() -> 最新的 system prompt（协议 + 实时状态）
ContextBuilder = Callable[[], str]


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
    for a in actions:
        name = str(a.get("action", "")).lower()
        if name == "continue":
            wants_continue = True
        elif name == "request_confirmation":
            confirmation = str(a.get("message", "") or "请确认以上内容，确认后我将继续。")
            opts = a.get("options")
            if isinstance(opts, list):
                for o in opts:
                    if isinstance(o, dict) and str(o.get("label") or "").strip():
                        item = {
                            "label": str(o.get("label")).strip(),
                            "description": str(o.get("description") or "").strip(),
                        }
                        if str(o.get("group") or "").strip():
                            item["group"] = str(o.get("group")).strip()
                        confirmation_options.append(item)
                    elif isinstance(o, str) and o.strip():
                        confirmation_options.append({"label": o.strip(), "description": ""})
        else:
            executable.append(a)
    return executable, wants_continue, confirmation, confirmation_options


# 向后兼容别名
_split_actions = split_actions


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
) -> AgentLoopResult:
    """on_event（可选）：async callable，接收 {"type": "step_started"/"actions_applied", ...}
    stream_hook（可选）：流式文本增量回调，每收到一段 LLM 文本就 await stream_hook(text)。
    user_text 可以是纯文本 str，也可以是多模态 content parts 列表（含 image_url）。
    """

    async def emit(event: Dict[str, Any]) -> None:
        if on_event:
            try:
                await on_event(event)
            except Exception:
                pass

    result = AgentLoopResult()
    messages: List[Dict[str, Any]] = list(history) + [{"role": "user", "content": user_text}]

    # 链路追踪：记录本次对话执行过程
    tracer = AgentTracer.get_instance()
    user_preview = user_text if isinstance(user_text, str) else str(user_text)[:80]
    tracer.start_trace(user_preview)

    for step in range(1, max_steps + 1):
        result.steps = step
        tracer.start_step()
        await emit({"type": SSE_STEP_STARTED, "step": step, "max_steps": max_steps})
        if step > 1:
            # 多轮循环"静默期"提示：上一轮工具执行完到本轮首 token 之间可能耗时数十秒，
            # 前端状态栏需明确告知正在进行第几轮思考（status 事件全链路已透传）
            await emit({
                "type": SSE_STATUS,
                "text": f"第 {step - 1} 轮操作已完成，继续思考中（第 {step}/{max_steps} 轮）…",
            })
        system_prompt = context_builder()  # 每轮刷新，让 LLM 看到上一轮执行后的最新状态

        # 过程时间线：模型推理轮本身也作为操作条目可见（读文档/调执行器之外的“思考”动作）
        _llm_t0 = time.monotonic()
        await emit({
            "type": SSE_TOOL_STARTED,
            "id": f"llm-s{step}",
            "name": "model_reasoning",
            "summary": f"模型推理规划（第 {step} 轮）",
        })
        content, finish_reason, fc_applied = await llm_call(system_prompt, messages, stream_hook)
        await emit({
            "type": SSE_TOOL_FINISHED,
            "id": f"llm-s{step}",
            "ok": True,
            "elapsed_ms": round((time.monotonic() - _llm_t0) * 1000, 1),
            "result_summary": f"模型推理规划（第 {step} 轮）完成",
        })

        # 空响应防护：模型返回了完全空的响应（无文本且无工具调用，常见于
        # 上游瞬时抖动）时自动重试一次，避免直接落为「没有返回可见回复」。
        if not content.strip() and fc_applied == 0:
            logger.warning(f"[AgentLoop] 第 {step} 轮模型返回空响应，自动重试一次")
            await emit({"type": SSE_STATUS, "text": f"第 {step} 轮响应为空，重试中…"})
            content, finish_reason, fc_applied = await llm_call(system_prompt, messages, stream_hook)

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
                    "请继续完成任务；全部完成后直接回复文本即可（不要再调用 Tool）。"
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
        # 规格向导闸机（S1）：声明 spec_wizard 的 Skill，规格文档由系统按向导
        # 拼装，模型手写规格一律不落盘，改为系统规格收集/审阅暂停卡
        spec_wizard_pending = False
        if executable:
            try:
                from src.video_agent.skill_runtime.registry import spec_wizard_active

                skill_name = str(getattr(executor, "skill_name", "") or "")
                if not skill_name:
                    used = (getattr(executor, "state", None) or {}).get("usedSkills") or []
                    skill_name = str(used[-1] or "") if used else ""
                if spec_wizard_active(skill_name):
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
                        spec_wizard_pending = True
                        result.warnings.append("规格文档由系统按向导拼装，模型手写规格已忽略")
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
        applied += stream_preapplied  # 流式预执行成功数计入本轮应用量
        _batch_ms = (time.monotonic() - _t0) * 1000
        result.applied_actions += applied
        if applied:
            await emit({"type": SSE_ACTIONS_APPLIED, "step": step, "count": applied})
        # 推理过程可视化：实时把本轮刚完成的操作描述推给前端状态栏 + 时间线
        new_logs = executor.action_log[_log_before:]
        if new_logs:
            await emit({"type": SSE_STATUS, "text": "已完成：" + "；".join(new_logs[-3:])})
        for i, desc in enumerate(new_logs):
            per_ms = _batch_ms / len(new_logs) if new_logs else 0.0
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
                )
        gate_rejections = list(getattr(executor, "gate_rejections", None) or [])
        if total_exec and applied < total_exec:
            if gate_rejections:
                result.warnings.append(
                    f"第 {step} 轮有 {total_exec - applied} 个操作被流程闸机拦截"
                    f"（原因：{gate_rejections[0][:60]}…）"
                )
            elif stream_consumed == 0:
                result.warnings.append(
                    f"第 {step} 轮有 {total_exec - applied} 个操作未匹配到目标（draft/group 不存在？）"
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

        # 阶段硬边界：写入规格/阶段文档后必须停下等审阅，不给模型顺手把后续阶段
        # （拆结构/写提示词）也打包做完的机会（模型未自行暂停时由系统强制）
        if (
            applied > 0
            and not confirmation
            and not wants_continue
            and any(
                str(a.get("action", "")).lower() in ("write_document", "write_doc", "save_document", "document_write")
                for a in executable
            )
        ):
            confirmation = "规格/阶段文档已写入，请审阅；确认无误后我再推进下一阶段。"

        # 规格向导激活：模型手写规格已被忽略，必须转系统向导暂停卡等用户选参
        if spec_wizard_pending and not confirmation:
            confirmation, confirmation_options = prompt_gates.spec_pause_card(executor.state)
            logger.info("[FlowGate] 规格向导激活，模型手写规格已忽略，转系统规格向导暂停卡")

        # 流程闸机硬边界（对齐 FC 轨）：本批刚搭建故事板结构时，确认卡片统一换成
        # 「审阅拆分方案」的系统文案——结构阶段闸机只建骨架不写详细提示词，
        # 模型自拟的「提示词已写好/开始生成」类文案属虚报，一律覆盖
        # （8888 事故：拆完分镜即引导「确认分镜与草案，开始生成视频」）。
        structure_kinds = set(getattr(executor, "structure_kinds_created", None) or set())
        if (
            structure_kinds
            and getattr(executor, "gate_enabled", False)
            and prompt_gates.gate_mode() == "strict"
        ):
            confirmation, confirmation_options = prompt_gates.structure_paused_confirmation(structure_kinds)
            logger.info(f"[FlowGate] 结构搭建后覆盖确认文案（kinds={sorted(structure_kinds)}）")

        visible = executor.strip_action_blocks(content)
        if visible and not gate_heal:
            # 结构纯净闸剥离了内联详细提示词：正文追加更正说明，
            # 避免持久化消息只剩模型「已编写提示词草案」的虚报文字
            stripped_n = int(getattr(executor, "prompts_stripped", 0) or 0)
            if stripped_n and getattr(executor, "gate_enabled", False):
                visible = (
                    visible
                    + f"\n\n【系统说明】本轮只搭建了故事板骨架，{stripped_n} 条内联详细提示词已被流程闸机剥离，"
                    "提示词草案尚未编写；确认拆分方案后再逐条编写。"
                )
            result.text = f"{result.text}\n\n{visible}".strip() if result.text else visible

        logger.info(
            f"[AgentLoop] step={step} actions={applied}/{total_exec} "
            f"continue={wants_continue} confirm={bool(confirmation)} finish={finish_reason or '-'}"
        )

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
                "请严格按上述要求修正后重新执行被拦截的操作（操作未全部成功前，严禁向用户声称已完成，"
                "也严禁请求用户确认未写入的内容）。"
            )
        else:
            feedback = (
                f"（系统）第 {step} 轮的 {applied} 个操作已执行，最新工作台状态已刷新到 system prompt。"
                "请继续完成任务；全部完成后不要再输出 continue。"
            )
        messages.append({"role": "user", "content": feedback})

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
