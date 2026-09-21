"""
Agent Chat Service — 聊天业务编排。

职责：
- 流式处理公共实现（真实供应商）：任务式后台任务与非流式共用
- 非流式聊天编排
- 会话持久化（用户/agent 消息、文档卡片、生图卡片）

模块结构：
- 多模态内容构建 → multimodal_builder.py
routes/agent.py 仅保留路由定义和请求/响应模型。

错误翻译域位于 web/chat_errors.py；chat_service 仅内部调用 _emit_stream_error
（消费方直连实现体，原尾部 _friendly_stream_error re-export 壳已随批次 E 收敛；
错误语义零变更）。
"""
from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    # 类型收窄引用：运行期不做 isinstance/pydantic 校验，仅标注，防循环导入
    from src.video_agent.web.routes.agent import ChatRequest

from loguru import logger

from src.video_agent.core.action_executor import StateOperationExecutor
from src.video_agent.core.agent_loop import is_conversation_loop_active
from src.video_agent.config import settings
from src.video_agent.state import conversation_ops
from src.video_agent.core import prompt_gates
from src.video_agent.core import session_log
from src.video_agent.core import workflow_runtime
from src.video_agent.web.attachments import bind_attachments, attachment_context, store_uploaded_docs
from src.video_agent.web.adjust_scope import (
    _active_adjust_scope,
    _scope_history_from_thread,
    _scope_task_limit_exceeded,
)
from src.video_agent.web.chat_cards import _stamp_doc_written, _video_card_items
from src.video_agent.web.generation import resolve_openai_endpoint
from src.video_agent.web.multimodal_builder import build_multimodal_content
from src.video_agent.core.provider_config import (
    get_provider_config,
    load_merged_providers,
    load_merged_providers_async,
    resolve_selected_draft_media_config,
)
from src.video_agent.web.error_payload import classify_exception, classify_legacy_code
from src.video_agent.state.manager import StateManager
from src.video_agent.state import chat_tail_ops
from src.video_agent.core.planner import Planner, PlannerContext, PlannerResponse
from src.video_agent.core.sse_events import (
    SSE_ACTIONS_APPLIED,
    SSE_DELTA,
    SSE_DOC_WRITTEN,
    SSE_DONE,
    SSE_ERROR,
    SSE_GUIDANCE_INJECTED,
    SSE_STATUS,
    SSE_STOPPED,
    status_event,
)
from src.video_agent.utils.stop_signal import is_stop_requested
from src.video_agent.core.token_budget import window_recent_turns
from src.video_agent.utils.prompts import load_prompt_section
from src.video_agent.web.stop_manager import (
    persist_stop_trace,
    snapshot_inflight_generations,
    stopped_event,
)
from src.video_agent.exceptions import AdapterError, GenerationError, VideoAgentError
from src.video_agent.adapters.base_chat import BaseChatAdapter
from src.video_agent.utils.cancel_token import GenerationCancelled
from src.video_agent.adapters.factory import AdapterFactory
from src.video_agent.tools.manager import ToolManager
from src.video_agent.core.tracer import AgentTracer

__all__ = ["non_stream_worker", "build_multimodal_content"]

# 停止阶段措辞/痕迹文案/停止持久化见 web/stop_manager.py


def _require_chat_provider(body: ChatRequest) -> None:
    """空供应商明确报错（演示兜底已删除）：
    走既有 error_payload 分类机制（VideoAgentError → classify_exception）。"""
    if not (getattr(body, "provider", "") or "").strip():
        raise VideoAgentError(
            "尚未配置聊天供应商，请先到「设置」中配置聊天供应商",
            status_code=400, error_code="PROVIDER_NOT_CONFIGURED")


async def _stream_worker_impl(body: ChatRequest, svc: StateManager, emit, pending_injector=None, stop_scope: str = "chat") -> None:
    """流式处理公共实现（真实供应商）；任务式后台任务 worker 的核心主体。

    pending_injector：可选 callable → List[{id, text}]，轮间引导注入器，
    由后台任务路径装配（agent_task_manager.drain_pending_guidance）。
    stop_scope：协作式停止标志作用域——任务式传输=task_id
    （多任务并发互不串）。"""
    # 铁律文档每轮确保存在（宪法）：项目级生产契约唯一表述源，聊天路径生效
    from src.video_agent.core.spec_rules import ensure_iron_rules_doc
    try:
        ensure_iron_rules_doc(svc.state_dict)
    except Exception as _e:
        logger.debug("[chat_service] 忽略异常: {}", _e)

    t0 = time.monotonic()
    executor = StateOperationExecutor(
        svc,
        selected_draft_id=body.selected_draft_id,
        selected_type=body.selected_type,
    )

    user_text = body.message.strip()
    if not user_text and not body.attachments:
        _empty_msg = "消息不能为空"
        await emit({"type": SSE_ERROR, "detail": _empty_msg, "error_code": "EMPTY_MESSAGE",
                    **classify_legacy_code("EMPTY_MESSAGE", _empty_msg).sse_fields()})
        return
    if not user_text:
        user_text = "请查看我上传的素材"

    use_studio_context = body.context_mode != "none"
    # 开场公共编排：暂停闭环 + 附件降级注入
    # + 轮始客观推进信号（decision 消费/闸预检分诊用）
    # + 重试续跑前置块（任务#6，经 leading_note 传多模态构建层）
    llm_user_text, advance_signal, _resume_note = await _prepare_chat_opening(
        svc, body, user_text, use_studio_context)

    # 会话层一次性豁免：随消息登记，Planner 本次消费
    if getattr(body, "gate_overrides", None) and use_studio_context:
        async with svc.lock:
            _store_gate_overrides(svc, body.gate_overrides)

    # Skill 写入文档：本轮激活了 Skill 即记入当前项目 usedSkills
    #（不再依赖消息携带 chip/slug；文档面板只展示已发送过的 Skill 文档）
    async with svc.lock:
        _record_active_skill(svc, body)

    # 多模态内容构建（有 content_parts 时按排版顺序交错；
    # 传入选中草稿信息用于素材超限时的优先级注入；
    # 续跑前置块经 leading_note 传入，防 content_parts 分支静默丢弃）
    llm_user_content = await build_multimodal_content(
        llm_user_text, body.attachments, body.images or [], body.content_parts or None,
        selected_draft_id=body.selected_draft_id, selected_type=body.selected_type,
        videos=body.videos or [], leading_note=_resume_note,
    )

    # ---------- 空供应商：明确报错（不再有演示兜底） ----------
    _require_chat_provider(body)

    # ---------- 真实供应商 ----------
    await _real_stream(svc, executor, body, user_text, llm_user_text, llm_user_content, use_studio_context, emit, t0, pending_injector=pending_injector, advance_signal=advance_signal, stop_scope=stop_scope, adjust_scope=_active_adjust_scope(body))


def start_agent_task(body: ChatRequest) -> Dict[str, Any]:
    """任务式传输：提交即返回 task_id，worker 后台运行。

    刷新/切项目只断订阅不杀任务；worker 绑定提交时所属项目与对话（任务级
    StateManager），不会把旧项目状态写进新项目/别的对话（批 6-1：定向优先，
    空参回落全局活跃项目/活跃对话，修复跨窗口串线）。
    """
    from src.video_agent.utils import gen_id
    from src.video_agent.web.agent_task_manager import get_agent_task_manager

    submission_svc = StateManager.get_instance()
    project_id = (getattr(body, "project_id", "") or "").strip() \
        or submission_svc.active_project_id or ""
    # 微调真子对话（批 S2）：scope 请求走并发上限闸（结构化提示，非新闸机）；
    # 开关关闭/未携带时 scope=None 回落旧行为（旧前端零破坏）
    scope = _active_adjust_scope(body)
    if scope is not None and _scope_task_limit_exceeded(project_id):
        raise VideoAgentError(
            f"微调任务已达并发上限（{int(settings.adjust_task_concurrency)} 个），"
            "请等待已有微调完成后再提交",
            status_code=429, error_code="ADJUST_SCOPE_BUSY")
    conversation_id = (getattr(body, "conversation_id", "") or "").strip() \
        or str(submission_svc.conversations_meta_payload().get("active_conversation_id") or "")
    # 会话忙闲闸（8888 事故批，对齐 dsh 单驱动/收件箱语义）：同会话已有
    # 运行中任务或活跃 agent 循环（含孤儿循环）时拒收新任务——8888 实证
    # 续跑新循环与停止后孤儿循环并行 4 分钟，状态写入互斥丢弃、分镜组
    # 重复创建、缓存前缀互踩。前端「执行中发消息」既有 /guidance 轮间
    # 注入通道（= dsh steer）不受影响；循环层 acquire 为权威兜底。
    tm = get_agent_task_manager()
    if next((r for r in tm.list_running()
             if str(r.get("conversation_id") or "") == conversation_id), None) \
            or is_conversation_loop_active(conversation_id):
        raise VideoAgentError(
            "上一条指令仍在执行中：请等待其完成，或先停止该任务再发送；"
            "执行中的补充要求请用「插入消息」通道传达",
            status_code=429, error_code="CONVERSATION_BUSY")
    workspace_dir = str(submission_svc._workspace_dir)
    task_id = gen_id("agt")
    record = tm.create(
        project_id,
        lambda: _run_agent_task(body, project_id, task_id, workspace_dir, conversation_id),
        task_id=task_id,
        model=getattr(body, "model", "") or "",
        conversation_id=conversation_id,
    )
    # scope 标记随记录（并发统计/前端事件分流同口径；非 scope 任务不携）
    if scope is not None:
        record["adjust_scope"] = scope
    return {"task_id": record["task_id"], "project_id": project_id}


async def _run_agent_task(body: ChatRequest, project_id: str, task_id: str,
                          workspace_dir: str, conversation_id: str = "") -> None:
    """后台任务 worker：绑定任务专属 StateManager（+对话绑定，批 6-1），
    事件经 task_manager.emit 下发。"""
    from src.video_agent.web.agent_task_manager import get_agent_task_manager

    tm = get_agent_task_manager()
    # 可观测性：worker 生命周期三点日志（启动/被取消/退出），
    # 静默消失类问题的根因定位依赖此链路
    logger.info(f"[AgentTask] {task_id} worker 启动")
    try:
        svc, token = StateManager.create_task_bound(project_id, workspace_dir)
    except Exception as e:
        logger.exception(f"[AgentTask] {task_id} 状态绑定失败: {e}")
        _detail = f"服务端异常: {e}"
        tm.emit(task_id, {
            "type": SSE_ERROR, "detail": _detail,
            "error_code": getattr(e, "error_code", None) or "INTERNAL_ERROR",
            **classify_exception(e, message=_detail).sse_fields(),
        })
        return
    # 对话绑定：本任务全部聊天写入定向到提交时的对话（不落盘、不改活跃指针）；
    # 绑定会话不存在时写入单点静默回落活跃对话（不阻断任务）
    svc.bound_conversation_id = conversation_id
    try:
        async def emit(event: Dict[str, Any]) -> None:
            tm.emit(task_id, event)

        # 轮间引导注入器——注册到本任务的排队消息逐轮被消费
        # （agent_loop 第 2 轮起调用），注入成功即 guidance_injected 事件下发。
        def pending_injector() -> List[Dict[str, Any]]:
            return tm.drain_pending_guidance(task_id)

        await _stream_worker_impl(body, svc, emit, pending_injector=pending_injector, stop_scope=task_id)
    except asyncio.CancelledError:
        # 用户主动停止（停止标志在位）且检查点未来得及发 stopped
        # 终态事件时补发，保证任何中断都有痕迹；随后原样上抛（asyncio 任务以
        # cancelled 终结，_on_done 会保留 stopped 状态不覆盖）
        if is_stop_requested(task_id):
            _rec = tm.get(task_id) or {}
            if _rec.get("status") != "stopped":
                tm.emit(task_id, stopped_event())
        logger.warning(f"[AgentTask] {task_id} worker 被取消（非用户停止即异常信号）")
        raise
    except Exception as e:
        logger.exception(f"[AgentTask] {task_id} 处理异常: {e}")
        _detail = f"服务端异常: {e}"
        tm.emit(task_id, {
            "type": SSE_ERROR,
            "detail": _detail,
            "error_code": getattr(e, "error_code", None) or "INTERNAL_ERROR",
            **classify_exception(e, message=_detail).sse_fields(),
        })
    finally:
        logger.info(f"[AgentTask] {task_id} worker 退出")
        # 任务结束：清空未注入的排队项（前端 done 后会自动重发为普通请求，防双注入）
        tm.clear_pending_guidance(task_id)
        # 防抖落盘冲刷：线程/对话消息必须在任务终态前落盘（前端收到 done 后
        # 可能立即重开浮窗装历史，300ms 防抖窗口未刷会读到空历史，任务 #19）
        try:
            svc.flush_save()
        except Exception as _fe:
            logger.warning(f"[AgentTask] {task_id} 终态冲刷失败: {_fe}")
        StateManager.release_task_bound(token)


def _resolve_selected_draft_media_config(svc, selected_draft_id: str, selected_type: str) -> tuple:
    """从选中草稿解析生图配置 (providerId, aspectRatio)。

    中间预览面板选中的草稿决定了 agent 生图时用哪个供应商和画面比例。
    解析口径统一归 provider_config.resolve_selected_draft_media_config
    （出图/出视频/出音频三类同模式按卡解析，任务 #20）。
    """
    return resolve_selected_draft_media_config(
        svc.get_full_snapshot(), selected_draft_id, selected_type, kind="image")


@dataclass
class _StreamCtx:
    """_real_stream 三段拆分（P1-4）的参数收敛：全部入参与各阶段中间结果。

    仅文件内部使用，模块命名空间导出不变（尾部承重壳 re-export 保持）。
    """
    svc: Any
    executor: Any
    body: ChatRequest
    user_text: str
    llm_user_text: str
    llm_user_content: Any
    use_studio_context: bool
    emit: Any
    t0: float
    pending_injector: Any = None
    advance_signal: str = ""
    stop_scope: str = "chat"
    # 微调作用域（批 S2）：非空 ⇔ 本请求归属隐藏线程子对话（服务端装历史/
    # scope 状态构建器/不携 Skill）
    adjust_scope: Dict[str, Any] = field(default_factory=dict)
    # --- 准备段中间结果 ---
    history: List[Dict[str, Any]] = field(default_factory=list)
    turn_id: str = ""
    state_builder: Any = None
    image_provider: str = ""
    image_aspect_ratio: str = ""
    candidates: List[tuple] = field(default_factory=list)
    # 会话级 compaction 预热任务已随批 C1 退役（线程装载 + 确定性截断链取代）
    planner: Any = None
    cand_provider: str = ""
    cand_model: str = ""
    # --- 分发段结果 ---
    final_text: str = ""
    final_payload: Dict[str, Any] = field(default_factory=dict)
    stopped_seen: bool = False
    stop_phase_seen: str = ""


def _stage_aware_state_builder(
    svc: Any, asset_mode: str,
    scope: Optional[Dict[str, Any]] = None,
):
    """状态上下文构建器（阶段裁剪已退役，对齐 dsh 不裁剪）。"""

    def _builder() -> str:
        return svc.build_agent_context(asset_mode, scope=scope)

    return _builder


# 批 C3：mechanical 历史替换短句（文案唯一源 = prompts/planner/feedback.md，
# Rule 6 CJK 文案外置；分节缺失时 warning 且不压缩，口径同降级引导段）
_MECHANICAL_HISTORY_SECTION = ("planner/feedback.md", "MECHANICAL_HISTORY_PLACEHOLDER")


def _main_history_from_thread(svc, conversation_id: str) -> List[Dict[str, Any]]:
    """主对话 history 服务端装载（批 C1，消息单一事实源=线程 chatMessages）：
    与 scope 子对话同源机制（adjust_scope._scope_history_from_thread）。
    前端 body.messages 窗口退役为兼容字段不再消费——窗口每轮滑动会改写
    history 首条字节，是前缀缓存第一层击穿根因（缓存基线 20.9%）。
    - 指定 conversation_id 优先取该会话；取不到回落活跃会话（老数据兜底）；
    - 媒体卡/文档卡等无正文条目跳过（已由状态 JSON 与事件卡承载）；
    - mechanical 消息压成固定短句（批 C3：机械流水账不进模型上下文，
      防 few-shot 污染教坏正文范式；动作明细由状态 JSON/事件卡承载）。"""
    _mech_line = load_prompt_section(*_MECHANICAL_HISTORY_SECTION)
    msgs = None
    cid = str(conversation_id or "")
    if cid:
        msgs = svc.get_conversation_messages(cid)
    if msgs is None:
        msgs = svc.get_chat_messages() or []
    out: List[Dict[str, Any]] = []
    for m in msgs:
        text = str(m.get("text") or "").strip()
        if not text:
            continue
        if m.get("kind") == "mechanical" and _mech_line:
            text = _mech_line
        entry: Dict[str, Any] = {
            "role": "user" if m.get("sender") == "user" else "assistant",
            "content": text,
        }
        # 思考回传（五项修法批 4）：字段透传，闸门由 truncate_history 统一执行
        if str(m.get("reasoning_content") or "").strip():
            entry["reasoning_content"] = str(m["reasoning_content"])
        out.append(entry)
    if not _mech_line:
        logger.warning("[ChatService] prompts/planner/feedback.md::"
                       "MECHANICAL_HISTORY_PLACEHOLDER 分节缺失，mechanical 消息不压缩")
    return out


async def _stream_prepare(ctx: _StreamCtx) -> Optional[PlannerContext]:
    """三段之一（准备）：history/compaction 预热/PlannerContext 装配。

    adapter 创建失败经既有出口发错并返回 None（调用方终止流）。
    """
    # history 装载（批 C1：主路径与 scope 路径同源——服务端线程单一事实源；
    # body.messages 窗口退役为兼容字段，线程为空时回落旧窗口兜底。
    # v4 主刀批 E1：LLM 历史唯一事实源切换为会话事件流（全量回放推导），
    # 事件流缺失先做 chatMessages 名义消息迁移；日志通道异常回落本函数既有
    # 线程装载（细案 D4）；非 studio 上下文不落流也不切装载（行为与现状一致））
    _sess_cid = str(getattr(ctx.body, "conversation_id", "") or "")
    _log_hist = (
        session_log.load_history(ctx.svc, _sess_cid) if ctx.use_studio_context else None)
    if ctx.adjust_scope:
        ctx.history = truncate_history(
            _log_hist if _log_hist is not None
            else _scope_history_from_thread(ctx.svc, _sess_cid))
    else:
        if _log_hist is not None:
            _thread_hist = _log_hist or _main_history_from_thread(ctx.svc, _sess_cid)
        else:
            _thread_hist = _main_history_from_thread(ctx.svc, _sess_cid)
        if _thread_hist:
            ctx.history = truncate_history(_thread_hist)
        else:
            ctx.history = truncate_history([
                {"role": m.get("role", "user"), "content": m.get("content", "")}
                for m in window_recent_turns(ctx.body.messages)
            ])

    # 轮次唯一标识——本轮持久化的正文/文档卡/图片卡共用同一 turnId，
    # 前端据此把产出聚合进同次容器（消除消息流碎片化）；随 done payload
    # 下发，流式端与历史重载端同构
    ctx.turn_id = uuid.uuid4().hex[:12]

    # 短锁：绑定附件 + 附件文档存档 + 记录用户消息（仅一次）；
    # 状态 JSON 改为惰性构建器：多步循环每个轮次重新构建，模型每轮看到最新状态
    async with ctx.svc.lock:
        if ctx.use_studio_context:
            if ctx.adjust_scope:
                # 子对话素材绑线程（二期子对话批 3）：跳过全局登记，引用追加到
                # 线程对话的 scopeRefs（不进 assets/uploadedDocs，主对话零污染）
                conversation_ops.bind_thread_scope_refs(
                    ctx.svc, str(getattr(ctx.body, "conversation_id", "") or ""),
                    ctx.body.attachments or [])
            else:
                bind_attachments(ctx.svc, ctx.body.attachments)
                store_uploaded_docs(ctx.svc, ctx.body.attachments)
            # 暂停回应结构化消费：点选回应与 active_pause 匹配即落标记（展示层）
            pause_answered = consume_pause_response(
                ctx.svc, getattr(ctx.body, "pause_response", None) or None)
            # 截断重答：用户消息已在历史尾部落盘（含编辑后正文），
            # 不重复持久化，避免气泡翻倍（内部 contextvar 守卫，非请求字段）；
            # 其余路径照常落盘
            if not chat_tail_ops.user_message_persisted.get():
                ctx.svc.add_chat_message(
                    "user", ctx.user_text,
                    doc_blocks=getattr(ctx.body, "doc_blocks", None) or None,
                    skill_blocks=getattr(ctx.body, "skill_blocks", None) or None,
                    pause_answered=pause_answered,
                    kind=getattr(ctx.body, "system_action", "") or "",
                )
                # 会话事件流同点落流（v4 批 E1）：与 chatMessages 用户消息
                # 同文同会话归属；turn/start 开启新轮（v4 批 E3）；
                # 二期 G4：多模态轮落 content parts 原文（回放=请求逐字节）；
                # 截断重答（已落盘）不重复落流
                if ctx.use_studio_context:
                    session_log.append_turn_start(ctx.svc, _sess_cid)
                    _g4_content = (ctx.llm_user_content
                                   if isinstance(ctx.llm_user_content, list)
                                   else ctx.user_text)
                    session_log.append_user_message(ctx.svc, _sess_cid, _g4_content)
            # 规格向导机械落盘投影管线已随用户裁决 2026-08-31 退役（D-08 清偿）

    # --- 解析中间面板选中的生图 provider + 画面比例（注入 image_generate 工具用）---
    ctx.image_provider, ctx.image_aspect_ratio = _resolve_selected_draft_media_config(
        ctx.svc, ctx.body.selected_draft_id, ctx.body.selected_type
    )

    # 用户裁决：模型选择权归用户——
    # 选什么用什么，联不通直接报错，不自动换厂商 fallback
    ctx.candidates = [(ctx.body.provider, ctx.body.model)]
    # 会话级 LLM 摘要 compaction 已随批 C1 退役（指令收拢与缓存稳定批）：
    # history 改线程全量装载后阈值必然命中 → 每请求都做 LLM 摘要且摘要文本
    # 逐请求漂移，成为新的前缀击穿源；context rot 职责由确定性截断链
    # （truncate_history 位置无关截断 + 会话层阈值压缩/truncate_messages
    # 预算保险丝）承担。history_compact 模块保留（scope 域与函数级测试仍引用）。

    # 单一候选：首候选即终选（原循环所有路径均在首轮 return，行为等价）
    ctx.cand_provider, ctx.cand_model = ctx.candidates[0]
    try:
        llm_adapter = _create_chat_adapter(ctx.cand_provider, ctx.cand_model)
    except GenerationError as e:
        logger.warning(f"[ChatService] 所选供应商 {ctx.cand_provider}/{ctx.cand_model} 端点解析失败: {e}")
        await _emit_stream_error(ctx.svc, ctx.body, e, ctx.emit, ctx.use_studio_context)
        return None

    ctx.planner = Planner(
        state_manager=ctx.svc, llm_adapter=llm_adapter, tool_manager=ToolManager,
        executor_factory=StateOperationExecutor,
        chat_provider=ctx.cand_provider, chat_model=ctx.cand_model,
        chat_adapter_factory=_create_chat_adapter,
    )
    resolved_skill = (
        "" if ctx.adjust_scope else _resolve_skill_name_for_injection(
            ctx.body.skill_name or "", ctx.body.skill_slug or "", ctx.svc.state_dict, ctx.user_text,
        )
    )
    # 状态惰性构建器：多步循环每轮刷新
    # scope 请求换 scope 裁剪构建器，目标组全量/其余指针）
    ctx.state_builder = (
        _stage_aware_state_builder(
            ctx.svc, ctx.body.asset_mode, scope=ctx.adjust_scope or None)
        if ctx.use_studio_context else None
    )
    prelude_notes = _build_prelude_notes(resolved_skill)
    return PlannerContext(
        history=ctx.history,
        selected_draft_id=ctx.body.selected_draft_id,
        selected_type=ctx.body.selected_type,
        state_builder=ctx.state_builder,
        degraded_state_builder=(
            (lambda: ctx.svc.build_agent_context_degraded(ctx.body.asset_mode)) if ctx.use_studio_context else None
        ),
        skill_name=resolved_skill,
        # 分诊只认用户原话（附件预览问号不参与提问判定）
        raw_user_text=ctx.user_text,
        prelude_notes=prelude_notes,
        use_studio_context=ctx.use_studio_context,
        asset_mode=ctx.body.asset_mode,
        image_generation_provider=ctx.image_provider,
        image_generation_aspect_ratio=ctx.image_aspect_ratio,
        user_id=getattr(ctx.body, "user_id", "") or "",
        # 会话级推理档位（对话栏选择器下发；""=模型原生）
        thinking_level=getattr(ctx.body, "thinking_level", "") or "",
        # 轮间引导注入器（任务式传输路径；非任务路径为 None）
        pending_injector=ctx.pending_injector,
        # 轮始客观推进信号（decision 消费/闸预检分诊；runtime 不据此自主行动）
        advance_signal=ctx.advance_signal,
        # 协作式停止标志作用域：SSE 直连="chat"，任务式传输=task_id
        stop_scope=ctx.stop_scope,
        # 微调作用域透传（非空 ⇔ 纪律提示段注入；内容恒定保前缀缓存）
        adjust_scope=dict(ctx.adjust_scope or {}),
        # 会话事件流归属（v4 批 E1）：studio 上下文才落流（与 chatMessages
        # 写路径同守卫）；agent_loop/turn_executor 镜像点据此判定
        session_conversation_id=(_sess_cid if ctx.use_studio_context else ""),
    )


async def _stream_dispatch(ctx: _StreamCtx, planner_ctx: PlannerContext) -> bool:
    """三段之二（分发）：Planner 事件流逐类透传。

    LLM 流式调用失败经既有出口发错并返回 False（调用方终止流）。
    """
    # 局部别名：事件透传分支保持原字面形态（test_status_i18n_keys 源码扫描钉死）
    emit = ctx.emit
    svc = ctx.svc
    applied_seen = False
    ctx.final_text = ""
    ctx.final_payload = {}
    # 停止终态目击（stopped 事件已透传）：防防御路径无 done 时误发 done
    ctx.stopped_seen = False
    ctx.stop_phase_seen = ""
    try:
        async for event in ctx.planner.handle_message_stream(ctx.llm_user_content, planner_ctx):
            if event.type == "status":
                # payload 携带完整 status_event（key+params）时原样透传，
                # 前端按 locale 翻译；无 payload 回落纯 text（动态自由文本路径）
                await emit(event.payload or {"type": SSE_STATUS, "text": event.text})
            elif event.type == "delta":
                await emit({"type": SSE_DELTA, "text": event.text})
            elif event.type == "actions_applied":
                applied_seen = True
                _ap = event.payload or {}
                await emit(_ap.get("status_event") or {"type": SSE_STATUS, "text": event.text})
                # 逐步可见：每批操作落盘后立即下发最新状态快照，
                # 前端不必等全部完成，推理中就能看到新建的分组/提示词
                if ctx.use_studio_context:
                    # 流式二期：子代理的 state_refresh 同带 subagent 标记，重建帧时
                    # 保留该字段（前端 actor 卡据此计步；丢弃则子级进度不可见）
                    _sa = _ap.get("subagent")
                    await emit({
                        "type": SSE_ACTIONS_APPLIED,
                        **({"subagent": _sa} if _sa else {}),
                        "payload": {
                            "count": (event.payload or {}).get("count", 0),
                            # 逐步可见：精简投影（9 板键 + chatMessages + board_version）
                            # 替代全量快照，前端 syncFromServer 免刷新应用本批操作
                            "state": svc.get_board_projection(),
                        },
                    })
            elif event.type == SSE_DOC_WRITTEN:
                # 即显事件透传时打戳本轮 turn_id（打戳逻辑
                # 抽 _stamp_doc_written 便于单测钉死）
                await emit(_stamp_doc_written(event.payload, ctx.turn_id))
            elif event.type in (
                "reasoning_delta", "tool_started", "tool_finished", SSE_GUIDANCE_INJECTED,
            ):
                # 过程时间线事件透传（深度思考增量 / 工具开始与完成 / 引导注入），
                # 仅 UI 展示用，不进下次 LLM 上下文
                await emit(event.payload or {"type": event.type, "text": event.text})
            elif event.type == SSE_STOPPED:
                # 停止终态事件透传：agent_loop 检查点已发 phase/step，
                # web 透传层负责富化在途外部生成任务登记（core 层不感知 web 注册表）。
                # 第一版不做真实撤销/补偿，仅登记 + 文案告知供应商侧仍在进行
                _sp = dict(event.payload or {"type": SSE_STOPPED})
                _sp.setdefault("inflight", snapshot_inflight_generations())
                ctx.stopped_seen = True
                ctx.stop_phase_seen = str(_sp.get("phase") or "")
                await emit(_sp)
            elif event.type == "done":
                ctx.final_payload = event.payload or {}
                ctx.final_text = ctx.final_payload.get("text", "")
            elif event.type == "error":
                # 透传上游结构化故障标记（-2）：保证故障判定不依赖文案
                p = event.payload or {}
                raise AdapterError(
                    event.text,
                    retryable=p.get("retryable"),
                    http_status=p.get("http_status"),
                )
    except (GenerationError, AdapterError) as e:
        # 单一候选、不自动换模型——失败直接报错；
        # 已执行过操作同样直接报错（避免重复落盘）
        logger.warning(f"[ChatService] LLM 流式调用失败 ({ctx.cand_provider}/{ctx.cand_model}): {e}")
        await _emit_stream_error(ctx.svc, ctx.body, e, ctx.emit, ctx.use_studio_context)
        return False
    return True


async def _stream_finalize(ctx: _StreamCtx) -> None:
    """三段之三（收尾）：停止痕迹或成功持久化 + done（终态事件出口不变）。"""
    # --- 停止路径：stopped 终态事件已由检查点先行下发，
    # 此处只落停止痕迹消息供刷新后恢复，不再发 done（stopped 即终态）；
    # 取消穿透防御路径（仅 stopped 事件无 done）同归此分支。
    # pause 相位豁免（问即停，决策史见 git tag adr-archive-20260901）：暂停发行复用 stopped 标记结束本轮，
    # 但非用户停止——照常走成功路径发 done（暂停卡随 done payload 下发）
    _finalize_stop_phase = str(
        ctx.final_payload.get("stop_phase") or ctx.stop_phase_seen or "")
    if (ctx.stopped_seen or ctx.final_payload.get("stopped")) and _finalize_stop_phase != "pause":
        # 停止痕迹持久化（stop_manager）；stopped 即终态，不再发 done
        await persist_stop_trace(
            ctx.svc, ctx.final_text,
            str(ctx.final_payload.get("stop_phase") or ctx.stop_phase_seen or "thinking"),
            ctx.cand_model or "", ctx.turn_id, ctx.use_studio_context,
        )
        return

    # --- 成功路径：持久化 + done ---
    # 局部别名：显式 kwarg 形态钉死同轮 turn_id 契约（指纹测试）
    turn_id = ctx.turn_id
    video_items = _video_card_items(ctx.final_payload)
    snap_id = ""
    if ctx.use_studio_context and (
        ctx.final_text or ctx.final_payload.get("image_urls")
        or ctx.final_payload.get("confirmation") or video_items
    ):
        applied = ctx.final_payload.get("applied_actions") or 0
        async with ctx.svc.lock:
            if ctx.final_text or ctx.final_payload.get("confirmation"):
                ctx.svc.add_chat_message(
                    "agent", ctx.final_text, model_name=ctx.cand_model or "",
                    meta=_build_meta_note(
                        time.monotonic() - ctx.t0,
                        ctx.final_payload.get("steps") or 1,
                        applied,
                    ),
                    confirm=ctx.final_payload.get("confirmation") or "",
                    applied_actions=applied,
                    action_log=ctx.final_payload.get("action_log") or [],
                    trace=ctx.final_payload.get("trace") or {},
                    confirm_options=ctx.final_payload.get("confirmation_options") or None,
                    turn_id=turn_id,
                    pause_id=str(ctx.final_payload.get("pause_id") or ""),
                    # 暂停卡语义种类持久化（前端历史重载按 kind 渲染标题）；
                    # 批 C3：机械占位正文落 kind="mechanical"（线程装载历史时
                    # 压成固定短句，机械流水账不进模型上下文防 few-shot 污染）
                    kind=str(ctx.final_payload.get("pause_kind") or (
                        "mechanical"
                        if ctx.final_payload.get("text_source") == "mechanical" else "")),
                    # quick-actions 芯片持久化（提醒类兜底卡出槽后不丢，刷新可重建）
                    suggested_actions=ctx.final_payload.get("suggested_actions") or None,
                    # 推理模型思考内容（五项修法批 4）：payload 仅在回传闸门开时携带
                    reasoning_content=str(ctx.final_payload.get("reasoning_content") or ""),
                    # 2026-09-21 批B（事故 5555/Q4）：问题级字段随历史持久化
                    # （刷新后暂停卡标题/说明/多选不丢）
                    pause_header=str(ctx.final_payload.get("pause_header") or ""),
                    pause_detail=str(ctx.final_payload.get("pause_detail") or ""),
                    pause_multi_select=bool(ctx.final_payload.get("pause_multi_select")),
                    # 2026-09-21 批F（事故 4444/Q2③+Q3）：问题级列表持久化
                    # （刷新后多问题卡不丢；空列表 = 旧形态，前端回落扁平面）
                    pause_questions=list(ctx.final_payload.get("pause_questions") or []),
                )
            # 文档完成卡片：独立条目持久化，刷新后可重建（同轮 turnId 聚合）
            for doc_name in (ctx.final_payload.get("documents_written") or []):
                ctx.svc.add_chat_message("agent", "", doc_card=doc_name, turn_id=turn_id)
            # 生图卡片随历史持久化（独立消息条目，与前端 finishStream 的两条消息结构一致，
            # 否则刷新页面后聊天记录里的图片卡片会丢失）
            image_urls = ctx.final_payload.get("image_urls") or []
            if image_urls:
                ctx.svc.add_chat_message("agent", "", image_urls=image_urls, turn_id=turn_id)
            # 视频卡同构持久化（独立消息条目，同轮 turnId 聚合）
            if video_items:
                ctx.svc.add_chat_message("agent", "", video_items=video_items, turn_id=turn_id)
            # R9 analysis 对话可见：本轮成功产出剧本分析（done payload 携非空
            # analysis_digest）时追加一条对话摘要，使用户在对话框直接看到分析结论
            # （不再仅右侧时间线事件卡）；无 digest 不追加。正文≤ 3 行，同轮 turnId 聚合。
            _analysis_digest = str(ctx.final_payload.get("analysis_digest") or "").strip()
            if _analysis_digest:
                ctx.svc.add_chat_message(
                    "agent", f"剧本分析已完成，摘要：{_analysis_digest}",
                    meta="剧本分析", turn_id=turn_id)
            # E1 消息级快照：轮末打快照挂最后一条 agent 消息（指针化：
            # 消息存 snapshotId，本体存 stateSnapshots；媒体只有 URL 指针）
            snap_id = ctx.svc.attach_snapshot_to_last_agent_message(label=f"轮次完成 {turn_id}")

    # 产物账本同轮下发（向导机械落盘投影已随裁决退役，不再并入 documents_written）
    done_payload: Dict[str, Any] = {
        **ctx.final_payload,
        # 精简投影（9 板键 + chatMessages + board_version）替代全量快照：
        # 前端 syncFromServer/replay 恢复免刷新消费；elapsed_ms/trace 等仍在载荷根
        "state": ctx.svc.get_board_projection() if ctx.use_studio_context else None,
        "elapsed_ms": int((time.monotonic() - ctx.t0) * 1000),
        "turn_id": turn_id,
        # E1：轮末快照指针同轮下发（live 消息挂回档动作，无需刷新）
        "snapshot_id": snap_id,
        # workflow 投影（run 快照 + 本轮事件，重连 replay 同源）
        "workflow": workflow_runtime.project(ctx.svc.state_dict, ctx.turn_id),
    }
    await ctx.emit({"type": SSE_DONE, "payload": done_payload})


async def _real_stream(svc, executor, body, user_text, llm_user_text, llm_user_content, use_studio_context, emit, t0, pending_injector=None, advance_signal: str = "", stop_scope: str = "chat", adjust_scope: Optional[Dict[str, Any]] = None) -> None:
    """真实供应商的流式处理（单一候选：选什么用什么，联不通直接报错）。

    生图/生视频 fallback 属独立机制（generation.py）。
    pending_injector：轮间引导注入器，经 PlannerContext 传入循环。
    stop_scope：协作式停止标志作用域，透传 PlannerContext → agent_loop 检查点。
    adjust_scope：微调作用域（批 S2），非空时服务端装历史 + scope 状态构建器。

    P1-4：函数体拆为 _stream_prepare/_stream_dispatch/_stream_finalize 三段，
    参数经 _StreamCtx 收敛；签名、事件语义与错误出口零变更。
    """
    ctx = _StreamCtx(
        svc=svc, executor=executor, body=body, user_text=user_text,
        llm_user_text=llm_user_text, llm_user_content=llm_user_content,
        use_studio_context=use_studio_context, emit=emit, t0=t0,
        pending_injector=pending_injector, advance_signal=advance_signal,
        stop_scope=stop_scope, adjust_scope=dict(adjust_scope or {}),
    )
    planner_ctx = await _stream_prepare(ctx)
    if planner_ctx is None:
        return
    if not await _stream_dispatch(ctx, planner_ctx):
        return
    await _stream_finalize(ctx)


# 错误翻译域实现体在 chat_errors.py：chat_service 仅内部调用 _emit_stream_error
#（_stream_prepare/_stream_dispatch 失败出口）；_friendly_stream_error 纯 re-export
# 壳已随批次E收敛删除，消费方直连 chat_errors.py


async def non_stream_worker(body: ChatRequest) -> Dict[str, Any]:
    """非流式聊天的业务逻辑（从 routes/agent.py 抽离）。

    路由层仅做参数校验 + 调用本函数 + 响应包装。
    返回 dict：{text, applied_actions, steps, warnings, confirmation, documents_written, state}
    """
    user_text = body.message.strip()
    if not user_text and not body.attachments:
        raise VideoAgentError("消息不能为空", status_code=400, error_code="EMPTY_MESSAGE")
    if not user_text:
        user_text = "请查看我上传的素材"

    # 请求幂等防护：同一 request_id 处理中时拒绝重复提交
    request_id = body.request_id or ""
    if not _acquire_request_slot(request_id):
        raise VideoAgentError("相同请求正在处理中，请勿重复发送", status_code=409,
                              error_code="DUPLICATE_REQUEST")
    try:
        return await _non_stream_inner(body, user_text)
    finally:
        _release_request_slot(request_id)


async def _non_stream_inner(body: ChatRequest, user_text: str) -> Dict[str, Any]:
    """非流式聊天主体（幂等槽位由 non_stream_worker 管理）"""
    svc = StateManager.get_instance()
    # 铁律文档每轮确保存在（宪法），非流式路径同样生效
    from src.video_agent.core.spec_rules import ensure_iron_rules_doc
    try:
        ensure_iron_rules_doc(svc.state_dict)
    except Exception as _e:
        logger.debug("[chat_service] 忽略异常: {}", _e)
    executor = StateOperationExecutor(
        svc,
        selected_draft_id=body.selected_draft_id,
        selected_type=body.selected_type,
    )

    use_studio_context = body.context_mode != "none"
    # 开场公共编排：同流式路径（暂停闭环 + 附件降级 + 推进信号 + 续跑块）
    llm_user_text, advance_signal, _resume_note_ns = await _prepare_chat_opening(
        svc, body, user_text, use_studio_context)

    # 会话层一次性豁免：同流式路径
    if getattr(body, "gate_overrides", None) and use_studio_context:
        async with svc.lock:
            _store_gate_overrides(svc, body.gate_overrides)

    # Skill 写入文档：同流式路径——本轮激活了 Skill 即记入 usedSkills
    async with svc.lock:
        _record_active_skill(svc, body)

    # 空供应商：明确报错（不再有演示兜底）
    _require_chat_provider(body)

    # 真实供应商
    # 批 C1：非流式路径同流式轨——history 服务端线程装载（单一事实源），
    # body.messages 窗口退役为兼容字段，线程为空回落旧窗口兜底。
    # v4 批 E1：studio 上下文优先事件流装载（同流式轨，细案 D4 回落同口径）
    _ns_cid = str(getattr(body, "conversation_id", "") or "")
    _ns_log_hist = (
        session_log.load_history(svc, _ns_cid) if use_studio_context else None)
    if _ns_log_hist is not None:
        _ns_thread_hist = _ns_log_hist or _main_history_from_thread(svc, _ns_cid)
    else:
        _ns_thread_hist = _main_history_from_thread(svc, _ns_cid)
    if _ns_thread_hist:
        history = truncate_history(_ns_thread_hist)
    else:
        history = truncate_history([
            {"role": m.get("role", "user"), "content": m.get("content", "")} for m in window_recent_turns(body.messages)
        ])

    # 多模态内容构建（有 content_parts 时按排版顺序交错；
    # 传入选中草稿信息用于素材超限时的优先级注入；
    # 续跑前置块经 leading_note 传入，防 content_parts 分支静默丢弃）
    llm_user_content = await build_multimodal_content(
        llm_user_text, body.attachments, body.images or [], body.content_parts or None,
        selected_draft_id=body.selected_draft_id, selected_type=body.selected_type,
        videos=body.videos or [], leading_note=_resume_note_ns,
    )

    async with svc.lock:
        if use_studio_context:
            bind_attachments(svc, body.attachments)
            store_uploaded_docs(svc, body.attachments)
            # 暂停回应结构化消费（非流式路径同构）
            ns_pause_answered = consume_pause_response(
                svc, getattr(body, "pause_response", None) or None)
            # 截断重答内部守卫（同流式轨）：用户消息已落盘时不重复持久化
            if not chat_tail_ops.user_message_persisted.get():
                svc.add_chat_message(
                    "user", user_text,
                    doc_blocks=getattr(body, "doc_blocks", None) or None,
                    skill_blocks=getattr(body, "skill_blocks", None) or None,
                    pause_answered=ns_pause_answered,
                    kind=getattr(body, "system_action", "") or "",
                )
                # 会话事件流同点落流（v4 批 E1，同流式轨口径；turn/start E3；
                # 二期 G4 多模态轮落 parts 原文）
                session_log.append_turn_start(svc, _ns_cid)
                _ns_g4_content = (llm_user_content
                                  if isinstance(llm_user_content, list)
                                  else user_text)
                session_log.append_user_message(svc, _ns_cid, _ns_g4_content)
            # （规格卡投影已随用户裁决 2026-08-31 退役，D-08 清偿）

    # --- 解析中间面板选中的生图 provider + 画面比例 ---
    image_provider2, image_aspect_ratio2 = _resolve_selected_draft_media_config(
        svc, body.selected_draft_id, body.selected_type
    )

    resolved_skill = _resolve_skill_name_for_injection(
        body.skill_name or "", body.skill_slug or "", svc.state_dict, user_text,
    )
    # 状态惰性构建器：多步循环每轮刷新
    state_builder = (
        _stage_aware_state_builder(svc, body.asset_mode)
        if use_studio_context else None
    )

    prelude_notes = _build_prelude_notes(resolved_skill)

    # 用户裁决：单一候选 = 用户所选，联不通直接报错
    candidates = [(body.provider, body.model)]
    # 会话级 LLM 摘要 compaction 已随批 C1 退役（同流式路径口径：
    # 线程装载 + 确定性截断链取代，LLM 摘要逐请求漂移会击穿前缀缓存）
    result = None
    used_model = body.model
    last_err: Optional[Exception] = None
    for idx, (cand_provider, cand_model) in enumerate(candidates):
        try:
            llm_adapter = _create_chat_adapter(cand_provider, cand_model)
        except GenerationError as e:
            logger.warning(f"[ChatService] 所选供应商 {cand_provider}/{cand_model} 端点解析失败: {e}")
            raise
        planner_ctx = PlannerContext(
            history=history, selected_draft_id=body.selected_draft_id, selected_type=body.selected_type,
            state_builder=state_builder,
            degraded_state_builder=(
                (lambda: svc.build_agent_context_degraded(body.asset_mode)) if use_studio_context else None
            ),
            skill_name=resolved_skill,
            # 分诊只认用户原话（附件预览问号不参与提问判定）
            raw_user_text=user_text,
            prelude_notes=prelude_notes,
            use_studio_context=use_studio_context, asset_mode=body.asset_mode,
            image_generation_provider=image_provider2,
            image_generation_aspect_ratio=image_aspect_ratio2,
            user_id=getattr(body, "user_id", "") or "",
            thinking_level=getattr(body, "thinking_level", "") or "",
            advance_signal=advance_signal,
            # 非流式无停止端点，独立 scope 防被 SSE 路径停止标志误杀
            stop_scope="nonstream",
            # 会话事件流归属（v4 批 E1，同流式轨口径）
            session_conversation_id=(_ns_cid if use_studio_context else ""),
        )
        planner = Planner(
            state_manager=svc, llm_adapter=llm_adapter, tool_manager=ToolManager,
            executor_factory=StateOperationExecutor,
            chat_provider=cand_provider, chat_model=cand_model,
            chat_adapter_factory=_create_chat_adapter,
        )
        applied_seen = False

        async def _on_event(ev: Dict[str, Any]) -> None:
            nonlocal applied_seen
            if ev.get("type") == SSE_ACTIONS_APPLIED:
                applied_seen = True

        try:
            result = await planner.handle_message(llm_user_content, planner_ctx, on_event=_on_event)
            used_model = cand_model
            break
        except GenerationCancelled as _cancel_exc:
            # 取消穿透闭环：分流为 stopped 终态，不进下方 error 分支
            logger.info(f"[ChatService] 生成任务已被取消（非流式）: {_cancel_exc}")
            result = PlannerResponse(
                stopped=True, stop_phase="tool_executing", text=str(_cancel_exc))
            used_model = cand_model
            break
        except (GenerationError, AdapterError) as e:
            # 单一候选、不自动换模型——失败直接报错
            logger.warning(f"[ChatService] LLM 非流式调用失败 ({cand_provider}/{cand_model}): {e}")
            raise
    if result is None:  # 理论不可达（最后候选失败已 raise），防御兜底
        raise last_err or GenerationError("无可用聊天模型")

    # turn_id 提升到 if 外，非流式返回体与流式 done payload
    # 契约对齐（turn_id + suggested_actions 同构，一致性）
    ns_turn_id = uuid.uuid4().hex[:12]
    if use_studio_context:
        async with svc.lock:
            if result.text:
                svc.add_chat_message(
                    "agent", result.text, model_name=used_model or "",
                    confirm=result.confirmation,
                    applied_actions=result.applied_actions,
                    action_log=result.action_log or [],
                    confirm_options=result.confirmation_options or None,
                    turn_id=ns_turn_id,
                    pause_id=result.pause_id,
                    kind=result.pause_kind or "",
                    suggested_actions=result.suggested_actions or None,
                    # 2026-09-21 批B（事故 5555/Q4）：问题级字段（非流式同流式契约）。
                    # getattr 取值：测试桩 SimpleNamespace 可能不带这些字段
                    # （与 planner_output 的同款兼容口径一致）。
                    pause_header=str(getattr(result, "pause_header", "") or ""),
                    pause_detail=str(getattr(result, "pause_detail", "") or ""),
                    pause_multi_select=bool(getattr(result, "pause_multi_select", False)),
                    # 2026-09-21 批F：问题级列表（非流式同流式契约；getattr 同口径）
                    pause_questions=list(getattr(result, "pause_questions", None) or []),
                )
            if result.image_urls:
                svc.add_chat_message("agent", "", image_urls=result.image_urls, turn_id=ns_turn_id)

    return {
        "text": result.text, "applied_actions": result.applied_actions, "steps": result.steps,
        "warnings": result.warnings, "confirmation": result.confirmation,
        "pause_id": result.pause_id,
        "documents_written": result.documents_written,
        "image_urls": result.image_urls,
        "state": svc.get_full_snapshot() if use_studio_context else None,
        "turn_id": ns_turn_id,
        "suggested_actions": result.suggested_actions,
        # 协作式停止标记（取消穿透分流同构）：与流式 done payload 的 stopped/stop_phase 对齐
        #（getattr 兼容测试打桩返回的无 stopped 属性对象）
        "stopped": bool(getattr(result, "stopped", False)),
        "stop_phase": getattr(result, "stop_phase", ""),
        # workflow 投影（非流式同构）
        "workflow": workflow_runtime.project(svc.state_dict, ns_turn_id),
    }

# 开场编排域/消费压缩域实现体在 chat_opening.py / chat_consume.py，re-export 保持既有引用不变
from src.video_agent.web.chat_opening import (
    _HISTORY_ASSISTANT_MAX_CHARS,
    _HISTORY_HEAD_CHARS,
    _HISTORY_TAIL_CHARS,
    _INFLIGHT_REQUESTS,
    _acquire_request_slot,
    _build_meta_note,
    _build_prelude_notes,
    _create_chat_adapter,
    _prepare_chat_opening,
    _record_active_skill,
    _release_request_slot,
    _resolve_skill_name_for_injection,
    _resolve_summary_adapter,
    _store_gate_overrides,
    truncate_history,
)
from src.video_agent.web.chat_consume import (
    _consume_pending_confirmation,
    consume_pause_response,
)
# 会话 compaction 域（实现体 history_compact.py，2026-09-03 按关注点切分）
from src.video_agent.web.history_compact import (
    _summary_thinking_level,
    _HISTORY_COMPACT_KEEP,
    _compact_card_enumeration,
    _maybe_compact_history,
)
# 错误翻译域（实现体 chat_errors.py）：chat_service 内部调用 _emit_stream_error
#（失败出口，非 re-export 壳）；外部消费方（tests）直连 chat_errors.py。
from src.video_agent.web.chat_errors import (
    _emit_stream_error,
)
