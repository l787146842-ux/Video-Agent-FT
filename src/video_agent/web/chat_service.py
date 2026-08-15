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
import re
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
from src.video_agent.web.provider_config import (
    get_provider_config,
    is_mock_provider,
    is_mock_provider_async,
    load_merged_providers,
    load_merged_providers_async,
)
from src.video_agent.web.sse import sse_event_generator  # noqa: F401  （B6 保留 sse.py 为正常模块；本行仅兼容旧导入路径）
from src.video_agent.state.manager import StateManager
from src.video_agent.core.planner import Planner, PlannerContext
from src.video_agent.core.sse_events import (
    SSE_ACTIONS_APPLIED,
    SSE_DELTA,
    SSE_DOC_WRITTEN,
    SSE_DONE,
    SSE_ERROR,
    SSE_GUIDANCE_INJECTED,
    SSE_MODEL_FALLBACK,
    SSE_STATUS,
)
from src.video_agent.memory import MemoryManager
from src.video_agent.exceptions import AdapterError, GenerationError, VideoAgentError
from src.video_agent.adapters.base_chat import BaseChatAdapter
from src.video_agent.adapters.factory import AdapterFactory
from src.video_agent.adapters.agy_cli import AgyCliChatAdapter
from src.video_agent.tools.manager import ToolManager
from src.video_agent.core.tracer import AgentTracer

__all__ = ["stream_worker", "non_stream_worker", "build_multimodal_content"]

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


def _resolve_skill_name_for_injection(
    skill_name: str, skill_slug: str, raw_state: Optional[Dict[str, Any]] = None,
    user_text: str = "",
) -> str:
    """Skill 全文硬注入的键名兜底：前端选中项（skill_name）优先；
    选中项为空但消息携带了 Skill 引用块（skill_slug）时，按 slug 解析出 Skill 名称，
    保证「随消息发送过的 Skill 必定全文注入」；两者皆空时先按消息文本匹配已注册 Skill
    （6666 事故：直接发 Skill 名也要能绑定），再回退项目 usedSkills 末位
    （7777 事故：后续轮次不带 Skill 导致执行器「未注册」）。
    """
    if skill_name:
        return skill_name
    if skill_slug:
        try:
            from src.video_agent.web import skill_docs as sd
            doc = sd.get_skill_doc(skill_slug)
            if doc:
                return str(doc.get("name") or skill_slug)
        except Exception as e:
            logger.warning(f"[ChatService] Skill slug({skill_slug}) 解析名称失败: {e}")
        return skill_slug
    from src.video_agent.skill_runtime.registry import (
        fallback_skill_from_state,
        match_skill_name_from_text,
    )

    text_match = match_skill_name_from_text(user_text)
    if text_match:
        return text_match
    return fallback_skill_from_state(raw_state)


def _build_prelude_notes(resolved_skill: str) -> List[tuple]:
    """前奏时间线（只登记真实发生的事件，8888 事故：不得用假操作冒充工具动作）。

    只保留「加载 Skill 流程基线」——它对应 prompt_builder 每轮真实注入当前 Skill 的
    <planner> 章节；「读取/存档上传文档」由 read_uploaded_doc 工具真实发生时记录，
    前奏不冒充读取。"""
    notes: List[tuple] = []
    if resolved_skill:
        notes.append(("system", f"加载 Skill「{resolved_skill}」流程规范进上下文"))
    return notes


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


def _summary_thinking_level() -> str:
    """摘要/压缩调用思考档位（B8 策略表化）：策略 summary 角色 > settings.aux_thinking_level。"""
    from src.video_agent.core import model_policy

    return model_policy.thinking_for("summary", getattr(settings, "aux_thinking_level", "") or "")


def _resolve_summary_adapter(body, candidates: List[tuple]) -> Optional[BaseChatAdapter]:
    """解析记忆摘要专用 adapter：摘要无需主模型能力，固定走便宜模型省 token。

    优先级（B8 策略表化）：模型策略表 summary 角色（provider:model）>
    settings.memory_summary_model > fallback 链末位 > None（跟随主模型）。
    解析失败静默回落 None（摘要仍走主模型，功能不中断）。
    """
    try:
        from src.video_agent.core import model_policy

        role = model_policy.resolve_role("summary")
        if role and role.get("model"):
            return _create_chat_adapter(role["provider"], role["model"])
        if role:
            return _create_chat_adapter(role["provider"], body.model)
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


def _record_active_skill(svc, body: Any) -> None:
    """B4/F30：当前技能三本账收敛——本轮实际激活了 Skill（skill_name/skill_slug
    可解析到已注册 Skill）就记入项目 usedSkills，不再依赖消息携带 chip；
    usedSkills 是唯一持久事实源（localStorage 仅作跨会话记忆）。"""
    name = str(getattr(body, "skill_name", "") or "").strip()
    slug = str(getattr(body, "skill_slug", "") or "").strip()
    if not name and not slug:
        return
    if not slug:
        try:
            from src.video_agent.web import skill_docs as sd

            for d in sd.list_skill_docs():
                if str(d.get("name") or "") == name:
                    slug = str(d.get("slug") or "")
                    break
        except Exception as e:
            logger.warning(f"[ChatService] 按名称解析 Skill slug 失败: {e}")
    if slug:
        svc.record_used_skill(slug)


async def _prepare_chat_opening(svc, body: Any, user_text: str, use_studio_context: bool) -> str:
    """开场公共编排（814F2：流式/非流式双路径单一实现，消除双份复制）。

    暂停闭环（消费上轮暂停态）+ 规格定稿/向导消费 + 附件降级注入，
    返回拼好的 LLM 用户消息文本。调用方需保证同一请求只调一次。
    """
    pending_confirm_note = ""
    spec_finalize_note = ""
    spec_wizard_note = ""
    if use_studio_context:
        async with svc.lock:
            pending_confirm_note = _consume_pending_confirmation(svc)
            spec_finalize_note = _finalize_spec_params(svc, user_text)
            spec_wizard_note = _consume_spec_wizard(svc, user_text)
    # 非 FC 通道（如 agy）调不了 read_uploaded_doc：附件文档降级为全文直注
    attachment_note = (
        attachment_context(body.attachments, full_text=not _channel_supports_fc(body.provider))
        if body.attachments else ""
    )
    llm_user_text = user_text + pending_confirm_note + spec_finalize_note + spec_wizard_note
    if attachment_note:
        llm_user_text = f"{llm_user_text}\n\n{attachment_note}"
    return llm_user_text


def _store_gate_overrides(svc, overrides) -> None:
    """814F7（§2.4）：把用户「本次放行」的 rule_id 列表写入 interaction，
    由本次请求的 Planner 消费一次即清除（单次生效、全程留痕）。
    调用方需持有 svc.lock。"""
    cleaned = [r for r in (overrides or []) if isinstance(r, str) and r.strip()]
    if not cleaned:
        return
    interaction = svc.state_dict.setdefault("interaction", {})
    interaction["gate_overrides"] = cleaned
    svc.save()
    logger.info(f"[GateOverride] 已登记 {len(cleaned)} 条一次性闸机豁免: {cleaned}")


# 会话级 compaction（814R4 恢复）：压缩后仍完整保留的最近消息条数
_HISTORY_COMPACT_KEEP = 4


async def _maybe_compact_history(
    history: List[Dict[str, Any]], svc, adapter,
) -> List[Dict[str, Any]]:
    """会话级 compaction（814R4 恢复）：历史超阈值时用便宜模型把较早消息压成摘要。

    对齐 Anthropic compaction 实践：保留决策与约束、丢弃冗余过程；
    摘要按对话消息数缓存于 interaction.session_summary（消息数变化即失效重建），
    失败静默回落原 history（compaction 是优化不是前置条件）。"""
    threshold = int(getattr(settings, "history_compact_threshold", 0) or 0)
    if threshold <= 0 or adapter is None or len(history) < threshold:
        return history
    interaction = svc.state_dict.setdefault("interaction", {})
    cached = interaction.get("session_summary") or {}
    msg_count = len(svc.get_chat_messages())
    summary = ""
    if cached.get("count") == msg_count and str(cached.get("text") or "").strip():
        summary = str(cached["text"])
    else:
        keep = _HISTORY_COMPACT_KEEP
        older = history[:-keep] if len(history) > keep else []
        if not older:
            return history
        dialog = "\n".join(
            f"{'user' if m.get('role') == 'user' else 'agent'}: {str(m.get('content', ''))[:300]}"
            for m in older[-20:]
        )
        from src.video_agent.utils.prompts import load_prompt_section

        tpl = load_prompt_section("planner/session_compact.md", "TEMPLATE")
        prompt = tpl.replace("{{dialog}}", dialog) if tpl else (
            "请把以下对话压缩为不超过 300 字的摘要，保留决策与约束：\n" + dialog)
        try:
            resp = await adapter.chat(
                [
                    {"role": "system", "content": "你是会话摘要助手。"},
                    {"role": "user", "content": prompt},
                ],
                timeout=settings.llm_timeout,
                thinking_level=_summary_thinking_level(),
            )
            summary = (resp.content or "").strip()
        except Exception as e:
            logger.warning(f"[ChatService] 会话 compaction 失败，保留原 history: {e}")
            return history
        if not summary:
            return history
        interaction["session_summary"] = {"count": msg_count, "text": summary[:1000]}
        svc.save_debounced()
        logger.info(f"[ChatService] 会话 compaction：{len(history)} 条 history 压缩为摘要+{keep} 条")
    return [
        {"role": "user", "content": f"（会话摘要，较早对话已压缩；工作台状态 JSON 仍是最新事实源）{summary}"},
    ] + history[-_HISTORY_COMPACT_KEEP:]


def _consume_pending_confirmation(svc, user_text: str = "") -> str:
    """消费「等待确认」暂停态：用户的新消息即是对上一轮暂停的回应。

    暂停态只写不清会让模型永远停在上一阶段；只清不带则模型看不到
    「用户已确认」的信号，两者都会导致从头重复同一套操作（读同一文档→
    写同一文档→再次请求确认）。此处同时完成：清除状态 + 把暂停说明
    以系统提示形式附在本轮用户消息后，返回附加提示（无暂停时返回空串）。
    调用方需持有 svc.lock。
    """
    interaction = svc.state_dict.get("interaction") or {}
    pause_kind = interaction.get("pending_pause_kind")
    if pause_kind == "collect":
        # 规格收集暂停的回应：视为已进入收集环节（后续由 _consume_spec_wizard 拼装）
        interaction["spec_collected"] = True
    # 暂停语义标记（summary/spec/collect）随回应消费清除，避免残留影响下一轮
    interaction.pop("pending_pause_kind", None)
    # 故事板待确认窗口（步骤3→步骤4 分界）：不依赖 awaiting_confirmation，
    # 用户任何新消息到达即视为已审阅故事板，解除提示词写入封锁
    if interaction.get("storyboard_pending"):
        interaction["storyboard_pending"] = False
        svc.save()
    # 确认闭环：上一轮展示过提示词草案（drafts_presented）且用户新消息到达，
    # 将未被重写过的草稿晋升为「已确认」（生成闸的前置条件）；
    # 期间被重写的草稿 tag 已在写入时重置，不会被误晋升
    presented = [d for d in (interaction.get("drafts_presented") or []) if d]
    if presented:
        promoted = 0
        presented_set = set(presented)
        for cat in ("keyElements", "shots", "audioItems"):
            for group in svc.state_dict.get(cat, []) or []:
                for draft in group.get("drafts", []) or []:
                    tag = str(draft.get("tag") or "").strip()
                    if draft.get("id") in presented_set and tag in ("", "Agent", "草稿", "推荐"):
                        draft["tag"] = "已确认"
                        promoted += 1
        interaction["drafts_presented"] = []
        svc.save()
        if promoted:
            logger.info(f"[ConfirmFlow] 用户回应到达：{promoted} 个已展示的 Prompt Draft 晋升为「已确认」")
    # 晋升兜底（8888 事故）：处于暂停态但 presented 记录缺失（记录链路异常或
    # 草稿经未记录路径写入）时，用户对暂停的回应即视为对当前带提示词草稿的确认，
    # 否则 tag 永远停在 Agent，生成闸反复拦截造成「确认了也出不了图」
    if not presented and interaction.get("awaiting_confirmation"):
        fallback_promoted = 0
        for cat in ("keyElements", "shots", "audioItems"):
            for group in svc.state_dict.get(cat, []) or []:
                for draft in group.get("drafts", []) or []:
                    tag = str(draft.get("tag") or "").strip()
                    if (draft.get("prompt") or "").strip() and tag in ("", "Agent", "草稿", "推荐"):
                        draft["tag"] = "已确认"
                        fallback_promoted += 1
        if fallback_promoted:
            svc.save()
            logger.info(f"[ConfirmFlow] presented 缺失兜底：{fallback_promoted} 个带提示词草稿晋升为「已确认」")
    if not interaction.get("awaiting_confirmation"):
        return ""
    paused_msg = str(interaction.get("confirmation_message") or "")[:300]
    interaction["awaiting_confirmation"] = False
    interaction["confirmation_message"] = ""
    svc.save()
    return (
        "\n\n（系统提示：上一轮已通过 request_confirmation/workflow_pause 暂停等待确认，"
        f"暂停内容：{paused_msg}。本条消息即对该暂停的回应：表示确认时，先把当前阶段产出物做完再暂停"
        "（如规格选择收齐后先写入规格文档，再进入下一阶段）；已完成的步骤（已读文档/已写规格）不必重复；"
        "提出修改意见时按新要求执行，完成后重新请求确认。）"
    )


def _consume_spec_wizard(svc, user_text: str) -> str:
    """规格向导消费（6666/1111 事故）：用户回应是规格收集暂停的候选项时，
    机械落盘为规格文档（系统拼装，模型不手写），返回附加系统提示。

    仅当：项目尚无规格文档 + 用户回应含可解析的制作参数/渠道选择或明确确认意图。
    调用方需持有 svc.lock。
    """
    import re
    from datetime import datetime, timezone

    from src.video_agent.core import prompt_gates
    from src.video_agent.utils import gen_id

    state = svc.state_dict
    if prompt_gates.has_spec_document(state):
        return ""
    text = str(user_text or "").strip()
    if not text:
        return ""
    used = state.get("usedSkills") or []
    skill_name = str(used[-1] or "") if used else ""
    # Skill 软维度（向导逐行回传格式「键：值」；出图/出视频渠道、图片分辨率、
    # 视频分辨率、分镜最大时长由顶部「全局设置」唯一提供，规格文档不再承载）
    dims = prompt_gates.skill_spec_dimensions(skill_name)
    selections = prompt_gates.parse_dim_selections(text, dims)
    # 用户可能整页点过占位卡（「维度：（待定）」）后发送：也算回应了向导，
    # 不能因此不落盘（否则 document_write 被拒 → 再次接管 → 死循环）
    responded = bool(selections) or any(
        re.search(re.escape(dim) + r"\s*[:：]", text) for dim in dims
    )
    if not responded:
        return ""
    # 未选维度用模型出题的候选首项兜底；无候选时以「（待定）」占位，
    # 保证规格文档维度与 Skill 声明完全一致（模型不能增删维度）
    model_filled: Dict[str, str] = {}
    cands = ((state.get("interaction") or {}).get("spec_soft_candidates") or {})
    for dim in dims:
        vals = cands.get(dim) or []
        if dim not in selections:
            model_filled[dim] = str(vals[0]) if vals else prompt_gates._PLACEHOLDER_DIM_VALUE
    content = prompt_gates.assemble_spec_doc(
        skill_name, selections, model_filled=model_filled,
    )
    if not content.strip():
        return ""
    docs = state.setdefault("documents", [])
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    name = "Final_Video_Spec.md"
    for d in docs:
        if d.get("name") == name:
            d["content"] = content
            d["updated_at"] = now
            break
    else:
        docs.insert(0, {
            "id": gen_id("doc"), "name": name, "content": content,
            "created_at": now, "updated_at": now,
        })
    inter = state.setdefault("interaction", {})
    inter["spec_collected"] = True
    # 8888 二轮：机械落盘也发文档卡片（持久化消息条 + 收尾快照携带），
    # 否则用户永远看不到规格卡
    svc.add_chat_message("agent", "", doc_card=name)
    svc.save()
    logger.info("[SpecWizard] 用户选择已机械落盘为规格文档 Final_Video_Spec.md")
    return (
        "\n\n（系统：已按你的选择拼装并写入 Final_Video_Spec.md 规格文档；"
        "接下来请按 Skill 流程开始拆分关键元素，并暂停等用户确认拆分方案。）"
    )


def _finalize_spec_params(svc, user_text: str) -> str:
    """规格暂停回应定稿（1111 事故）：summary 暂停的「确认」不得定稿规格；
    spec 暂停的「确认」按展示值定稿；显式选择（分辨率/时长）任意情况下生效。"""
    from src.video_agent.core import prompt_gates

    inter = svc.state_dict.get("interaction") or {}
    if inter.get("pending_pause_kind") == "summary":
        return ""
    spec = None
    for d in svc.state_dict.get("documents") or []:
        if prompt_gates.is_spec_doc_name(str(d.get("name") or "")):
            spec = d
            break
    if spec is None:
        return ""
    allow_confirm = inter.get("pending_pause_kind") == "spec"
    new_content, applied = prompt_gates.apply_spec_param_selections(
        str(spec.get("content") or ""),
        str(user_text or ""),
        allow_confirm_intent=allow_confirm,
    )
    if not applied:
        return ""
    spec["content"] = new_content
    svc.save()
    return "（系统：已按你的选择/确认定稿规格参数：" + "、".join(applied[:6]) + "）"


def _compact_card_enumeration(text: str) -> str:
    """把「N 组 M 卡（名称）：…」式逐卡枚举压缩为一行（8888 事故：正文逐卡罗列
    既耗 token 又撑长卡片）。少于 3 行枚举不触发。"""
    import re

    text = str(text or "")
    line_re = re.compile(r"(?m)^\s*-\s*\*\*\d+\s*组\s*\d+\s*卡（[^）]*）\*\*：.*$")
    matches = list(line_re.finditer(text))
    if len(matches) < 3:
        return text
    # 保留首行前的引导语与末行后的收尾（如「请在左侧故事板审阅」）
    head = text[:matches[0].start()]
    tail = text[matches[-1].end():]
    return (
        head.rstrip()
        + "\n- **逐卡明细已写入左侧故事板**（详见左侧草稿卡，正文不再逐卡罗列）。\n"
        + tail.lstrip()
    )


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

    pending_injector（B0/F2）：可选 callable → List[{id, text}]，轮间引导注入器，
    由后台任务路径装配（agent_task_manager.drain_pending_guidance）。"""
    # 铁律文档每轮确保存在（宪法 D2）：项目级生产契约唯一表述源，
    # 真实聊天/任务路径同样生效，不能只在 mock 路径创建
    from src.video_agent.core.spec_rules import ensure_iron_rules_doc
    try:
        ensure_iron_rules_doc(svc.state_dict)
    except Exception:
        pass

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
    # 开场公共编排（814F2）：暂停闭环 + 规格定稿/向导 + 附件降级注入
    llm_user_text = await _prepare_chat_opening(svc, body, user_text, use_studio_context)

    # 会话层一次性豁免（814F7）：随消息登记，Planner 本次消费
    if getattr(body, "gate_overrides", None) and use_studio_context:
        async with svc.lock:
            _store_gate_overrides(svc, body.gate_overrides)

    # Skill 写入文档（B4/F30）：本轮激活了 Skill 即记入当前项目 usedSkills
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
    不会把旧项目状态写进新项目（7777 事故根因之一）。
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
    svc, token = StateManager.create_task_bound(project_id, workspace_dir)
    try:
        async def emit(event: Dict[str, Any]) -> None:
            tm.emit(task_id, event)

        # B0/F2 恢复：轮间引导注入器——注册到本任务的排队消息逐轮被消费
        # （agent_loop 第 2 轮起调用），注入成功即 guidance_injected 事件下发。
        def pending_injector() -> List[Dict[str, Any]]:
            return tm.drain_pending_guidance(task_id)

        await _stream_worker_impl(body, svc, emit, pending_injector=pending_injector)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.exception(f"[AgentTask] {task_id} 处理异常: {e}")
        tm.emit(task_id, {
            "type": SSE_ERROR,
            "detail": f"服务端异常: {e}",
            "error_code": getattr(e, "error_code", None) or "INTERNAL_ERROR",
        })
    finally:
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
                provider_id = draft.get("providerId", "") or ""
                aspect_ratio = draft.get("aspectRatio", "") or ""
                return provider_id or settings.default_image_provider_id, aspect_ratio
    return settings.default_image_provider_id, aspect_ratio


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


async def _fallback_candidates(provider_id: str, model: str) -> List[tuple]:
    """构建 fallback 候选链（7777 二轮新语义）：同模型跨厂商，模型永不换。

    主 (provider, model) → 其他启用供应商中明确在 chat_models 里列出
    同名模型的供应商。模型列表为空的供应商无法验证是否提供该模型，不入链；
    mock 供应商不入链；总长度受 settings.model_fallback_max_candidates 限制。
    """
    limit = max(1, settings.model_fallback_max_candidates)
    candidates: List[tuple] = [(provider_id, model)]
    if not str(model or "").strip():
        return candidates[:limit]
    if await is_mock_provider_async(provider_id, model):
        return candidates[:limit]
    try:
        providers = await load_merged_providers_async()
    except Exception:
        return candidates[:limit]
    for p in providers:
        if len(candidates) >= limit:
            break
        pid = p.get("id") or ""
        if not pid or pid == provider_id or not p.get("enabled", True):
            continue
        if await is_mock_provider_async(pid):
            continue
        models = [str(m or "").strip() for m in (p.get("chat_models") or [])]
        if model in models and (pid, model) not in candidates:
            candidates.append((pid, model))
    return candidates[:limit]


def _fallback_switch_payload(candidates: List[tuple], idx: int) -> Dict[str, str]:
    """降级事件应下发的 (provider, model) —— 实际生效的下一候选（B0/F4 修正）。

    此前误发失败方供应商（cand_provider），同模型跨厂商降级时前端选择器跳转失效。"""
    nxt = candidates[idx + 1]
    return {"provider": nxt[0], "model": nxt[1]}


async def _real_stream(svc, executor, body, user_text, llm_user_text, llm_user_content, use_studio_context, emit, t0, pending_injector=None) -> None:
    """真实供应商的流式处理（含模型 fallback 链）。

    主模型遇 5xx/超时等瞬时故障且尚未执行任何操作时，自动切换备用模型重试
    （避免重复执行已落盘的操作）；成功时 done payload 携带 fallback_model 供前端标注。
    pending_injector（B0/F2）：轮间引导注入器，经 PlannerContext 传入循环。
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
            svc.add_chat_message(
                "user", user_text,
                doc_blocks=getattr(body, "doc_blocks", None) or None,
                skill_blocks=getattr(body, "skill_blocks", None) or None,
            )

    state_builder = (
        (lambda: svc.build_agent_context(body.asset_mode)) if use_studio_context else None
    )

    # --- 解析中间面板选中的生图 provider + 画面比例（注入 generate_image 工具用）---
    image_provider, image_aspect_ratio = _resolve_selected_draft_media_config(
        svc, body.selected_draft_id, body.selected_type
    )

    candidates = (
        await _fallback_candidates(body.provider, body.model)
        if settings.model_fallback_enabled
        else [(body.provider, body.model)]
    )
    # 会话级 compaction（814R4 恢复；B5/F33：预热后台——便宜模型摘要与
    # fallback 候选的 adapter 创建/端点解析并行，首 token 不被摘要往返阻塞；
    # 命中缓存时任务即刻完成，语义与同步等待完全一致）
    summary_adapter = _resolve_summary_adapter(body, candidates)
    _compact_task = asyncio.create_task(_maybe_compact_history(history, svc, summary_adapter))

    for idx, (cand_provider, cand_model) in enumerate(candidates):
        try:
            llm_adapter = _create_chat_adapter(cand_provider, cand_model)
        except GenerationError as e:
            logger.warning(f"[ChatService] fallback 候选 {cand_provider}/{cand_model} 端点解析失败: {e}")
            if idx == len(candidates) - 1:
                if _compact_task is not None and not _compact_task.done():
                    _compact_task.cancel()
                await _emit_stream_error(svc, body, e, emit, use_studio_context)
                return
            continue
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
            prelude_notes=prelude_notes,
            use_studio_context=use_studio_context,
            # 814R1 恢复：非 FC 通道（如 agy CLI）注入 text_actions.md 文本协议全文
            text_protocol=not _channel_supports_fc(body.provider),
            asset_mode=body.asset_mode,
            image_generation_provider=image_provider,
            image_generation_aspect_ratio=image_aspect_ratio,
            user_id=getattr(body, "user_id", "") or "",
            # 814H7：会话级推理档位（对话栏选择器下发；""=模型原生）
            thinking_level=getattr(body, "thinking_level", "") or "",
            # B0/F2：轮间引导注入器（任务式传输路径；非任务路径为 None）
            pending_injector=pending_injector,
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
                elif event.type in (
                    "reasoning_delta", "tool_started", "tool_finished", SSE_GUIDANCE_INJECTED, SSE_DOC_WRITTEN,
                ):
                    # 过程时间线事件透传（深度思考增量 / 工具开始与完成 / 文档即显 / 引导注入），
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
                f"[ChatService] 模型 {cand_model} 瞬时故障（{str(e)[:80]}），fallback 到 {candidates[idx + 1][0]}/{next_model}"
            )
            await emit({"type": SSE_STATUS, "text": f"模型 {cand_model} 繁忙/异常，已切换 {next_model} 重试…"})
            # 降级即时联动（7777）：切换时刻就下发，前端立即把选择器跳到实际生效的组合。
            # B0/F4 修正：provider 必须为「下一候选」的供应商（同模型跨厂商降级时
            # 真正变化的是厂商），此前误发失败方供应商导致前端跳转失效
            AgentTracer.get_instance().record_fallback(next_provider, next_model)
            await emit({"type": SSE_MODEL_FALLBACK, **_fallback_switch_payload(candidates, idx)})
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
                        confirm_options=final_payload.get("confirmation_options") or None,
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
    text = _friendly_stream_error_text(e)
    if use_studio_context:
        async with svc.lock:
            # B2/F22：错误前缀统一为 ⚠️（与前端 streamError 渲染一致，刷新后不跳变）
            svc.add_chat_message("agent", f"⚠️ {text}", model_name=body.model or "")
    await emit({"type": SSE_ERROR, "detail": text, "error_code": getattr(e, "error_code", "INTERNAL_ERROR")})


def _friendly_stream_error_text(e: Exception) -> str:
    """上游错误人话翻译（2222 反馈：裸 JSON 报错看不懂）。

    预扣费额度不足等常见上游故障给出可操作提示；其余错误保持原文透传。
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
            "请为上游账户充值，或在 API 设置页切换其他供应商/模型后重试。"
        )
    return msg


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
    # 铁律文档每轮确保存在（宪法 D2），非流式路径同样生效
    from src.video_agent.core.spec_rules import ensure_iron_rules_doc
    try:
        ensure_iron_rules_doc(svc.state_dict)
    except Exception:
        pass
    executor = StudioActionExecutor(
        svc,
        selected_draft_id=body.selected_draft_id,
        selected_type=body.selected_type,
    )

    use_studio_context = body.context_mode != "none"
    # 开场公共编排（814F2）：同流式路径（暂停闭环 + 规格定稿/向导 + 附件降级）
    llm_user_text = await _prepare_chat_opening(svc, body, user_text, use_studio_context)

    # 会话层一次性豁免（814F7）：同流式路径
    if getattr(body, "gate_overrides", None) and use_studio_context:
        async with svc.lock:
            _store_gate_overrides(svc, body.gate_overrides)

    # Skill 写入文档（B4/F30）：同 stream_worker——本轮激活了 Skill 即记入 usedSkills
    async with svc.lock:
        _record_active_skill(svc, body)

    # mock 路径
    if is_mock_provider(body.provider, body.model):
        async with svc.lock:
            if use_studio_context:
                bind_attachments(svc, body.attachments)
                svc.add_chat_message(
                    "user", user_text,
                    doc_blocks=getattr(body, "doc_blocks", None) or None,
                    skill_blocks=getattr(body, "skill_blocks", None) or None,
                )
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
            svc.add_chat_message(
                "user", user_text,
                doc_blocks=getattr(body, "doc_blocks", None) or None,
                skill_blocks=getattr(body, "skill_blocks", None) or None,
            )

    # 状态惰性构建器（P0）：多步循环每轮刷新
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
        prelude_notes=prelude_notes,
        # 814R1 恢复：非 FC 通道（如 agy CLI）注入 text_actions.md 文本协议全文
        text_protocol=not _channel_supports_fc(body.provider),
        use_studio_context=use_studio_context, asset_mode=body.asset_mode,
        image_generation_provider=image_provider2,
        image_generation_aspect_ratio=image_aspect_ratio2,
        user_id=getattr(body, "user_id", "") or "",
        thinking_level=getattr(body, "thinking_level", "") or "",
    )

    # 非流式复用与 _real_stream 相同的 fallback 链：主模型瞬时故障（5xx/超时/连接失败）
    # 且尚未执行任何操作时，自动切换备用模型重试；已执行操作则不重试（避免重复落盘）
    candidates = (
        await _fallback_candidates(body.provider, body.model)
        if settings.model_fallback_enabled
        else [(body.provider, body.model)]
    )
    # 会话级 compaction（814R4 恢复；B5/F33：同流式路径——预热后台）
    summary_adapter = _resolve_summary_adapter(body, candidates)
    _compact_task = asyncio.create_task(_maybe_compact_history(history, svc, summary_adapter))
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
                if _compact_task is not None and not _compact_task.done():
                    _compact_task.cancel()
                raise
            continue
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
                    confirm_options=result.confirmation_options or None,
                )
            if result.image_urls:
                svc.add_chat_message("agent", "", image_urls=result.image_urls)

    return {
        "text": result.text, "applied_actions": result.applied_actions, "steps": result.steps,
        "warnings": result.warnings, "confirmation": result.confirmation,
        "documents_written": result.documents_written,
        "image_urls": result.image_urls,
        "state": svc.get_full_snapshot() if use_studio_context else None,
        "memory_hits": getattr(planner_ctx, "memory_hits", None) or [],
    }
