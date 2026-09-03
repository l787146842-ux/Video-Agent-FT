"""
Planner — 对话式 Agent 的唯一入口（Rule1）。

设计方案核心：
- Planner 直接持有 LLM Adapter 引用（Rule6: 外部调用走 Adapter），不经过 Tool Manager
- Tool Manager 只管理"业务 Tool"（故事板操作、生图、文档等）
- 动作通道唯一 = FC 工具调用
- 多步循环（上限每步实时读 settings，Q3），LLM 可请求 continue 推进后续轮次
- 流式通过 AsyncGenerator 穿透（SSE）

单轮 llm_call/FC 响应消费/回喂治理/上下文预算装配切出
core/turn_executor.py（TurnExecutor）；本文件保留入口编排、契约
数据结构、工具裁剪与轮末组装委托。
"""
import asyncio
import uuid
from dataclasses import dataclass, field, replace as dc_replace
from typing import Any, AsyncGenerator, Callable, Dict, List, Optional, Tuple, Union

from loguru import logger

from src.video_agent.core.chat_port import ChatAdapterPort, ChatResponse
from src.video_agent.utils.cancel_token import GenerationCancelled
from src.video_agent.config import settings
from src.video_agent.state.manager import StateManager
from src.video_agent.tools.base import ToolResult
from src.video_agent.tools.manager import ToolManager
# MCP 两段式注入段 2：未启用 MCP 工具 schema 不进 FC payload
from src.video_agent.tools.mcp import catalog as mcp_catalog
from src.video_agent.utils.prompts import load_prompt, render_prompt
from src.video_agent.core.agent_loop import current_max_steps, run_agent_loop
from src.video_agent.core.fc_tool_runner import (
    FCExecuteResult,
    FCToolRunner,
)
from src.video_agent.core.prompt_builder import PromptBuilder
# 动作执行器与操作描述已下沉 core；顶层导入替代旧 web 延迟导入
from src.video_agent.core.action_executor import StateOperationExecutor
from src.video_agent.core.action_descriptions import aggregate_action_log
from src.video_agent.core.ports import canvas_online_cached, skill_docs_port
# 轮末组装域切入 planner_output
from src.video_agent.core.planner_output import append_costly_retry_action, assemble_response
# 阶段表/探针/闸预检纯数据层（导入期同时落地
# step_done_probe 注册钩子，不得删除）
from src.video_agent.core import stage_probes
from src.video_agent.core import prompt_gates
from src.video_agent.core import fc_response, planner_gate_session, planner_triage
# 单轮执行协作臂：单轮执行 + FC 响应消费 + 回喂治理 + 上下文预算装配
from src.video_agent.core.turn_executor import TurnExecutor
from src.video_agent.utils.live_metrics import record_degradation
from src.video_agent.core.sse_events import status_event
from src.video_agent.skill_runtime.registry import fallback_skill_from_state
# Workflow Runtime：账本 + 裁判数据层
from src.video_agent.core import workflow_runtime


# 绑定工作台状态的工具集：use_studio_context=False 时不下发（节省 schema token）
_STUDIO_STATE_TOOLS = frozenset({
    "storyboard_create_group", "storyboard_patch_draft", "storyboard_add_draft",
    "storyboard_delete_group", "storyboard_confirm_draft", "storyboard_media_to_chat",
    "view_storyboard_media",
    "read_draft", "document_write", "read_uploaded_doc", "read_project_doc",
    "read_state_group",
})

# 画布工具集：画布离线/未启用时不下发（节省 schema token）
_CANVAS_TOOLS = frozenset({
    "canvas_list", "canvas_read_nodes", "canvas_add_node", "canvas_update_node",
    "canvas_delete_node", "canvas_list_assets", "canvas_batch_add_nodes",
})

# 后台节点任务登记；drain 供测试/关停等待
_BG_TASKS: set = set()


async def drain_background_tasks() -> None:
    """等待在途后台节点任务完成（幂等；测试与优雅关停钩子）。"""
    for t in list(_BG_TASKS):
        try:
            await t
        except Exception:
            pass


@dataclass
class PlannerContext:
    """每轮对话的上下文参数"""
    history: List[Dict[str, Any]] = field(default_factory=list)
    selected_draft_id: str = ""
    selected_type: str = ""
    state_json: str = ""
    # 状态 JSON 的惰性构建器：多步循环每个轮次都会调用一次，
    # 保证模型在每轮看到先前轮次执行后的最新工作台状态。
    # 传入 state_json 字符串是旧调用方式的兼容降级（整段固定不变）。
    state_builder: Optional[Callable[[], str]] = None
    skill_name: str = ""         # 前端当前选中的 Skill 名称（目录标注用，提高相关性判断准确率）
    # 用户键入原文（未经多模态/附件拼装）。闸预检/分诊历史消费点
    # 只认原话——附件预览里的剧本对白问号不得参与判定（根因）。
    raw_user_text: str = ""
    use_studio_context: bool = True
    asset_mode: str = "bound"    # 资产过滤模式
    image_generation_provider: str = ""  # 选中草稿的生图 provider，用于强制注入
    image_generation_aspect_ratio: str = ""  # 选中草稿的画面比例（如 16:9），用于强制注入
    # 降级状态构建器（token 保险丝）：system 段超预算时用「只留组标题/计数」的
    # 降级状态 JSON 重建 system prompt，保证请求不超窗发出
    degraded_state_builder: Optional[Callable[[], str]] = None
    # 前奏时间线：只登记真实发生的 system 动作（绑定 Skill：轻量状态块+流程纪律），
    # 读取/存档由对应工具真实发生时记录，前奏不得冒充工具操作
    prelude_notes: List[tuple] = field(default_factory=list)
    # 多用户归属：可选用户标识，入 trace 审计
    user_id: str = ""
    # 会话级推理档位（对话栏「推理等级」选择器下发；""=模型原生能力）
    thinking_level: str = ""
    # 轮间引导注入器（任务式传输注册的排队消息，逐轮消费）。
    # 由 web 层按 task_id 装配（agent_task_manager.drain_pending_guidance）；
    # None = 无注入（非任务路径）。
    pending_injector: Optional[Callable[[], List[Dict[str, Any]]]] = None
    # 轮始客观推进信号（输入类 decision 消费/闸预检分诊；
    # runtime 不据此自主行动）：
    # "pause"=上轮暂停被消费；"wizard"=规格向导回应被消费；
    # "continue"=点选系统派生继续选项；"attachment"=本轮带附件。
    # 空串 = 自由对话轮（提问等），交接模型循环。
    advance_signal: str = ""
    # 协作式停止标志作用域（端到端中断协议）：
    # SSE 直连="chat"；任务式传输=task_id（web 层按传输路径装配）
    stop_scope: str = "chat"
    # 同源裁剪解释：阶段探测驱动的工具裁剪结果与解释文案由
    # _compute_excluded_tools 单一事实源签发，prompt_builder 只消费不自判：
    # stage_note 非空 ⇔ 阶段裁剪生效（成对出现，消灭「静默裁剪」反模式）
    stage_excluded_tools: frozenset = frozenset()
    stage_note: str = ""
    # 微调作用域（微调真子对话）：非空 ⇔ 本请求归属隐藏线程子对话，
    # 纪律提示段（prompts/planner/adjust.md）据此注入；
    # 内容恒定不嵌目标编号（保前缀缓存），目标信息由状态裁剪面携带。
    adjust_scope: Dict[str, Any] = field(default_factory=dict)
    # turn_budget 客观步数（P3 状态即数据）：(current_step, max_steps)
    # 由 turn_executor 每步更新，经状态尾部消息注入给模型；
    # None = 不注入（首轮/非循环路径）。
    step_info: Optional[tuple] = None


@dataclass
class PlannerResponse:
    """Planner 返回结果"""
    text: str = ""
    applied_actions: int = 0
    steps: int = 0
    warnings: List[str] = field(default_factory=list)
    confirmation: str = ""
    documents_written: List[str] = field(default_factory=list)
    image_urls: List[str] = field(default_factory=list)  # image_generate（single 模式）产出的图片 URL
    # 待插入前端对话输入框的故事板媒体（insert_chat_media / storyboard_media_to_chat 产出）
    chat_inserts: List[Dict[str, Any]] = field(default_factory=list)
    # 已执行操作的中文描述清单（前端「阶段完成」卡片展开用，随消息持久化）
    action_log: List[str] = field(default_factory=list)
    # 确认卡片的候选选项（每项 {label, description}，前端渲染为单选卡片）
    confirmation_options: List[Dict[str, Any]] = field(default_factory=list)
    # 执行轨迹（每轮 step/耗时/操作数），前端「执行轨迹」折叠区展示
    trace: Dict[str, Any] = field(default_factory=dict)
    # 建议动作按钮（重试/继续，确定性交互；详见 agent_loop 同名字段）
    suggested_actions: List[Dict[str, str]] = field(default_factory=list)
    # 暂停卡结构化标识（对标 AskUserQuestion 范式）：三个 confirm 产生源
    # （FC workflow_pause / 闸预检兜底卡 / 轮末策略卡）在两个汇流点统一签发，
    # 随 done payload 下发；用户回应经 ChatRequest.pause_response 结构化回携
    pause_id: str = ""
    # 暂停卡语义种类（remind/collect/stage_done/confirm，前端标题渲染唯一依据）
    pause_kind: str = ""
    # 协作式停止标记：随 done payload 下发，web 透传层据此
    # 落停止痕迹消息并不再发 done（stopped 终态事件已由 agent_loop 先行下发）
    stopped: bool = False
    stop_phase: str = ""


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
        llm_adapter: Optional[ChatAdapterPort] = None,
        executor_factory: Optional[Callable[..., Any]] = None,
        skill_docs: Optional[Any] = None,
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
        # 当前对话聊天供应商（与主模型一致；web 层注入）
        self.chat_provider = chat_provider
        self.chat_model = chat_model
        # 按上下文裁剪的工具集合（handle_message 时计算）
        self._excluded_tools: frozenset = frozenset()
        # system 超预算时的降级重建器（handle_message 时按 context 装配）
        self._system_degrader: Optional[Callable[[str], str]] = None
        # 拆出的协作臂：prompt 组装与 FC 执行，Planner 保留同名委托
        self._prompt_builder = PromptBuilder(
            self._get_skill_docs,
            lambda: self.state_manager.active_project_id,
            # 分阶段聚焦注入：实时读取工作台状态推断当前制作阶段
            lambda: self.state_manager.state_dict,
        )
        self._fc_runner = FCToolRunner(self.tool_manager)
        self._fc_runner.chat_provider = self.chat_provider
        self._fc_runner.chat_model = self.chat_model
        # 拆出的协作臂：单轮执行 + FC 响应消费 + 回喂治理 +
        # 上下文预算装配；handle_message 每轮 bind_turn 后委托 llm_call，
        # 摘要路径复用其 call_llm（预算管线同一实现）
        self._turn_executor = TurnExecutor(self)

    def _get_skill_docs(self):
        """Skill 文档提供者：优先注入实例，缺省经 core 端口取 web 层实现
        （依赖倒置：装配点注入，core 不 import web）"""
        if self._skill_docs is None:
            self._skill_docs = skill_docs_port()
        return self._skill_docs

    def _compute_excluded_tools(self, context: PlannerContext) -> frozenset:
        """按上下文计算本轮不下发的工具集（token 治理：schema 全量常驻是每轮固定开销）。

        同源裁剪解释：阶段裁剪的 (excluded, note) 在此一并签发到
        context（stage_excluded_tools/stage_note），prompt_builder 据此注入解释段，
        裁剪与解释同源同条件，不再各自判定。
        """
        excluded = set()
        # 先复位再签发：防 context 对象跨轮复用时残留旧值
        context.stage_excluded_tools = frozenset()
        context.stage_note = ""
        if not context.use_studio_context:
            excluded |= _STUDIO_STATE_TOOLS
        if not settings.canvas_enabled:
            excluded |= _CANVAS_TOOLS
        else:
            # 已探测过且离线才裁剪；从未探测（None）保持现状
            # 依赖倒置：经 core.ports.canvas_online_cached 端口读取（core 不 import adapters）
            if canvas_online_cached() is False:
                excluded |= _CANVAS_TOOLS
        # 混合形态第一层：阶段探测驱动的工具裁剪（仅 Skill 激活 + strict），
        # 用工具可见性隔离阶段；第二层由既有闸机兜底
        if context.skill_name and context.use_studio_context \
                and prompt_gates.gate_mode() == "strict":
            try:
                stage_excluded, stage_note = prompt_gates.stage_tool_restrictions(
                    self.state_manager.state_dict
                )
                excluded |= set(stage_excluded)
                # 裁剪非空才携带解释（两者成对，prompt_builder 见 note 即注入）
                if stage_excluded:
                    context.stage_excluded_tools = frozenset(stage_excluded)
                    context.stage_note = stage_note
            except Exception:
                pass  # 裁剪失败不阻断对话，闸机层仍生效
        # read_skill 全程可见（任务#12 渐进式披露：L2 正文经 read_skill 按需读取，
        # 选中 Skill 全文直注时也不关重读入口）
        # MCP 两段式注入：白名单（interaction.mcp_enabled）外
        # 的 MCP 工具 schema 不下发（deny-first 可见性面；目录块已告知存在）
        try:
            excluded |= set(mcp_catalog.inactive_tool_names())
        except Exception:
            pass  # 裁剪失败不阻断对话；未启用工具直调仍被 adapter 拒执行
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

    # ---------- 暂停卡结构化签发（单一实现，汇流点一专用） ----------
    def _issue_pause(self, response: "PlannerResponse") -> None:
        """为携带 confirmation 的响应签发 pause_id 并登记 interaction.active_pause。

        汇流点一（handle_message 轮末组装后）覆盖 FC workflow_pause 与轮末策略卡；
        汇流点二（_run_gate_precheck）的提醒类兜底卡已出槽（批 B），改走正文注入 +
        quick-actions 芯片，不再经本方法登记。登记不改变
        awaiting_confirmation 既有语义（消费链零行为变更），只叠加结构化标识。
        """
        if not response.confirmation:
            return
        if response.pause_id:
            # 问即停（决策史见 git tag adr-archive-20260901）：发行点（FCToolRunner）已以同一 pause_id 原子
            # 登记暂停三态，汇流点不重复签发（幂等；轮末策略卡无预置
            # pause_id 时仍走下方签发路径）
            return
        response.pause_id = uuid.uuid4().hex[:12]
        try:
            workflow_runtime.reduce_interaction(self.state_manager, set_flags={
                "active_pause": {
                    "pause_id": response.pause_id,
                    "message": response.confirmation,
                    "options": list(response.confirmation_options or []),
                    # 发行轮次戳（批 C）：供轮始自愈对账计算卡龄，
                    # 超阈未消费的残留卡自动退役（防永远停在旧阶段）
                    "issued_turn_seq": int(
                        self.state_manager.state_dict.get("turn_seq") or 0),
                },
            })
        except Exception as _e:
            # 承重接线遥测：暂停登记断线降级端点可见（对勾派生依赖此登记）
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
        （文本块解析仅消费系统内部合成的确认块）。
        stream_hook: 可选 async callable(text)，流式模式下每段 LLM 增量文本回调。
        """
        # 当前 Skill 归属：请求未携带 Skill 时回退项目 usedSkills 末位，
        # 保证后续轮次仍绑定同一执行器；单一实现见 registry.fallback_skill_from_state。
        if not context.skill_name:
            context.skill_name = fallback_skill_from_state(self.state_manager.state_dict)

        # 轮始清理 workflow 编译缓存（sidecar 声明轮间可编辑，缓存仅限本轮）
        workflow_runtime.clear_compile_cache()
        # 子对话不发确认卡（二期子对话批 3）：scope 任务命中 workflow_pause 直接
        # 放行（FCToolRunner 据此旗标不登记暂停/不组卡）；主对话问即停语义不变。
        # Planner 实例每请求新建（chat_service 装配），旗标不跨请求泄漏。
        self._scope_auto_pause = bool(context.adjust_scope)

        # 按上下文裁剪本轮下发的工具集 + 装配 system 超预算降级器（token 治理）
        self._excluded_tools = self._compute_excluded_tools(context)
        self._system_degrader = self._make_system_degrader(context)
        # 三通道分离 C：轮始重置 FC runner 跨批跟踪（阶段边界只认本轮）
        self._fc_runner.reset_turn_tracking()
        # 会话级推理档位（""=原生；主模型调用透传，端点不认则静默忽略）
        self._chat_thinking_level = context.thinking_level or ""

        # 构建状态视图载体（Q2：文本轨动作分派已退役，动作通道唯一 = FC；
        # 载体供 agent_loop/轮末策略读 state 与动作描述）：优先注入的工厂，缺省 core 层实现
        factory = self.executor_factory
        if factory is None:
            factory = StateOperationExecutor
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

        # Workflow Runtime：runtime 为「账本 + 裁判数据层」——轮始只做
        # run 同步（RunStarted 幂等）与客观数据预取；本轮做什么永远由模型
        # 接到用户消息后发起工具调用，runtime 无自主行动能力。
        # （C1b 裁决 2026-08-31：stage_precondition 越阶硬闸退役，
        # 流程顺序改由模型读 planner 散文自主执行。）
        if settings.pipeline_orchestrator_enabled and context.skill_name:
            # 轮始 run 同步（RunStarted 幂等）+ 输入类 decision 消费
            # （waiting_user→ready，DecisionResolved 入事件账本）。
            try:
                _rt = workflow_runtime.WorkflowRuntime(
                    self.state_manager, context.skill_name)
                _run0 = _rt.start_run()
                if str(context.advance_signal or "").strip():
                    _pend = _run0.get("pending_decision") or {}
                    if ((_pend.get("schema") or {}).get("type")) == "input":
                        _rt.resolve_decision(
                            str(_pend.get("token") or ""),
                            str(context.advance_signal))
            except Exception as _e:
                # 承重接线遥测：轮始 run 同步失败 fail-open 不阻断对话
                record_degradation("planner.run_sync")
                logger.debug("[WorkflowRuntime] 轮始 run 同步跳过: {}", _e)

        # 轮始闸预检只装配兜底卡（原料闸/规格闸，层 9 由代码执行不依赖
        # 模型自觉）；其余交接模型循环。
        # （C1b 裁决 2026-08-31：越阶硬闸退役，顺序由模型自主。）
        if settings.pipeline_orchestrator_enabled and context.skill_name:
            # 闸预检只认用户原话——user_message 可能是多模态拼装
            # （附件预览含剧本对白问号，不得参与豁免/回执意图判定）
            try:
                _orch = await self._run_gate_precheck(
                    context, context.raw_user_text or user_message)
            except Exception as _e:
                # 承重接线遥测：预检失败 fail-open 不阻断对话
                record_degradation("planner.gate_precheck")
                logger.warning("[ControlFlow] 闸预检失败（交接模型循环）: {}", _e)
                _orch = None
            if _orch is not None:
                return _orch

        # 单轮执行委托 TurnExecutor：收集器在此定义、跨多步
        # 共享，轮末由 assemble_response 统一合并
        image_urls_collector: List[str] = []
        # chat_inserts_collector 用于跨多步收集「插入对话输入框」的媒体
        chat_inserts_collector: List[Dict[str, Any]] = []
        # action_log_collector 用于跨多步收集 FC 工具的操作描述
        action_log_collector: List[str] = []
        # confirmation_options_collector 用于跨多步收集确认卡片的候选选项
        confirmation_options_collector: List[Dict[str, Any]] = []
        # docs_written_collector 用于跨多步收集 FC 轨写入的文档名（渲染文档卡片）
        docs_written_collector: List[str] = []
        # FC 轨闸机拦截/豁免文案收集器（每批 execute 返回的 warnings），
        # 循环结束后并入 loop_result.warnings，与文本轨拦截可见性对齐
        fc_warnings_collector: List[str] = []
        # Q22：花钱生成失败登记跨批累积，轮始清空（runner 为实例级共享）
        self._fc_runner.costly_failures.clear()

        # 装配本轮执行器（实现体 core/turn_executor.py）：单轮 llm_call
        # 携带停止检查点/FC 响应消费/回喂治理（惰性压缩/图片剥离）
        self._turn_executor.bind_turn(
            context=context,
            gate_override_scope=gate_override_scope,
            collectors={
                "image_urls": image_urls_collector,
                "chat_inserts": chat_inserts_collector,
                "action_log": action_log_collector,
                "confirmation_options": confirmation_options_collector,
                "docs_written": docs_written_collector,
                "fc_warnings": fc_warnings_collector,
            },
            on_event=on_event,
        )

        # 构建 context_builder
        def context_builder() -> str:
            return self._build_system_prompt(context)

        # 委托给统一循环（越阶/越暂停由闸机在工具调用点否决）
        loop_result = await run_agent_loop(
            user_message,
            llm_call=self._turn_executor.llm_call,
            context_builder=context_builder,
            executor=executor,
            history=context.history,
            stream_hook=stream_hook,
            on_event=on_event,
            prelude_notes=context.prelude_notes,
            user_id=context.user_id,
            pending_injector=context.pending_injector,
            stop_scope=context.stop_scope,
        )

        # Q22 裁决 2026-09-01：花钱生成失败不静默——轮末机械附一键重试选项卡（实现体 planner_output）
        append_costly_retry_action(loop_result, self._fc_runner.costly_failures)

        # 轮末组装委托 planner_output：warnings 并入/总结强入/
        # 占位替换/收集器去重/原料提醒卡覆盖/响应构造。
        # 聚合工具顶层导入（patch 目标=本命名空间）
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
        # 协作式停止标记透传：轮末组装不改停止语义，
        # 只把循环的 stopped/stop_phase 随响应下发（web 层据此落痕迹）
        response.stopped = bool(loop_result.stopped)
        response.stop_phase = str(loop_result.stop_phase or "")
        # 问即停：发行点签发的 pause_id 透传，供 _issue_pause 幂等
        response.pause_id = str(getattr(loop_result, "pause_id", "") or "")

        # 暂停卡结构化签发（汇流点一）：FC workflow_pause 与轮末策略卡均在此汇流
        self._issue_pause(response)

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
                # 队列级 status 走 status_event key+params；payload 携带完整
                # status 事件，chat_service 透传
                step = event.get("step", 1)
                max_steps = event.get("max_steps") or current_max_steps()
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
            elif etype in ("reasoning_delta", "tool_started", "tool_finished", "guidance_injected", "doc_written", "stopped"):
                # 过程时间线事件穿透（前端渲染深度思考/工具条目）；
                # stopped=停止终态事件（agent_loop 检查点发出，
                # web 透传层富化在途登记后作为终态帧下发）
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
        # 必须取消后台任务，否则孤儿任务继续烧 token 并写状态
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
        if error_holder and isinstance(error_holder[0], GenerationCancelled):
            # 取消穿透闭环：分流为 stopped 终态，不进 error 分支
            _cancel_exc = error_holder[0]
            yield PlannerEvent(type="stopped", text=str(_cancel_exc), payload={
                "type": "stopped", "phase": "tool_executing",
                "detail": str(_cancel_exc),
            })
            return
        if error_holder:
            exc = error_holder[0]
            yield PlannerEvent(type="error", text=str(exc), payload={
                "error_code": getattr(exc, "error_code", "INTERNAL_ERROR"),
                "retryable": getattr(exc, "retryable", None),
                "http_status": getattr(exc, "http_status", None),
            })
            return

        result = result_holder[0] if result_holder else PlannerResponse()
        # 空回复占位统一由前端渲染（「（空回复）」单一形态），
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
            "suggested_actions": result.suggested_actions,
            "pause_kind": result.pause_kind,
            # 协作式停止标记：web 透传层据此落停止痕迹、不再发 done
            "stopped": bool(result.stopped),
            "stop_phase": result.stop_phase,
        })

    # ---------- 内部方法 ----------

    def _build_system_prompt(self, context: PlannerContext) -> str:
        """构建 system prompt（委托 PromptBuilder；段落顺序为前缀缓存优化）。
        协议单轨：统一注入 protocol.md。"""
        return self._prompt_builder.build_system_prompt(context)

    # ---------- 闸预检（层 9 兜底卡，实现体 = planner_triage.run_gate_precheck） ----------
    #
    # 轮始只装配原料闸/规格闸兜底卡（由代码执行不依赖模型自觉）；提醒类不占
    # 暂停槽（正文注入 + quick-actions 芯片）；其余交接模型循环；越阶/越暂停
    # 由闸机在工具调用点否决。

    async def _run_gate_precheck(
        self, context: "PlannerContext", user_message: Any = "",
    ) -> Optional["PlannerResponse"]:
        """轮始闸预检；返回 None = 交接模型循环（实现体 planner_triage）。"""
        return await planner_triage.run_gate_precheck(
            self.state_manager, context.skill_name, user_message,
            PlannerResponse)

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
    ) -> FCExecuteResult:
        """执行 Function Calling 返回的 tool_calls（委托 FCToolRunner.execute，
        返回结构化 FCExecuteResult；位置解包仍兼容，
        新调用方按字段名取用）。"""
        return await self._fc_runner.execute(
            response, image_provider=image_provider, image_aspect_ratio=image_aspect_ratio,
            on_status=on_status, on_event=on_event, injected_skill=injected_skill,
            selected_draft_id=selected_draft_id, selected_type=selected_type,
            gate_override=gate_override,
            # scope 子对话暂停放行旗标（handle_message 轮始按 adjust_scope 置位）
            scope_auto_pause=bool(getattr(self, "_scope_auto_pause", False)),
        )


