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
from dataclasses import dataclass, field, replace as dc_replace
from typing import Any, AsyncGenerator, Callable, Dict, List, Optional, Tuple, Union

from loguru import logger

from src.video_agent.adapters.base_chat import BaseChatAdapter, ChatResponse, StreamChunk
from src.video_agent.config import settings
from src.video_agent.core.token_budget import context_window_for_model, estimate_messages_tokens, truncate_messages
from src.video_agent.memory import MemoryManager
from src.video_agent.state.manager import StateManager
from src.video_agent.tools.base import ToolResult
from src.video_agent.tools.manager import ToolManager
from src.video_agent.utils.prompts import load_prompt, render_prompt
from src.video_agent.core.agent_loop import MAX_STEPS, run_agent_loop
from src.video_agent.core.fc_tool_runner import (
    FEEDBACK_COMPRESSED,
    FEEDBACK_FULL_TOOLS,
    FEEDBACK_MARKER,
    FEEDBACK_MAX_TOTAL_CHARS,
    FCToolRunner,
    compress_prior_feedback,
    describe_fc_tool,
    format_tool_results,
    render_read_result,
    should_compress_feedback,
    strip_prior_feedback_images,
)
from src.video_agent.core.prompt_builder import PromptBuilder
from src.video_agent.core import prompt_gates
from src.video_agent.core.sse_events import SSE_ACTIONS_APPLIED, SSE_REASONING_DELTA, SSE_STATUS
from src.video_agent.core.stream_suppressor import StreamActionSuppressor  # re-export 兼容旧导入
from src.video_agent.core.tracer import AgentTracer
from src.video_agent.skill_runtime.registry import fallback_skill_from_state
from src.video_agent.workflows.engine import WorkflowEngine


# 绑定工作台状态的工具集：use_studio_context=False 时不下发（节省 schema token）
_STUDIO_STATE_TOOLS = frozenset({
    "storyboard_create_group", "storyboard_patch_draft", "storyboard_add_draft",
    "storyboard_delete_group", "storyboard_confirm_draft", "storyboard_media_to_chat",
    "view_storyboard_media",
    "read_draft", "document_write", "read_uploaded_doc", "read_project_doc",
})

# 画布工具集：画布离线/未启用时不下发（节省 schema token）
_CANVAS_TOOLS = frozenset({
    "canvas_list", "canvas_read_nodes", "canvas_add_node", "canvas_update_node",
    "canvas_delete_node", "canvas_list_assets", "canvas_batch_add_nodes",
})


@dataclass
class PlannerContext:
    """每轮对话的上下文参数"""
    history: List[Dict[str, Any]] = field(default_factory=list)
    selected_draft_id: str = ""
    selected_type: str = ""
    state_json: str = ""
    # 状态 JSON 的惰性构建器（P0 修复）：多步循环每一轮都会调用一次，
    # 保证模型在每轮看到上一轮执行后的最新工作台状态。
    # 传入 state_json 字符串是旧调用方式的兼容降级（整段固定不变）。
    state_builder: Optional[Callable[[], str]] = None
    skill_name: str = ""         # 前端当前选中的 Skill 名称（目录标注用，提高相关性判断准确率）
    use_studio_context: bool = True
    asset_mode: str = "bound"    # 资产过滤模式
    image_generation_provider: str = ""  # 选中草稿的生图 provider，用于强制注入
    image_generation_aspect_ratio: str = ""  # 选中草稿的画面比例（如 16:9），用于强制注入
    # 降级状态构建器（token 保险丝）：system 段超预算时用「只留组标题/计数」的
    # 降级状态 JSON 重建 system prompt，保证请求不超窗发出
    degraded_state_builder: Optional[Callable[[], str]] = None
    # 本轮记忆检索命中明细（4.7：随 done payload 下发前端可视化）
    memory_hits: List[Dict[str, Any]] = field(default_factory=list)


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
    # 确认卡片的候选选项（每项 {label, description}，前端渲染为单选卡片）
    confirmation_options: List[Dict[str, Any]] = field(default_factory=list)
    # 执行轨迹（每轮 step/耗时/操作数），前端「执行轨迹」折叠区展示
    trace: Dict[str, Any] = field(default_factory=dict)
    # 本轮记忆检索命中明细（4.7：随 done payload 下发前端可视化）
    memory_hits: List[Dict[str, Any]] = field(default_factory=list)


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
        executor_factory: Optional[Callable[..., Any]] = None,
        skill_docs: Optional[Any] = None,
        summary_adapter: Optional[BaseChatAdapter] = None,
        chat_provider: str = "",
        chat_model: str = "",
    ):
        # state_manager 缺省回落单例（Rule3）；core 层不绕过它直接碰状态
        self.state_manager = state_manager or StateManager.get_instance()
        self.tool_manager = tool_manager or ToolManager
        self.llm_adapter = llm_adapter
        self.workflow_engine = workflow_engine
        # executor_factory: 文本解析路径的执行器工厂（web 层装配时显式注入，
        # 消除 core→web 顶层依赖；None 时延迟导入兼容测试/CLI 调用方）
        self.executor_factory = executor_factory
        # skill_docs: Skill 文档目录提供者（web.skill_docs 模块或等价对象），None 时延迟导入
        self._skill_docs = skill_docs
        # 记忆摘要专用 adapter（None = 跟随主模型）；由 web 层按
        # settings.memory_summary_model / fallback 链末位装配
        self.summary_adapter = summary_adapter
        # 当前对话聊天供应商（决策 E：执行器与主模型一致；web 层注入）
        self.chat_provider = chat_provider
        self.chat_model = chat_model
        # 按上下文裁剪的工具集合（handle_message 时计算）
        self._excluded_tools: frozenset = frozenset()
        # system 超预算时的降级重建器（handle_message 时按 context 装配）
        self._system_degrader: Optional[Callable[[str], str]] = None
        # 拆出的协作臂（批次5）：prompt 组装与 FC 执行，Planner 保留同名委托
        self._prompt_builder = PromptBuilder(
            self._get_skill_docs,
            lambda: self.state_manager.active_project_id,
            # 分阶段聚焦注入：实时读取工作台状态推断当前制作阶段
            lambda: self.state_manager.state_dict,
        )
        self._fc_runner = FCToolRunner(self.tool_manager)
        self._fc_runner.chat_provider = self.chat_provider
        self._fc_runner.chat_model = self.chat_model

    def _get_skill_docs(self):
        """Skill 文档提供者：优先注入实例，缺省延迟导入 web.skill_docs（Rule2 登记例外）"""
        if self._skill_docs is None:
            from src.video_agent.web import skill_docs as sd
            self._skill_docs = sd
        return self._skill_docs

    # 阶段完成引导兜底（agent_loop 层 9）：执行器跑完但模型未暂停时，
    # 系统客观补下一步引导卡；本文件不承载流程 prose（归属见第十三章 13.3）

    def _compute_excluded_tools(self, context: PlannerContext) -> frozenset:
        """按上下文计算本轮不下发的工具集（token 治理：schema 全量常驻是每轮固定开销）"""
        excluded = set()
        if not context.use_studio_context:
            excluded |= _STUDIO_STATE_TOOLS
        if not settings.canvas_enabled:
            excluded |= _CANVAS_TOOLS
        else:
            # 已探测过且离线才裁剪；从未探测（None）保持现状
            from src.video_agent.adapters.canvas_adapter import canvas_online_cached
            if canvas_online_cached() is False:
                excluded |= _CANVAS_TOOLS
        # 混合形态第一层：阶段探测驱动的工具裁剪（仅 Skill 激活 + strict），
        # 用工具可见性隔离阶段；第二层由既有闸机兑底（文本轨不受裁剪影响）
        if context.skill_name and context.use_studio_context \
                and prompt_gates.gate_mode() == "strict":
            try:
                stage_excluded, _ = prompt_gates.stage_tool_restrictions(
                    self.state_manager.state_dict
                )
                excluded |= set(stage_excluded)
            except Exception:
                pass  # 裁剪失败不阻断对话，闸机层仍生效
        return frozenset(excluded)

    def _make_system_degrader(self, context: PlannerContext) -> Optional[Callable[[str], str]]:
        """system 超预算保险丝：用降级状态 JSON（只留组标题/计数）重建 system prompt。
        未提供 degraded_state_builder 时返回 None（truncate 维持原策略）。"""
        if context.degraded_state_builder is None:
            return None

        def _degrade(_system_text: str) -> str:
            degraded_ctx = dc_replace(
                context,
                state_builder=context.degraded_state_builder,
                state_json=context.degraded_state_builder(),
            )
            return self._build_system_prompt(degraded_ctx)

        return _degrade

    def _context_window(self) -> int:
        """当前模型的上下文窗口（按模型名查表，缺省回落全局配置）"""
        model = getattr(self.llm_adapter, "model", "") if self.llm_adapter else ""
        return context_window_for_model(model)

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
        # 当前 Skill 归属（7777 事故）：请求未携带 Skill 时回退项目 usedSkills 末位，
        # 保证后续轮次仍绑定同一执行器；单一实现见 registry.fallback_skill_from_state。
        if not context.skill_name:
            context.skill_name = fallback_skill_from_state(self.state_manager.state_dict)

        # 按上下文裁剪本轮下发的工具集 + 装配 system 超预算降级器（token 治理）
        self._excluded_tools = self._compute_excluded_tools(context)
        self._system_degrader = self._make_system_degrader(context)

        # 构建 executor（文本解析路径用）：优先注入的工厂，缺省延迟导入 web 层实现
        factory = self.executor_factory
        if factory is None:
            from src.video_agent.web.actions import StudioActionExecutor
            factory = StudioActionExecutor
        executor = factory(
            self.state_manager,
            selected_draft_id=context.selected_draft_id,
            selected_type=context.selected_type,
            # Skill 流程激活时打开提示词结构闸机（写入即校验，不合格打回重写）；
            # 旧工厂签名不认 gate_enabled 时静默回退（兼容测试 stub）
        )
        if context.skill_name:
            try:
                executor.gate_enabled = True
            except Exception:
                pass
        # 流式增量执行计数重置（边写边填：上次调用的残留不得带入本次）
        try:
            executor.stream_preapplied = 0
            executor.stream_consumed = 0
        except Exception:
            pass

        # 包装 llm_call：处理 FC tool_calls 后返回 (content, finish_reason, fc_applied)
        # image_urls_collector 用于跨多步收集生图产物
        image_urls_collector: List[str] = []
        # chat_inserts_collector 用于跨多步收集「插入对话输入框」的媒体
        chat_inserts_collector: List[Dict[str, Any]] = []
        # action_log_collector 用于跨多步收集 FC 工具的操作描述
        action_log_collector: List[str] = []
        # confirmation_options_collector 用于跨多步收集确认卡片的候选选项
        confirmation_options_collector: List[Dict[str, Any]] = []
        # docs_written_collector 用于跨多步收集 FC 轨写入的文档名（渲染文档卡片）
        docs_written_collector: List[str] = []

        async def _emit_status(text: str) -> None:
            """推理过程可视化：把 FC 工具执行进度实时推给前端状态栏"""
            if on_event is not None:
                await on_event({"type": SSE_STATUS, "text": text})

        async def _emit_event(event: Dict[str, Any]) -> None:
            """过程时间线事件透传（tool_started/tool_finished）"""
            if on_event is not None:
                await on_event(event)

        tracer = AgentTracer.get_instance()

        async def llm_call(system_prompt: str, messages: List[Dict[str, Any]], hook=None) -> tuple:
            # 流式路径：使用 chat_stream + hook 回调
            if hook:
                content_parts: List[str] = []
                finish = ""
                stream_tool_calls: List[Dict[str, Any]] = []
                suppressor = StreamActionSuppressor()
                # 边写边填：studio-actions 块内每个 JSON 对象一流式闭合就立即执行，
                # 草稿卡片逐张填充，不等全部写完一次性弹出
                from src.video_agent.web.action_parser import StreamingActionExtractor
                extractor = StreamingActionExtractor()
                async for chunk in self._call_llm_stream(system_prompt, messages):
                    if chunk.type == "text_delta" and chunk.text:
                        content_parts.append(chunk.text)
                        # P2-1：仅屏蔽 studio-actions 围栏，普通代码块照常推送
                        out = suppressor.feed(chunk.text)
                        if out:
                            await hook(out)
                        # 被抑制的动作块内容喂给增量提取器，闭合即执行
                        if suppressor.suppressed:
                            for act in extractor.feed(suppressor.suppressed):
                                # 流程信号（continue/确认）不预执行，留待循环末尾统一处理
                                if not executor._is_mutating(act):
                                    continue
                                executor.stream_consumed += 1
                                try:
                                    if executor.execute([act], accumulate=True):
                                        executor.stream_preapplied += 1
                                        if on_event is not None:
                                            await on_event({
                                                "type": SSE_ACTIONS_APPLIED,
                                                "count": 1,
                                            })
                                except Exception as e:
                                    logger.warning(f"[Planner] 流式增量执行失败: {act} -> {e}")
                            suppressor.suppressed = ""
                    elif chunk.type == "reasoning_delta" and chunk.text:
                        # 深度思考：记入 trace（持久化展示）+ 实时推给前端，不进 LLM 上下文
                        tracer.record_reasoning(chunk.text)
                        if on_event is not None:
                            await on_event({"type": SSE_REASONING_DELTA, "text": chunk.text})
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
                tail = suppressor.flush()
                if tail:
                    await hook(tail)
                content = "".join(content_parts)
                response = ChatResponse(content=content, finish_reason=finish, tool_calls=stream_tool_calls)
            else:
                response = await self._call_llm(system_prompt, messages)

            content, finish, fc_applied, tool_results = await self._handle_fc_response(
                response,
                image_urls_collector=image_urls_collector,
                chat_inserts_collector=chat_inserts_collector,
                action_log_collector=action_log_collector,
                confirmation_options_collector=confirmation_options_collector,
                docs_written_collector=docs_written_collector,
                image_provider=context.image_generation_provider,
                image_aspect_ratio=context.image_generation_aspect_ratio,
                on_status=_emit_status,
                on_event=_emit_event,
                injected_skill=context.skill_name,
                selected_draft_id=context.selected_draft_id,
                selected_type=context.selected_type,
            )
            # 渐进式披露的回路关键：read_* 工具读回的全文必须回喂进 messages，
            # 否则模型「读了个寂寞」，Skill 流程/规格约束根本不进上下文
            if tool_results:
                feedback = Planner._format_tool_results(tool_results)
                if feedback:
                    if context.skill_name:
                        reminder = (
                            "\n【提醒】当前有选中 Skill：遵守其阶段划分与暂停点，"
                            "到达确认点时用 request_confirmation / workflow_pause 真正停下，不要一口气做完全部阶段。"
                        )
                        if isinstance(feedback, list):
                            feedback = feedback + [{"type": "text", "text": reminder}]
                        else:
                            feedback += reminder
                    # token 治理（P1）：新一轮回喂入库前，把更早轮次的 read_* 全文
                    # 回喂压缩为一句话占位，避免多份全文在 messages 里叠加计费。
                    # 惰性压缩（质量优化）：仅当消息总量逼近 token 预算时才压，
                    # 短对话保留全文；选中 Skill 不受影响（它硬注入在 system prompt 里）
                    if Planner._should_compress_feedback(messages):
                        Planner._compress_prior_feedback(messages)
                    # 按需调图：新回喂带图片时，先剥离旧轮已加载的图片，
                    # 上下文始终只保留最新一轮的画面（vision token 治理）
                    if isinstance(feedback, list):
                        strip_prior_feedback_images(messages)
                    messages.append({"role": "user", "content": feedback})
            return content, finish, fc_applied

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

        # 纯工具轮无总结文字时，用实际操作清单替换无信息量的占位文案：
        # 占位文案进入历史后模型看不出上一轮做了什么（读文档/写文档/请求确认），
        # 用户下一条「确认」进来就会失去参照、从头重复同一套操作
        # 粗粒度聚合（Rule: 阶段反馈不逐卡罗列）：延迟导入 web 层描述工具（同 executor_factory 回落模式）
        from src.video_agent.web.action_descriptions import aggregate_action_log
        if loop_result.applied_actions and (
            not loop_result.text.strip() or "模型未输出总结文字" in loop_result.text
        ):
            merged_log = aggregate_action_log(action_log_collector + executor.action_log)
            if merged_log:
                loop_result.text = (
                    f"已执行 {loop_result.applied_actions} 个操作：" + "；".join(merged_log[:12])
                )

        # 转换为 PlannerResponse（chat_inserts：FC 路径收集 + 文本解析路径 executor 收集，按 URL 去重）
        merged_inserts: List[Dict[str, Any]] = []
        seen_urls = set()
        for it in (chat_inserts_collector + executor.chat_inserts):
            u = it.get("url")
            if u and u not in seen_urls:
                seen_urls.add(u)
                merged_inserts.append(it)
        # 文档卡片：文本轨 executor.documents_written + FC 轨 docs_written_collector，去重保序
        merged_docs: List[str] = []
        seen_docs = set()
        for dn in (executor.documents_written + docs_written_collector):
            if dn and dn not in seen_docs:
                seen_docs.add(dn)
                merged_docs.append(dn)
        response = PlannerResponse(
            text=loop_result.text,
            applied_actions=loop_result.applied_actions,
            steps=loop_result.steps,
            warnings=loop_result.warnings,
            confirmation=loop_result.confirmation,
            documents_written=merged_docs,
            image_urls=image_urls_collector,
            chat_inserts=merged_inserts,
            # 阶段完成卡片粗粒度展示：连续同类操作合并（如「新建关键元素分组 ×3」），
            # 不逐张卡片罗列；随消息持久化与 done payload 一并下发
            action_log=aggregate_action_log(action_log_collector + executor.action_log),
            confirmation_options=loop_result.confirmation_options or confirmation_options_collector,
            trace=loop_result.trace,
        )

        # 记忆系统：后台异步记录本轮对话（不阻塞响应流），按项目隔离
        if settings.memory_enabled:
            MemoryManager.get_instance().record_dialog_background(
                user_message, loop_result.text, self._make_summarize_fn(),
                project_id=self.state_manager.active_project_id,
            )
        response.memory_hits = list(getattr(context, "memory_hits", None) or [])

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
                # payload 携带 count：web 层据此下发最新状态快照，前端逐步刷新故事板
                await queue.put(PlannerEvent(
                    type="actions_applied", text=f"已应用 {count} 个操作",
                    payload={"count": count},
                ))
            elif etype == "executing_actions":
                await queue.put(PlannerEvent(type="status", text="正在执行操作…"))
            elif etype in ("reasoning_delta", "tool_started", "tool_finished", "guidance_injected"):
                # 过程时间线事件穿透（前端渲染深度思考/工具条目）
                await queue.put(PlannerEvent(type=etype, text=event.get("text", ""), payload=event))

        # 在后台任务中运行统一循环，通过 queue 穿透事件
        result_holder: List[PlannerResponse] = []
        error_holder: List[Exception] = []

        async def _run():
            try:
                resp = await self.handle_message(
                    user_message, context, stream_hook=on_delta, on_event=on_event
                )
                result_holder.append(resp)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                error_holder.append(e)
            finally:
                await queue.put(None)  # 哨兵：结束

        task = asyncio.create_task(_run())

        # 消费队列事件并 yield；消费方提前关闭（如 SSE 客户端断连）时
        # 必须取消后台任务，否则孤儿任务继续烧 token 并写状态（P0-1）
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield item
        finally:
            if not task.done():
                task.cancel()

        # 处理结果
        if error_holder:
            exc = error_holder[0]
            yield PlannerEvent(type="error", text=str(exc), payload={
                "error_code": getattr(exc, "error_code", "INTERNAL_ERROR"),
                "retryable": getattr(exc, "retryable", None),
                "http_status": getattr(exc, "http_status", None),
            })
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
            "confirmation_options": result.confirmation_options,
            "trace": result.trace,
            "memory_hits": result.memory_hits,
        })

    # ---------- 内部方法 ----------

    # 回喂消息的识别前缀（与 format_tool_results 首行保持一致）
    _FEEDBACK_MARKER = FEEDBACK_MARKER
    # 旧轮回喂被压缩后的占位文案
    _FEEDBACK_COMPRESSED = FEEDBACK_COMPRESSED

    @staticmethod
    def _should_compress_feedback(messages: List[Dict[str, Any]]) -> bool:
        """惰性压缩决策（委托 fc_tool_runner.should_compress_feedback）"""
        return should_compress_feedback(messages)

    @staticmethod
    def _compress_prior_feedback(messages: List[Dict[str, Any]]) -> None:
        """压缩旧轮回喂全文为占位文案（委托 fc_tool_runner.compress_prior_feedback）"""
        compress_prior_feedback(messages)

    def _build_system_prompt(self, context: PlannerContext) -> str:
        """构建 system prompt（委托 PromptBuilder；段落顺序为前缀缓存优化）"""
        return self._prompt_builder.build_system_prompt(context)

    def _build_skill_catalog(self, context: PlannerContext) -> str:
        """构建 Skill 目录（委托 PromptBuilder）"""
        return self._prompt_builder.build_skill_catalog(context)

    def _build_selected_skill_block(self, skill_name: str) -> str:
        """选中 Skill 的全文注入块（委托 PromptBuilder）"""
        return self._prompt_builder.build_selected_skill_block(skill_name)

    @staticmethod
    def _last_user_text(context: PlannerContext) -> str:
        """从历史中取最近一条用户消息作为记忆检索 query（委托 PromptBuilder）"""
        return PromptBuilder.last_user_text(context)

    def _make_summarize_fn(self):
        """包装摘要调用：优先用注入的便宜模型 adapter（摘要无需主模型能力），
        未配置时回落主模型；无 adapter 返回 None（降级截取）"""
        adapter = self.summary_adapter or self.llm_adapter
        if adapter is None:
            return None
        use_main = adapter is self.llm_adapter

        async def _fn(prompt: str) -> str:
            if use_main:
                resp = await self._call_llm(
                    "你是记忆整理助手。",
                    [{"role": "user", "content": prompt}],
                )
            else:
                # 摘要专用模型：直接裸调用（无工具、无状态注入），成本最小化
                resp = await adapter.chat(
                    [
                        {"role": "system", "content": "你是记忆整理助手。"},
                        {"role": "user", "content": prompt},
                    ],
                    timeout=settings.llm_timeout,
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
        # Token 预算截断：窗口按模型查表；system 自身超预算时走降级保险丝
        max_tokens = int(self._context_window() * settings.token_budget_ratio)
        full_messages = truncate_messages(full_messages, max_tokens, system_degrader=self._system_degrader)

        if self.llm_adapter is None:
            # 无 adapter 时返回空响应（mock 路径由上层处理）
            return ChatResponse(content="", finish_reason="stop")

        if self.llm_adapter.supports_function_calling:
            # 模式 A：标准 function calling（工具集按上下文裁剪）
            tools_schema = self.tool_manager.get_all_tool_schemas(exclude=self._excluded_tools)
            return await self.llm_adapter.chat(
                full_messages, tools=tools_schema, timeout=settings.llm_timeout
            )
        else:
            # 模式 B：纯文本（fallback 到 studio-actions 文本解析）
            return await self.llm_adapter.chat(full_messages, timeout=settings.llm_timeout)

    async def _call_llm_stream(self, system: str, messages: List[Dict[str, Any]]) -> AsyncGenerator[StreamChunk, None]:
        """流式 LLM 调用"""
        full_messages = [{"role": "system", "content": system}] + messages
        # Token 预算截断：窗口按模型查表；system 自身超预算时走降级保险丝
        max_tokens = int(self._context_window() * settings.token_budget_ratio)
        full_messages = truncate_messages(full_messages, max_tokens, system_degrader=self._system_degrader)

        if self.llm_adapter is None:
            return

        tools_schema = None
        if self.llm_adapter.supports_function_calling:
            tools_schema = self.tool_manager.get_all_tool_schemas(exclude=self._excluded_tools)

        async for chunk in self.llm_adapter.chat_stream(
            full_messages, tools=tools_schema, timeout=settings.llm_stream_timeout
        ):
            yield chunk

    async def _handle_fc_response(
        self,
        response: ChatResponse,
        image_urls_collector: Optional[List[str]] = None,
        chat_inserts_collector: Optional[List[Dict[str, Any]]] = None,
        action_log_collector: Optional[List[str]] = None,
        confirmation_options_collector: Optional[List[Dict[str, Any]]] = None,
        docs_written_collector: Optional[List[str]] = None,
        image_provider: str = "",
        image_aspect_ratio: str = "",
        on_status=None,
        on_event=None,
        injected_skill: str = "",
        selected_draft_id: str = "",
        selected_type: str = "",
    ) -> Tuple:
        """处理 LLM 响应中的 FC tool_calls。
        返回 (content, finish_reason, fc_applied, tool_results)，
        tool_results: [{name, ok, data, error}] 供回喂进对话上下文"""
        if response.tool_calls:
            (fc_applied, fc_confirmation, image_urls,
             chat_inserts, fc_action_log, fc_confirmation_options,
             fc_tool_results, fc_docs_written) = await self._execute_fc_tools(
                response, image_provider=image_provider, image_aspect_ratio=image_aspect_ratio,
                on_status=on_status, on_event=on_event, injected_skill=injected_skill,
                selected_draft_id=selected_draft_id, selected_type=selected_type,
            )
            if image_urls_collector is not None:
                image_urls_collector.extend(image_urls)
            if chat_inserts_collector is not None:
                chat_inserts_collector.extend(chat_inserts)
            if action_log_collector is not None:
                action_log_collector.extend(fc_action_log)
            if confirmation_options_collector is not None:
                confirmation_options_collector.extend(fc_confirmation_options)
            if docs_written_collector is not None:
                docs_written_collector.extend(fc_docs_written)
            if fc_confirmation:
                confirm_action: Dict[str, Any] = {
                    "action": "request_confirmation", "message": fc_confirmation,
                }
                if fc_confirmation_options:
                    confirm_action["options"] = fc_confirmation_options
                confirm_block = json.dumps([confirm_action], ensure_ascii=False)
                # 空正文兜底处理：FC 模型常只发暂停工具不带正文，若不补可见文字，
                # 用户会看到「模型返回了空内容」而非完成总结（事情干完了却像失败了）
                visible = (response.content or "").strip()
                if not visible:
                    visible = fc_confirmation
                content = visible + f"\n```studio-actions\n{confirm_block}\n```"
                return content, response.finish_reason, 0, fc_tool_results
            return response.content, response.finish_reason, fc_applied, fc_tool_results
        return response.content, response.finish_reason, 0, []

    async def _execute_fc_tools(
        self, response: ChatResponse, image_provider: str = "", image_aspect_ratio: str = "",
        on_status=None, on_event=None, injected_skill: str = "",
        selected_draft_id: str = "", selected_type: str = "",
    ) -> Tuple[int, str, List[str], List[Dict[str, Any]], List[str], List[Dict[str, Any]], List[Dict[str, Any]], List[str]]:
        """执行 Function Calling 返回的 tool_calls（委托 FCToolRunner）。
        返回 (applied_count, confirmation_message, image_urls, chat_inserts, action_log,
        confirmation_options, tool_results, docs_written)"""
        return await self._fc_runner.execute(
            response, image_provider=image_provider, image_aspect_ratio=image_aspect_ratio,
            on_status=on_status, on_event=on_event, injected_skill=injected_skill,
            selected_draft_id=selected_draft_id, selected_type=selected_type,
        )

    # read_* 系列：读回的全文必须完整回喂进上下文（渐进式披露的「借阅归还」）；
    # 其他写入类工具只回报成功与否，避免重复携带大 JSON 膨胀上下文
    _FEEDBACK_FULL_TOOLS = FEEDBACK_FULL_TOOLS
    # 单次回喂总量保险丝（read_* 各自已有 max_doc_chars 截断，这里防多文档叠加）
    _FEEDBACK_MAX_TOTAL_CHARS = FEEDBACK_MAX_TOTAL_CHARS

    @staticmethod
    def _format_tool_results(tool_results: List[Dict[str, Any]]) -> Union[str, List[Dict[str, Any]]]:
        """把本轮 FC 工具执行结果格式化为回喂消息（委托 fc_tool_runner）"""
        return format_tool_results(tool_results)

    @staticmethod
    def _render_read_result(name: str, data: Dict[str, Any]) -> str:
        """按 read_* 工具类型渲染读回全文（委托 fc_tool_runner）"""
        return render_read_result(name, data)

    @staticmethod
    def _describe_fc_tool(name: str, args: Dict[str, Any]) -> str:
        """FC 工具的中文简述（委托 fc_tool_runner）"""
        return describe_fc_tool(name, args)

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


def _prepend_script_summary(visible: str, tool_results) -> str:
    """总结强制入正文（Q1：script_analyze 与暂停同批时一句话总结不得丢失）。

    若本轮 script_analyze 成功产出 summary 且正文尚未包含它，就在正文最前
    拼一段「剧本一句话总结」；已包含或无可信结果时原样返回。
    """
    summary = ""
    for tr in tool_results or []:
        if not isinstance(tr, dict):
            continue
        if str(tr.get("name") or "") == "script_analyze" and tr.get("ok"):
            s = str((tr.get("data") or {}).get("summary") or "").strip()
            if s:
                summary = s
                break
    if not summary:
        return str(visible or "")
    norm = lambda s: str(s or "").replace("“", "").replace("”", "").replace("'", "").replace('"', "")
    if norm(summary) in norm(visible):
        return str(visible or "")
    return f"**剧本一句话总结**：{summary}\n\n{visible}"
