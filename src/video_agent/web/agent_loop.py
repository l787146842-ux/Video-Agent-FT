"""
Agent 多步执行循环。

单轮「LLM → 解析 actions → 执行」升级为有界循环（最多 max_steps 轮）：
LLM 可以在 studio-actions 末尾输出 {"action": "continue"} 请求下一轮，
系统执行本轮操作后刷新上下文再次调用，直到 LLM 不再请求继续或达到上限。

llm_call / context_builder 以 callable 注入，便于单元测试。
"""
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Tuple

from loguru import logger

from src.video_agent.web.actions import StudioActionExecutor

MAX_STEPS = 3

# llm_call(system_prompt, messages) -> (content, finish_reason)
LlmCall = Callable[[str, List[Dict[str, Any]]], Awaitable[Tuple[str, str]]]
# context_builder() -> 最新的 system prompt（协议 + 实时状态）
ContextBuilder = Callable[[], str]


@dataclass
class AgentLoopResult:
    text: str = ""
    applied_actions: int = 0
    steps: int = 0
    warnings: List[str] = field(default_factory=list)


def _split_actions(actions: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], bool]:
    """分离出 continue 信号，返回 (可执行的 actions, 是否请求下一轮)"""
    executable = [a for a in actions if str(a.get("action", "")).lower() != "continue"]
    wants_continue = len(executable) != len(actions)
    return executable, wants_continue


async def run_agent_loop(
    user_text: str,
    *,
    llm_call: LlmCall,
    context_builder: ContextBuilder,
    executor: StudioActionExecutor,
    history: List[Dict[str, Any]],
    max_steps: int = MAX_STEPS,
) -> AgentLoopResult:
    result = AgentLoopResult()
    messages: List[Dict[str, Any]] = list(history) + [{"role": "user", "content": user_text}]

    for step in range(1, max_steps + 1):
        result.steps = step
        system_prompt = context_builder()  # 每轮刷新，让 LLM 看到上一轮执行后的最新状态

        content, finish_reason = await llm_call(system_prompt, messages)

        if finish_reason == "length":
            result.warnings.append(
                f"第 {step} 轮回复被 max_tokens 截断，studio-actions 可能不完整"
            )

        actions = executor.parse_actions_from_reply(content)
        if not actions and executor.has_action_block(content):
            result.warnings.append(
                f"第 {step} 轮的 studio-actions 块解析失败（JSON 无效或被截断），本轮操作已丢弃"
            )

        executable, wants_continue = _split_actions(actions)
        applied = executor.execute(executable)
        result.applied_actions += applied
        if executable and applied < len(executable):
            result.warnings.append(
                f"第 {step} 轮有 {len(executable) - applied} 个操作未匹配到目标（draft/group 不存在？）"
            )

        visible = executor.strip_action_blocks(content)
        if visible:
            result.text = f"{result.text}\n\n{visible}".strip() if result.text else visible

        logger.info(
            f"[AgentLoop] step={step} actions={applied}/{len(executable)} "
            f"continue={wants_continue} finish={finish_reason or '-'}"
        )

        if not wants_continue:
            break
        if step == max_steps:
            result.warnings.append(f"已达到多步上限（{max_steps} 轮），循环终止")
            break

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
        result.text = "已更新故事板和当前预览。" if result.applied_actions else "（Agent 没有返回可见回复）"
    return result
