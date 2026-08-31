"""
/api/agent — Agent 聊天端点（路由层，业务逻辑委托给 chat_service.py）

流程：服务端构建上下文 → 多步 LLM 循环（默认≤6 轮，全局设置页可实时热调，AGENT_MAX_STEPS 定初始值）→ 经 Function Calling 工具调用执行动作（动作通道唯一）→ 持久化 → 返回。

- 上下文注入在服务端完成（前端只发消息本体 + 选中态），服务端是唯一事实源；
- 未配置供应商时明确报错；真实供应商失败返回 502 + 真实错误。
"""
import asyncio
import json
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from loguru import logger

from src.video_agent.web.chat_service import non_stream_worker
from src.video_agent.core.stop_signal import request_stop
from src.video_agent.web.task_manager import snapshot_inflight_generations
from src.video_agent.exceptions import AdapterError, GenerationError, VideoAgentError
from src.video_agent.web.error_payload import (
    LEGACY_NOT_FOUND,
    LEGACY_VALIDATION_ERROR,
    classify_exception,
)
from src.video_agent.core.tracer import AgentTracer
from src.video_agent.core.live_metrics import (
    get_budget_breakdown,
    get_cache_stats,
    get_degradations,
    get_live_context,
    get_sections,
)
from src.video_agent.core.token_budget import context_window_for_model, estimate_tokens
from src.video_agent.state.manager import StateManager
from src.video_agent.state.models import CAT_KEY_ELEMENTS, CAT_SHOTS, CAT_AUDIO_ITEMS

router = APIRouter()

# 空项目状态骨架的基线 token：新建项目即使没有任何内容，状态 JSON 也有固定骨架
# （空列表/interaction 节），这部分不计入「已用」，避免新项目一创建就显示 0.3K
_EMPTY_STATE_BASELINE_TOKENS: Optional[int] = None


def _empty_state_baseline() -> int:
    global _EMPTY_STATE_BASELINE_TOKENS
    if _EMPTY_STATE_BASELINE_TOKENS is None:
        empty = {
            CAT_KEY_ELEMENTS: [], CAT_SHOTS: [], CAT_AUDIO_ITEMS: [],
            "assets": [], "documents": [], "uploadedDocs": [],
            "interaction": {"awaiting_confirmation": False, "confirmation_message": ""},
        }
        _EMPTY_STATE_BASELINE_TOKENS = estimate_tokens(
            json.dumps(empty, ensure_ascii=False, separators=(",", ":"))
        )
    return _EMPTY_STATE_BASELINE_TOKENS


class ChatRequest(BaseModel):
    message: str
    # 请求幂等键：前端每次发送生成唯一 id，同 id 处理中时拒绝重复提交
    request_id: str = ""
    provider: str = ""
    model: str = ""
    ms_model: str = ""
    messages: List[Dict[str, str]] = []
    images: List[str] = []
    videos: List[str] = []
    attachments: List[Dict[str, str]] = []
    # 有序富文本片段（文字/图片/视频/音频交错）：前端富文本输入框按用户排版顺序
    # 序列化而来，后端据此构建交错多模态内容，让 LLM 精确识别文字↔媒体对应关系。
    # 每项形如 {"type":"text","text":...} / {"type":"image|video|audio","url":...,"name":...}
    content_parts: List[Dict[str, str]] = []
    selected_draft_id: str = ""
    selected_type: str = ""
    context_mode: str = "studio"
    asset_mode: str = "bound"
    # 本次消息携带的 Skill slug（前端仅当消息中含 Skill 引用块时才传）：
    # 后端据此把该 Skill 记入当前项目的 usedSkills，文档面板只展示已发送过的 Skill 文档。
    skill_slug: str = ""
    # 前端当前选中的 Skill 名称（渐进式披露：system prompt 只注入 Skill 目录，
    # 选中项仅作相关性标注，不注入全文）
    skill_name: str = ""
    # 用户消息携带的引用块（展示用，随消息持久化，刷新后可重建）：
    # doc_blocks = 随消息发送的文档附件名称；skill_blocks = 随消息发送的 Skill 名称
    doc_blocks: List[str] = []
    skill_blocks: List[str] = []
    # 会话层一次性闸机豁免（§2.4）：前端拦截提示上的「本次放行」按钮
    # 携带 rule_id 列表（或 "all"）；后端写入 interaction.gate_overrides，
    # 由本次请求的 Planner 消费一次即清除（单次生效、留痕于用户消息）
    gate_overrides: List[str] = []
    # 多用户归属（基础）：可选用户标识，入 trace 审计；完整鉴权另行立项
    user_id: str = ""
    # 会话级推理档位（对话栏「推理等级」选择器）：low/medium/high；
    # ""=默认（模型原生能力，不下发 reasoning_effort）
    thinking_level: str = ""
    # 暂停回应结构化回携（对标 AskUserQuestion 范式）：用户点选暂停卡选项时
    # 携带 {"pause_id", "value", "label"}；后端校验与 interaction.active_pause
    # 匹配后随用户消息持久化 pauseAnsweredId/Value，前端对勾不再靠文本反推。
    # 自由打字回应不携带，LLM 语义不变（消息正文仍是唯一输入）
    pause_response: Dict[str, str] = {}
    # 系统动作标记（如 gate_override=「本次放行」）：携带时用户消息持久化带
    # kind 标记，前端渲染为系统动作行而非用户气泡（LLM 语义不变）
    system_action: str = ""
    # 重试续跑标记（任务#6）：错误/停止气泡「重试/继续」建议动作点击时前端携带；
    # 后端据此把上轮失败现场归档（trace/错误消息）渲染为前置块注入，
    # 带上下文续跑而非从零重来；取不到现场静默回落机械重发，重试本身不受影响。
    resume_failed: bool = False
    # 截断重答的「用户消息已落盘」标记由后端内部
    # contextvar（state.chat_tail_ops.user_message_persisted）传递


class ChatResponse(BaseModel):
    text: str
    applied_actions: int = 0
    steps: int = 1
    warnings: List[str] = []
    confirmation: str = ""
    pause_id: str = ""
    documents_written: List[str] = []
    # non_stream_worker 实际返回的字段（避免被 response_model 静默过滤）
    image_urls: List[str] = []
    chat_inserts: List[Dict[str, Any]] = []
    action_log: List[str] = []
    state: Optional[Dict[str, Any]] = None
    # 用户停止终态字段（避免被 response_model 静默过滤）
    stopped: bool = False
    stop_phase: str = ""


@router.post("/agent/chat", response_model=ChatResponse)
async def agent_chat(body: ChatRequest):
    """非流式聊天端点（业务逻辑委托给 chat_service.non_stream_worker）

    错误出口统一：全部走 ErrorPayload 契约（code/kind/message/raw），
    状态码语义维持原状（400 输入不合法 / 502 上游失败）"""
    if not body.message.strip() and not body.attachments:
        # 与 chat_service 非流式守卫同码（EMPTY_MESSAGE 已有，不新增）
        raise VideoAgentError("消息不能为空", status_code=400, error_code="EMPTY_MESSAGE")
    try:
        result = await non_stream_worker(body)
    except ValueError as e:
        raise VideoAgentError(
            str(e), status_code=400, error_code=LEGACY_VALIDATION_ERROR
        ) from e
    except (GenerationError, AdapterError) as e:
        logger.warning(f"[Agent] LLM 调用失败: {e}")
        # 沿用原 502 语义（不随异常自带 status_code 漂移），响应体走 ErrorPayload
        payload = classify_exception(e)
        return JSONResponse(status_code=502, content=payload.http_body(e.error_code))
    return ChatResponse(**result)


@router.get("/agent/traces")
async def get_agent_traces(limit: int = 50):
    """获取最近 N 条 Agent 执行链路追踪（调试用）"""
    tracer = AgentTracer.get_instance()
    return {"traces": tracer.get_recent_traces(min(limit, 50))}


@router.get("/agent/metrics")
async def get_agent_metrics():
    """成本看板聚合——轨迹数/平均耗时/轮次/操作数/闸机拦截率/降级频率。"""
    return AgentTracer.get_instance().metrics()


@router.get("/agent/gates")
async def get_agent_gates(limit: int = 50):
    """获取最近 N 条闸机判定（rule_id/层/结果/是否被申诉放行）+ 规则注册表概览。

    与 /agent/traces 并列的调试端点：闸机策略分层的审计入口，
    平台层规则（platform.*）不可被 Skill manifest 配置（地板模型强制不变量）。"""
    from src.video_agent.core import prompt_gates
    tracer = AgentTracer.get_instance()
    return {
        "recent": tracer.get_recent_gates(min(limit, 50)),
        "rules": [
            {"rule_id": meta.rule_id, "layer": meta.layer, "description": meta.description}
            for meta in prompt_gates.GATE_RULES.values()
        ],
    }


@router.get("/agent/degradations")
async def get_agent_degradations():
    """核心探测点意外降级计数（接线断裂可观测）。

    与 /agent/traces、/agent/gates 并列的调试端点：探测点（规格向导探测/
    闸机装配/流程检查点解析等）异常回落默认值时计数 +1，运行期健康信号。"""
    return {"degradations": get_degradations()}


@router.post("/agent/tasks")
async def create_agent_task(body: ChatRequest):
    """任务式传输：提交 Agent 聊天任务，立即返回 task_id（worker 后台运行）。"""
    from src.video_agent.web.chat_service import start_agent_task

    return start_agent_task(body)


@router.get("/agent/tasks")
async def list_agent_tasks(project_id: str = ""):
    """查询某项目仍在运行的后台 Agent 任务（刷新/切回后重连用）。"""
    from src.video_agent.web.agent_task_manager import get_agent_task_manager

    return {"tasks": get_agent_task_manager().list_running(project_id)}


@router.get("/agent/tasks/{task_id}/events")
async def agent_task_events(task_id: str, request: Request):
    """订阅后台任务事件流：先回放累计状态（replay），再增量推送；断线只断订阅。"""
    from src.video_agent.web.agent_task_manager import get_agent_task_manager

    tm = get_agent_task_manager()
    q = tm.subscribe(task_id)
    if q is None:
        raise VideoAgentError(
            f"任务 '{task_id}' 不存在", status_code=404, error_code=LEGACY_NOT_FOUND
        )

    async def gen():
        try:
            # 心跳保活（对齐 generate.py）：长静默轮（执行器数十秒）
            # 响应体无数据会被中间代理 idle 断开；SSE 注释帧前端 parseSSE
            # 天然跳过（非 data: 行），零前端变更
            idle_polls = 0
            # 订阅存活绝对上限：大于最长任务时长（30min）的保险丝，
            # 超过即 break 交 finally 清理，防僵尸订阅永驻
            deadline = time.monotonic() + 45 * 60
            while True:
                if time.monotonic() > deadline:
                    # 保险丝熔断前下发结构化终态帧：前端落错误气泡而非静默断流
                    yield (
                        "data: " + json.dumps({
                            "type": "error", "kind": "stream_timeout",
                            "message": "订阅超时，任务仍在后台运行，刷新可重连",
                        }, ensure_ascii=False) + "\n\n"
                    )
                    break
                if await request.is_disconnected():
                    break
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    idle_polls += 1
                    if idle_polls >= 15:  # 约 15s 静默发一次心跳
                        idle_polls = 0
                        yield ": heartbeat\n\n"
                    continue
                idle_polls = 0
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
                if ev.get("type") in ("done", "error", "task_status", "stopped"):
                    break
        finally:
            tm.unsubscribe(task_id, q)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


@router.post("/agent/tasks/{task_id}/stop")
async def stop_agent_task(task_id: str):
    """真正停止后台任务（停止按钮调用）；刷新/切项目不调用。

    端到端中断协议：先登记在途外部生成任务、
    置任务作用域停止标志（scope=task_id），再 cancel；响应携带在途项说明。
    """
    from src.video_agent.web.agent_task_manager import get_agent_task_manager

    inflight = snapshot_inflight_generations()
    request_stop(task_id)
    ok = get_agent_task_manager().stop(task_id)
    return {"ok": ok, "cancelled": 1 if ok else 0, "inflight": inflight}


class GuidanceItem(BaseModel):
    """排队消息登记体（id=前端排队条目 id，text=纯文本正文）。"""
    id: str
    text: str


@router.post("/agent/tasks/{task_id}/guidance")
async def register_task_guidance(task_id: str, item: GuidanceItem):
    """把用户推理中发送的排队消息登记到运行中任务，供轮间注入。

    任务不存在/已结束时返回 ok=False，前端回落「任务结束后自动出队重发」。"""
    from src.video_agent.web.agent_task_manager import get_agent_task_manager

    ok = get_agent_task_manager().add_pending_guidance(task_id, item.model_dump())
    return {"ok": ok}


@router.get("/agent/context-usage")
async def get_context_usage(model: str = ""):
    """估算当前会话将发送给 LLM 的上下文用量（Studio 状态上下文 + 聊天记录）。

    前端在发送按钮旁展示「已用多少K上下文」小圆圈：
    - chars: 上下文字符总数
    - est_tokens: 估算 token 数（与 token_budget 截断同口径：中文约1.5字/token）
    - window_tokens: 当前模型上下文窗口（供前端算圆环填充比）
    - cache_*: P2-1 KV-cache 遥测——供应商前缀缓存命中汇聚（滚动窗口口径）
    """
    svc = StateManager.get_instance()
    # 后台任务专属实例写盘后，全局单例内存可能陈旧（反馈：用量一直 0）；
    # 磁盘账本更新时先重载，保证静态估算不返回过期空值
    svc.reload_if_stale()
    try:
        state_json = svc.build_agent_context("bound")
    except Exception as e:  # 上下文构建失败不应阻断用量展示
        logger.warning(f"[Agent] 上下文用量统计失败: {e}")
        state_json = ""
    history_json = json.dumps(svc.get_chat_messages(), ensure_ascii=False)
    # 状态段扣除空项目基线：新项目（无分组/无历史）显示 0，
    # 用量只随真实内容（分组/草稿/文档/聊天记录）增长
    state_tokens = max(0, estimate_tokens(state_json) - _empty_state_baseline())
    history_tokens = estimate_tokens(history_json)
    chars = len(state_json) + len(history_json)
    # 推理中实时值优先（反馈）：主循环每次 LLM 调用前记录截断后的真实
    # 上下文规模，180s 有效期内直接采用，静态估算作兜底
    live = get_live_context(svc.active_project_id)
    est_tokens = int(live["est_tokens"]) if live else state_tokens + history_tokens
    # P2-1 KV-cache 遥测：最近 LLM 调用的前缀缓存命中汇聚（无样本时全 0）
    cache_stats = get_cache_stats(svc.active_project_id)
    # 第 5 批（Q6）：每轮 token 分配账（180s 有效期内取 live 值，否则 null）；
    # skill 份额按 system 段字符占比拆分（sections 遥测同批同源）
    breakdown = get_budget_breakdown(svc.active_project_id)
    if breakdown:
        sections = get_sections(svc.active_project_id)
        sec_total = int(sections.get("total") or 0)
        skill_chars = int(sections.get("skill") or 0)
        sys_t = int(breakdown.get("system") or 0)
        breakdown = {
            **breakdown,
            "skill": int(sys_t * skill_chars / sec_total) if sec_total else 0,
        }
    return {
        "chars": chars,
        "est_tokens": est_tokens,
        "state_chars": len(state_json),
        "history_chars": len(history_json),
        "window_tokens": context_window_for_model(model) if model else 0,
        "cache_hit_rate": cache_stats["hit_rate"],
        "cache_sample_count": cache_stats["samples"],
        "cache_prompt_tokens": cache_stats["prompt_tokens"],
        "cache_cached_tokens": cache_stats["cached_tokens"],
        "breakdown": breakdown,
    }
