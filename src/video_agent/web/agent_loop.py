"""
Agent 多步执行循环。

单轮「LLM → 解析 actions → 执行」升级为有界循环（最多 max_steps 轮）：
LLM 可以在 studio-actions 末尾输出 {"action": "continue"} 请求下一轮，
系统执行本轮操作后刷新上下文再次调用，直到 LLM 不再请求继续或达到上限。

llm_call / context_builder 以 callable 注入，便于单元测试。
"""
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple, Union

from loguru import logger

from src.video_agent.config import settings
from src.video_agent.core.tracer import AgentTracer
from src.video_agent.web.actions import StudioActionExecutor

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
    # 执行轨迹（每轮 step/耗时/操作数/finish_reason），前端「执行轨迹」折叠区展示
    trace: Dict[str, Any] = field(default_factory=dict)


def split_actions(actions: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], bool, str]:
    """分离流程信号，返回 (可执行的 actions, 是否请求下一轮, 确认请求文案)"""
    executable: List[Dict[str, Any]] = []
    wants_continue = False
    confirmation = ""
    for a in actions:
        name = str(a.get("action", "")).lower()
        if name == "continue":
            wants_continue = True
        elif name == "request_confirmation":
            confirmation = str(a.get("message", "") or "请确认以上内容，确认后我将继续。")
        else:
            executable.append(a)
    return executable, wants_continue, confirmation


# 向后兼容别名
_split_actions = split_actions


async def run_agent_loop(
    user_text: Union[str, List[Dict[str, Any]]],
    *,
    llm_call: LlmCall,
    context_builder: ContextBuilder,
    executor: StudioActionExecutor,
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
        await emit({"type": "step_started", "step": step, "max_steps": max_steps})
        system_prompt = context_builder()  # 每轮刷新，让 LLM 看到上一轮执行后的最新状态

        content, finish_reason, fc_applied = await llm_call(system_prompt, messages, stream_hook)

        # 空响应防护：模型返回了完全空的响应（无文本且无工具调用，常见于
        # 上游瞬时抖动）时自动重试一次，避免直接落为「没有返回可见回复」。
        if not content.strip() and fc_applied == 0:
            logger.warning(f"[AgentLoop] 第 {step} 轮模型返回空响应，自动重试一次")
            await emit({"type": "status", "text": f"第 {step} 轮响应为空，重试中…"})
            content, finish_reason, fc_applied = await llm_call(system_prompt, messages, stream_hook)

        if finish_reason == "length":
            result.warnings.append(
                f"第 {step} 轮回复被 max_tokens 截断，studio-actions 可能不完整"
            )

        # FC 路径：tool_calls 已在 llm_call 内部执行，跳过文本解析
        if fc_applied > 0:
            result.applied_actions += fc_applied
            await emit({"type": "actions_applied", "step": step, "count": fc_applied})
            visible = content.strip()
            if visible:
                result.text = f"{result.text}\n\n{visible}".strip() if result.text else visible
            logger.info(
                f"[AgentLoop] step={step} fc_applied={fc_applied} "
                f"confirm=False finish={finish_reason or '-'}"
            )
            # FC 多步支持：工具执行后允许继续下一轮（LLM 可在下轮选择不再调用工具来结束）
            # 仅当 finish_reason 为 "stop" 且无可见文本时才继续（表示 LLM 可能还想做更多）
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

        executable, wants_continue, confirmation = _split_actions(actions)
        if executable:
            await emit({"type": "executing_actions", "step": step, "count": len(executable)})
        _log_before = len(executor.action_log)
        applied = executor.execute(executable)
        result.applied_actions += applied
        if applied:
            await emit({"type": "actions_applied", "step": step, "count": applied})
        # 推理过程可视化：实时把本轮刚完成的操作描述推给前端状态栏
        new_logs = executor.action_log[_log_before:]
        if new_logs:
            await emit({"type": "status", "text": "已完成：" + "；".join(new_logs[-3:])})
        if executable and applied < len(executable):
            result.warnings.append(
                f"第 {step} 轮有 {len(executable) - applied} 个操作未匹配到目标（draft/group 不存在？）"
            )

        visible = executor.strip_action_blocks(content)
        if visible:
            result.text = f"{result.text}\n\n{visible}".strip() if result.text else visible

        logger.info(
            f"[AgentLoop] step={step} actions={applied}/{len(executable)} "
            f"continue={wants_continue} confirm={bool(confirmation)} finish={finish_reason or '-'}"
        )

        if confirmation:
            # 暂停等待用户确认：终止循环，把确认请求带回给前端
            result.confirmation = confirmation
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
        messages.append({
            "role": "user",
            "content": (
                f"（系统）第 {step} 轮的 {applied} 个操作已执行，最新工作台状态已刷新到 system prompt。"
                "请继续完成任务；全部完成后不要再输出 continue。"
            ),
        })

    if not result.text:
        if result.applied_actions:
            # 操作已在各轮实时写入工作台，只是模型没输出总结文字：
            # 明确告知操作数量，避免用户误以为什么都没发生。
            result.text = (
                f"已执行 {result.applied_actions} 个操作，故事板与当前预览已更新（模型未输出总结文字）。"
            )
        else:
            result.text = "（Agent 没有返回可见回复：模型返回了空内容，可能是上游瞬时抖动，请重试或换模型）"
    result.trace = tracer.finish_trace(total_actions=result.applied_actions)
    return result
