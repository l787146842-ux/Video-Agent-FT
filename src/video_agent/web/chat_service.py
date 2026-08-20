"""
Agent Chat Service — 聊天业务编排（从 routes/agent.py 抽离）。

职责：
- 流式 worker 执行（mock / 真实供应商，含模型 fallback 链）
- 非流式聊天编排
- 会话持久化（用户/agent 消息、文档卡片、生图卡片）

拆分（修复计划书 -6）：
- 多模态内容构建 → multimodal_builder.py
- SSE 事件推送 → sse.py
routes/agent.py 仅保留路由定义和请求/响应模型。
"""
import asyncio
import re
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from src.video_agent.web.action_executor import StudioActionExecutor
from src.video_agent.config import settings
from src.video_agent.core import prompt_gates
from src.video_agent.web.attachments import bind_attachments, attachment_context, store_uploaded_docs
from src.video_agent.web.generation import resolve_openai_endpoint
from src.video_agent.web.mock_chat import mock_stream
from src.video_agent.web.mock_llm import mock_llm_reply
from src.video_agent.web.multimodal_builder import (
    build_multimodal_content,
    _TYPE_TO_CATEGORY,
)
from src.video_agent.web.provider_config import (
    get_provider_config,
    is_mock_provider,
    is_mock_provider_async,
    load_merged_providers,
    load_merged_providers_async,
)
from src.video_agent.web.sse import sse_event_generator  # noqa: 1 （保留 sse.py 为正常模块；本行仅兼容旧导入路径）
from src.video_agent.state.manager import StateManager
from src.video_agent.core.planner import Planner, PlannerContext
from src.video_agent.core.sse_events import (
    SSE_ACTIONS_APPLIED,
    SSE_DELTA,
    SSE_DOC_WRITTEN,
    SSE_DONE,
    SSE_ERROR,
    SSE_GUIDANCE_INJECTED,
    SSE_STATUS,
    status_event,
)
from src.video_agent.memory import MemoryManager
from src.video_agent.exceptions import AdapterError, GenerationError, VideoAgentError
from src.video_agent.adapters.base_chat import BaseChatAdapter
from src.video_agent.adapters.factory import AdapterFactory
from src.video_agent.tools.manager import ToolManager
from src.video_agent.core.tracer import AgentTracer

__all__ = ["stream_worker", "non_stream_worker", "build_multimodal_content"]











































async def stream_worker(body: Any, emit) -> None:
    """流式聊天的后台 worker（mock + 真实供应商）。

    Args:
        body: ChatRequest 实例
        emit: async callable(event_dict) 用于向队列推送 SSE 事件
    """
    request_id = body.request_id or ""
    if not _acquire_request_slot(request_id):
        await emit({"type": SSE_ERROR, "detail": "相同请求正在处理中，请勿重复发送",
                    "error_code": "DUPLICATE_REQUEST"})
        return
    try:
        svc = StateManager.get_instance()
        await _stream_worker_impl(body, svc, emit)
    finally:
        _release_request_slot(request_id)


async def _stream_worker_impl(body: Any, svc: StateManager, emit, pending_injector=None) -> None:
    """流式处理公共实现（mock + 真实供应商）；供 SSE worker 与后台任务 worker 复用。

    pending_injector：可选 callable → List[{id, text}]，轮间引导注入器，
    由后台任务路径装配（agent_task_manager.drain_pending_guidance）。"""
    # 铁律文档每轮确保存在（宪法）：项目级生产契约唯一表述源，
    # 真实聊天/任务路径同样生效，不能只在 mock 路径创建
    from src.video_agent.core.spec_rules import ensure_iron_rules_doc
    try:
        ensure_iron_rules_doc(svc.state_dict)
    except Exception as _e:
        logger.debug("[chat_service] 忽略异常: {}", _e)

    # 一条龙指令仅本条消息生效——任务开始清除上一任务残留标记
    if prompt_gates.clear_flow_directive(svc.state_dict):
        svc.save_debounced()

    t0 = time.monotonic()
    executor = StudioActionExecutor(
        svc,
        selected_draft_id=body.selected_draft_id,
        selected_type=body.selected_type,
    )

    user_text = body.message.strip()
    if not user_text and not body.attachments:
        await emit({"type": SSE_ERROR, "detail": "消息不能为空", "error_code": "EMPTY_MESSAGE"})
        return
    if not user_text:
        user_text = "请查看我上传的素材"

    use_studio_context = body.context_mode != "none"
    # 开场公共编排：暂停闭环 + 规格定稿/向导 + 附件降级注入
    llm_user_text = await _prepare_chat_opening(svc, body, user_text, use_studio_context)

    # 会话层一次性豁免：随消息登记，Planner 本次消费
    if getattr(body, "gate_overrides", None) and use_studio_context:
        async with svc.lock:
            _store_gate_overrides(svc, body.gate_overrides)

    # Skill 写入文档：本轮激活了 Skill 即记入当前项目 usedSkills
    #（不再依赖消息携带 chip/slug；文档面板只展示已发送过的 Skill 文档）
    async with svc.lock:
        _record_active_skill(svc, body)

    # 多模态内容构建（有 content_parts 时按排版顺序交错；
    # 传入选中草稿信息用于素材超限时的优先级注入）
    llm_user_content = await build_multimodal_content(
        llm_user_text, body.attachments, body.images or [], body.content_parts or None,
        selected_draft_id=body.selected_draft_id, selected_type=body.selected_type,
        videos=body.videos or [],
    )

    # ---------- mock：模拟流式 ----------
    if is_mock_provider(body.provider, body.model):
        await mock_stream(
            svc, executor, body, user_text, llm_user_text,
            use_studio_context, emit, t0, meta_builder=_build_meta_note,
        )
        return

    # ---------- 真实供应商 ----------
    await _real_stream(svc, executor, body, user_text, llm_user_text, llm_user_content, use_studio_context, emit, t0, pending_injector=pending_injector)


def start_agent_task(body: Any) -> Dict[str, Any]:
    """任务式传输（D 批）：提交即返回 task_id，worker 后台运行。

    刷新/切项目只断订阅不杀任务；worker 绑定提交时所属项目（任务级 StateManager），
    不会把旧项目状态写进新项目（根因之一）。
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


async def _run_agent_task(body: Any, project_id: str, task_id: str, workspace_dir: str) -> None:
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
        tm.emit(task_id, {
            "type": SSE_ERROR, "detail": f"服务端异常: {e}",
            "error_code": getattr(e, "error_code", None) or "INTERNAL_ERROR",
        })
        return
    try:
        async def emit(event: Dict[str, Any]) -> None:
            tm.emit(task_id, event)

        # 恢复：轮间引导注入器——注册到本任务的排队消息逐轮被消费
        # （agent_loop 第 2 轮起调用），注入成功即 guidance_injected 事件下发。
        def pending_injector() -> List[Dict[str, Any]]:
            return tm.drain_pending_guidance(task_id)

        await _stream_worker_impl(body, svc, emit, pending_injector=pending_injector)
    except asyncio.CancelledError:
        logger.warning(f"[AgentTask] {task_id} worker 被取消（非用户停止即异常信号）")
        raise
    except Exception as e:
        logger.exception(f"[AgentTask] {task_id} 处理异常: {e}")
        tm.emit(task_id, {
            "type": SSE_ERROR,
            "detail": f"服务端异常: {e}",
            "error_code": getattr(e, "error_code", None) or "INTERNAL_ERROR",
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


# ---------- 模型 fallback 链（退役：用户裁决 2026-08-20） ----------
# 模型选择权归用户：选什么用什么，联不通直接报错。自动换厂商 fallback
# （_fallback_candidates/_fallback_switch_payload/_is_retryable_adapter_error）
# 已删除；model_fallback 事件骨架仅留兼容旧任务 replay（协议表见退役注记）。
# 生图/生视频 fallback 属独立机制（generation.py），不在本裁决范围。


def _stamp_doc_written(payload: Optional[Dict[str, Any]], turn_id: str) -> Dict[str, Any]:
    """ ：doc_written 即显事件打戳本轮 turn_id。

    发射端（agent_loop/fc_tool_runner）无 turn_id 概念，打戳归透传层
    （turn_id 在 _real_stream 起始生成）；前端即显卡据此与 done 主消息
    同 turnId 严格归组（显式 id 原则延伸，不再依赖相邻兜底）。
    """
    out = dict(payload or {"type": SSE_DOC_WRITTEN})
    out["turn_id"] = turn_id
    return out


async def _real_stream(svc, executor, body, user_text, llm_user_text, llm_user_content, use_studio_context, emit, t0, pending_injector=None) -> None:
    """真实供应商的流式处理（含模型 fallback 链）。

    主模型遇 5xx/超时等瞬时故障且尚未执行任何操作时，自动切换备用模型重试
    （避免重复执行已落盘的操作）；成功时 done payload 携带 fallback_model 供前端标注。
    pending_injector：轮间引导注入器，经 PlannerContext 传入循环。
    """
    history = truncate_history([
        {"role": m.get("role", "user"), "content": m.get("content", "")}
        for m in body.messages[-10:]
    ])

    # 轮次唯一标识——本轮持久化的正文/文档卡/图片卡共用同一 turnId，
    # 前端据此把产出聚合进同次容器（消除消息流碎片化）；随 done payload
    # 下发，流式端与历史重载端同构
    turn_id = uuid.uuid4().hex[:12]

    # 短锁：绑定附件 + 附件文档存档 + 记录用户消息（仅一次，不随 fallback 重复）；
    # 状态 JSON 改为惰性构建器：多步循环每一轮重新构建，模型每轮看到最新状态
    async with svc.lock:
        if use_studio_context:
            bind_attachments(svc, body.attachments)
            store_uploaded_docs(svc, body.attachments)
            # 暂停回应结构化消费：点选回应与 active_pause 匹配即落标记（展示层）
            pause_answered = consume_pause_response(
                svc, getattr(body, "pause_response", None) or None)
            svc.add_chat_message(
                "user", user_text,
                doc_blocks=getattr(body, "doc_blocks", None) or None,
                skill_blocks=getattr(body, "skill_blocks", None) or None,
                pause_answered=pause_answered,
                kind=getattr(body, "system_action", "") or "",
            )
            # 向导挂起的规格卡补落（用户消息之后）并发即显事件
            await emit_pending_doc_card(svc, turn_id, emit)

    state_builder = (
        (lambda: svc.build_agent_context(body.asset_mode)) if use_studio_context else None
    )

    # --- 解析中间面板选中的生图 provider + 画面比例（注入 generate_image 工具用）---
    image_provider, image_aspect_ratio = _resolve_selected_draft_media_config(
        svc, body.selected_draft_id, body.selected_type
    )

    # 批 C 退役（用户裁决 2026-08-20）：模型选择权归用户——
    # 选什么用什么，联不通直接报错，不自动换厂商 fallback
    candidates = [(body.provider, body.model)]
    # 会话级 compaction（恢复；：预热后台——便宜模型摘要与
    # fallback 候选的 adapter 创建/端点解析并行，首 token 不被摘要往返阻塞；
    # 命中缓存时任务即刻完成，语义与同步等待完全一致）
    summary_adapter = _resolve_summary_adapter(body, candidates)
    _compact_task = asyncio.create_task(_maybe_compact_history(history, svc, summary_adapter))

    for idx, (cand_provider, cand_model) in enumerate(candidates):
        try:
            llm_adapter = _create_chat_adapter(cand_provider, cand_model)
        except GenerationError as e:
            logger.warning(f"[ChatService] 所选供应商 {cand_provider}/{cand_model} 端点解析失败: {e}")
            if _compact_task is not None and not _compact_task.done():
                _compact_task.cancel()
            await _emit_stream_error(svc, body, e, emit, use_studio_context)
            return
        # 进入候选前取回压缩结果（预热失败/超时由 _maybe_compact_history 内部回落原 history）
        if _compact_task is not None:
            history = await _compact_task
            _compact_task = None

        planner = Planner(
            state_manager=svc, llm_adapter=llm_adapter, tool_manager=ToolManager,
            executor_factory=StudioActionExecutor,
            summary_adapter=summary_adapter,
            chat_provider=cand_provider, chat_model=cand_model,
        )
        resolved_skill = _resolve_skill_name_for_injection(
            body.skill_name or "", body.skill_slug or "", svc.state_dict, user_text,
        )
        prelude_notes = _build_prelude_notes(resolved_skill)
        planner_ctx = PlannerContext(
            history=history,
            selected_draft_id=body.selected_draft_id,
            selected_type=body.selected_type,
            state_builder=state_builder,
            degraded_state_builder=(
                (lambda: svc.build_agent_context_degraded(body.asset_mode)) if use_studio_context else None
            ),
            skill_name=resolved_skill,
            # 分诊只认用户原话（附件预览问号不参与提问判定）
            raw_user_text=user_text,
            prelude_notes=prelude_notes,
            use_studio_context=use_studio_context,
            asset_mode=body.asset_mode,
            image_generation_provider=image_provider,
            image_generation_aspect_ratio=image_aspect_ratio,
            user_id=getattr(body, "user_id", "") or "",
            # 会话级推理档位（对话栏选择器下发；""=模型原生）
            thinking_level=getattr(body, "thinking_level", "") or "",
            # 轮间引导注入器（任务式传输路径；非任务路径为 None）
            pending_injector=pending_injector,
        )

        applied_seen = False
        final_text = ""
        final_payload: Dict[str, Any] = {}
        try:
            async for event in planner.handle_message_stream(llm_user_content, planner_ctx):
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
                    if use_studio_context:
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
                    await emit(_stamp_doc_written(event.payload, turn_id))
                elif event.type in (
                    "reasoning_delta", "tool_started", "tool_finished", SSE_GUIDANCE_INJECTED,
                ):
                    # 过程时间线事件透传（深度思考增量 / 工具开始与完成 / 引导注入），
                    # 仅 UI 展示用，不进下次 LLM 上下文
                    await emit(event.payload or {"type": event.type, "text": event.text})
                elif event.type == "done":
                    final_payload = event.payload or {}
                    final_text = final_payload.get("text", "")
                elif event.type == "error":
                    # 透传上游结构化故障标记（-2）：保证 fallback 链判定不依赖文案
                    p = event.payload or {}
                    raise AdapterError(
                        event.text,
                        retryable=p.get("retryable"),
                        http_status=p.get("http_status"),
                    )
        except (GenerationError, AdapterError) as e:
            # 批 C 裁决：单一候选、不自动换模型——失败直接报错；
            # 已执行过操作同样直接报错（避免重复落盘）
            logger.warning(f"[ChatService] LLM 流式调用失败 ({cand_provider}/{cand_model}): {e}")
            await _emit_stream_error(svc, body, e, emit, use_studio_context)
            return

        # --- 成功路径：持久化 + done ---
        if use_studio_context and (final_text or final_payload.get("image_urls") or final_payload.get("confirmation")):
            applied = final_payload.get("applied_actions") or 0
            async with svc.lock:
                if final_text or final_payload.get("confirmation"):
                    svc.add_chat_message(
                        "agent", final_text, model_name=cand_model or "",
                        meta=_build_meta_note(
                            time.monotonic() - t0,
                            final_payload.get("steps") or 1,
                            applied,
                        ),
                        confirm=final_payload.get("confirmation") or "",
                        applied_actions=applied,
                        action_log=drain_pending_action_log(svc)
                        + (final_payload.get("action_log") or []),
                        trace=final_payload.get("trace") or {},
                        confirm_options=final_payload.get("confirmation_options") or None,
                        turn_id=turn_id,
                        pause_id=str(final_payload.get("pause_id") or ""),
                    )
                # 文档完成卡片：独立条目持久化，刷新后可重建（同轮 turnId 聚合）
                for doc_name in (final_payload.get("documents_written") or []):
                    svc.add_chat_message("agent", "", doc_card=doc_name, turn_id=turn_id)
                # 生图卡片随历史持久化（独立消息条目，与前端 finishStream 的两条消息结构一致，
                # 否则刷新页面后聊天记录里的图片卡片会丢失）
                image_urls = final_payload.get("image_urls") or []
                if image_urls:
                    svc.add_chat_message("agent", "", image_urls=image_urls, turn_id=turn_id)

        done_payload: Dict[str, Any] = {
            **final_payload,
            "state": svc.get_full_snapshot() if use_studio_context else None,
            "elapsed_ms": int((time.monotonic() - t0) * 1000),
            "turn_id": turn_id,
        }
        await emit({"type": SSE_DONE, "payload": done_payload})
        return


async def _emit_stream_error(svc, body, e: Exception, emit, use_studio_context: bool) -> None:
    """流式失败统一出口：持久化错误消息 + 发 error 事件。

    ：错误分层——气泡只展示一句人话（friendly），
    上游原始报文（raw）随 errorDetail 持久化 + payload raw 下发，前端折叠展示。
    """
    friendly, raw = _friendly_stream_error(e)
    if use_studio_context:
        async with svc.lock:
            # 错误前缀统一为 ⚠️（与前端 streamError 渲染一致，刷新后不跳变）
            svc.add_chat_message(
                "agent", f"⚠️ {friendly}", model_name=body.model or "",
                error_detail=raw,
            )
    await emit({
        "type": SSE_ERROR, "detail": friendly, "raw": raw,
        "error_code": getattr(e, "error_code", "INTERNAL_ERROR"),
    })


def _friendly_stream_error(e: Exception) -> Tuple[str, str]:
    """上游错误人话翻译（反馈：裸 JSON 报错看不懂）。

    返回 (friendly, raw)：friendly = 一句可操作的人话；
    raw = 上游原始报文（未命中翻译时为空串，前端不渲染技术详情折叠）。
    """
    msg = str(e)
    if "insufficient_user_quota" in msg or "预扣费" in msg:
        m_remain = re.search(r"剩余额度[:：]\s*＄?\$?([\d.]+)", msg)
        m_need = re.search(r"需要预扣费额度[:：]\s*＄?\$?([\d.]+)", msg)
        detail = ""
        if m_remain and m_need:
            detail = f"（账户剩余 ${m_remain.group(1)}，本次需预扣 ${m_need.group(1)}）"
        return (
            f"上游供应商账户额度不足{detail}，无法预扣本次调用费用——这不是上下文超限。"
            "上下文越长预扣越高，故常在任务后半程触发。"
            "请为上游账户充值，或在 API 设置页切换其他供应商/模型后重试。",
            msg,
        )
    status = getattr(e, "http_status", None)
    # 批 A：中继拒收通知单（slow 队列等）优先翻译——须在 401/403 鉴权分支前，
    # 否则 403 被误译为「Key 过期」；裁决：不自动换模型，只提示手动
    low = msg.lower()
    if "10605" in msg or "queuetype" in low or "中继拒收通知单" in msg:
        return (
            "上游排队拒收（slow 队列瞬时不接客）：非 Key 或上下文问题。"
            "请稍后重试；如需可在选择器手动切换其他模型号再发。",
            msg,
        )
    if status in (401, 403):
        return (
            f"鉴权失败（HTTP {status}）：API Key 未配置、已过期或不正确。"
            "请到 API 设置页检查对应供应商的 Key 后重试。",
            msg,
        )
    if status == 429:
        return (
            "上游供应商限流或配额不足（HTTP 429）。请稍后重试，或切换其他供应商/模型。",
            msg,
        )
    if isinstance(status, int) and 500 <= status < 600:
        return (
            f"上游供应商瞬时故障（HTTP {status}）。请稍后重试；"
            "如需可在选择器手动切换其他供应商/模型。",
            msg,
        )
    low = msg.lower()
    if "timeout" in low or "timed out" in low or "connect" in low:
        return (
            "上游供应商连接超时或失败。请检查网络，或切换其他供应商/模型后重试。",
            msg,
        )
    return msg, ""


async def non_stream_worker(body: Any) -> Dict[str, Any]:
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


async def _non_stream_inner(body: Any, user_text: str) -> Dict[str, Any]:
    """非流式聊天主体（幂等槽位由 non_stream_worker 管理）"""
    svc = StateManager.get_instance()
    # 铁律文档每轮确保存在（宪法），非流式路径同样生效
    from src.video_agent.core.spec_rules import ensure_iron_rules_doc
    try:
        ensure_iron_rules_doc(svc.state_dict)
    except Exception as _e:
        logger.debug("[chat_service] 忽略异常: {}", _e)
    # 一条龙指令仅本条消息生效（与非流式路径对齐）
    if prompt_gates.clear_flow_directive(svc.state_dict):
        svc.save_debounced()
    executor = StudioActionExecutor(
        svc,
        selected_draft_id=body.selected_draft_id,
        selected_type=body.selected_type,
    )

    use_studio_context = body.context_mode != "none"
    # 开场公共编排：同流式路径（暂停闭环 + 规格定稿/向导 + 附件降级）
    llm_user_text = await _prepare_chat_opening(svc, body, user_text, use_studio_context)

    # 会话层一次性豁免：同流式路径
    if getattr(body, "gate_overrides", None) and use_studio_context:
        async with svc.lock:
            _store_gate_overrides(svc, body.gate_overrides)

    # Skill 写入文档：同 stream_worker——本轮激活了 Skill 即记入 usedSkills
    async with svc.lock:
        _record_active_skill(svc, body)

    # mock 路径
    _wiz_card = ""
    if is_mock_provider(body.provider, body.model):
        async with svc.lock:
            if use_studio_context:
                bind_attachments(svc, body.attachments)
                svc.add_chat_message(
                    "user", user_text,
                    doc_blocks=getattr(body, "doc_blocks", None) or None,
                    skill_blocks=getattr(body, "skill_blocks", None) or None,
                )
                # 规格卡补落（用户消息之后），名字随载荷下发保 live 可见
                _wiz_card = flush_pending_doc_card(svc)
            # 单轨化：mock 动作以结构化 dict 直达执行器，不经文本块解析
            visible, actions = mock_llm_reply(llm_user_text, svc.build_agent_context(body.asset_mode))
            applied = executor.execute(actions)
            if use_studio_context:
                svc.add_chat_message("agent", visible, model_name=body.model or "")
        return {
            "text": visible, "applied_actions": applied, "steps": 1,
            "warnings": ["当前为 mock 供应商，回复由本地规则生成，未调用真实 LLM"],
            "confirmation": "",
            "documents_written": executor.documents_written + ([_wiz_card] if _wiz_card else []),
            "state": svc.get_full_snapshot(),
        }

    # 真实供应商
    history = truncate_history([
        {"role": m.get("role", "user"), "content": m.get("content", "")} for m in body.messages[-10:]
    ])

    # 多模态内容构建（有 content_parts 时按排版顺序交错；
    # 传入选中草稿信息用于素材超限时的优先级注入）
    llm_user_content = await build_multimodal_content(
        llm_user_text, body.attachments, body.images or [], body.content_parts or None,
        selected_draft_id=body.selected_draft_id, selected_type=body.selected_type,
        videos=body.videos or [],
    )

    _wiz_card_ns = ""
    async with svc.lock:
        if use_studio_context:
            bind_attachments(svc, body.attachments)
            store_uploaded_docs(svc, body.attachments)
            # 暂停回应结构化消费（非流式路径同构）
            ns_pause_answered = consume_pause_response(
                svc, getattr(body, "pause_response", None) or None)
            svc.add_chat_message(
                "user", user_text,
                doc_blocks=getattr(body, "doc_blocks", None) or None,
                skill_blocks=getattr(body, "skill_blocks", None) or None,
                pause_answered=ns_pause_answered,
                kind=getattr(body, "system_action", "") or "",
            )
            # 规格卡补落（用户消息之后， 非流式轨同步），名字随载荷下发
            _wiz_card_ns = flush_pending_doc_card(svc)

    # 状态惰性构建器：多步循环每轮刷新
    state_builder = (
        (lambda: svc.build_agent_context(body.asset_mode)) if use_studio_context else None
    )

    # --- 解析中间面板选中的生图 provider + 画面比例 ---
    image_provider2, image_aspect_ratio2 = _resolve_selected_draft_media_config(
        svc, body.selected_draft_id, body.selected_type
    )

    resolved_skill = _resolve_skill_name_for_injection(
        body.skill_name or "", body.skill_slug or "", svc.state_dict, user_text,
    )
    prelude_notes = _build_prelude_notes(resolved_skill)
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
    )

    # 批 C 退役（用户裁决 2026-08-20）：单一候选 = 用户所选，联不通直接报错
    candidates = [(body.provider, body.model)]
    # 会话级 compaction（恢复；：同流式路径——预热后台）
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
        planner = Planner(
            state_manager=svc, llm_adapter=llm_adapter, tool_manager=ToolManager,
            executor_factory=StudioActionExecutor,
            summary_adapter=summary_adapter,
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
        except (GenerationError, AdapterError) as e:
            # 批 C 裁决：单一候选、不自动换模型——失败直接报错
            logger.warning(f"[ChatService] LLM 非流式调用失败 ({cand_provider}/{cand_model}): {e}")
            raise
    if result is None:  # 理论不可达（最后候选失败已 raise），防御兜底
        raise last_err or GenerationError("无可用聊天模型")

    #自查补漏：turn_id 提升到 if 外，非流式返回体与流式 done payload
    # 契约对齐（turn_id + suggested_actions 同构， 一致性）
    ns_turn_id = uuid.uuid4().hex[:12]
    if use_studio_context:
        async with svc.lock:
            if result.text:
                svc.add_chat_message(
                    "agent", result.text, model_name=used_model or "",
                    confirm=result.confirmation,
                    applied_actions=result.applied_actions,
                    action_log=drain_pending_action_log(svc) + (result.action_log or []),
                    confirm_options=result.confirmation_options or None,
                    turn_id=ns_turn_id,
                    pause_id=result.pause_id,
                )
            if result.image_urls:
                svc.add_chat_message("agent", "", image_urls=result.image_urls, turn_id=ns_turn_id)

    return {
        "text": result.text, "applied_actions": result.applied_actions, "steps": result.steps,
        "warnings": result.warnings, "confirmation": result.confirmation,
        "pause_id": result.pause_id,
        "documents_written": result.documents_written + ([_wiz_card_ns] if _wiz_card_ns else []),
        "image_urls": result.image_urls,
        "state": svc.get_full_snapshot() if use_studio_context else None,
        "memory_hits": getattr(planner_ctx, "memory_hits", None) or [],
        "turn_id": ns_turn_id,
        "suggested_actions": result.suggested_actions,
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
    _consume_spec_wizard,
    _finalize_spec_params,
    _maybe_compact_history,
    consume_pause_response,
    drain_pending_action_log,
    emit_pending_doc_card,
    flush_pending_doc_card,
)
