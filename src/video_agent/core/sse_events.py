"""SSE 事件名常量（后端唯一权威定义， 契约集中化）。

Agent 聊天流协议：任务式事件流（GET /api/agent/tasks/{id}/events）的 SSE data 帧均为
{"type": <下列常量>, ...}。前端联合类型已由本文件 Pydantic 模型经
scripts/gen_api_types.py 生成（api.generated.ts 的 SseEvent），
改动任一事件名/字段时重新运行生成器即双侧同步（--check 门禁钉死）。

放在 core 层（而非 web 层）的原因：事件的生产者（planner/agent_loop/
fc_tool_runner）在 core 层，web 层（chat_service 等）可以引用 core，
反过来则违反分层铁律。
"""

# 过程状态文案（如"正在调用模型…"）
SSE_STATUS = "status"
# 正文增量
SSE_DELTA = "delta"
# 深度思考增量（仅 UI 展示，不进下次上下文）
SSE_REASONING_DELTA = "reasoning_delta"
# 过程时间线：工具/操作开始（携带 id/name/summary/args；args = 输入参数
# 预览，必经 core/tool_args_preview 裁剪脱敏，前端按工具名分级展开）
SSE_TOOL_STARTED = "tool_started"
# 过程时间线：工具/操作完成（携带 id/ok/elapsed_ms/result_summary）
SSE_TOOL_FINISHED = "tool_finished"
# 文档写入即显（携带 name）：文档卡片不等整轮结束立即渲染（
# 规格卡被同轮的长耗时拆解压在轮末才出现）
SSE_DOC_WRITTEN = "doc_written"
# 模型降级即时联动（携带 provider/model）：切换时刻即下发，前端立即把
# 输入框选择器跳到实际生效的组合（轮被停止时 done 永不到达，
# 仅靠 done payload 的 fallback_model 会漏跳）
SSE_MODEL_FALLBACK = "model_fallback"
# 本轮结束（携带完整 payload，含状态快照）
SSE_DONE = "done"
# 停止终态（端到端中断协议）：用户主动停止的明确终态事件。
# 携带 phase=thinking/tool_executing/streaming（前端措辞区分）与
# inflight=在途外部生成任务登记（web 透传层富化）；任何中断都有痕迹、都有出口。
SSE_STOPPED = "stopped"
# 错误（携带 detail，可携带 error_code 供前端 i18n；
# 增 raw = 上游原始报文，前端「技术详情」折叠展示；
# 结构化 code/kind/message（ErrorPayload 契约，见 web/error_payload.py））
SSE_ERROR = "error"
# 本轮操作已执行（agent_loop 内部事件，前端目前忽略）
SSE_ACTIONS_APPLIED = "actions_applied"
# 多步循环的轮次开始（agent_loop 内部事件，前端目前忽略）
SSE_STEP_STARTED = "step_started"
# 引导消息轮间注入成功（携带 id/text）：前端据此渲染用户气泡
# 并从排队区移除对应条目（未被注入的条目由排队区兜底在任务结束后发出）
SSE_GUIDANCE_INJECTED = "guidance_injected"


def status_event(key: str, text: str, params: dict | None = None) -> dict:
    """状态事件统一构造（i18n 断裂缝。

    固定文案的状态事件必须经本函数发射：key+params 供前端按 locale 翻译
    （前端字典键与 key 一致），text 为中文兜底（过渡期保留，前端 key 优先、
    无 key 或字典缺失时回退 text）。动态内容（执行器进度等自由文本）
    不经本函数，直接发 {"type": SSE_STATUS, "text": ...}。
    """
    return {
        "type": SSE_STATUS,
        "key": key,
        "text": text,
        "params": params or {},
    }


# ============================================================
# SSE 载荷编译期契约：Pydantic 模型 = 前端 TS 类型的
# 单一事实源。发射侧仍为裸 dict（零运行时开销，不受影响）；本节模型
# 仅服务 scripts/gen_api_types.py 的 TS 导出与 --check 门禁——事件名或
# 字段变更时 TS 契约漂移即 CI 红。
# 深层结构（trace/state/workflow 快照）已有各自 dataclass 投影，此处以
# Dict[str, Any] 透传并注释来源。
# ============================================================
from typing import Any, Dict, List, Literal, Optional, Union  # noqa: E402

from pydantic import BaseModel, Field  # noqa: E402


class _SseFrame(BaseModel):
    """判别字段基座：type 为必填字面量（TS 侧生成 '字面量' 判别列）。"""
    type: str


class SseStatusEvent(_SseFrame):
    type: Literal["status"]
    text: str = ""
    key: str = ""
    # 插值参数仅标量（前端 i18n 字典插值契约；Dict[str, Any] 会使
    # 生成类型退化为 Record<string, unknown>，消费侧 parseRoundParams 无法收窄）
    params: Dict[str, Union[str, int, float]] = Field(default_factory=dict)


class SseDeltaEvent(_SseFrame):
    type: Literal["delta"]
    text: str = ""


class SseReasoningDeltaEvent(_SseFrame):
    type: Literal["reasoning_delta"]
    text: str = ""


class SseToolStartedEvent(_SseFrame):
    type: Literal["tool_started"]
    # id/name/summary 为发射侧必携字段（无默认 → 生成 TS 必填，
    # 对齐前端消费侧 toolStarted(id, name, summary) 签名）
    id: str
    name: str
    summary: str
    args: Optional[Dict[str, Any]] = None
    # 事件卡折叠区全文（对齐批：分析报告全文挂卡，仅 event_card 携带）
    detail_md: Optional[str] = None


class SseToolFinishedEvent(_SseFrame):
    type: Literal["tool_finished"]
    id: str
    ok: bool
    elapsed_ms: float
    result_summary: str = ""
    # 事件卡折叠区全文（仅 event_card 携带）
    detail_md: Optional[str] = None
    planning: Optional[bool] = None


class SseDocWrittenEvent(_SseFrame):
    type: Literal["doc_written"]
    name: str = ""
    turn_id: Optional[str] = None


class SseActionsAppliedEvent(_SseFrame):
    type: Literal["actions_applied"]
    count: Optional[int] = None
    step: Optional[int] = None
    # web 透传层快照形态：payload.count + payload.state（ServerStateSnapshot）
    payload: Optional[Dict[str, Any]] = None


class SseStoppedInflightItem(BaseModel):
    task_id: str = ""
    media_type: str = ""       # image | video
    model: str = ""
    draft_id: str = ""
    summary: str = ""          # 前 60 字


class SseStoppedEvent(_SseFrame):
    type: Literal["stopped"]
    phase: str = ""            # thinking | tool_executing | streaming
    step: Optional[int] = None
    inflight: Optional[List[SseStoppedInflightItem]] = None


class SseModelFallbackEvent(_SseFrame):
    """模型降级即时联动帧（发射端已退役，帧骨架仅兼容旧任务 replay，
    与 sse_protocol.py 登记口径一致；导出供前端 use-sse 既有 handler 类型化）。"""
    type: Literal["model_fallback"]
    provider: str = ""
    model: str = ""


class SseErrorEvent(_SseFrame):
    type: Literal["error"]
    detail: Optional[str] = None
    text: Optional[str] = None
    raw: Optional[str] = None
    error_code: Optional[str] = None
    code: str = ""
    kind: str = ""
    message: str = ""


class SseGuidanceInjectedEvent(_SseFrame):
    type: Literal["guidance_injected"]
    id: str = ""
    text: str = ""


class SseDoneChatInsert(BaseModel):
    kind: str = ""             # image | video | audio
    url: str = ""
    name: str = ""
    thumb: str = ""


class SseDoneConfirmationOption(BaseModel):
    label: str = ""
    description: str = ""
    group: str = ""
    value: str = ""


class SseDoneSuggestedAction(BaseModel):
    kind: str = ""             # retry | continue | next
    label: str = ""
    value: str = ""


class SseDonePayload(BaseModel):
    """done.payload 全家桶（core PlannerResponse 核心字段 + web 层富化；
    trace/state/workflow 为既有 dataclass 投影的 dict 透传）。"""
    text: str = ""
    applied_actions: int = 0
    steps: int = 1
    warnings: List[str] = Field(default_factory=list)
    confirmation: str = ""
    pause_id: str = ""
    documents_written: List[str] = Field(default_factory=list)
    image_urls: List[str] = Field(default_factory=list)
    chat_inserts: List[SseDoneChatInsert] = Field(default_factory=list)
    action_log: List[str] = Field(default_factory=list)
    confirmation_options: List[SseDoneConfirmationOption] = Field(default_factory=list)
    suggested_actions: List[SseDoneSuggestedAction] = Field(default_factory=list)
    pause_kind: str = ""
    # E1 消息级快照指针：轮末快照挂最后一条 agent 消息后同轮下发，
    # 前端 live 消息凭此挂「回到此刻/从此刻新开项目」（刷新前可见）
    snapshot_id: str = ""
    stopped: bool = False
    stop_phase: str = ""
    # 兼容字段：旧任务 replay 的 done_payload 可能携带；
    # 现行契约下降级走 model_fallback/replay.fallback 通道，发射端不再写入
    fallback_model: Optional[str] = None
    elapsed_ms: Optional[int] = None
    turn_id: Optional[str] = None
    state: Optional[Dict[str, Any]] = None      # ServerStateSnapshot 投影
    trace: Optional[Dict[str, Any]] = None      # AgentTrace（core/tracer.py）
    workflow: Optional[Dict[str, Any]] = None   # WorkflowProjection 投影


class SseDoneEvent(_SseFrame):
    type: Literal["done"]
    payload: SseDonePayload = Field(default_factory=SseDonePayload)


class AgentTaskToolEntry(BaseModel):
    """replay.tools[i]：任务累计工具条目（重连重建时间线）。"""
    id: str = ""
    name: str = ""
    summary: str = ""
    args: Optional[Dict[str, Any]] = None
    status: str = "running"    # running | done | failed
    elapsed_ms: Optional[float] = None
    result_summary: str = ""
    planning: Optional[bool] = None
    started_at_ms: Optional[int] = None


class AgentTaskReplayPayload(BaseModel):
    """任务流订阅首帧 replay.payload（web/agent_task_manager.subscribe）。"""
    task_id: str = ""
    project_id: str = ""
    model: str = ""
    status: str = ""           # running|done|error|cancelled|stopped|interrupted
    status_text: str = ""
    reasoning: str = ""
    text: str = ""
    tools: List[AgentTaskToolEntry] = Field(default_factory=list)
    snapshot: Optional[Dict[str, Any]] = None
    done_payload: Optional[Dict[str, Any]] = None   # SseDonePayload 原样 dict
    stopped_payload: Optional[Dict[str, Any]] = None
    docs: List[str] = Field(default_factory=list)
    wf_event_sequence: int = 0
    workflow: Optional[Dict[str, Any]] = None
    fallback: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    error_payload: Optional[Dict[str, Any]] = None  # {code,kind,raw}


class SseReplayEvent(_SseFrame):
    type: Literal["replay"]
    payload: AgentTaskReplayPayload = Field(default_factory=AgentTaskReplayPayload)


class SseTaskStatusEvent(_SseFrame):
    type: Literal["task_status"]
    status: str = ""


# 事件帧注册表（TS 导出顺序 = 本表顺序；payload-only 模型经 $ref 随帧导出）。
# 新增/改名事件必须同批维护：常量 + 本表 + web/sse_protocol.py 登记，
# 前端联合类型随生成器自动同步（test_sse_contract_parity 对拍生成物）。
TS_EVENT_FRAMES: List[tuple] = [
    ("SseStatusEvent", SseStatusEvent),
    ("SseDeltaEvent", SseDeltaEvent),
    ("SseReasoningDeltaEvent", SseReasoningDeltaEvent),
    ("SseToolStartedEvent", SseToolStartedEvent),
    ("SseToolFinishedEvent", SseToolFinishedEvent),
    ("SseDocWrittenEvent", SseDocWrittenEvent),
    ("SseActionsAppliedEvent", SseActionsAppliedEvent),
    ("SseStoppedInflightItem", SseStoppedInflightItem),
    ("SseStoppedEvent", SseStoppedEvent),
    ("SseModelFallbackEvent", SseModelFallbackEvent),
    ("SseErrorEvent", SseErrorEvent),
    ("SseGuidanceInjectedEvent", SseGuidanceInjectedEvent),
    ("SseDoneChatInsert", SseDoneChatInsert),
    ("SseDoneConfirmationOption", SseDoneConfirmationOption),
    ("SseDoneSuggestedAction", SseDoneSuggestedAction),
    ("SseDonePayload", SseDonePayload),
    ("SseDoneEvent", SseDoneEvent),
    ("AgentTaskToolEntry", AgentTaskToolEntry),
    ("AgentTaskReplayPayload", AgentTaskReplayPayload),
    ("SseReplayEvent", SseReplayEvent),
    ("SseTaskStatusEvent", SseTaskStatusEvent),
]

__all__ = [
    "SSE_STATUS",
    "SSE_DELTA",
    "SSE_REASONING_DELTA",
    "SSE_TOOL_STARTED",
    "SSE_TOOL_FINISHED",
    "SSE_DOC_WRITTEN",
    "SSE_MODEL_FALLBACK",
    "SSE_DONE",
    "SSE_STOPPED",
    "SSE_ERROR",
    "SSE_ACTIONS_APPLIED",
    "SSE_STEP_STARTED",
    "SSE_GUIDANCE_INJECTED",
    "status_event",
    "TS_EVENT_FRAMES",
]
