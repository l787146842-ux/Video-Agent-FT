"""SSE 事件名常量（后端唯一权威定义，批次6 契约集中化）。

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
# 过程时间线：工具/操作开始（携带 id/name/summary）
SSE_TOOL_STARTED = "tool_started"
# 过程时间线：工具/操作完成（携带 id/ok/elapsed_ms/result_summary）
SSE_TOOL_FINISHED = "tool_finished"
# 本轮结束（携带完整 payload，含状态快照）
SSE_DONE = "done"
# 错误（携带 detail，可携带 error_code 供前端 i18n）
SSE_ERROR = "error"
# 文本解析路径的操作已执行（agent_loop 内部事件，前端目前忽略）
SSE_ACTIONS_APPLIED = "actions_applied"
# 多步循环的轮次开始（agent_loop 内部事件，前端目前忽略）
SSE_STEP_STARTED = "step_started"
# 即将执行解析出的操作（agent_loop 内部事件，前端目前忽略）
SSE_EXECUTING_ACTIONS = "executing_actions"

__all__ = [
    "SSE_STATUS",
    "SSE_DELTA",
    "SSE_REASONING_DELTA",
    "SSE_TOOL_STARTED",
    "SSE_TOOL_FINISHED",
    "SSE_DONE",
    "SSE_ERROR",
    "SSE_ACTIONS_APPLIED",
    "SSE_STEP_STARTED",
    "SSE_EXECUTING_ACTIONS",
]
