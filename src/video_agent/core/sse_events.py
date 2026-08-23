"""SSE 事件名常量（后端唯一权威定义， 契约集中化）。

Agent 聊天流协议：POST /api/agent/chat/stream 的 SSE data 帧均为
{"type": <下列常量>, ...}。前端联合类型见 src/web/types/index.ts 的 SseEvent，
改动任一事件名/字段时两侧必须同步。

放在 core 层（而非 web 层）的原因：事件的生产者（planner/agent_loop/
fc_tool_runner）在 core 层，web 层（chat_service/mock_chat）可以引用 core，
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
# 停止终态（端到端中断协议，任务 #17）：用户主动停止的明确终态事件。
# 携带 phase=thinking/tool_executing/streaming（前端措辞区分）与
# inflight=在途外部生成任务登记（web 透传层富化）；任何中断都有痕迹、都有出口。
SSE_STOPPED = "stopped"
# 错误（携带 detail，可携带 error_code 供前端 i18n；
# 增 raw = 上游原始报文，前端「技术详情」折叠展示；
# 任务 #19：增结构化 code/kind/message（ErrorPayload 契约，见 web/error_payload.py））
SSE_ERROR = "error"
# 本轮操作已执行（agent_loop 内部事件，前端目前忽略）
SSE_ACTIONS_APPLIED = "actions_applied"
# 多步循环的轮次开始（agent_loop 内部事件，前端目前忽略）
SSE_STEP_STARTED = "step_started"
# executing_actions 已随文本块执行路径退役删除（ADR-0001）
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
]
