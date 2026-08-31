"""
Agent Chat Service — 聊天业务编排。

职责：
- 流式处理公共实现（真实供应商）：任务式后台任务与非流式共用
- 非流式聊天编排
- 会话持久化（用户/agent 消息、文档卡片、生图卡片）

模块结构：
- 多模态内容构建 → multimodal_builder.py
routes/agent.py 仅保留路由定义和请求/响应模型。

错误翻译域位于 web/chat_errors.py；
本文件尾部留承重壳 re-export（coupling_registry R13 登记），
既有引用与测试 patch 目标不变，错误语义零变更。
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
from src.video_agent.config import settings
from src.video_agent.core import prompt_gates
from src.video_agent.core import stage_probes
from src.video_agent.core import workflow_runtime
from src.video_agent.web.attachments import bind_attachments, attachment_context, store_uploaded_docs
from src.video_agent.web.chat_cards import _stamp_doc_written, _video_card_items
from src.video_agent.web.generation import resolve_openai_endpoint
from src.video_agent.web.multimodal_builder import (
    build_multimodal_content,
    _TYPE_TO_CATEGORY,
)
from src.video_agent.core.provider_config import (
    get_provider_config,
    load_merged_providers,
    load_merged_providers_async,
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
from src.video_agent.core.stop_signal import is_stop_requested
from src.video_agent.core.token_budget import window_recent_turns
from src.video_agent.web.stop_manager import (
    persist_stop_trace,
    snapshot_inflight_generations,
    stopped_event,
)
from src.video_agent.exceptions import AdapterError, GenerationError, VideoAgentError
from src.video_agent.adapters.base_chat import BaseChatAdapter
from src.video_agent.adapters.cancel_token import GenerationCancelled
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
    await _real_stream(svc, executor, body, user_text, llm_user_text, llm_user_content, use_studio_context, emit, t0, pending_injector=pending_injector, advance_signal=advance_signal, stop_scope=stop_scope)


def start_agent_task(body: ChatRequest) -> Dict[str, Any]:
    """任务式传输：提交即返回 task_id，worker 后台运行。

    刷新/切项目只断订阅不杀任务；worker 绑定提交时所属项目（任务级 StateManager），
    不会把旧项目状态写进新项目。
    """
    from src.video_agent.utils import gen_id
    from src.video_agent.web.agent_task_manager import get_agent_task_manager

    submission_svc = StateManager.get_instance()
    project_id = submission_svc.active_project_id or ""
    workspace_dir = str(submission_svc._workspace_dir)
    task_id = gen_id("agt")
    tm = get_agent_task_manager()
    record = tm.create(
        project_id,
        lambda: _run_agent_task(body, project_id, task_id, workspace_dir),
        task_id=task_id,
        model=getattr(body, "model", "") or "",
    )
    return {"task_id": record["task_id"], "project_id": project_id}


async def _run_agent_task(body: ChatRequest, project_id: str, task_id: str, workspace_dir: str) -> None:
    """后台任务 worker：绑定任务专属 StateManager，事件经 task_manager.emit 下发。"""
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
        StateManager.release_task_bound(token)


def _resolve_selected_draft_media_config(svc, selected_draft_id: str, selected_type: str) -> tuple:
    """从选中草稿解析生图配置 (providerId, aspectRatio)。

    中间预览面板选中的草稿决定了 agent 生图时用哪个供应商和画面比例。
    """
    provider_id = ""
    aspect_ratio = ""
    if not selected_draft_id:
        return settings.default_image_provider_id, aspect_ratio
    category = _TYPE_TO_CATEGORY.get(selected_type, selected_type)
    raw_state = svc.get_full_snapshot()
    for group in (raw_state.get(category) or []):
        if not isinstance(group, dict):
            continue
        for draft in (group.get("drafts") or []):
            if isinstance(draft, dict) and draft.get("id") == selected_draft_id:
                provider_id = draft.get("imageProviderId", "") or draft.get("providerId", "") or ""
                aspect_ratio = draft.get("aspectRatio", "") or ""
                return provider_id or settings.default_image_provider_id, aspect_ratio
    return settings.default_image_provider_id, aspect_ratio


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
    # --- 准备段中间结果 ---
    history: List[Dict[str, Any]] = field(default_factory=list)
    turn_id: str = ""
    state_builder: Any = None
    image_provider: str = ""
    image_aspect_ratio: str = ""
    candidates: List[tuple] = field(default_factory=list)
    compact_task: Any = None
    planner: Any = None
    cand_provider: str = ""
    cand_model: str = ""
    # --- 分发段结果 ---
    final_text: str = ""
    final_payload: Dict[str, Any] = field(default_factory=dict)
    stopped_seen: bool = False
    stop_phase_seen: str = ""


def _stage_aware_state_builder(svc: Any, asset_mode: str, skill: str):
    """第 5 批（Q6）：状态注入阶段感知构建器。

    Skill 激活时每步实时探测当前创作阶段传入 build_agent_context
    （分阶段裁剪注入面）；无 Skill / 探测失败回落全量注入（保守不失约束）。
    """

    def _builder() -> str:
        stage = ""
        if skill:
            try:
                spec = stage_probes.current_stage(svc.state_dict, skill)
                stage = spec.key if spec else ""
            except Exception:
                stage = ""
        return svc.build_agent_context(asset_mode, stage=stage)

    return _builder


async def _stream_prepare(ctx: _StreamCtx) -> Optional[PlannerContext]:
    """三段之一（准备）：history/compaction 预热/PlannerContext 装配。

    adapter 创建失败经既有出口发错并返回 None（调用方终止流）。
    """
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
            # 规格向导机械落盘投影管线已随用户裁决 2026-08-31 退役（D-08 清偿）

    # --- 解析中间面板选中的生图 provider + 画面比例（注入 image_generate 工具用）---
    ctx.image_provider, ctx.image_aspect_ratio = _resolve_selected_draft_media_config(
        ctx.svc, ctx.body.selected_draft_id, ctx.body.selected_type
    )

    # 用户裁决：模型选择权归用户——
    # 选什么用什么，联不通直接报错，不自动换厂商 fallback
    ctx.candidates = [(ctx.body.provider, ctx.body.model)]
    # 会话级 compaction：预热后台——便宜模型摘要的
    # adapter 创建/端点解析并行，首 token 不被摘要往返阻塞；
    # 命中缓存时任务即刻完成，语义与同步等待完全一致
    summary_adapter = _resolve_summary_adapter(ctx.body, ctx.candidates)
    ctx.compact_task = asyncio.create_task(_maybe_compact_history(ctx.history, ctx.svc, summary_adapter))

    # 单一候选：首候选即终选（原循环所有路径均在首轮 return，行为等价）
    ctx.cand_provider, ctx.cand_model = ctx.candidates[0]
    try:
        llm_adapter = _create_chat_adapter(ctx.cand_provider, ctx.cand_model)
    except GenerationError as e:
        logger.warning(f"[ChatService] 所选供应商 {ctx.cand_provider}/{ctx.cand_model} 端点解析失败: {e}")
        if ctx.compact_task is not None and not ctx.compact_task.done():
            ctx.compact_task.cancel()
        await _emit_stream_error(ctx.svc, ctx.body, e, ctx.emit, ctx.use_studio_context)
        return None
    # 进入候选前取回压缩结果（预热失败/超时由 _maybe_compact_history 内部回落原 history）
    if ctx.compact_task is not None:
        ctx.history = await ctx.compact_task
        ctx.compact_task = None

    ctx.planner = Planner(
        state_manager=ctx.svc, llm_adapter=llm_adapter, tool_manager=ToolManager,
        executor_factory=StateOperationExecutor,
        chat_provider=ctx.cand_provider, chat_model=ctx.cand_model,
    )
    resolved_skill = _resolve_skill_name_for_injection(
        ctx.body.skill_name or "", ctx.body.skill_slug or "", ctx.svc.state_dict, ctx.user_text,
    )
    # 状态惰性构建器：多步循环每轮刷新（阶段感知，resolved_skill 后装配）
    ctx.state_builder = (
        _stage_aware_state_builder(ctx.svc, ctx.body.asset_mode, resolved_skill)
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
                    await emit({
                        "type": SSE_ACTIONS_APPLIED,
                        "payload": {
                            "count": (event.payload or {}).get("count", 0),
                            "state": svc.get_full_snapshot(),
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
    # pause 相位豁免（问即停，ADR-0006）：暂停发行复用 stopped 标记结束本轮，
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
                    # 暂停卡语义种类持久化（前端历史重载按 kind 渲染标题）
                    kind=str(ctx.final_payload.get("pause_kind") or ""),
                    # quick-actions 芯片持久化（提醒类兜底卡出槽后不丢，刷新可重建）
                    suggested_actions=ctx.final_payload.get("suggested_actions") or None,
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
            # E1 消息级快照：轮末打快照挂最后一条 agent 消息（指针化：
            # 消息存 snapshotId，本体存 stateSnapshots；媒体只有 URL 指针）
            snap_id = ctx.svc.attach_snapshot_to_last_agent_message(label=f"轮次完成 {turn_id}")

    # 产物账本同轮下发（向导机械落盘投影已随裁决退役，不再并入 documents_written）
    done_payload: Dict[str, Any] = {
        **ctx.final_payload,
        "state": ctx.svc.get_full_snapshot() if ctx.use_studio_context else None,
        "elapsed_ms": int((time.monotonic() - ctx.t0) * 1000),
        "turn_id": turn_id,
        # E1：轮末快照指针同轮下发（live 消息挂回档动作，无需刷新）
        "snapshot_id": snap_id,
        # workflow 投影（run 快照 + 本轮事件，重连 replay 同源）
        "workflow": workflow_runtime.project(ctx.svc.state_dict, ctx.turn_id),
    }
    await ctx.emit({"type": SSE_DONE, "payload": done_payload})


async def _real_stream(svc, executor, body, user_text, llm_user_text, llm_user_content, use_studio_context, emit, t0, pending_injector=None, advance_signal: str = "", stop_scope: str = "chat") -> None:
    """真实供应商的流式处理（单一候选：选什么用什么，联不通直接报错）。

    生图/生视频 fallback 属独立机制（generation.py）。
    pending_injector：轮间引导注入器，经 PlannerContext 传入循环。
    stop_scope：协作式停止标志作用域，透传 PlannerContext → agent_loop 检查点。

    P1-4：函数体拆为 _stream_prepare/_stream_dispatch/_stream_finalize 三段，
    参数经 _StreamCtx 收敛；签名、事件语义与错误出口零变更。
    """
    ctx = _StreamCtx(
        svc=svc, executor=executor, body=body, user_text=user_text,
        llm_user_text=llm_user_text, llm_user_content=llm_user_content,
        use_studio_context=use_studio_context, emit=emit, t0=t0,
        pending_injector=pending_injector, advance_signal=advance_signal,
        stop_scope=stop_scope,
    )
    planner_ctx = await _stream_prepare(ctx)
    if planner_ctx is None:
        return
    if not await _stream_dispatch(ctx, planner_ctx):
        return
    await _stream_finalize(ctx)


# 错误翻译域实现体在 chat_errors.py：_emit_stream_error /
# _friendly_stream_error 经尾部 re-export 保持既有引用不变


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
            # （规格卡投影已随用户裁决 2026-08-31 退役，D-08 清偿）

    # --- 解析中间面板选中的生图 provider + 画面比例 ---
    image_provider2, image_aspect_ratio2 = _resolve_selected_draft_media_config(
        svc, body.selected_draft_id, body.selected_type
    )

    resolved_skill = _resolve_skill_name_for_injection(
        body.skill_name or "", body.skill_slug or "", svc.state_dict, user_text,
    )
    # 状态惰性构建器：多步循环每轮刷新（阶段感知，resolved_skill 后装配）
    state_builder = (
        _stage_aware_state_builder(svc, body.asset_mode, resolved_skill)
        if use_studio_context else None
    )

    prelude_notes = _build_prelude_notes(resolved_skill)

    # 用户裁决：单一候选 = 用户所选，联不通直接报错
    candidates = [(body.provider, body.model)]
    # 会话级 compaction：同流式路径——预热后台；PlannerContext
    # 在取回压缩结果之后构建，history 必须是压缩后列表，与流式轨同构
    summary_adapter = _resolve_summary_adapter(body, candidates)
    _compact_task = asyncio.create_task(_maybe_compact_history(history, svc, summary_adapter))
    result = None
    used_model = body.model
    last_err: Optional[Exception] = None
    for idx, (cand_provider, cand_model) in enumerate(candidates):
        try:
            llm_adapter = _create_chat_adapter(cand_provider, cand_model)
        except GenerationError as e:
            logger.warning(f"[ChatService] 所选供应商 {cand_provider}/{cand_model} 端点解析失败: {e}")
            if _compact_task is not None and not _compact_task.done():
                _compact_task.cancel()
            raise
        if _compact_task is not None:
            history = await _compact_task
            _compact_task = None
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
        )
        planner = Planner(
            state_manager=svc, llm_adapter=llm_adapter, tool_manager=ToolManager,
            executor_factory=StateOperationExecutor,
            chat_provider=cand_provider, chat_model=cand_model,
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
    _HISTORY_ASSISTANT_RECENT_MAX_CHARS,
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
    _summary_thinking_level,
    _HISTORY_COMPACT_KEEP,
    _compact_card_enumeration,
    _consume_pending_confirmation,
    _maybe_compact_history,
    consume_pause_response,
)
# 错误翻译域承重壳（实现体 chat_errors.py）：消费方为
# _real_stream 内部调用与 tests（test_error_payload/test_relay_error_envelope/
# test_truncate_resend 经 chat_service.* 导入），迁移需全量改引用；
# 公开错误出口门面，测试钉死 chat_service 命名空间，长期承重
from src.video_agent.web.chat_errors import (
    _emit_stream_error,
    _friendly_stream_error,
)
