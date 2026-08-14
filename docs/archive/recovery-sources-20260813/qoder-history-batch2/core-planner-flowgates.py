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
from src.video_agent.core.agent_loop import MAX_STEPS, run_agent_loop
from src.video_agent.core.tracer import AgentTracer
from src.video_agent.web.actions import StudioActionExecutor
from src.video_agent.workflows.engine import WorkflowEngine


@dataclass
class PlannerContext:
    """每轮对话的上下文参数"""
    history: List[Dict[str, Any]] = field(default_factory=list)
    selected_draft_id: str = ""
    selected_type: str = ""
    state_json: str = ""
    extra_system: str = ""       # 前端 skill 的角色提示词（渐进式披露后不再全文注入，仅兼容保留）
    skill_name: str = ""         # 前端当前选中的 Skill 名称（目录标注用，提高相关性判断准确率）
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


class StreamActionSuppressor:
    """流式增量过滤器（P2-1）：只抑制 ```studio-actions 围栏块，
    普通文本与普通 markdown 代码块照常推送。

    旧逻辑：累计文本中一旦出现 ``` 就永久停止推送，普通代码块也被误杀。
    现为状态机：进入 studio-actions 块后暂停推送（直到闭合围栏），
    其余内容（含普通代码块与其围栏本身）照旧推送。
    围栏可能跨 chunk 截断（如先收到 `` 再收到 `studio-actions），
    通过保留尾部 2 字符与等待信息行换行来解决。
    """

    FENCE = "```"
    SUPPRESS_LANG = "studio-actions"

    def __init__(self) -> None:
        self.buf = ""
        self.pos = 0        # 围栏状态已解析到的位置
        self.emit_upto = 0  # 已推送（或已整块跳过）的位置
        self.in_actions = False
        self._post_fence = False  # 闭合围栏恰在缓冲末尾，待确认下一个字符是否为换行

    def feed(self, delta: str) -> str:
        """追加增量文本，返回本次可推送的部分（可能为空串）"""
        self.buf += delta
        if self._post_fence:
            # 上轮闭合围栏停在缓冲末尾：吞掉属于围栏行的尾随换行
            self._post_fence = False
            if self.pos < len(self.buf) and self.buf[self.pos] == "\n":
                self.pos += 1
                self.emit_upto = self.pos
        out_parts: List[str] = []
        while True:
            if not self.in_actions:
                i = self.buf.find(self.FENCE, self.pos)
                if i == -1:
                    # 未见完整围栏：尾部保留 2 字符（可能是截断的 `` / ```）
                    safe = max(self.pos, len(self.buf) - (len(self.FENCE) - 1))
                    self.pos = safe
                    break
                # 围栏前的待推文本先冲刷出去
                if i > self.emit_upto:
                    out_parts.append(self.buf[self.emit_upto:i])
                    self.emit_upto = i
                # 围栏起始已确定；信息行未收完则暂等
                nl = self.buf.find("\n", i + len(self.FENCE))
                if nl == -1:
                    self.pos = i
                    break
                info = self.buf[i + len(self.FENCE):nl].strip()
                if info.startswith(self.SUPPRESS_LANG):
                    self.in_actions = True
                    self.pos = nl + 1
                    self.emit_upto = nl + 1  # 开栏行进入抑制区，不推送
                else:
                    self.pos = nl + 1  # 普通代码块，围栏行照常放行
            else:
                j = self.buf.find(self.FENCE, self.pos)
                if j == -1:
                    break
                end = j + len(self.FENCE)
                if end < len(self.buf):
                    if self.buf[end] == "\n":
                        end += 1
                else:
                    # 闭合围栏恰在缓冲末尾：换行归属待下一个 chunk 确认
                    self._post_fence = True
                self.pos = end
                self.emit_upto = end  # 整块（含闭合围栏）跳过
                self.in_actions = False
        if self.pos > self.emit_upto:
            out_parts.append(self.buf[self.emit_upto:self.pos])
            self.emit_upto = self.pos
        return "".join(out_parts)

    def flush(self) -> str:
        """流结束时冲刷剩余缓冲：未闭合的 studio-actions 块仍保持抑制"""
        if self.in_actions:
            return ""
        out = self.buf[self.emit_upto:]
        self.emit_upto = self.pos = len(self.buf)
        return out


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
        # Skill 声明式流程门禁（handle_message 里按选中 Skill 解析）
        self._flow_gates = None

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

        # Skill 声明式流程门禁（硬校验）：解析选中 Skill 声明的检查点，
        # 由代码强制执行——越阶操作直接拦截并强制暂停，不依赖模型自觉。
        # 未声明检查点的 Skill 不受影响（_flow_gates 为 None）。
        self._flow_gates = None
        if context.skill_name:
            try:
                from src.video_agent.web.skill_docs import resolve_skill_content
                from src.video_agent.core.flow_gates import FlowGateSet
                _skill_name, _skill_content = resolve_skill_content(context.skill_name)
                self._flow_gates = FlowGateSet.from_skill(_skill_content or "")
            except Exception as e:  # 解析失败不阻断对话，降级为无门禁
                logger.warning(f"[Planner] 流程检查点解析失败（降级为无门禁）: {e}")
                self._flow_gates = None

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
                async for chunk in self._call_llm_stream(system_prompt, messages):
                    if chunk.type == "text_delta" and chunk.text:
                        content_parts.append(chunk.text)
                        # P2-1：仅屏蔽 studio-actions 围栏，普通代码块照常推送
                        out = suppressor.feed(chunk.text)
                        if out:
                            await hook(out)
                    elif chunk.type == "reasoning_delta" and chunk.text:
                        # 深度思考：记入 trace（持久化展示）+ 实时推给前端，不进 LLM 上下文
                        tracer.record_reasoning(chunk.text)
                        if on_event is not None:
                            await on_event({"type": "reasoning_delta", "text": chunk.text})
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
                image_provider=context.image_generation_provider,
                image_aspect_ratio=context.image_generation_aspect_ratio,
                on_status=_emit_status,
                on_event=_emit_event,
            )
            # 渐进式披露的回路关键：read_* 工具读回的全文必须回喂进 messages，
            # 否则模型「读了个寂寞」，Skill 流程/规格约束根本不进上下文
            if tool_results:
                feedback = Planner._format_tool_results(tool_results)
                if feedback:
                    if context.skill_name:
                        feedback += (
                            "\n【提醒】当前有选中 Skill：遵守其阶段划分与暂停点，"
                            "到达确认点时用 request_confirmation / workflow_pause 真正停下，不要一口气做完全部阶段。"
                        )
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
            flow_gates=self._flow_gates,
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
            elif etype in ("reasoning_delta", "tool_started", "tool_finished"):
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
            "trace": result.trace,
        })

    # ---------- 内部方法 ----------

    def _build_system_prompt(self, context: PlannerContext) -> str:
        """构建 system prompt：从 prompts/ 加载 + 注入状态上下文"""
        parts: List[str] = []

        # 渐进式披露：不再注入全部 Skill 全文（extra_system），
        # 改为注入 Skill 目录（名称+摘要），全文由模型按需调 read_skill 加载
        catalog = self._build_skill_catalog(context)
        if catalog:
            parts.append(catalog)

        # 硬保障：用户在前端选中的 Skill 强制全文注入。
        # 原因：模型不一定主动调 read_skill，非 FC 通道（如 gemini-cli）根本调不了；
        # 选中项是用户明确指定的任务依据，丢了它产出质量直接劣化。
        # 未选中的 Skill 仍保持目录 + 按需加载，token 治理不回退。
        if context.skill_name:
            selected_block = self._build_selected_skill_block(context.skill_name)
            if selected_block:
                parts.append(selected_block)

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
    def _build_skill_catalog(context: PlannerContext) -> str:
        """构建 Skill 目录（渐进式披露的「目录」）：全部文档 Skill 的名称+摘要常驻，
        全文不注入，模型判断相关性后调 read_skill 按需加载。
        代码内置 Skill（编剧/分镜师/制片）已彻底移除，不进目录。"""
        # 延迟导入，避免 core 层与 web/skills 的循环依赖
        from src.video_agent.web.skill_docs import list_skill_docs

        lines: List[str] = []
        try:
            for d in list_skill_docs():
                name = d.get("name") or d.get("slug") or ""
                desc = (d.get("description") or "").strip() or "未提供摘要"
                lines.append(f"- {name}：{desc}")
        except Exception:  # 文档目录读取失败不阻断对话
            pass
        if not lines:
            return ""
        header = (
            "== Skill 目录（渐进式披露：上下文只有各 Skill 的名称与摘要。"
            "执行任务前必须先调用 read_skill（name=Skill 名称）加载对应 Skill 的完整流程，"
            "不要凭目录摘要自行推测流程细节）==\n" + "\n".join(lines)
        )
        if context.skill_name:
            header += (
                f"\n用户当前在前端选中了「{context.skill_name}」，其全文已另行注入下方"
                f"（无需再对它调 read_skill）；其他 Skill 需要时仍要先 read_skill。"
            )
        return header

    def _build_selected_skill_block(self, skill_name: str) -> str:
        """选中 Skill 的全文注入块（硬保障，不依赖模型自觉调 read_skill）；
        若该 Skill 声明了流程检查点（self._flow_gates），追加强制执行说明"""
        from src.video_agent.web.skill_docs import resolve_skill_content
        try:
            display, content = resolve_skill_content(skill_name)
        except Exception:  # 解析失败不阻断对话
            logger.warning(f"[Planner] 选中 Skill「{skill_name}」解析失败，降级为仅目录")
            return ""
        content = (content or "").strip()
        if not content:
            return ""
        if len(content) > settings.max_doc_chars:
            content = content[:settings.max_doc_chars] + "\n……（Skill 全文超长，已截断）"
        return (
            f"== 当前选中 Skill「{display or skill_name}」全文（已直接注入，必须严格遵守"
            f"其中的流程与规范；不要再对它调用 read_skill）==\n{content}\n\n"
            "【Skill 流程纪律】\n"
            "按本 Skill 声明的阶段与暂停点执行；到达确认点时用 request_confirmation（文本模式）或 "
            "workflow_pause（Tool 模式）真正停下，只在正文写「请确认」而不发信号是无效的。"
            + (
                "\n本 Skill 声明了流程检查点，系统已强制执行：越阶操作会被直接拦截并强制暂停，"
                "不要尝试绕过，先完成当前阶段再继续。" if self._flow_gates is not None else ""
            )
        )

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
        on_event=None,
    ) -> Tuple:
        """处理 LLM 响应中的 FC tool_calls。
        返回 (content, finish_reason, fc_applied, tool_results)，
        tool_results: [{name, ok, data, error}] 供回喂进对话上下文"""
        if response.tool_calls:
            (fc_applied, fc_confirmation, image_urls,
             chat_inserts, fc_action_log, fc_tool_results) = await self._execute_fc_tools(
                response, image_provider=image_provider, image_aspect_ratio=image_aspect_ratio,
                on_status=on_status, on_event=on_event,
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
                return content, response.finish_reason, 0, fc_tool_results
            return response.content, response.finish_reason, fc_applied, fc_tool_results
        return response.content, response.finish_reason, 0, []

    async def _execute_fc_tools(
        self, response: ChatResponse, image_provider: str = "", image_aspect_ratio: str = "",
        on_status=None, on_event=None,
    ) -> Tuple[int, str, List[str], List[Dict[str, Any]], List[str], List[Dict[str, Any]]]:
        """执行 Function Calling 返回的 tool_calls。
        返回 (applied_count, confirmation_message, image_urls, chat_inserts, action_log, tool_results)"""
        applied = 0
        confirmation = ""
        image_urls: List[str] = []
        chat_inserts: List[Dict[str, Any]] = []
        action_log: List[str] = []
        tool_results: List[Dict[str, Any]] = []
        tracer = AgentTracer.get_instance()
        for ci, call in enumerate(response.tool_calls):
            func = call.get("function", {}) if isinstance(call, dict) else {}
            name = func.get("name", "")
            args_raw = func.get("arguments", "{}")
            try:
                args = json.loads(args_raw) if isinstance(args_raw, str) else args_raw
            except json.JSONDecodeError:
                args = {}

            # 过程时间线：工具开始（前端渲染运行态条目）
            tool_event_id = str(call.get("id") or f"fc-{ci}") if isinstance(call, dict) else f"fc-{ci}"
            start_summary = self._describe_fc_tool(name, args)
            if on_event is not None:
                await on_event({
                    "type": "tool_started",
                    "id": tool_event_id,
                    "name": name,
                    "summary": start_summary,
                })
            _tool_t0 = time.monotonic()

            # --- Skill 声明式流程门禁：拦截越阶工具调用（硬校验，不依赖模型自觉） ---
            if self._flow_gates is not None:
                gate_op = self._flow_gates.classify_fc(name, args)
                gate_ok, gate_missing = self._flow_gates.check_op(
                    gate_op, StateManager.get_instance().state_dict
                )
                if not gate_ok:
                    reason = self._flow_gates.block_reason(gate_op, gate_missing)
                    logger.warning(f"[Planner] 流程门禁拦截工具 '{name}': {'、'.join(gate_missing)}")
                    if on_event is not None:
                        await on_event({
                            "type": "tool_finished",
                            "id": tool_event_id,
                            "ok": False,
                            "elapsed_ms": 0.0,
                            "result_summary": "被流程门禁拦截",
                        })
                    tracer.record_action(name=name, summary="被流程门禁拦截", elapsed_ms=0.0, ok=False)
                    tool_results.append({"name": name, "ok": False, "error": reason})
                    self._flow_gates.mark_blocked(reason)
                    continue

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
            _tool_ms = (time.monotonic() - _tool_t0) * 1000
            if result.success:
                applied += 1
                if name == "workflow_pause":
                    confirmation = args.get("message", "请确认以上内容。")
                desc = self._describe_fc_tool(name, args)
                action_log.append(desc)
                # 推理过程可视化：每完成一个工具就推一条状态
                if on_status is not None:
                    await on_status(f"已完成：{desc}")
                # 过程时间线：工具完成 + trace 记录
                if on_event is not None:
                    await on_event({
                        "type": "tool_finished",
                        "id": tool_event_id,
                        "ok": True,
                        "elapsed_ms": round(_tool_ms, 1),
                        "result_summary": desc,
                    })
                tracer.record_action(name=name, summary=desc, elapsed_ms=_tool_ms, ok=True)
                tool_results.append({"name": name, "ok": True, "data": getattr(result, "data", None)})
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
                if on_event is not None:
                    await on_event({
                        "type": "tool_finished",
                        "id": tool_event_id,
                        "ok": False,
                        "elapsed_ms": round(_tool_ms, 1),
                        "result_summary": str(getattr(result, "error", "") or "执行失败")[:120],
                    })
                tracer.record_action(
                    name=name, summary=start_summary, elapsed_ms=_tool_ms, ok=False,
                )
                tool_results.append({
                    "name": name, "ok": False,
                    "error": str(getattr(result, "error", "") or "执行失败")[:200],
                })
        return applied, confirmation, image_urls, chat_inserts, action_log, tool_results

    # read_* 系列：读回的全文必须完整回喂进上下文（渐进式披露的「借阅归还」）；
    # 其他写入类工具只回报成功与否，避免重复携带大 JSON 膨胀上下文
    _FEEDBACK_FULL_TOOLS = {"read_skill", "read_project_doc", "read_uploaded_doc", "read_draft"}
    # 单次回喂总量保险丝（read_* 各自已有 max_doc_chars 截断，这里防多文档叠加）
    _FEEDBACK_MAX_TOTAL_CHARS = 100000

    @staticmethod
    def _format_tool_results(tool_results: List[Dict[str, Any]]) -> str:
        """把本轮 FC 工具执行结果格式化为回喂消息。

        read_* 工具携带读回的全文（Skill 流程/规格/剧本/草稿提示词），
        必须让模型在后续轮次真正看到，否则按需加载形同虚设。
        """
        lines: List[str] = ["（系统）本轮调用的工具已执行完毕，结果如下："]
        total = 0
        for tr in tool_results:
            name = str(tr.get("name", ""))
            if not tr.get("ok"):
                lines.append(f"- {name}：执行失败 —— {tr.get('error') or '未知错误'}")
                continue
            if name not in Planner._FEEDBACK_FULL_TOOLS:
                lines.append(f"- {name}：执行成功")
                continue
            data = tr.get("data") or {}
            body = Planner._render_read_result(name, data)
            if total + len(body) > Planner._FEEDBACK_MAX_TOTAL_CHARS:
                lines.append(f"- {name}：执行成功（全文因总量超限未附，请勿重复读取，按已有信息继续）")
                continue
            total += len(body)
            lines.append(
                f"- {name} 执行成功，以下是读回的全文（后续任务必须遵守其中流程与约束，"
                f"不要重复调用同一工具）：\n{body}"
            )
        return "\n".join(lines) if len(lines) > 1 else ""

    @staticmethod
    def _render_read_result(name: str, data: Dict[str, Any]) -> str:
        """按 read_* 工具类型渲染读回全文"""
        if name == "read_draft":
            parts: List[str] = []
            for d in (data.get("drafts") or []):
                parts.append(
                    f"【草稿 {d.get('index', '')}「{d.get('label', '')}」"
                    f"（{d.get('group_title', '')}，draft_id={d.get('draft_id', '')}）】\n{d.get('prompt', '')}"
                )
            return "\n\n".join(parts) if parts else "（无内容）"
        doc_name = data.get("name", "")
        content = data.get("content", "") or "（空）"
        return f"【{doc_name}】\n{content}"

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
        if name == "read_draft":
            return f"读取草稿「{str(args.get('draft_id') or '未知')}」提示词全文"
        if name == "document_write":
            return f"写入文档「{doc or '未命名'}」"
        if name == "read_uploaded_doc":
            return f"读取上传文档「{str(args.get('name') or args.get('doc_id') or '未知')}」"
        if name == "read_skill":
            return f"加载 Skill「{str(args.get('name') or '未知')}」完整流程"
        if name == "read_project_doc":
            return f"读取规格文档「{str(args.get('name') or '未知')}」"
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
