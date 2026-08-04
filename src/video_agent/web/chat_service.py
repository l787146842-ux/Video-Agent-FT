"""
Agent Chat Service — 聊天业务编排（从 routes/agent.py 抽离）。

职责：
- 流式 worker 执行（mock / 真实供应商，含模型 fallback 链）
- 非流式聊天编排
- 会话持久化（用户/agent 消息、文档卡片、生图卡片）

拆分（修复计划书 P1-6）：
- 多模态内容构建 → multimodal_builder.py
- SSE 事件推送 → sse.py
routes/agent.py 仅保留路由定义和请求/响应模型。
"""
import asyncio
import time
from typing import Any, Dict, List, Optional

from loguru import logger

from src.video_agent.web.actions import StudioActionExecutor
from src.video_agent.config import settings
from src.video_agent.web.attachments import bind_attachments, attachment_context, store_uploaded_docs
from src.video_agent.web.generation import resolve_openai_endpoint
from src.video_agent.web.mock_chat import mock_stream
from src.video_agent.web.mock_llm import mock_llm_reply
from src.video_agent.web.multimodal_builder import (
    build_multimodal_content,
    _TYPE_TO_CATEGORY,
)
from src.video_agent.web.provider_config import is_mock_provider, load_merged_providers, get_provider_config
from src.video_agent.web.sse import sse_event_generator  # noqa: F401  （re-export，路由层从此导入）
from src.video_agent.state.manager import StateManager
from src.video_agent.core.planner import Planner, PlannerContext
from src.video_agent.core.sse_events import (
    SSE_ACTIONS_APPLIED,
    SSE_DELTA,
    SSE_DONE,
    SSE_ERROR,
    SSE_STATUS,
)
from src.video_agent.memory import MemoryManager
from src.video_agent.exceptions import AdapterError, GenerationError, VideoAgentError
from src.video_agent.adapters.base_chat import BaseChatAdapter
from src.video_agent.adapters.factory import AdapterFactory
from src.video_agent.adapters.agy_cli import AgyCliChatAdapter
from src.video_agent.tools.manager import ToolManager

__all__ = ["stream_worker", "non_stream_worker", "sse_event_generator", "build_multimodal_content"]

# 请求幂等防护（P2）：同一 request_id 正在处理中时拒绝重复提交，
# 防止 SSE 断连重发/双标签页重复发送导致操作重复落盘。
# 完成后即移除，不影响断线重连后的正常重发。
_INFLIGHT_REQUESTS: set = set()


def _acquire_request_slot(request_id: str) -> bool:
    """尝试占用请求槽位：未携 id 直接放行；已占用返回 False"""
    if not request_id:
        return True
    if request_id in _INFLIGHT_REQUESTS:
        return False
    _INFLIGHT_REQUESTS.add(request_id)
    return True


def _release_request_slot(request_id: str) -> None:
    if request_id:
        _INFLIGHT_REQUESTS.discard(request_id)


_HISTORY_ASSISTANT_MAX_CHARS = 600          # 非最新 assistant 回复的总上限（头+尾合计）
# 历史消息截断（token 浪费治理）：assistant 回复的有价值内容（草稿 prompt/规格文档）
# 已在工作台状态 JSON 里，旧回复全文重复注入毫无意义；user 消息是用户指令，保持全文。
_HISTORY_ASSISTANT_RECENT_MAX_CHARS = 2000  # 最新一条 assistant 回复的上限（紧邻决策与下一步计划最相关，保真度优先）
_HISTORY_HEAD_CHARS = 300                   # 旧回复保留头部（开头常是结论/总结）
_HISTORY_TAIL_CHARS = 300                   # 旧回复保留尾部（结尾常是下一步建议/待办决策）


def truncate_history(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """组装发给 LLM 的历史：assistant 超长消息截断，user 消息全文保留。

    截断策略（质量优化版）：
    - 最新一条 assistant 回复：保留前 2000 字（上一轮的决策/下一步与当前追问最相关）；
    - 更早的 assistant 回复：保留头 300 + 尾 300（旧版只留头部，
      会丢掉结尾的下一步建议与待确认事项）；
    - 截断处附说明，让模型知道完整内容可从工作台状态 JSON 获取。
    """
    last_assistant_idx = -1
    for i, m in enumerate(messages):
        if m.get("role", "user") == "assistant":
            last_assistant_idx = i

    out: List[Dict[str, Any]] = []
    for i, m in enumerate(messages):
        role = m.get("role", "user")
        content = m.get("content", "")
        if not isinstance(content, str):
            out.append({"role": role, "content": content})
            continue
        if role == "assistant":
            if i == last_assistant_idx:
                if len(content) > _HISTORY_ASSISTANT_RECENT_MAX_CHARS:
                    content = (
                        content[:_HISTORY_ASSISTANT_RECENT_MAX_CHARS]
                        + "\n…（最新回复超长已截断，完整内容见工作台状态 JSON 与项目文档）"
                    )
            elif len(content) > _HISTORY_ASSISTANT_MAX_CHARS:
                head = content[:_HISTORY_HEAD_CHARS]
                tail = content[-_HISTORY_TAIL_CHARS:]
                content = (
                    head
                    + "\n…（历史回复中部已省略，只保留首尾）…\n"
                    + tail
                    + "\n…（历史回复已截断，最新完整内容见工作台状态 JSON）"
                )
        out.append({"role": role, "content": content})
    return out


def _channel_supports_fc(provider_id: str) -> bool:
    """判断供应商的聊天通道是否支持 Function Calling。

    gemini-cli 协议走 AgyCliChatAdapter（无 FC），其他协议走 OpenAI 兼容
    chat adapter（支持 FC）。非 FC 通道调不了 read_* 工具，
    附件文档与选中 Skill 必须降级为全文直接注入，否则模型根本看不到。
    """
    try:
        cfg = get_provider_config(provider_id) or {}
    except Exception:
        cfg = {}
    return (cfg.get("protocol") or "openai") != "gemini-cli"


def _resolve_summary_adapter(body, candidates: List[tuple]) -> Optional[BaseChatAdapter]:
    """解析记忆摘要专用 adapter：摘要无需主模型能力，固定走便宜模型省 token。

    优先级：settings.memory_summary_model（"provider:model"）> fallback 链末位 > None（跟随主模型）。
    解析失败静默回落 None（摘要仍走主模型，功能不中断）。
    """
    try:
        spec = (settings.memory_summary_model or "").strip()
        if spec:
            prov, _, mdl = spec.partition(":")
            return _create_chat_adapter(prov or body.provider, mdl or body.model)
        if settings.model_fallback_enabled and len(candidates) > 1:
            cand_provider, cand_model = candidates[-1]
            return _create_chat_adapter(cand_provider, cand_model)
    except Exception as e:
        logger.warning(f"[ChatService] 记忆摘要模型解析失败，回落主模型: {e}")
    return None


def _create_chat_adapter(provider_id: str, model: str):
    """按供应商协议创建 chat adapter。

    Antigravity CLI（gemini-cli 协议）对齐画布行为：聊天走本机 agy CLI
    登录态，不走反代；model=auto 时不传 --model，由 agy 自行路由
    （曾硬路由到 custom-api 反代导致 400 model not register）。
    其他供应商维持原 OpenAI 兼容端点解析路径。
    """
    cfg = get_provider_config(provider_id)
    if cfg and cfg.get("protocol") == "gemini-cli":
        logger.info(f"[ChatService] Antigravity CLI 聊天走本机 agy: model={model}")
        return AgyCliChatAdapter(model=model)
    base_url, api_key, effective_model = resolve_openai_endpoint(provider_id, model)
    return AdapterFactory.get_or_create_chat_adapter(provider_id, base_url, api_key, effective_model)


def _build_meta_note(elapsed_secs: float, steps: int, applied: int) -> str:
    """生成消息耗时角标文案（与前端 finishStream 的 meta 格式一致），随消息持久化"""
    parts = [f"耗时 {elapsed_secs:.1f}s"]
    if steps > 1:
        parts.append(f"{steps} 轮")
    if applied > 0:
        parts.append(f"更新 {applied} 项")
    return " · ".join(parts)


async def stream_worker(body: Any, emit) -> None:
    """流式聊天的后台 worker（mock + 真实供应商）。

    Args:
        body: ChatRequest 实例
        emit: async callable(event_dict) 用于向队列推送 SSE 事件
    """
    t0 = time.monotonic()
    request_id = body.request_id or ""
    if not _acquire_request_slot(request_id):
        await emit({"type": SSE_ERROR, "detail": "相同请求正在处理中，请勿重复发送",
                    "error_code": "DUPLICATE_REQUEST"})
        return
    try:
        svc = StateManager.get_instance()
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
        # 非 FC 通道（如 agy）调不了 read_uploaded_doc：附件文档降级为全文直注
        attachment_note = (
            attachment_context(body.attachments, full_text=not _channel_supports_fc(body.provider))
            if body.attachments else ""
        )
        llm_user_text = f"{user_text}\n\n{attachment_note}" if attachment_note else user_text

        # Skill 写入文档：消息携带 Skill 引用块时（前端此时才传 skill_slug），
        # 记入当前项目 usedSkills，文档面板只展示已发送过的 Skill 文档。
        if body.skill_slug:
            async with svc.lock:
                svc.record_used_skill(body.skill_slug)

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
        await _real_stream(svc, executor, body, user_text, llm_user_text, llm_user_content, use_studio_context, emit, t0)

    except Exception as e:
        logger.exception(f"[ChatService] 流式处理异常: {e}")
        # VideoAgentError 携带 error_code 供前端 i18n 翻译；未知异常按 INTERNAL_ERROR
        code = getattr(e, "error_code", None) or "INTERNAL_ERROR"
        await emit({"type": SSE_ERROR, "detail": f"服务端异常: {e}", "error_code": code})
    finally:
        _release_request_slot(request_id)


def _resolve_selected_draft_media_config(svc, selected_draft_id: str, selected_type: str) -> tuple:
    """从选中草稿解析生图配置 (providerId, aspectRatio)。

    中间预览面板选中的草稿决定了 agent 生图时用哪个供应商和画面比例。
    """
    provider_id = ""
    aspect_ratio = ""
    if not selected_draft_id:
        return provider_id, aspect_ratio
    category = _TYPE_TO_CATEGORY.get(selected_type, selected_type)
    raw_state = svc.get_full_snapshot()
    for group in (raw_state.get(category) or []):
        if not isinstance(group, dict):
            continue
        for draft in (group.get("drafts") or []):
            if isinstance(draft, dict) and draft.get("id") == selected_draft_id:
                provider_id = draft.get("providerId", "") or ""
                aspect_ratio = draft.get("aspectRatio", "") or ""
                return provider_id, aspect_ratio
    return provider_id, aspect_ratio


# ---------- 模型 fallback 链 ----------

def _is_retryable_adapter_error(e: Exception) -> bool:
    """判定 AdapterError 是否为可切换备用模型重试的瞬时故障。

    优先使用结构化标记（P0-2）：AdapterError.retryable 由 Adapter 层在抛错时
    填充（5xx / 超时 / 连接失败 → True，4xx → False）；无标记的旧异常回退
    文案匹配。仅瞬时故障可重试，4xx（鉴权/参数错误）重试无意义。
    """
    flag = getattr(e, "retryable", None)
    if flag is not None:
        return bool(flag)
    msg = str(e)
    return (
        "HTTP 5" in msg
        or "流式请求失败" in msg
        or "请求失败" in msg
        or "超时" in msg
    )


def _fallback_candidates(provider_id: str, model: str) -> List[tuple]:
    """构建 fallback 候选链：主模型 → 同供应商其他 chat 模型 → 其他启用供应商的 chat 模型。

    总长度受 settings.model_fallback_max_candidates 限制；mock 供应商不入链。
    """
    limit = max(1, settings.model_fallback_max_candidates)
    candidates: List[tuple] = [(provider_id, model)]
    # 供应商未配置属于配置错误（非瞬时故障），不跨供应商切换
    if get_provider_config(provider_id) is None:
        return candidates[:limit]
    try:
        providers = load_merged_providers()
    except Exception:
        return candidates[:limit]
    current = next((p for p in providers if p.get("id") == provider_id), None)
    if current:
        for m in (current.get("chat_models") or []):
            if m and m != model:
                candidates.append((provider_id, m))
    for p in providers:
        if len(candidates) >= limit:
            break
        pid = p.get("id") or ""
        if not pid or pid == provider_id or not p.get("enabled", True):
            continue
        if is_mock_provider(pid):
            continue
        for m in (p.get("chat_models") or []):
            if m and (pid, m) not in candidates:
                candidates.append((pid, m))
                if len(candidates) >= limit:
                    break
    return candidates[:limit]


async def _real_stream(svc, executor, body, user_text, llm_user_text, llm_user_content, use_studio_context, emit, t0) -> None:
    """真实供应商的流式处理（含模型 fallback 链）。

    主模型遇 5xx/超时等瞬时故障且尚未执行任何操作时，自动切换备用模型重试
    （避免重复执行已落盘的操作）；成功时 done payload 携带 fallback_model 供前端标注。
    """
    history = truncate_history([
        {"role": m.get("role", "user"), "content": m.get("content", "")}
        for m in body.messages[-10:]
    ])

    # 短锁：绑定附件 + 附件文档存档 + 记录用户消息（仅一次，不随 fallback 重复）；
    # 状态 JSON 改为惰性构建器（P0）：多步循环每一轮重新构建，模型每轮看到最新状态
    async with svc.lock:
        if use_studio_context:
            bind_attachments(svc, body.attachments)
            store_uploaded_docs(svc, body.attachments)
            svc.add_chat_message("user", user_text)

    state_builder = (
        (lambda: svc.build_agent_context(body.asset_mode)) if use_studio_context else None
    )

    # --- 解析中间面板选中的生图 provider + 画面比例（注入 generate_image 工具用）---
    image_provider, image_aspect_ratio = _resolve_selected_draft_media_config(
        svc, body.selected_draft_id, body.selected_type
    )

    candidates = (
        _fallback_candidates(body.provider, body.model)
        if settings.model_fallback_enabled
        else [(body.provider, body.model)]
    )

    for idx, (cand_provider, cand_model) in enumerate(candidates):
        try:
            llm_adapter = _create_chat_adapter(cand_provider, cand_model)
        except GenerationError as e:
            logger.warning(f"[ChatService] fallback 候选 {cand_provider}/{cand_model} 端点解析失败: {e}")
            if idx == len(candidates) - 1:
                await _emit_stream_error(svc, body, e, emit, use_studio_context)
                return
            continue

        planner = Planner(
            state_manager=svc, llm_adapter=llm_adapter, tool_manager=ToolManager,
            executor_factory=StudioActionExecutor,
            summary_adapter=_resolve_summary_adapter(body, candidates),
        )
        planner_ctx = PlannerContext(
            history=history,
            selected_draft_id=body.selected_draft_id,
            selected_type=body.selected_type,
            state_builder=state_builder,
            degraded_state_builder=(
                (lambda: svc.build_agent_context_degraded(body.asset_mode)) if use_studio_context else None
            ),
            skill_name=body.skill_name or "",
            use_studio_context=use_studio_context,
            asset_mode=body.asset_mode,
            image_generation_provider=image_provider,
            image_generation_aspect_ratio=image_aspect_ratio,
        )

        applied_seen = False
        final_text = ""
        final_payload: Dict[str, Any] = {}
        try:
            async for event in planner.handle_message_stream(llm_user_content, planner_ctx):
                if event.type == "status":
                    await emit({"type": SSE_STATUS, "text": event.text})
                elif event.type == "delta":
                    await emit({"type": SSE_DELTA, "text": event.text})
                elif event.type == "actions_applied":
                    applied_seen = True
                    await emit({"type": SSE_STATUS, "text": event.text})
                elif event.type in ("reasoning_delta", "tool_started", "tool_finished"):
                    # 过程时间线事件透传（深度思考增量 / 工具开始与完成），
                    # 仅 UI 展示用，不进下次 LLM 上下文
                    await emit(event.payload or {"type": event.type, "text": event.text})
                elif event.type == "done":
                    final_payload = event.payload or {}
                    final_text = final_payload.get("text", "")
                elif event.type == "error":
                    # 透传上游结构化故障标记（P0-2）：保证 fallback 链判定不依赖文案
                    p = event.payload or {}
                    raise AdapterError(
                        event.text,
                        retryable=p.get("retryable"),
                        http_status=p.get("http_status"),
                    )
        except (GenerationError, AdapterError) as e:
            # 已执行过操作 → 不得重试（避免重复写入）；不可重试/候选用尽 → 报错
            if applied_seen or not _is_retryable_adapter_error(e) or idx == len(candidates) - 1:
                logger.warning(f"[ChatService] LLM 流式调用失败 ({cand_provider}/{cand_model}): {e}")
                await _emit_stream_error(svc, body, e, emit, use_studio_context)
                return
            next_model = candidates[idx + 1][1]
            logger.warning(
                f"[ChatService] 模型 {cand_model} 瞬时故障（{str(e)[:80]}），fallback 到 {next_model}"
            )
            await emit({"type": SSE_STATUS, "text": f"模型 {cand_model} 繁忙/异常，已切换 {next_model} 重试…"})
            continue

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
                        action_log=final_payload.get("action_log") or [],
                        trace=final_payload.get("trace") or {},
                    )
                # 文档完成卡片：独立条目持久化，刷新后可重建
                for doc_name in (final_payload.get("documents_written") or []):
                    svc.add_chat_message("agent", "", doc_card=doc_name)
                # 生图卡片随历史持久化（独立消息条目，与前端 finishStream 的两条消息结构一致，
                # 否则刷新页面后聊天记录里的图片卡片会丢失）
                image_urls = final_payload.get("image_urls") or []
                if image_urls:
                    svc.add_chat_message("agent", "", image_urls=image_urls)

        done_payload: Dict[str, Any] = {
            **final_payload,
            "state": svc.get_full_snapshot() if use_studio_context else None,
            "elapsed_ms": int((time.monotonic() - t0) * 1000),
        }
        if idx > 0:
            done_payload["fallback_model"] = cand_model
            # 降级显式告警：备用模型的产出质量可能不同于主模型，
            # 必须让用户可见（随消息持久化到 warnings），不做静默降级
            warnings = list(done_payload.get("warnings") or [])
            warnings.append(f"主模型瞬时故障，本次回复由备用模型 {cand_model} 生成，质量可能与主模型不同")
            done_payload["warnings"] = warnings
        await emit({"type": SSE_DONE, "payload": done_payload})
        return


async def _emit_stream_error(svc, body, e: Exception, emit, use_studio_context: bool) -> None:
    """流式失败统一出口：持久化错误消息 + 发 error 事件（透传上游原文）"""
    if use_studio_context:
        async with svc.lock:
            svc.add_chat_message("agent", f"[错误] {e}", model_name=body.model or "")
    await emit({"type": SSE_ERROR, "detail": str(e), "error_code": getattr(e, "error_code", "INTERNAL_ERROR")})


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

    # 请求幂等防护（P2）：同一 request_id 处理中时拒绝重复提交
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
    executor = StudioActionExecutor(
        svc,
        selected_draft_id=body.selected_draft_id,
        selected_type=body.selected_type,
    )

    use_studio_context = body.context_mode != "none"
    # 非 FC 通道（如 agy）调不了 read_uploaded_doc：附件文档降级为全文直注
    attachment_note = (
        attachment_context(body.attachments, full_text=not _channel_supports_fc(body.provider))
        if body.attachments else ""
    )
    llm_user_text = f"{user_text}\n\n{attachment_note}" if attachment_note else user_text

    # Skill 写入文档：同 stream_worker（仅消息携带 Skill 引用块时前端才传 slug）
    if body.skill_slug:
        async with svc.lock:
            svc.record_used_skill(body.skill_slug)

    # mock 路径
    if is_mock_provider(body.provider, body.model):
        async with svc.lock:
            if use_studio_context:
                bind_attachments(svc, body.attachments)
                svc.add_chat_message("user", user_text)
            raw_reply = mock_llm_reply(llm_user_text, svc.build_agent_context(body.asset_mode))
            actions = executor.parse_actions_from_reply(raw_reply)
            visible = executor.strip_action_blocks(raw_reply) or raw_reply
            applied = executor.execute(actions)
            if use_studio_context:
                svc.add_chat_message("agent", visible, model_name=body.model or "")
        return {
            "text": visible, "applied_actions": applied, "steps": 1,
            "warnings": ["当前为 mock 供应商，回复由本地规则生成，未调用真实 LLM"],
            "confirmation": "", "documents_written": executor.documents_written,
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

    async with svc.lock:
        if use_studio_context:
            bind_attachments(svc, body.attachments)
            store_uploaded_docs(svc, body.attachments)
            svc.add_chat_message("user", user_text)

    # 状态惰性构建器（P0）：多步循环每轮刷新
    state_builder = (
        (lambda: svc.build_agent_context(body.asset_mode)) if use_studio_context else None
    )

    # --- 解析中间面板选中的生图 provider + 画面比例 ---
    image_provider2, image_aspect_ratio2 = _resolve_selected_draft_media_config(
        svc, body.selected_draft_id, body.selected_type
    )

    planner_ctx = PlannerContext(
        history=history, selected_draft_id=body.selected_draft_id, selected_type=body.selected_type,
        state_builder=state_builder,
        degraded_state_builder=(
            (lambda: svc.build_agent_context_degraded(body.asset_mode)) if use_studio_context else None
        ),
        skill_name=body.skill_name or "",
        use_studio_context=use_studio_context, asset_mode=body.asset_mode,
        image_generation_provider=image_provider2,
        image_generation_aspect_ratio=image_aspect_ratio2,
    )

    # 非流式复用与 _real_stream 相同的 fallback 链：主模型瞬时故障（5xx/超时/连接失败）
    # 且尚未执行任何操作时，自动切换备用模型重试；已执行操作则不重试（避免重复落盘）
    candidates = (
        _fallback_candidates(body.provider, body.model)
        if settings.model_fallback_enabled
        else [(body.provider, body.model)]
    )
    result = None
    used_model = body.model
    last_err: Optional[Exception] = None
    for idx, (cand_provider, cand_model) in enumerate(candidates):
        try:
            llm_adapter = _create_chat_adapter(cand_provider, cand_model)
        except GenerationError as e:
            logger.warning(f"[ChatService] fallback 候选 {cand_provider}/{cand_model} 端点解析失败: {e}")
            last_err = e
            if idx == len(candidates) - 1:
                raise
            continue
        planner = Planner(
            state_manager=svc, llm_adapter=llm_adapter, tool_manager=ToolManager,
            executor_factory=StudioActionExecutor,
            summary_adapter=_resolve_summary_adapter(body, candidates),
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
            last_err = e
            if applied_seen or not _is_retryable_adapter_error(e) or idx == len(candidates) - 1:
                raise
            logger.warning(
                f"[ChatService] 模型 {cand_model} 瞬时故障（{str(e)[:80]}），"
                f"非流式 fallback 到 {candidates[idx + 1][1]}"
            )
            continue
    if result is None:  # 理论不可达（最后候选失败已 raise），防御兜底
        raise last_err or GenerationError("无可用聊天模型")

    # 降级显式告警（与流式路径一致）：备用模型产出必须让用户可见，不做静默降级
    if used_model != body.model and body.model:
        result.warnings.append(
            f"主模型瞬时故障，本次回复由备用模型 {used_model} 生成，质量可能与主模型不同"
        )

    if use_studio_context:
        async with svc.lock:
            if result.text:
                svc.add_chat_message(
                    "agent", result.text, model_name=used_model or "",
                    confirm=result.confirmation,
                    applied_actions=result.applied_actions,
                    action_log=result.action_log,
                )
            if result.image_urls:
                svc.add_chat_message("agent", "", image_urls=result.image_urls)

    return {
        "text": result.text, "applied_actions": result.applied_actions, "steps": result.steps,
        "warnings": result.warnings, "confirmation": result.confirmation,
        "documents_written": result.documents_written,
        "image_urls": result.image_urls,
        "state": svc.get_full_snapshot() if use_studio_context else None,
    }
