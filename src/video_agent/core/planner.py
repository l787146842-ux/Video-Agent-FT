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
from src.video_agent.config import (
    EXECUTION_MODE_GATE_MODES,
    normalize_exec_mode,
    normalize_exec_pref,
    settings,
)
from src.video_agent.state.manager import StateManager
from src.video_agent.tools.base import ToolResult
from src.video_agent.tools.manager import ToolManager
# MCP 两段式注入段 2：未启用 MCP 工具 schema 不进 FC payload
from src.video_agent.tools.mcp import catalog as mcp_catalog
from src.video_agent.utils.prompts import load_prompt, render_prompt
from src.video_agent.utils.prompts import load_prompt_section
from src.video_agent.core.agent_loop import run_agent_loop
from src.video_agent.core.tracer import AgentTracer
# 子代理可选模档：读模型分层策略表（core→core 无环；空/未配 = 跟随主模型）
from src.video_agent.core import model_policy
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
from src.video_agent.core import session_log
# 单轮执行协作臂：单轮执行 + FC 响应消费 + 回喂治理 + 上下文预算装配
from src.video_agent.core.turn_executor import TurnExecutor
from src.video_agent.utils.live_metrics import record_degradation
from src.video_agent.core.sse_events import status_event
from src.video_agent.skill_runtime.progress import emit_event_card
from src.video_agent.skill_runtime.registry import fallback_skill_from_state, tool_sections
# Workflow Runtime：账本 + 裁判数据层
from src.video_agent.core import workflow_contract, workflow_runtime
from src.video_agent.core import state_delta as state_delta_mod
from src.video_agent.core.pause_composer import PAUSE_KIND_STAGE_DONE
# 正宗子代理：契约常量/纯辅助（subagent 仅依赖 utils.prompts，无环）+ 子会话创建
from src.video_agent.core import subagent as subagent_mod
from src.video_agent.state import conversation_ops


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

# 批 10 · 执行偏好注入文案唯一源（分节键 = PREF_<档位大写>；
# 消费端 _load_execution_pref_note，经状态尾部消息每步注入）
_EXEC_PREF_NOTE_FILE = "planner/execution_preference.md"

# 执行模式注入文案唯一源（2026-09-06 对齐批；分节键 = MODE_<档位大写>；
# 消费端 _load_execution_mode_note；ai_decide 默认档无分节 = 不注入，行为与
# 现状一致。key_steps_confirm/pause_all 两档另有轮末阶段闸机械拦停兜底）
_EXEC_MODE_NOTE_FILE = "planner/execution_mode.md"

# 后台节点任务登记；drain 供测试/关停等待
_BG_TASKS: set = set()

# 子代理标题最大长度（含省略号）
_SUBAGENT_LABEL_MAX = 40


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
    # 8888 事故批（对齐 dsh「父停杀子、子停不碍父」）：循环自己的停止标志
    # 清理作用域。空 = 与 stop_scope 相同（顶级循环行为不变）；子代理构造
    # context 时必须传独立作用域（父 scope::sub::子会话 id）——子循环观察
    # stop_scope（父标志置位即停），但轮始/收尾只清理本作用域，不再截胡
    # 父循环待消费的停止标志（8888 实证：共享标志被子代理清掉，主循环
    # 失聪成孤儿，与续跑新循环并行 4 分钟）
    stop_scope_own: str = ""
    # 同源裁剪解释（stage_excluded_tools/stage_note）已随批 B 工具全量常驻
    # 退役（2026-09-09 用户裁决）：阶段裁剪与边界注释不再存在，正确性由
    # 闸机 + 工具自身校验兜底。
    # 批 10 · 执行偏好注入（外部标杆同款：偏好进 Agent 上下文由模型行为执行，
    # 闸机兜底硬保证见批 9 同意账本）：轮始按档位签发，经状态尾部消息
    # 每步注入；文案唯一源 = prompts/planner/execution_preference.md
    execution_pref_note: str = ""
    # 执行模式注入（2026-09-06 对齐批）：轮始按档位签发，经状态尾部
    # 消息每步注入；文案唯一源 = prompts/planner/execution_mode.md；
    # ai_decide 默认档 = 空串不注入（行为与现状一致）。
    execution_mode_note: str = ""
    # 轮末阶段闸快照（2026-09-06 对齐批）：轮始 ensure_run 的 run 快照，
    # 供轮末对比「本轮是否有阶段节点翻转完成」（机械闸触发判据，客观探针口径）
    workflow_run0: Dict[str, Any] = field(default_factory=dict)
    # 微调作用域（微调真子对话）：非空 ⇔ 本请求归属隐藏线程子对话，
    # 纪律提示段（prompts/planner/adjust.md）据此注入；
    # 内容恒定不嵌目标编号（保前缀缓存），目标信息由状态裁剪面携带。
    adjust_scope: Dict[str, Any] = field(default_factory=dict)
    # 正宗子代理（run_subagent）上下文标记：
    # subagent_depth = 委派深度（顶级 0，子级 = 父+1，恢复态不得归零）；
    # subagent_no_confirm = 子级不向用户发确认（复用 _scope_auto_pause 通道）；
    # subagent_deny = 子级工具 deny 集（非空 ⇒ 子级可见面 = 主代理面 − 本集，
    # 对齐 dsh inherit∩restrict；含 run_subagent 天然防递归）。
    subagent_depth: int = 0
    subagent_no_confirm: bool = False
    subagent_deny: Optional[frozenset] = None
    # 轮内被裁剪工具集（R11 裁剪可见性）：轮始由 _compute_excluded_tools 签发，
    # 供 build_state_tail_message 渲染 UNAVAILABLE 段（模型可见哪些工具本轮不可用）。
    turn_excluded: Optional[frozenset] = None
    # （step_info 已随二期 G3 退役删除：状态尾部步数行每步必变是强制
    # 前缀失效源；轮次信息由 STEP_FEEDBACK「第 N 轮」承载）
    # 会话事件流归属（v4 主刀批 E1）：本请求的 conversation_id（可空=活跃会话，
    # 落流时按 target_chat_messages 同序解析）；空 + 非 studio 上下文 = 不落流。
    # LLM 历史唯一事实源 = 事件流（docs/会话层append-only化细案.md D3/D5）。
    session_conversation_id: str = ""
    # 轮首状态事件正文（二期 G3，dsh inject 同位）：handle_message 轮始构建
    # （build_state_tail_message 全家）并落 source=state 事件后存此；
    # run_agent_loop 组装 messages 时追加在 user 消息之后（与日志 seq 同序，
    # 回放=请求逐字节）。空串 = 本轮无状态注入（非 studio / 构建失败回落）。
    state_event_content: str = ""
    # B 方案增量对账（state_delta_enabled）：上一轮的状态 digest/哈希
    _state_digest: Optional[Dict[str, Dict[str, str]]] = None
    _state_hash: str = ""


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
    # 正文来源（批 C3）：mechanical = 轮末机械占位替换产出；随 done payload
    # 下发，web 层落 kind="mechanical"，线程装载历史时压成固定短句
    text_source: str = ""
    # 推理模型思考内容（五项修法批 4，透传自 AgentLoopResult）：是否随 done
    # payload 下发/持久化由 settings.llm_reasoning_passthrough 闸门控制
    reasoning_content: str = ""
    # 协作式停止标记：随 done payload 下发，web 透传层据此
    # 落停止痕迹消息并不再发 done（stopped 终态事件已由 agent_loop 先行下发）
    stopped: bool = False
    stop_phase: str = ""
    # R9 analysis 对话可见：本轮 script_analysis_report 成功产出的分析摘要
    # （fc_tool_runner 成功路径签发）；随 done payload 下发，web 层据此在
    # 对话框追加一条「剧本分析」摘要消息（不再仅右侧时间线事件卡）。空串=本轮无分析。
    analysis_digest: str = ""


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
        chat_adapter_factory: Optional[Callable[[str, str], Any]] = None,
    ):
        # state_manager 缺省回落单例（Rule3）；core 层不绕过它直接碰状态
        self.state_manager = state_manager or StateManager.get_instance()
        self.tool_manager = tool_manager or ToolManager
        self.llm_adapter = llm_adapter
        # chat_adapter_factory: 按 (provider, model) 造 chat adapter 的工厂（web 层
        # 装配点注入，消除 core→adapters/web 依赖；None = 子代理无法换模→跟随父档）。
        self._chat_adapter_factory = chat_adapter_factory
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
        """按上下文计算本轮不下发的工具集（轮始一次，轮内冻结——批 B1）。

        批 B（工具全量常驻，2026-09-09 用户裁决）：阶段裁剪退役——故事板
        结构就绪前的 generate_video 不再从可见面裁掉，改由第二层兜底
        （工具自身校验 + gen_confirm/tool_risk 闸 + 失败回喂带保留声明）；
        裁剪每步重算曾是前缀缓存击穿点，全量常驻后 tools 跨步字节稳定。
        仅保留轮界级裁剪源（canvas 探针 / MCP 白名单 / 非 studio 上下文）。
        """
        excluded = set()
        # K6 批（2026-09-16 对齐 dsh）：structured_output 为子代理专属完工
        # 打卡工具——主代理面（含自由对话）裁剪；prompt_builder 的
        # UNAVAILABLE 段不渲染 CHILD_ONLY_TOOLS（主代理不感知打卡工具）。
        if not getattr(context, "subagent_depth", 0):
            excluded |= subagent_mod.CHILD_ONLY_TOOLS
        # 子代理 deny 模式（2026-09-15 1111 批，对齐 dsh inherit∩restrict）：
        # 子级继承主代理整面工具，仅剔除 deny 集（run_subagent 防递归 / 花钱
        # 生成 / workflow_pause / stage 去 read_skill）。不再用硬编码 allowlist
        # （会漏授阶段落点工具，1111 实证 script_analysis_report 未授予）。
        # deny 叠加在 studio/canvas/MCP 常规裁剪之上（子级与父同受这些轮界裁剪）。
        deny = getattr(context, "subagent_deny", None)
        if deny:
            excluded |= set(deny)
        # 生产轮主代理裁剪（分工重设计，2026-09-15）：仅顶级生产轮生效；
        # 子级（depth≥1）/微调（adjust_scope）/自由对话（无 skill）不裁。
        # 子级**不继承**本裁剪——否则阶段执行器会被饿死（script_analyze 需
        # read_uploaded_doc、建组需 storyboard_create_group）；裁剪集 = 各可委派
        # 阶段生产工具并集（subagent.PRODUCTION_MAIN_PRUNE 单一源）。
        if (getattr(context, "skill_name", "")
                and not getattr(context, "subagent_depth", 0)
                and not getattr(context, "adjust_scope", None)):
            excluded |= subagent_mod.PRODUCTION_MAIN_PRUNE
        if not context.use_studio_context:
            excluded |= _STUDIO_STATE_TOOLS
        if not settings.canvas_enabled:
            excluded |= _CANVAS_TOOLS
        else:
            # 已探测过且离线才裁剪；从未探测（None）保持现状
            # 依赖倒置：经 core.ports.canvas_online_cached 端口读取（core 不 import adapters）
            if canvas_online_cached() is False:
                excluded |= _CANVAS_TOOLS
        # read_skill 全程可见（任务#12 渐进式披露：L2 正文经 read_skill 按需读取，
        # 选中 Skill 全文直注时也不关重读入口）
        # MCP 两段式注入：白名单（interaction.mcp_enabled）外
        # 的 MCP 工具 schema 不下发（deny-first 可见性面；目录块已告知存在）
        try:
            excluded |= set(mcp_catalog.inactive_tool_names())
        except Exception:
            pass  # 裁剪失败不阻断对话；未启用工具直调仍被 adapter 拒执行
        return frozenset(excluded)

    async def _launch_subagent(
        self, task: str, parent_ctx: "PlannerContext", kind: str = "",
        stage: str = "", on_event=None,
    ) -> str:
        """正宗子代理（one-shot）：模型经 FC `run_subagent` 发起 → 在隔离上下文里
        复用同一 `run_agent_loop`（经子 Planner）连续跑完 → 只回摘要。

        `kind` = 具名类型（qoder 花名册形态）：决定子级工具白名单与职责块。
        `stage` = 阶段执行器（2026-09-15 试点，对齐 Flova 章节隔离）：带 stage 时
        系统精准注入该阶段 Skill 章节全文 + 工具面去 read_skill（断跨阶段预读
        污染）；未知/缺省回落通用形态全现状。
        非机械执行器：发起方=模型、走同一 `guard_pipeline`、无 `exec_*`。子 Planner
        自带独立 FCToolRunner/TurnExecutor 实例（避免与父共享 runner 的轮内状态），
        仅共享 StateManager（父此刻挂起等待，无并发写冲突）。"""
        try:
            child_depth = subagent_mod.resolve_child_depth(
                getattr(parent_ctx, "subagent_depth", 0))
        except subagent_mod.SubagentDepthError:
            return "（已达子代理深度上限，无法再委派，请在当前层完成。）"
        resolved_stage = subagent_mod.resolve_stage(stage)
        # 子会话：独立隐藏线程（携血缘）；创建失败回落不落流（子级仍在内存跑完）。
        child_cid = ""
        resolved_kind = subagent_mod.resolve_subagent_kind(kind)
        # meta 记阶段（左栏子线程记录可辨）：带 stage 时 subagent_kind 位记 stage:名
        meta_kind = f"stage:{resolved_stage}" if resolved_stage else resolved_kind
        try:
            parent_cid = str(getattr(parent_ctx, "session_conversation_id", "") or "")
            conv = conversation_ops.create_scoped_conversation(
                self.state_manager,
                {"kind": "subagent", "parent_conversation": parent_cid,
                 "subagent_kind": meta_kind,
                 "label": (lambda t: t[:_SUBAGENT_LABEL_MAX - 1] + "\u2026" if len(t) > _SUBAGENT_LABEL_MAX else t)((task or ""))},
                title="子代理")
            child_cid = str((conv or {}).get("id") or "")
        except Exception as _e:  # 子会话创建失败不阻断委派（降级为不落流）
            logger.warning("[Subagent] 子会话创建失败，回落不落流: {}", _e)
        # 子级任务落为 user/message 事件（只读记录首行）：子级在 core 内联跑、
        # 不经 web/chat_service，默认无 SOURCE_USER 事件，此处补齐使隐藏线程事件流自描述。
        if child_cid:
            session_log.append_user_message(
                self.state_manager, child_cid, task, source=session_log.SOURCE_USER)
        # 子级模型档：缺省完全继承父级（跟随主模型）；仅当 model_policy 的
        # `subagent` 行显式配了 provider（且装配点注入了工厂）才接管；解析
        # 失败静默回落父档（子级仍跑完，功能不断）。思考档同理：仅显式配则覆盖。
        child_adapter = self.llm_adapter
        child_provider = self.chat_provider
        child_model = self.chat_model
        child_thinking = getattr(parent_ctx, "thinking_level", "") or ""
        try:
            role = model_policy.resolve_role("subagent")
            if role and role.get("provider") and self._chat_adapter_factory is not None:
                p = str(role["provider"])
                m = str(role.get("model") or self.chat_model)
                built = self._chat_adapter_factory(p, m)
                if built is not None:
                    child_adapter, child_provider, child_model = built, p, m
            sub_think = model_policy.thinking_for("subagent")
            if sub_think:
                child_thinking = sub_think
        except Exception as _e:  # noqa: BLE001
            logger.warning("[Subagent] 子代理模档解析失败，回落父档: {}", _e)
        child_ctx = PlannerContext(
            history=[],
            session_conversation_id=child_cid,
            use_studio_context=True,
            skill_name="",
            raw_user_text=task,
            user_id=getattr(parent_ctx, "user_id", "") or "",
            thinking_level=child_thinking,
            stop_scope=getattr(parent_ctx, "stop_scope", "chat") or "chat",
            # 8888 事故批：子代理独立停止清理作用域（父停杀子、子停不碍父，
            # 见 PlannerContext.stop_scope_own 注解）；绑定子会话 id 保唯一
            stop_scope_own=(
                f"{getattr(parent_ctx, 'stop_scope', 'chat') or 'chat'}"
                f"::sub::{child_cid}"),
            subagent_depth=child_depth,
            subagent_no_confirm=True,
            subagent_deny=subagent_mod.child_deny_set(resolved_stage),
            # K5 批（2026-09-16 对齐 flova）：子代理工作台状态通道——子级与父
            # 共享同一 StateManager 缓存（同键命中），状态尾每轮刷新；flova
            # 实证不裁剪，故不引入裁剪表（体量由既有预算压缩兜底）。
            state_builder=lambda: self.state_manager.build_agent_context(
                getattr(parent_ctx, "asset_mode", "bound") or "bound"),
        )
        child = Planner(
            state_manager=self.state_manager,
            tool_manager=self.tool_manager,
            llm_adapter=child_adapter,
            executor_factory=self.executor_factory,
            skill_docs=self._skill_docs,
            chat_provider=child_provider,
            chat_model=child_model,
            chat_adapter_factory=self._chat_adapter_factory,
        )
        # 构建子级任务文本（通用：固定范围声明 + 幂等锚 + 任务书；
        # 带 stage：另加一行阶段标注）
        base_task = subagent_mod.build_subagent_task(task, stage=resolved_stage)
        # K6 批（2026-09-16 对齐 dsh scoped prompt section）：打卡指令随委派
        # 任务下发（唯一源 = shared/structured_output.md::BRIEF；subagent.md
        # 逐字锁零触碰）——子代理收尾必须 structured_output 打卡一次。
        _brief = (load_prompt_section("shared/structured_output.md", "BRIEF")
                  or "").strip()
        if _brief:
            base_task += f"\n\n{_brief}"
        # 平台注入 Skill 章节内容到子代理（省 read_skill 往返）：
        # 带 stage → 精准注入该阶段章节全文（不截断；章节缺失回落全文截断）；
        # 不带 stage → 现状全文前 8000 字截断（通用委派零改动）。
        parent_skill = str(getattr(parent_ctx, "skill_name", "") or "").strip()
        if parent_skill and self._skill_docs is not None:
            injected = ""
            if resolved_stage:
                try:
                    injected = tool_sections(parent_skill, resolved_stage)
                except Exception as _e:
                    logger.warning("[Subagent] 阶段章节取读失败（回落全文截断）: {}", _e)
                    injected = ""
            if injected:
                base_task += (
                    f"\n\n===== 注入 Skill 章节（{parent_skill} · {resolved_stage}）=====\n"
                    f"{injected}")
            else:
                try:
                    getter = getattr(self._skill_docs, "get_skill_doc", None)
                    if getter:
                        doc = getter(parent_skill)
                        if doc and doc.get("content"):
                            sk = doc["content"]
                            if len(sk) > 8000:
                                sk = sk[:8000] + "\n...（章节内容截断，超预算，子代理可按需调 read_skill 读全文）"
                            base_task += f"\n\n===== 注入 Skill 章节（{parent_skill}）=====\n{sk}"
                except Exception as _e:
                    logger.warning("[Subagent] Skill 章节注入失败（跳过）: {}", _e)
        # 子在同一 asyncio task/同一 context 内联跑：包一层追踪隔离带（D1），
        # 防子崩溃在 finish 之前把本任务绑定留在子的已空态、导致父轮 trace 断链
        # （正常回退由子 finish_trace 沿父帧链完成，见 tracer D2）。
        with AgentTracer.get_instance().child_trace_scope():
            # 2026-09-15 1111 批（对齐 flova/dsh 子活动实时可见）：把父的 on_event
            # 透传给子循环，子级 state_refresh/timeline/tool 事件进入父 SSE，
            # 故事板增量亮卡（此前子级 emit 无出口，做完才一次性弹出）。
            resp = await child.handle_message(base_task, child_ctx, on_event=on_event)
        return str(getattr(resp, "text", "") or "").strip() or "（子代理未产出摘要）"

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

    def _apply_stage_gate(self, response: "PlannerResponse", context: "PlannerContext") -> None:
        """轮末阶段闸（2026-09-06 对齐批，宪法 §2.3 闸机）。

        执行模式 ∈ EXECUTION_MODE_GATE_MODES（key_steps_confirm/pause_all）
        且有活跃 Skill 时：本轮内有阶段节点翻转完成（轮始快照 vs 轮末
        sync_run 重算，客观探针口径）且新当前节点符合档位目标
        （key_steps_confirm=审批节点；pause_all=任意节点）→ 平台机械签发
        暂停卡：confirmation/options + workflow_run.pending_decision
        （token 前缀 review:，chat_consume.resolve_decision 消费落
        DecisionResolved，审批节点完成入账）。签发复用 _issue_pause 单一链。
        档位 > Skill 散文（2026-09-06 用户裁决）：确认档下 Skill 声明
        「直通」不影响本闸——停由平台保证，模型只在停点呈现成果。
        ai_decide（默认档）/auto_full 不启用机械闸：默认档行为与现状一致。
        同步说明：sync_run 轮末重算对所有档位执行（审计账本恢复推进），
        闸签发仅限确认档。"""
        if not (settings.pipeline_orchestrator_enabled and context.skill_name):
            return
        if context.adjust_scope:
            # 子对话不发确认卡（二期子对话批 3 同款纪律，与 FC 轨
            # scope_auto_pause 对齐）：微调真子对话内阶段翻转不签发闸卡
            return
        try:
            state = self.state_manager.state_dict or {}
            # 轮末账本同步（全档位）：completed_nodes 客观重算，账本恢复推进
            run_after = workflow_runtime.sync_run(state, context.skill_name)
        except Exception as _e:
            record_degradation("planner.stage_gate")
            logger.warning("[StageGate] 轮末 run 同步跳过: {}", _e)
            return
        mode = normalize_exec_mode(settings.execution_mode)
        if mode not in EXECUTION_MODE_GATE_MODES:
            return
        # 单一活跃暂停槽位：响应已带确认/暂停标识、槽位被占、有待决决议 → 不发行
        if response.confirmation or response.pause_id:
            return
        interaction = state.get("interaction") or {}
        if interaction.get("active_pause") or interaction.get("awaiting_confirmation"):
            return
        if run_after.get("pending_decision"):
            return
        node_before = str((getattr(context, "workflow_run0", None) or {}).get("current_node") or "")
        completed_after = set(run_after.get("completed_nodes") or [])
        if not node_before or node_before not in completed_after:
            return  # 本轮无阶段翻转（纯对话/同阶段中间步），不停
        node_id = str(run_after.get("current_node") or "")
        if not node_id:
            return
        if mode == "key_steps_confirm":
            if node_id not in workflow_contract.DEFAULT_V2_REVIEW_NODES:
                return
        title = workflow_contract.NODE_TITLES.get(node_id, node_id)
        response.confirmation = f"「{title}」已完成，请过目本阶段成果并选择下一步。"
        response.confirmation_options = [
            {"label": "确认，继续推进",
             "description": "当前阶段成果确认通过，进入下一阶段"},
            {"label": "提出调整",
             "description": "对当前阶段成果提出修改意见后再继续"},
        ]
        response.pause_kind = PAUSE_KIND_STAGE_DONE
        # 挂起决议（review: 前缀 = chat_consume 轮末解析约定）：用户批复经
        # resolve_decision 落 DecisionResolved，审批节点完成入账
        run_after["pending_decision"] = {
            "token": f"review:{run_after.get('run_id')}:{node_id}",
            "node_id": node_id,
            "schema": {"type": "approval"},
        }
        run_after["status"] = "waiting_user"

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
        self._scope_auto_pause = bool(
            context.adjust_scope or getattr(context, "subagent_no_confirm", False))
        # 正宗子代理：仅顶级轮（depth 0）且开关开时注入启动器（捕获本轮 context）；
        # 子级（depth≥1）置 None ⇒ 子级无法再委派（防递归）。随请求实例隔离，不跨请求泄漏。
        if settings.subagent_enabled and not getattr(context, "subagent_depth", 0):
            self._fc_runner.subagent_launcher = (
                lambda task, kind="", stage="", on_event=None:
                    self._launch_subagent(task, context, kind, stage, on_event=on_event))
        else:
            self._fc_runner.subagent_launcher = None

        # 按上下文裁剪本轮下发的工具集 + 装配 system 超预算降级器（token 治理）
        self._excluded_tools = self._compute_excluded_tools(context)
        # one visibility = one permission（dsh subagent.md L90-97）：轮内裁剪集
        # 同步下发执行器，被裁工具即便被模型误调也拒绝执行（不止从 schema 消失）。
        self._fc_runner.turn_excluded = self._excluded_tools
        # R11 裁剪可见性：同步写入 context，供 build_state_tail_message 渲染 UNAVAILABLE 段
        context.turn_excluded = self._excluded_tools
        self._system_degrader = self._make_system_degrader(context)
        # 批 10 · 执行偏好注入：轮始按档位签发（文案唯一源外置，见
        # prompts/planner/execution_preference.md；闸机兜底见批 9 同意账本）
        context.execution_pref_note = self._load_execution_pref_note()
        # 执行模式注入（2026-09-06）：轮始按档位签发（ai_decide 默认档 = 空串
        # 不注入；key_steps_confirm/pause_all 两档另有轮末阶段闸机械拦停兜底）
        context.execution_mode_note = self._load_execution_mode_note()
        # 状态注入事件化（二期 G3，dsh inject 同位）：轮首构建状态正文
        # （状态 JSON + 降级引导 + 偏好/模式 note + 进度 + 草稿指针）落
        # source=state 事件，轮内步间零注入（尾部消息每步重建退役）；
        # 需要全量时模型调 read_state_group 按需读（外部标杆转录同形态）
        context.state_event_content = self._build_and_log_state_event(context)
        # 三通道分离 C：轮始重置 FC runner 跨批跟踪（阶段边界只认本轮）
        self._fc_runner.reset_turn_tracking()
        # 会话级推理档位（""=原生；主模型调用透传，端点不认则静默忽略）
        self._chat_thinking_level = context.thinking_level or ""

        # 批 2 · 插播报：轮间隙发生媒体变更（用户手动改/删/绑定素材或生成回填，
        # 落库时经 media 指纹 diff 记 media_synced 流事件）→ 轮始一次性播报
        # 「素材变更已同步」（外部标杆 姿势：检测手动编辑后按最新状态重做）
        if on_event is not None:
            try:
                taken = self.state_manager.consume_flow_events("media_synced")
                if taken:
                    await emit_event_card(
                        "素材变更已同步",
                        "检测到项目素材被更新，将按最新状态继续",
                        emitter=on_event, pre_turn=True,
                    )
            except Exception as _e:
                logger.debug("[planner] 忽略异常: {}", _e)

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
            # 轮始轻量确保（批 3 · B3：run 已存在即直接返回，不空跑全量探针；
            # 重算唯一触发点 = 写动作落账）+ 输入类 decision 消费
            # （waiting_user→ready，DecisionResolved 入事件账本）。
            try:
                _rt = workflow_runtime.WorkflowRuntime(
                    self.state_manager, context.skill_name)
                _run0 = _rt.ensure_run()
                # 轮末阶段闸快照（2026-09-06）：供轮末对比本轮阶段翻转
                context.workflow_run0 = dict(_run0 or {})
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
            # 假停取证批：步事实日志用（仅观测，不参与行为）
            model=str(getattr(self.llm_adapter, "model", "") or ""),
            pending_injector=context.pending_injector,
            stop_scope=context.stop_scope,
            # 8888 事故批：循环自己的停止清理作用域（子代理独立；顶级为空
            # = 与 stop_scope 同，行为不变）
            stop_scope_own=str(getattr(context, "stop_scope_own", "") or ""),
            # 会话事件流归属（v4 批 E1）：agent_loop FC 镜像点落流用
            session_conversation_id=str(getattr(context, "session_conversation_id", "") or ""),
            # 轮首状态事件正文（二期 G3）：组装时追加在 user 消息后
            # （与日志 seq 同序，回放=请求逐字节）
            state_event_content=str(getattr(context, "state_event_content", "") or ""),
            # 子代理深度（R6 fakestop 豁免）：透传至 agent_loop 轮末策略
            subagent_depth=context.subagent_depth,
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
        # R9 analysis 对话可见：透传 fc_runner 本轮成功路径签发的分析摘要
        # （chat 持久化归 web 层，core 层不调 add_chat_message）
        response.analysis_digest = str(getattr(self._fc_runner, "analysis_digest", "") or "")
        # 问即停：发行点签发的 pause_id 透传，供 _issue_pause 幂等
        response.pause_id = str(getattr(loop_result, "pause_id", "") or "")

        # 轮末阶段闸（2026-09-06 对齐批）：确认档下里程碑完成机械签发
        # 暂停卡（档位 > Skill 散文），非确认档仅做账本轮末同步；
        # 暂停卡结构化签发（汇流点一）：FC workflow_pause / 轮末策略卡 /
        # 阶段闸卡在此汇流，经 _issue_pause 单一链登记
        self._apply_stage_gate(response, context)
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
                if step > 1:
                    sev = status_event(
                        "agent.roundStart",
                        f"第 {step} 轮推理中…（执行上轮操作后继续规划）",
                        {"step": step},
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

        _done_payload = {
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
            # 正文来源（批 C3）：web 层据此落 kind="mechanical"，
            # 线程装载历史时机械占位压成固定短句
            "text_source": result.text_source,
            # 协作式停止标记：web 透传层据此落停止痕迹、不再发 done
            "stopped": bool(result.stopped),
            "stop_phase": result.stop_phase,
            # R9 analysis 对话可见：本轮分析摘要（非空时 web 层追加对话消息）
            "analysis_digest": result.analysis_digest,
        }
        # 推理模型思考内容（五项修法批 4）：default-off——闸门开且非空才随
        # done payload 下发（web 层据此持久化，供下轮历史回传）
        if settings.llm_reasoning_passthrough and result.reasoning_content:
            _done_payload["reasoning_content"] = result.reasoning_content
        yield PlannerEvent(type="done", payload=_done_payload)

    # ---------- 内部方法 ----------

    def _build_system_prompt(self, context: PlannerContext) -> str:
        """构建 system prompt（委托 PromptBuilder；段落顺序为前缀缓存优化）。
        协议单轨：统一注入 protocol.md。
        工具集轮始冻结（指令收拢批 B1）：_excluded_tools 在轮始
        （handle_message 入口）一次性计算，轮内不变——tools schema 参与
        请求前缀，每步重算会在阶段翻转时击穿缓存（原「每步刷新」是 9999
        旧注释滞留的补丁；批 B 工具全量常驻后，正确性由闸机 + 工具自身
        校验兜底，可见性裁剪仅余 canvas/MCP 等轮界级变更）。
        """
        return self._prompt_builder.build_system_prompt(context)

    def tools_schema(self) -> Optional[list]:
        """请求工具清单唯一取件点（批 B4 组装单一化，dsh PromptAssembly 形态）：
        分节 system（context_builder）与 tools schema 同源于 planner 单一拦截点，
        turn_executor 只消费，不再各自访问 tool_manager/_excluded_tools 内部件。"""
        if self.llm_adapter is None or not self.llm_adapter.supports_function_calling:
            return None
        return self.tool_manager.get_all_tool_schemas(exclude=self._excluded_tools)

    def _load_execution_pref_note(self) -> str:
        """当前执行偏好 → 模型可见注入行（批 10）。

        文案唯一源 = prompts/planner/execution_preference.md（外置分节，
        与 gates/messages.md 同款加载机制）；档位枚举清洗归 config 单一
        事实源（normalize_exec_pref），脏值回落默认档对应分节。
        语义：偏好由模型行为执行（主动先审后生成），闸机兜底硬保证。"""
        key = normalize_exec_pref(settings.execution_preference).upper()
        return load_prompt_section(
            _EXEC_PREF_NOTE_FILE, f"PREF_{key}") or ""

    def _load_execution_mode_note(self) -> str:
        """当前执行模式 → 模型可见注入行（2026-09-06 对齐批）。

        文案唯一源 = prompts/planner/execution_mode.md（外置分节）；
        档位枚举清洗归 config 单一事实源（normalize_exec_mode），脏值回落
        默认档。ai_decide 默认档不注入任何内容：文件无对应分节属设计约定，
        直接跳过查找（避免把「故意不存在」当缺失打警告）；
        key_steps_confirm/pause_all 两档的平台机械拦停由轮末阶段闸承重，
        本注入只承担引导呈现语义。"""
        mode = normalize_exec_mode(settings.execution_mode)
        if mode == "ai_decide":
            return ""
        return load_prompt_section(
            _EXEC_MODE_NOTE_FILE, f"MODE_{mode.upper()}") or ""

    def _build_and_log_state_event(self, context: "PlannerContext") -> str:
        """轮首状态事件构建 + 落流（二期 G3 + B 方案增量对账）。

        B 方案（state_delta_enabled）：首轮全量基线，后续轮只推变化的组
        （digest 未变绝不重复注入）；全量回滚开关 = settings.state_delta_enabled。
        """
        if not context.use_studio_context:
            return ""
        pb = getattr(self, "_prompt_builder", None)
        if pb is None or context.state_builder is None:
            return ""

        if settings.state_delta_enabled:
            raw_state = self.state_manager.state_dict
            new_digests, new_hash, delta = state_delta_mod.compare_state(
                context._state_digest, context._state_hash, raw_state)

            if not state_delta_mod.has_any_change(delta):
                # 状态无变化，跳过本轮注入
                return ""

            if delta.get("_fresh"):
                # 首轮/恢复后首轮：全量基线
                try:
                    content = pb.build_state_tail_message(context)
                except Exception as _e:
                    logger.warning(f"[Planner] 状态基线构建失败（本轮零注入）: {_e}")
                    return ""
            else:
                # 增量消息：仅变化组
                content = state_delta_mod.build_delta_message(delta)

            if content:
                context._state_digest = new_digests
                context._state_hash = new_hash
                if context.session_conversation_id:
                    session_log.append_user_message(
                        self.state_manager, context.session_conversation_id,
                        content, source=session_log.SOURCE_STATE)
            return content

        # 旧行为（state_delta_enabled=False）：每轮全量
        try:
            content = pb.build_state_tail_message(context)
        except Exception as _e:
            logger.warning(f"[Planner] 状态事件构建失败（本轮零注入）: {_e}")
            return ""
        if not content:
            return ""
        if context.session_conversation_id:
            session_log.append_user_message(
                self.state_manager, context.session_conversation_id,
                content, source=session_log.SOURCE_STATE)
        return content

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


