"""
Planner — 对话式 Agent 的唯一入口（Rule1）。

设计方案核心：
- Planner 直接持有 LLM Adapter 引用（Rule6: 外部调用走 Adapter），不经过 Tool Manager
- Tool Manager 只管理"业务 Tool"（故事板操作、生图、文档等）
- 双模式兼容：Function Calling + 文本解析 fallback（Rule2）
- 多步循环（MAX_STEPS），LLM 可请求 continue 推进下一轮
- 流式通过 AsyncGenerator 穿透（SSE）
"""
import json
import time
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Callable, Dict, List, Optional, Tuple, Union

from loguru import logger

from src.video_agent.adapters.base_chat import BaseChatAdapter, ChatResponse, StreamChunk
from src.video_agent.state.manager import StateManager
from src.video_agent.tools.manager import ToolManager
from src.video_agent.utils.prompts import load_prompt, render_prompt
from src.video_agent.web.actions import StudioActionExecutor, strip_action_blocks
from src.video_agent.web.agent_loop import MAX_STEPS, run_agent_loop, split_actions, AgentLoopResult
from src.video_agent.workflows.engine import WorkflowEngine


@dataclass
class PlannerContext:
    """每轮对话的上下文参数"""
    history: List[Dict[str, Any]] = field(default_factory=list)
    selected_draft_id: str = ""
    selected_type: str = ""
    state_json: str = ""
    extra_system: str = ""       # 前端 skill 的角色提示词
    use_studio_context: bool = True
    asset_mode: str = "bound"    # 资产过滤模式


@dataclass
class PlannerResponse:
    """Planner 返回结果"""
    text: str = ""
    applied_actions: int = 0
    steps: int = 0
    warnings: List[str] = field(default_factory=list)
    confirmation: str = ""
    documents_written: List[str] = field(default_factory=list)


@dataclass
class PlannerEvent:
    """流式事件"""
    type: str = "delta"          # delta | status | actions_applied | done | error
    text: str = ""
    payload: Optional[Dict[str, Any]] = None


class Planner:
    """
    对话式 Agent 核心（Rule1: 唯一入口）。

    持有：
    - llm_adapter: LLM 对话能力（直接持有，不经 ToolManager）
    - tool_manager: 业务 Tool 注册表（故事板 CRUD、生图、文档等）
    - state_manager: 状态写入唯一入口（Rule3）
    - workflow_engine: 工作流推进（可选）
    """

    def __init__(
        self,
        state_manager: Optional[StateManager] = None,
        tool_manager: Optional[type] = None,   # ToolManager 是类级别注册，传类引用
        llm_adapter: Optional[BaseChatAdapter] = None,
        workflow_engine: Optional[WorkflowEngine] = None,
    ):
        self.state_manager = state_manager
        self.tool_manager = tool_manager or ToolManager
        self.llm_adapter = llm_adapter
        self.workflow_engine = workflow_engine

    # ---------- 核心对话入口 ----------

    async def handle_message(
        self,
        user_message: str,
        context: PlannerContext,
    ) -> PlannerResponse:
        """
        非流式对话处理（多步循环）。
        委托给 run_agent_loop 统一循环骨架，内部通过 llm_call 包装器处理双模式（FC / 文本解析）。
        """
        self._current_context = context

        # 构建 executor（文本解析路径用）
        svc = StateManager.get_instance()
        executor = StudioActionExecutor(
            svc,
            selected_draft_id=context.selected_draft_id,
            selected_type=context.selected_type,
        )

        # 包装 llm_call：处理 FC tool_calls 后返回 (content, finish_reason, fc_applied)
        async def llm_call(system_prompt: str, messages: List[Dict[str, Any]]) -> tuple:
            response = await self._call_llm(system_prompt, messages)
            # FC 路径：内部执行 tool_calls，返回已执行数量
            if response.tool_calls:
                fc_applied, fc_confirmation = await self._execute_fc_tools(response)
                # 确认信号：通过 studio-actions 块传递给 loop 处理
                if fc_confirmation:
                    content = response.content + f'\n```studio-actions\n[{{"action": "request_confirmation", "message": "{fc_confirmation}"}}]\n```'
                    return content, response.finish_reason, 0  # 确认走文本解析路径
                return response.content, response.finish_reason, fc_applied
            return response.content, response.finish_reason, 0

        # 构建 context_builder
        def context_builder() -> str:
            return self._build_system_prompt(context)

        # 委托给统一循环
        loop_result = await run_agent_loop(
            user_message,
            llm_call=llm_call,
            context_builder=context_builder,
            executor=executor,
            history=context.history,
            max_steps=MAX_STEPS,
        )

        # 转换为 PlannerResponse
        return PlannerResponse(
            text=loop_result.text,
            applied_actions=loop_result.applied_actions,
            steps=loop_result.steps,
            warnings=loop_result.warnings,
            confirmation=loop_result.confirmation,
            documents_written=executor.documents_written,
        )

    async def handle_message_stream(
        self,
        user_message: str,
        context: PlannerContext,
    ) -> AsyncGenerator[PlannerEvent, None]:
        """
        流式对话处理（SSE 穿透）。

        事件类型：
        - delta: 可见文本增量
        - status: 阶段提示
        - actions_applied: 操作已执行
        - done: 最终结果
        - error: 失败
        """
        messages = list(context.history) + [{"role": "user", "content": user_message}]
        result = PlannerResponse()

        for step in range(1, MAX_STEPS + 1):
            result.steps = step
            yield PlannerEvent(type="status", text=f"第 {step} 轮推理中…" if step > 1 else "正在推理…")

            system = self._build_system_prompt(context)

            # 流式调用 LLM
            content_parts: List[str] = []
            finish_reason = ""
            try:
                async for chunk in self._call_llm_stream(system, messages):
                    if chunk.type == "text_delta" and chunk.text:
                        # 过滤 studio-actions 块（不喷到前端）
                        content_parts.append(chunk.text)
                        # 简化：只转发围栏前的文本
                        full_so_far = "".join(content_parts)
                        if "```" not in full_so_far:
                            yield PlannerEvent(type="delta", text=chunk.text)
                    elif chunk.type == "tool_call":
                        yield PlannerEvent(type="status", text="正在执行操作…")
            except Exception as e:
                yield PlannerEvent(type="error", text=str(e))
                return

            full_content = "".join(content_parts)
            response = ChatResponse(content=full_content, finish_reason=finish_reason)

            # 执行工具
            applied, confirmation, wants_continue = await self._execute_response(response)
            result.applied_actions += applied
            if applied:
                yield PlannerEvent(type="actions_applied", text=f"已应用 {applied} 个操作")

            visible = strip_action_blocks(full_content)
            if visible:
                result.text = f"{result.text}\n\n{visible}".strip() if result.text else visible

            if confirmation:
                result.confirmation = confirmation
                break
            if not wants_continue:
                break
            if step == MAX_STEPS:
                result.warnings.append(f"已达到多步上限（{MAX_STEPS} 轮）")
                break

            messages.append({"role": "assistant", "content": full_content})
            messages.append({
                "role": "user",
                "content": f"（系统）第 {step} 轮操作已执行，请继续。",
            })

        if not result.text:
            result.text = "已更新。" if result.applied_actions else "（无回复）"

        yield PlannerEvent(type="done", payload={
            "text": result.text,
            "applied_actions": result.applied_actions,
            "steps": result.steps,
            "warnings": result.warnings,
            "confirmation": result.confirmation,
        })

    # ---------- 内部方法 ----------

    def _build_system_prompt(self, context: PlannerContext) -> str:
        """构建 system prompt：从 prompts/ 加载 + 注入状态上下文"""
        parts: List[str] = []

        # 前端 skill 角色提示词
        if context.extra_system:
            parts.append(context.extra_system.strip())

        if context.use_studio_context:
            # Rule4: 从 prompts/ 目录加载
            protocol = load_prompt("planner/system.md")
            if protocol:
                parts.append(protocol)

            # 注入状态上下文
            if context.selected_draft_id:
                parts.append(
                    f"\n用户当前选中的草稿：draft_id={context.selected_draft_id}"
                    f"（类型 {context.selected_type or '未知'}）。studio-actions 里的 \"current\" 指向它。"
                )
            if context.state_json:
                parts.append("当前工作台状态 JSON 如下（每轮自动刷新）：\n\n" + context.state_json)

        return "\n\n".join(parts)

    async def _call_llm(self, system: str, messages: List[Dict[str, Any]]) -> ChatResponse:
        """
        双模式 LLM 调用（§2.2）：
        - 模式 A：adapter 支持 function calling → 传入 tool schemas
        - 模式 B：不支持 → 纯文本调用，从回复中解析 studio-actions
        """
        full_messages = [{"role": "system", "content": system}] + messages

        if self.llm_adapter is None:
            # 无 adapter 时返回空响应（mock 路径由上层处理）
            return ChatResponse(content="", finish_reason="stop")

        if self.llm_adapter.supports_function_calling:
            # 模式 A：标准 function calling
            tools_schema = self.tool_manager.get_all_tool_schemas()
            return await self.llm_adapter.chat(full_messages, tools=tools_schema)
        else:
            # 模式 B：纯文本（fallback 到 studio-actions 文本解析）
            return await self.llm_adapter.chat(full_messages)

    async def _call_llm_stream(self, system: str, messages: List[Dict[str, Any]]) -> AsyncGenerator[StreamChunk, None]:
        """流式 LLM 调用"""
        full_messages = [{"role": "system", "content": system}] + messages

        if self.llm_adapter is None:
            return

        tools_schema = None
        if self.llm_adapter.supports_function_calling:
            tools_schema = self.tool_manager.get_all_tool_schemas()

        async for chunk in self.llm_adapter.chat_stream(full_messages, tools=tools_schema):
            yield chunk

    async def _execute_fc_tools(self, response: ChatResponse) -> Tuple[int, str]:
        """执行 Function Calling 返回的 tool_calls。返回 (applied_count, confirmation_message)"""
        applied = 0
        confirmation = ""
        for call in response.tool_calls:
            func = call.get("function", {}) if isinstance(call, dict) else {}
            name = func.get("name", "")
            args_raw = func.get("arguments", "{}")
            try:
                args = json.loads(args_raw) if isinstance(args_raw, str) else args_raw
            except json.JSONDecodeError:
                args = {}

            result = await self.tool_manager.invoke_tool(name, args)
            if result.success:
                applied += 1
                if name == "workflow_pause":
                    confirmation = args.get("message", "请确认以上内容。")
            else:
                logger.warning(f"[Planner] Tool '{name}' failed: {result.error}")
        return applied, confirmation

    async def _execute_response(self, response: ChatResponse) -> Tuple[int, str, bool]:
        """
        执行 LLM 响应中的工具调用。

        返回 (applied_count, confirmation_message, wants_continue)

        双路径：
        - response.tool_calls 非空 → 通过 ToolManager 执行（Function Calling 模式）
        - 否则 → 从文本中解析 studio-actions（文本解析 fallback）
        """
        applied = 0
        confirmation = ""
        wants_continue = False

        # 路径 A：Function Calling 返回的 tool_calls
        if response.tool_calls:
            applied, confirmation = await self._execute_fc_tools(response)

        # 路径 B：文本解析 studio-actions（fallback / 兼容现有协议）
        if not response.tool_calls and response.content:
            applied, confirmation, wants_continue = self._parse_and_execute_text(response.content)

        return applied, confirmation, wants_continue

    def _parse_and_execute_text(self, content: str) -> Tuple[int, str, bool]:
        """从文本中解析 studio-actions 并执行（复用 agent_loop.split_actions）"""
        svc = StateManager.get_instance()
        ctx = getattr(self, '_current_context', None)
        executor = StudioActionExecutor(
            svc,
            selected_draft_id=ctx.selected_draft_id if ctx else "",
            selected_type=ctx.selected_type if ctx else "",
        )
        actions = executor.parse_actions_from_reply(content)

        if not actions:
            return 0, "", False

        executable, wants_continue, confirmation = split_actions(actions)
        applied = executor.execute(executable)
        return applied, confirmation, wants_continue

    # ---------- 兼容旧接口（CLI 用） ----------

    async def analyze_request(self, user_goal: str) -> None:
        """兼容旧 CLI 入口 — 通过 StateManager.update() 写入（Rule3）"""
        if not self.state_manager:
            return
        self.state_manager.update("user_goal", user_goal)
        self.state_manager.update("plan.style", "Cinematic")
        self.state_manager.update("plan.duration_seconds", 10)
        self.state_manager.update("status", "in_progress")
        logger.info("[Planner] Planning complete (legacy mode).")

    async def auto_resolve_workflow(self, workflow_name: str = "default_video_line") -> str:
        """兼容旧 CLI 入口"""
        logger.info(f"[Planner] Resolving workflow blueprint: {workflow_name}")
        return workflow_name
