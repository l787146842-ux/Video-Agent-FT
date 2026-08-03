"""
Planner — 对话式 Agent 的唯一入口（Rule1）。

设计方案核心：
- Planner 直接持有 LLM Adapter 引用（Rule6: 外部调用走 Adapter），不经过 Tool Manager
- Tool Manager 只管理"业务 Tool"（故事板操作、生图、文档等）
- 双模式兼容：Function Calling + 文本解析 fallback（Rule2）
- 多步循环（MAX_STEPS），LLM 可请求 continue 推进下一轮
- 流式通过 AsyncGenerator 穿透（SSE）
"""
import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Callable, Dict, List, Optional, Tuple, Union

from loguru import logger

from src.video_agent.adapters.base_chat import BaseChatAdapter, ChatResponse, StreamChunk
from src.video_agent.config import settings
from src.video_agent.core.token_budget import truncate_messages
from src.video_agent.memory import MemoryManager
from src.video_agent.state.manager import StateManager
from src.video_agent.tools.manager import ToolManager
from src.video_agent.utils.prompts import load_prompt, render_prompt
from src.video_agent.web.actions import StudioActionExecutor
from src.video_agent.web.agent_loop import MAX_STEPS, run_agent_loop
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
    image_generation_provider: str = ""  # 选中草稿的生图 provider，用于强制注入
    image_generation_aspect_ratio: str = ""  # 选中草稿的画面比例（如 16:9），用于强制注入


@dataclass
class PlannerResponse:
    """Planner 返回结果"""
    text: str = ""
    applied_actions: int = 0
    steps: int = 0
    warnings: List[str] = field(default_factory=list)
    confirmation: str = ""
    documents_written: List[str] = field(default_factory=list)
    image_urls: List[str] = field(default_factory=list)  # generate_image 工具产出的图片 URL
    # 待插入前端对话输入框的故事板媒体（insert_chat_media / storyboard_media_to_chat 产出）
    chat_inserts: List[Dict[str, Any]] = field(default_factory=list)
    # 已执行操作的中文描述清单（前端「阶段完成」卡片展开用，随消息持久化）
    action_log: List[str] = field(default_factory=list)
    # 执行轨迹（每轮 step/耗时/操作数），前端「执行轨迹」折叠区展示
    trace: Dict[str, Any] = field(default_factory=dict)


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
        stream_hook=None,
        on_event=None,
    ) -> PlannerResponse:
        """
        对话处理（多步循环）—— 流式/非流式统一入口。
        委托给 run_agent_loop 统一循环骨架，内部通过 llm_call 包装器处理双模式（FC / 文本解析）。
        stream_hook: 可选 async callable(text)，流式模式下每段 LLM 增量文本回调。
        """
        # 构建 executor（文本解析路径用）
        svc = StateManager.get_instance()
        executor = StudioActionExecutor(
            svc,
            selected_draft_id=context.selected_draft_id,
            selected_type=context.selected_type,
        )

        # 包装 llm_call：处理 FC tool_calls 后返回 (content, finish_reason, fc_applied)
        # image_urls_collector 用于跨多步收集生图产物
        image_urls_collector: List[str] = []
        # chat_inserts_collector 用于跨多步收集「插入对话输入框」的媒体
        chat_inserts_collector: List[Dict[str, Any]] = []
        # action_log_collector 用于跨多步收集 FC 工具的操作描述
        action_log_collector: List[str] = []

        async def _emit_status(text: str) -> None:
            """推理过程可视化：把 FC 工具执行进度实时推给前端状态栏"""
            if on_event is not None:
                await on_event({"type": "status", "text": text})

        async def llm_call(system_prompt: str, messages: List[Dict[str, Any]], hook=None) -> tuple:
            # 流式路径：使用 chat_stream + hook 回调
            if hook:
                content_parts: List[str] = []
                finish = ""
                stream_tool_calls: List[Dict[str, Any]] = []
                async for chunk in self._call_llm_stream(system_prompt, messages):
                    if chunk.type == "text_delta" and chunk.text:
                        content_parts.append(chunk.text)
                        full_so_far = "".join(content_parts)
                        if "```" not in full_so_far:
                            await hook(chunk.text)
                    elif chunk.type == "tool_call":
                        stream_tool_calls.append({
                            "id": f"call_stream_{len(stream_tool_calls)}",
                            "type": "function",
                            "function": {
                                "name": chunk.tool_name,
                                "arguments": json.dumps(chunk.tool_args, ensure_ascii=False),
                            },
                        })
                    elif chunk.type == "done":
                        finish = chunk.finish_reason or "stop"
                content = "".join(content_parts)
                response = ChatResponse(content=content, finish_reason=finish, tool_calls=stream_tool_calls)
            else:
                response = await self._call_llm(system_prompt, messages)

            return await self._handle_fc_response(
                response,
                image_urls_collector=image_urls_collector,
                chat_inserts_collector=chat_inserts_collector,
                action_log_collector=action_log_collector,
                image_provider=context.image_generation_provider,
                image_aspect_ratio=context.image_generation_aspect_ratio,
                on_status=_emit_status,
            )

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
            stream_hook=stream_hook,
            on_event=on_event,
        )

        # 转换为 PlannerResponse（chat_inserts：FC 路径收集 + 文本解析路径 executor 收集，按 URL 去重）
        merged_inserts: List[Dict[str, Any]] = []
        seen_urls = set()
        for it in (chat_inserts_collector + executor.chat_inserts):
            u = it.get("url")
            if u and u not in seen_urls:
                seen_urls.add(u)
                merged_inserts.append(it)
        response = PlannerResponse(
            text=loop_result.text,
            applied_actions=loop_result.applied_actions,
            steps=loop_result.steps,
            warnings=loop_result.warnings,
            confirmation=loop_result.confirmation,
            documents_written=executor.documents_written,
            image_urls=image_urls_collector,
            chat_inserts=merged_inserts,
            action_log=action_log_collector + executor.action_log,
            trace=loop_result.trace,
        )

        # 记忆系统：后台异步记录本轮对话（不阻塞响应流）
        if settings.memory_enabled:
            MemoryManager.get_instance().record_dialog_background(
                user_message, loop_result.text, self._make_summarize_fn()
            )

        return response

    async def handle_message_stream(
        self,
        user_message: str,
        context: PlannerContext,
    ) -> AsyncGenerator[PlannerEvent, None]:
        """
        流式对话处理（SSE 穿透）—— 委托给统一的 handle_message + stream_hook。

        事件类型：
        - delta: 可见文本增量
        - status: 阶段提示
        - actions_applied: 操作已执行
        - done: 最终结果
        - error: 失败
        """
        queue: asyncio.Queue = asyncio.Queue()

        async def on_delta(text: str) -> None:
            await queue.put(PlannerEvent(type="delta", text=text))

        async def on_event(event: Dict[str, Any]) -> None:
            etype = event.get("type", "")
            if etype == "step_started":
                step = event.get("step", 1)
                await queue.put(PlannerEvent(
                    type="status",
                    text=(f"第 {step} 轮推理中…（执行上轮操作后继续规划）" if step > 1
                          else "正在推理…（模型正在阅读状态并规划操作）"),
                ))
            elif etype == "actions_applied":
                count = event.get("count", 0)
                await queue.put(PlannerEvent(type="actions_applied", text=f"已应用 {count} 个操作"))
            elif etype == "executing_actions":
                await queue.put(PlannerEvent(type="status", text="正在执行操作…"))

        # 在后台任务中运行统一循环，通过 queue 穿透事件
        result_holder: List[PlannerResponse] = []
        error_holder: List[str] = []

        async def _run():
            try:
                resp = await self.handle_message(
                    user_message, context, stream_hook=on_delta, on_event=on_event
                )
                result_holder.append(resp)
            except Exception as e:
                error_holder.append(str(e))
            finally:
                await queue.put(None)  # 哨兵：结束

        task = asyncio.create_task(_run())

        # 消费队列事件并 yield
        while True:
            item = await queue.get()
            if item is None:
                break
            yield item

        # 处理结果
        if error_holder:
            yield PlannerEvent(type="error", text=error_holder[0])
            return

        result = result_holder[0] if result_holder else PlannerResponse()
        if not result.text:
            result.text = "已更新。" if result.applied_actions else "（无回复）"

        yield PlannerEvent(type="done", payload={
            "text": result.text,
            "applied_actions": result.applied_actions,
            "steps": result.steps,
            "warnings": result.warnings,
            "confirmation": result.confirmation,
            "documents_written": result.documents_written,
            "image_urls": result.image_urls,
            "chat_inserts": result.chat_inserts,
            "action_log": result.action_log,
            "trace": result.trace,
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

            # 混合记忆检索注入（语义 + 关键词 + 时间衰减）
            if settings.memory_enabled:
                query = self._last_user_text(context)
                if query:
                    memory_ctx = MemoryManager.get_instance().build_context(query)
                    if memory_ctx:
                        parts.append(memory_ctx)

        return "\n\n".join(parts)

    @staticmethod
    def _last_user_text(context: PlannerContext) -> str:
        """从历史中取最近一条用户消息作为记忆检索 query"""
        for msg in reversed(context.history or []):
            if msg.get("role") == "user":
                content = msg.get("content", "")
                if isinstance(content, str):
                    return content
                if isinstance(content, list):
                    return " ".join(
                        str(p.get("text", "")) for p in content
                        if isinstance(p, dict) and p.get("type") == "text"
                    )
        return ""

    def _make_summarize_fn(self):
        """用当前 LLM adapter 包装摘要调用；无 adapter 返回 None（降级截取）"""
        if self.llm_adapter is None:
            return None

        async def _fn(prompt: str) -> str:
            resp = await self._call_llm(
                "你是记忆整理助手。",
                [{"role": "user", "content": prompt}],
            )
            return resp.content or ""

        return _fn

    async def _call_llm(self, system: str, messages: List[Dict[str, Any]]) -> ChatResponse:
        """
        双模式 LLM 调用（§2.2）：
        - 模式 A：adapter 支持 function calling → 传入 tool schemas
        - 模式 B：不支持 → 纯文本调用，从回复中解析 studio-actions
        """
        full_messages = [{"role": "system", "content": system}] + messages
        # Token 预算截断：超过上下文窗口比例时自动截断历史
        max_tokens = int(settings.context_window_size * settings.token_budget_ratio)
        full_messages = truncate_messages(full_messages, max_tokens)

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
        # Token 预算截断
        max_tokens = int(settings.context_window_size * settings.token_budget_ratio)
        full_messages = truncate_messages(full_messages, max_tokens)

        if self.llm_adapter is None:
            return

        tools_schema = None
        if self.llm_adapter.supports_function_calling:
            tools_schema = self.tool_manager.get_all_tool_schemas()

        async for chunk in self.llm_adapter.chat_stream(full_messages, tools=tools_schema):
            yield chunk

    async def _handle_fc_response(
        self,
        response: ChatResponse,
        image_urls_collector: Optional[List[str]] = None,
        chat_inserts_collector: Optional[List[Dict[str, Any]]] = None,
        action_log_collector: Optional[List[str]] = None,
        image_provider: str = "",
        image_aspect_ratio: str = "",
        on_status=None,
    ) -> Tuple:
        """处理 LLM 响应中的 FC tool_calls，返回 (content, finish_reason, fc_applied)"""
        if response.tool_calls:
            fc_applied, fc_confirmation, image_urls, chat_inserts, fc_action_log = await self._execute_fc_tools(
                response, image_provider=image_provider, image_aspect_ratio=image_aspect_ratio,
                on_status=on_status,
            )
            if image_urls_collector is not None:
                image_urls_collector.extend(image_urls)
            if chat_inserts_collector is not None:
                chat_inserts_collector.extend(chat_inserts)
            if action_log_collector is not None:
                action_log_collector.extend(fc_action_log)
            if fc_confirmation:
                confirm_block = json.dumps(
                    [{"action": "request_confirmation", "message": fc_confirmation}],
                    ensure_ascii=False,
                )
                content = response.content + f"\n```studio-actions\n{confirm_block}\n```"
                return content, response.finish_reason, 0
            return response.content, response.finish_reason, fc_applied
        return response.content, response.finish_reason, 0

    async def _execute_fc_tools(
        self, response: ChatResponse, image_provider: str = "", image_aspect_ratio: str = "",
        on_status=None,
    ) -> Tuple[int, str, List[str], List[Dict[str, Any]], List[str]]:
        """执行 Function Calling 返回的 tool_calls。
        返回 (applied_count, confirmation_message, image_urls, chat_inserts, action_log)"""
        applied = 0
        confirmation = ""
        image_urls: List[str] = []
        chat_inserts: List[Dict[str, Any]] = []
        action_log: List[str] = []
        for call in response.tool_calls:
            func = call.get("function", {}) if isinstance(call, dict) else {}
            name = func.get("name", "")
            args_raw = func.get("arguments", "{}")
            try:
                args = json.loads(args_raw) if isinstance(args_raw, str) else args_raw
            except json.JSONDecodeError:
                args = {}

            # --- 生图模型强制注入：用中间面板选中的 provider 覆盖 mock ---
            if name == "generate_image" and image_provider:
                if "adapter_provider" not in args or args.get("adapter_provider") in ("mock", "", None):
                    args["adapter_provider"] = image_provider
                    logger.info("[Planner] Injected image gen provider from draft: %s",
                                image_provider)
            # --- 画面比例注入：用中间面板选中的比例 ---
            if name == "generate_image" and image_aspect_ratio:
                if not args.get("aspect_ratio"):
                    args["aspect_ratio"] = image_aspect_ratio
                    logger.info("[Planner] Injected image gen aspect ratio from draft: %s",
                                image_aspect_ratio)

            result = await self.tool_manager.invoke_tool(name, args)
            if result.success:
                applied += 1
                if name == "workflow_pause":
                    confirmation = args.get("message", "请确认以上内容。")
                desc = self._describe_fc_tool(name, args)
                action_log.append(desc)
                # 推理过程可视化：每完成一个工具就推一条状态
                if on_status is not None:
                    await on_status(f"已完成：{desc}")
                # --- 收集 generate_image 产出的图片 URL ---
                data = getattr(result, "data", None)
                if data and "image_urls" in data:
                    urls = data["image_urls"]
                    if isinstance(urls, list):
                        image_urls.extend(urls)
                # --- 收集 storyboard_media_to_chat 产出的对话输入框插入项 ---
                if data and "chat_inserts" in data:
                    inserts = data["chat_inserts"]
                    if isinstance(inserts, list):
                        chat_inserts.extend(inserts)
            else:
                logger.warning(f"[Planner] Tool '{name}' failed: {getattr(result, 'error', '')}")
        return applied, confirmation, image_urls, chat_inserts, action_log

    @staticmethod
    def _describe_fc_tool(name: str, args: Dict[str, Any]) -> str:
        """FC 工具的中文简述（与 studio-actions 描述风格对齐）"""
        title = str(args.get("title") or "").strip()
        draft_id = str(args.get("draft_id") or "").strip()
        label = str(args.get("label") or "").strip()
        doc = str(args.get("key") or args.get("name") or "").strip()
        if name == "storyboard_create_group":
            return f"新建分组「{title or '未命名'}」"
        if name == "storyboard_patch_draft":
            return f"更新草稿「{label or draft_id or '当前草稿'}」"
        if name == "storyboard_add_draft":
            return f"新增草稿「{label or '未命名'}」"
        if name == "storyboard_delete_group":
            return f"删除分组 {args.get('group_id', '')}"
        if name == "storyboard_confirm_draft":
            return f"确认草稿「{label or draft_id or '当前草稿'}」"
        if name == "storyboard_media_to_chat":
            return "插入故事板媒体到对话输入框"
        if name == "document_write":
            return f"写入文档「{doc or '未命名'}」"
        if name in ("generate_image", "image_generate"):
            return "发起生图"
        if name == "generate_video":
            return "发起视频生成"
        if name == "workflow_pause":
            return "请求阶段确认"
        return f"执行工具 {name}"

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
