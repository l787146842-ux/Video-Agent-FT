"""
Planner — 对话式 Agent 的唯一入口（Rule1）。

设计方案核心：
- Planner 直接持有 LLM Adapter 引用（Rule6: 外部调用走 Adapter），不经过 Tool Manager
- Tool Manager 只管理"业务 Tool"（故事板操作、生图、文档等）
- 动作通道唯一 = FC 工具调用（4-4 双轨退役，ADR-0001）
- 多步循环（MAX_STEPS），LLM 可请求 continue 推进下一轮
- 流式通过 AsyncGenerator 穿透（SSE）
"""
import asyncio
import json
import time
import uuid
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
from src.video_agent.utils.prompts import load_prompt, load_prompt_section, render_prompt
from src.video_agent.core.agent_loop import MAX_STEPS, run_agent_loop
from src.video_agent.core.fc_tool_runner import (
    FCToolRunner,
    compress_prior_feedback,
    format_tool_results,
    should_compress_feedback,
    strip_prior_feedback_images,
)
from src.video_agent.core.prompt_builder import PromptBuilder
# 八轮 B2：轮末组装域切入 planner_output
from src.video_agent.core.planner_output import assemble_response
from src.video_agent.core import prompt_gates
# 批 7 拆分协作臂：豁免消费/确定性分诊/FC 响应合并（同名委托保持既有调用/测试路径）
from src.video_agent.core import fc_response, planner_gate_session, planner_triage
from src.video_agent.core.live_metrics import record_degradation, record_live_context
from src.video_agent.core.sse_events import SSE_REASONING_DELTA, SSE_STATUS, status_event
from src.video_agent.core.tracer import AgentTracer
from src.video_agent.skill_runtime.registry import fallback_skill_from_state


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

# 814R1 曾设流式预执行阶段边界延迟集合：随 4-4 文本轨退役删除
# （流式「边写边填」预执行为文本轨基础设施，FC 轨动作经 tool_calls 执行）。

# 选中 Skill 时的流程提醒（814R1 恢复外置：prompts/planner/feedback.md 单一事实源）
_SKILL_REMINDER = load_prompt_section("planner/feedback.md", "SKILL_REMINDER") or (
    "【提醒】当前有选中 Skill：遵守其阶段划分与暂停点，到达确认点时用 "
    "workflow_pause 真正停下，不要一口气做完全部阶段。")


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
    # audit-0819f：用户键入原文（未经多模态/附件拼装）。分诊（_triage_control）
    # 只认原话——附件预览里的剧本对白问号不得参与提问判定（1111 事故根因）。
    raw_user_text: str = ""
    use_studio_context: bool = True
    asset_mode: str = "bound"    # 资产过滤模式
    image_generation_provider: str = ""  # 选中草稿的生图 provider，用于强制注入
    image_generation_aspect_ratio: str = ""  # 选中草稿的画面比例（如 16:9），用于强制注入
    # 降级状态构建器（token 保险丝）：system 段超预算时用「只留组标题/计数」的
    # 降级状态 JSON 重建 system prompt，保证请求不超窗发出
    degraded_state_builder: Optional[Callable[[], str]] = None
    # 本轮记忆检索命中明细（4.7：随 done payload 下发前端可视化）
    memory_hits: List[Dict[str, Any]] = field(default_factory=list)
    # 前奏时间线（Q8/6666/8888）：只登记真实发生的 system 动作（加载 Skill 流程基线），
    # 读取/存档由对应工具真实发生时记录，前奏不得冒充工具操作
    prelude_notes: List[tuple] = field(default_factory=list)
    # 多用户归属（814E6 基础）：可选用户标识，入 trace 审计
    user_id: str = ""
    # 814H7：会话级推理档位（对话栏「推理等级」选择器下发；""=模型原生能力）
    thinking_level: str = ""
    # B0/F2 恢复：轮间引导注入器（任务式传输注册的排队消息，逐轮消费）。
    # 由 web 层按 task_id 装配（agent_task_manager.drain_pending_guidance）；
    # None = 无注入（非任务路径）。
    pending_injector: Optional[Callable[[], List[Dict[str, Any]]]] = None


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
    # 五轮 S3/#3：建议动作按钮（重试/继续，确定性交互；详见 agent_loop 同名字段）
    suggested_actions: List[Dict[str, str]] = field(default_factory=list)
    # 暂停卡结构化标识（对标 AskUserQuestion 范式）：三个 confirm 产生源
    # （FC workflow_pause / 编排器机械卡 / 轮末策略卡）在两个汇流点统一签发，
    # 随 done payload 下发；用户回应经 ChatRequest.pause_response 结构化回携
    pause_id: str = ""


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
    """

    def __init__(
        self,
        state_manager: Optional[StateManager] = None,
        tool_manager: Optional[type] = None,   # ToolManager 是类级别注册，传类引用
        llm_adapter: Optional[BaseChatAdapter] = None,
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
        # 用工具可见性隔离阶段；第二层由既有闸机兜底
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
        return context_window_for_model(model, provider_id=getattr(self, "chat_provider", "") or "")

    # ---------- 暂停卡结构化签发（单一实现，两个汇流点共用） ----------

    def _issue_pause(self, response: "PlannerResponse") -> None:
        """为携带 confirmation 的响应签发 pause_id 并登记 interaction.active_pause。

        汇流点一（handle_message 轮末组装后）覆盖 FC workflow_pause 与轮末策略卡；
        汇流点二（_run_orchestrator_path）覆盖编排器机械卡。登记不改变
        awaiting_confirmation 既有语义（分诊/消费链零行为变更），只叠加结构化标识。
        """
        if not response.confirmation:
            return
        response.pause_id = uuid.uuid4().hex[:12]
        try:
            inter = self.state_manager.state_dict.setdefault("interaction", {})
            inter["active_pause"] = {
                "pause_id": response.pause_id,
                "message": response.confirmation,
                "options": list(response.confirmation_options or []),
            }
            self.state_manager.save_debounced()
        except Exception as _e:
            # 承重接线遥测（批 8）：暂停登记断线降级端点可见（对勾派生依赖此登记）
            record_degradation("planner._issue_pause")
            logger.warning("[PauseId] active_pause 登记失败（不影响暂停卡渲染）: {}", _e)

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
        委托给 run_agent_loop 统一循环骨架；动作通道唯一 = FC 工具调用
        （4-4 双轨退役；文本块解析仅消费系统内部合成的确认块与 mock 输出）。
        stream_hook: 可选 async callable(text)，流式模式下每段 LLM 增量文本回调。
        """
        # 当前 Skill 归属（7777 事故）：请求未携带 Skill 时回退项目 usedSkills 末位，
        # 保证后续轮次仍绑定同一执行器；单一实现见 registry.fallback_skill_from_state。
        if not context.skill_name:
            context.skill_name = fallback_skill_from_state(self.state_manager.state_dict)

        # 按上下文裁剪本轮下发的工具集 + 装配 system 超预算降级器（token 治理）
        self._excluded_tools = self._compute_excluded_tools(context)
        self._system_degrader = self._make_system_degrader(context)
        # 814H7：会话级推理档位（""=原生；主模型调用透传，端点不认则静默忽略）
        self._chat_thinking_level = context.thinking_level or ""

        # 构建 executor（文本解析路径用）：优先注入的工厂，缺省延迟导入 web 层实现
        factory = self.executor_factory
        if factory is None:
            from src.video_agent.web.action_executor import StudioActionExecutor
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
            except Exception as _e:
                logger.debug("[planner] 忽略异常: {}", _e)

        # 会话层一次性豁免（§2.4）：按钮路径登记单次消费即清除（留痕）；
        # 无显式豁免时回落正则意图识别兜底（委托 planner_gate_session）
        gate_override_scope = planner_gate_session.consume_gate_overrides(
            self.state_manager, user_message)
        try:
            executor.gate_override = gate_override_scope
        except Exception as _e:
            logger.warning("[GateOverride] gate_override 装配失败（豁免未传达执行器）: {}", _e)

        # audit-0819e 控制流统一（ADR-0002，1111 事故根治）：废除 0818 概率语料
        # 路由——一切消息先过确定性分诊：advance 由外层循环接管，其余交接
        # 受界模型循环（阶段前置闸/步间回收保证顺序不破）。分诊与编排器
        # 进出全记结构化事件（1111 教训：控制流决策必须可观测，不得考古）。
        if settings.pipeline_orchestrator_enabled and context.skill_name:
            # audit-0819f：分诊只认用户原话——user_message 可能是多模态拼装
            # （附件预览含剧本对白问号，1111 事故曾误判 handoff）
            triage = self._triage_control(
                context.raw_user_text or user_message, context.skill_name)
            logger.info("[ControlFlow] triage={} skill={}", triage, context.skill_name)
            try:
                AgentTracer.get_instance().record_control_flow(
                    "triage", triage, context.skill_name)
            except Exception:
                pass
            if triage == "advance":
                _orch = await self._run_orchestrator_path(context, user_message)
                if _orch is not None:
                    return _orch

        # 0818 架构板正批 B3：门禁链与剧本闸装配退役，顺序与原料闸能力
        # 迁入 pipeline_orchestrator（状态驱动、机械回卡）。

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
        # B0/F3：FC 轨闸机拦截/豁免文案收集器（每批 execute() 返回的 warnings），
        # 循环结束后并入 loop_result.warnings，与文本轨拦截可见性对齐
        fc_warnings_collector: List[str] = []

        async def _emit_status(text: str, key: str = "", params: Optional[Dict[str, Any]] = None) -> None:
            """推理过程可视化：把 FC 工具执行进度实时推给前端状态栏。
            固定文案携带 key+params（四轮 R3/#5：前端按 locale 翻译，text 兜底）。"""
            if on_event is not None:
                if key:
                    await on_event(status_event(key, text, params))
                else:
                    await on_event({"type": SSE_STATUS, "text": text})

        async def _emit_event(event: Dict[str, Any]) -> None:
            """过程时间线事件透传（tool_started/tool_finished）"""
            if on_event is not None:
                await on_event(event)

        tracer = AgentTracer.get_instance()

        async def llm_call(system_prompt: str, messages: List[Dict[str, Any]], hook=None) -> tuple:
            # N6：主模型调用计数（成本看板平均耗时口径）
            tracer.record_llm_call()
            # audit-0819b：确认信号结构化直通——本轮 FC 批的暂停确认由
            # _handle_fc_response 写入本 holder，随 5 元组上抛 agent_loop，
            # 不再合成 studio-actions 文本块回绕解析（对齐 AskUserQuestion 范式）
            _confirm_holder: Dict[str, Any] = {}
            # 纯规划计时（2222 反馈）：只量模型流/调用本身，FC 工具执行时间
            # 不计入「Agent 正在规划本步动作」条目，避免规划行虚高掩盖工具耗时
            _t_plan = time.monotonic()
            # 流式路径：使用 chat_stream + hook 回调
            if hook:
                content_parts: List[str] = []
                finish = ""
                stream_tool_calls: List[Dict[str, Any]] = []
                async for chunk in self._call_llm_stream(system_prompt, messages):
                    if chunk.type == "text_delta" and chunk.text:
                        content_parts.append(chunk.text)
                        # audit-0819b 单轨化：确认走结构化 workflow_pause 工具，
                        # studio-actions 文本块通道已退役（ADR-0001）——
                        # 正文原样透传，流式抑制器（S01）同批下账
                        await hook(chunk.text)
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
                content = "".join(content_parts)
                response = ChatResponse(content=content, finish_reason=finish, tool_calls=stream_tool_calls)
                plan_ms = (time.monotonic() - _t_plan) * 1000
            else:
                response = await self._call_llm(system_prompt, messages)
                plan_ms = (time.monotonic() - _t_plan) * 1000

            content, finish, fc_applied, tool_results, fc_warnings = await self._handle_fc_response(
                response,
                image_urls_collector=image_urls_collector,
                chat_inserts_collector=chat_inserts_collector,
                action_log_collector=action_log_collector,
                confirmation_options_collector=confirmation_options_collector,
                docs_written_collector=docs_written_collector,
                fc_warnings_collector=fc_warnings_collector,
                image_provider=context.image_generation_provider,
                image_aspect_ratio=context.image_generation_aspect_ratio,
                on_status=_emit_status,
                on_event=_emit_event,
                injected_skill=context.skill_name,
                selected_draft_id=context.selected_draft_id,
                selected_type=context.selected_type,
                gate_override=gate_override_scope,
                confirmation_collector=_confirm_holder,
            )
            # 渐进式披露的回路关键：read_* 工具读回的全文必须回喂进 messages，
            # 否则模型「读了个寂寞」，Skill 流程/规格约束根本不进上下文
            if tool_results:
                feedback = format_tool_results(tool_results)
                if feedback:
                    if context.skill_name:
                        reminder = "\n" + _SKILL_REMINDER
                        if isinstance(feedback, list):
                            feedback = feedback + [{"type": "text", "text": reminder}]
                        else:
                            feedback += reminder
                    # token 治理（P1）：新一轮回喂入库前，把更早轮次的 read_* 全文
                    # 回喂压缩为一句话占位，避免多份全文在 messages 里叠加计费。
                    # 惰性压缩（质量优化）：仅当消息总量逼近 token 预算时才压，
                    # 短对话保留全文；选中 Skill 不受影响（它硬注入在 system prompt 里）
                    if should_compress_feedback(messages, self._context_window()):
                        compress_prior_feedback(messages)
                    # 按需调图：新回喂带图片时，先剥离旧轮已加载的图片，
                    # 上下文始终只保留最新一轮的画面（vision token 治理）
                    if isinstance(feedback, list):
                        strip_prior_feedback_images(messages)
                    messages.append({"role": "user", "content": feedback})
            _extra: Dict[str, Any] = {}
            if _confirm_holder.get("message"):
                _extra = {
                    "confirmation": _confirm_holder["message"],
                    "confirmation_options": _confirm_holder.get("options") or [],
                }
            return content, finish, fc_applied, plan_ms, _extra

        # 构建 context_builder
        def context_builder() -> str:
            return self._build_system_prompt(context)

        # 步间回收（控制流统一）：每个 FC 批落盘后外层循环再评估状态——
        # 确定性阶段就绪/应发机械卡即回收控制权（实现体 planner_triage.make_reclaim_hook）
        _between_steps_reclaim = planner_triage.make_reclaim_hook(
            self.state_manager, context.skill_name)

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
            prelude_notes=context.prelude_notes,
            user_id=context.user_id,
            pending_injector=context.pending_injector,
            between_steps=_between_steps_reclaim,
        )

        # 轮末组装委托 planner_output（八轮 B2 切出）：warnings 并入/总结强入/
        # 占位替换/双轨收集器去重/原料提醒卡覆盖/响应构造，行为不变。
        # web 层聚合工具延迟导入（同 executor_factory 回落模式；patch 目标=本命名空间）
        from src.video_agent.web.action_descriptions import aggregate_action_log
        response = assemble_response(
            loop_result,
            executor=executor,
            response_factory=PlannerResponse,
            fc_warnings_collector=fc_warnings_collector,
            action_log_collector=action_log_collector,
            chat_inserts_collector=chat_inserts_collector,
            docs_written_collector=docs_written_collector,
            image_urls_collector=image_urls_collector,
            confirmation_options_collector=confirmation_options_collector,
            analysis_summary=str(
                ((self.state_manager.state_dict or {}).get("analysis") or {}).get("summary") or ""
            ).strip(),
            aggregate_action_log=aggregate_action_log,
        )

        # 暂停卡结构化签发（汇流点一）：FC workflow_pause 与轮末策略卡均在此汇流
        self._issue_pause(response)

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
                # 五轮 S1/#1：队列级 status 走 status_event key+params（i18n 残留清偿，
                # 同四轮 R3/#5 模式）；payload 携带完整 status 事件，chat_service 透传
                step = event.get("step", 1)
                max_steps = event.get("max_steps", MAX_STEPS)
                if step > 1:
                    sev = status_event(
                        "agent.roundStart",
                        f"第 {step} 轮推理中…（执行上轮操作后继续规划）",
                        {"step": step, "max": max_steps},
                    )
                else:
                    sev = status_event(
                        "agent.planning", "正在推理…（模型正在读状态并规划操作）", {},
                    )
                await queue.put(PlannerEvent(type="status", text=sev["text"], payload=sev))
            elif etype == "actions_applied":
                count = event.get("count", 0)
                sev = status_event("agent.actionsApplied", f"已应用 {count} 个操作", {"count": count})
                # payload 携带 count：web 层据此下发最新状态快照，前端逐步刷新故事板
                await queue.put(PlannerEvent(
                    type="actions_applied", text=sev["text"],
                    payload={"count": count, "status_event": sev},
                ))
            elif etype in ("reasoning_delta", "tool_started", "tool_finished", "guidance_injected", "doc_written"):
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
        # B2/F17：空回复占位统一由前端渲染（「（空回复）」单一形态），
        # 后端流式 done 不再替换占位文案（非流式路径仍以 result.text 原样返回）

        yield PlannerEvent(type="done", payload={
            "text": result.text,
            "applied_actions": result.applied_actions,
            "steps": result.steps,
            "warnings": result.warnings,
            "confirmation": result.confirmation,
            "pause_id": result.pause_id,
            "documents_written": result.documents_written,
            "image_urls": result.image_urls,
            "chat_inserts": result.chat_inserts,
            "action_log": result.action_log,
            "confirmation_options": result.confirmation_options,
            "trace": result.trace,
            "memory_hits": result.memory_hits,
            "suggested_actions": result.suggested_actions,
        })

    # ---------- 内部方法 ----------

    def _build_system_prompt(self, context: PlannerContext) -> str:
        """构建 system prompt（委托 PromptBuilder；段落顺序为前缀缓存优化）。
        814R1 恢复双协议瘦身：FC 通道注入瘦身版协议（system_fc.md），文本通道用完整协议。"""
        fc_mode = bool(
            self.llm_adapter is not None
            and getattr(self.llm_adapter, "supports_function_calling", False)
        )
        return self._prompt_builder.build_system_prompt(context, fc_mode=fc_mode)

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
                # 摘要专用模型：直接裸调用（无工具、无状态注入），成本最小化；
                # 814H7/B8：辅助摘要档位独立于主模型（策略表 summary 角色 > 全局设置）
                from src.video_agent.core import model_policy

                resp = await adapter.chat(
                    [
                        {"role": "system", "content": "你是记忆整理助手。"},
                        {"role": "user", "content": prompt},
                    ],
                    timeout=settings.llm_timeout,
                    thinking_level=model_policy.thinking_for(
                        "summary", getattr(settings, "aux_thinking_level", "") or ""
                    ),
                )
            return resp.content or ""

        return _fn

    async def _call_llm(self, system: str, messages: List[Dict[str, Any]]) -> ChatResponse:
        """
        LLM 调用（§2.2）：支持 function calling 的 adapter 传入 tool schemas；
        不支持的（mock/演示）纯文本调用（4-4 后不再作为生产动作通道）。
        """
        full_messages = [{"role": "system", "content": system}] + messages
        # Token 预算截断：窗口按模型查表；system 自身超预算时走降级保险丝
        max_tokens = int(self._context_window() * settings.token_budget_ratio)
        full_messages = truncate_messages(full_messages, max_tokens, system_degrader=self._system_degrader)
        # 实时上下文度量（2222 反馈）：截断后的真实消息记入 live 注册表，
        # context-usage 接口推理中即可看到用量随轮次增长
        record_live_context(self.state_manager.active_project_id, full_messages)

        if self.llm_adapter is None:
            # 无 adapter 时返回空响应（mock 路径由上层处理）
            return ChatResponse(content="", finish_reason="stop")

        if self.llm_adapter.supports_function_calling:
            # 模式 A：标准 function calling（工具集按上下文裁剪）
            tools_schema = self.tool_manager.get_all_tool_schemas(exclude=self._excluded_tools)
            return await self.llm_adapter.chat(
                full_messages, tools=tools_schema, timeout=settings.llm_timeout,
                thinking_level=getattr(self, "_chat_thinking_level", "") or "",
            )
        else:
            # 模式 B：纯文本（fallback 到 studio-actions 文本解析）
            return await self.llm_adapter.chat(
                full_messages, timeout=settings.llm_timeout,
                thinking_level=getattr(self, "_chat_thinking_level", "") or "",
            )

    async def _call_llm_stream(self, system: str, messages: List[Dict[str, Any]]) -> AsyncGenerator[StreamChunk, None]:
        """流式 LLM 调用"""
        full_messages = [{"role": "system", "content": system}] + messages
        # Token 预算截断：窗口按模型查表；system 自身超预算时走降级保险丝
        max_tokens = int(self._context_window() * settings.token_budget_ratio)
        full_messages = truncate_messages(full_messages, max_tokens, system_degrader=self._system_degrader)
        # 实时上下文度量（2222 反馈）：同 _call_llm，推理中用量可见
        record_live_context(self.state_manager.active_project_id, full_messages)

        if self.llm_adapter is None:
            return

        tools_schema = None
        if self.llm_adapter.supports_function_calling:
            tools_schema = self.tool_manager.get_all_tool_schemas(exclude=self._excluded_tools)

        async for chunk in self.llm_adapter.chat_stream(
            full_messages, tools=tools_schema, timeout=settings.llm_stream_timeout,
            thinking_level=getattr(self, "_chat_thinking_level", "") or "",
        ):
            yield chunk

    # ---------- 控制流统一（ADR-0002）：确定性分诊（实现体 = planner_triage） ----------
    #
    # 概率语料路由已删除：语料路由错过一次 = 全程失控。分诊只认客观状态
    # 事实，措辞不参与判定；交接后由阶段前置闸与步间回收保底。
    # 同名委托保持既有调用/测试路径（宪法 §12 登记壳）。

    def _is_adhoc_edit(self, user_message: Any) -> bool:
        """ad-hoc 特征（客观事实）：消息命中既有资产名 → 交接模型循环。"""
        return planner_triage.is_adhoc_edit(self.state_manager.state_dict, user_message)

    def _is_question(self, user_message: Any) -> bool:
        """提问客观特征（标点/疑问词）：自由提问不错抓进流程推进。"""
        return planner_triage.is_question(user_message)

    def _triage_control(self, user_message: Any, skill: str) -> str:
        """确定性分诊：返回 advance | handoff，零语料（实现体 planner_triage）。"""
        return planner_triage.triage_control(
            self.state_manager.state_dict, user_message, skill)

    async def _run_orchestrator_path(
        self, context: "PlannerContext", user_message: Any = "",
    ) -> Optional["PlannerResponse"]:
        """编排器快路径；返回 None = 创作型阶段交接模型循环（实现体 planner_triage）。"""
        return await planner_triage.run_orchestrator_path(
            self.state_manager, context.skill_name, user_message,
            PlannerResponse, self._issue_pause)

    async def _handle_fc_response(
        self,
        response: ChatResponse,
        image_urls_collector: Optional[List[str]] = None,
        chat_inserts_collector: Optional[List[Dict[str, Any]]] = None,
        action_log_collector: Optional[List[str]] = None,
        confirmation_options_collector: Optional[List[Dict[str, Any]]] = None,
        docs_written_collector: Optional[List[str]] = None,
        fc_warnings_collector: Optional[List[str]] = None,
        image_provider: str = "",
        image_aspect_ratio: str = "",
        on_status=None,
        on_event=None,
        injected_skill: str = "",
        selected_draft_id: str = "",
        selected_type: str = "",
        gate_override: Any = False,
        confirmation_collector: Optional[Dict[str, Any]] = None,
    ) -> Tuple:
        """处理 LLM 响应中的 FC tool_calls（实现体 fc_response.merge_fc_response）。
        返回 (content, finish_reason, fc_applied, tool_results, fc_warnings)；
        执行经 self._execute_fc_tools 注入（monkeypatch 目标不变）。"""
        return await fc_response.merge_fc_response(
            response, self._execute_fc_tools,
            image_urls_collector=image_urls_collector,
            chat_inserts_collector=chat_inserts_collector,
            action_log_collector=action_log_collector,
            confirmation_options_collector=confirmation_options_collector,
            docs_written_collector=docs_written_collector,
            fc_warnings_collector=fc_warnings_collector,
            image_provider=image_provider,
            image_aspect_ratio=image_aspect_ratio,
            on_status=on_status,
            on_event=on_event,
            injected_skill=injected_skill,
            selected_draft_id=selected_draft_id,
            selected_type=selected_type,
            gate_override=gate_override,
            confirmation_collector=confirmation_collector,
        )

    async def _execute_fc_tools(
        self, response: ChatResponse, image_provider: str = "", image_aspect_ratio: str = "",
        on_status=None, on_event=None, injected_skill: str = "",
        selected_draft_id: str = "", selected_type: str = "",
        gate_override: Any = False,
    ) -> Tuple[int, str, List[str], List[Dict[str, Any]], List[str], List[Dict[str, Any]], List[Dict[str, Any]], List[str], List[str]]:
        """执行 Function Calling 返回的 tool_calls（委托 FCToolRunner）。
        返回 (applied_count, confirmation_message, image_urls, chat_inserts, action_log,
        confirmation_options, tool_results, docs_written, warnings)"""
        return await self._fc_runner.execute(
            response, image_provider=image_provider, image_aspect_ratio=image_aspect_ratio,
            on_status=on_status, on_event=on_event, injected_skill=injected_skill,
            selected_draft_id=selected_draft_id, selected_type=selected_type,
            gate_override=gate_override,
        )


