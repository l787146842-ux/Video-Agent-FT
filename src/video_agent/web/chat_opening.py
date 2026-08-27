"""开场编排域：请求幂等/历史截断/技能解析/暂停闭环消费前的拼装。"""
from __future__ import annotations

import asyncio
import re
import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    # 类型收窄引用：仅标注不做运行期校验，防循环导入
    from src.video_agent.web.routes.agent import ChatRequest

from loguru import logger

from src.video_agent.core.action_executor import StateOperationExecutor
from src.video_agent.config import settings
from src.video_agent.web.attachments import bind_attachments, attachment_context, store_uploaded_docs
from src.video_agent.web.generation import resolve_openai_endpoint
from src.video_agent.web.multimodal_builder import (
    build_multimodal_content,
)
from src.video_agent.core.provider_config import (
    get_provider_config,
)
from src.video_agent.state.manager import StateManager
from src.video_agent.core import prompt_gates
from src.video_agent.core.planner import Planner, PlannerContext
from src.video_agent.exceptions import AdapterError, GenerationError, VideoAgentError
from src.video_agent.adapters.base_chat import BaseChatAdapter
from src.video_agent.adapters.factory import AdapterFactory
from src.video_agent.tools.manager import ToolManager
from src.video_agent.core.tracer import AgentTracer

__all__ = ["build_multimodal_content"]

from src.video_agent.web.chat_consume import (
    _consume_pending_confirmation,
    _consume_spec_wizard,
    _finalize_spec_params,
)


# 请求幂等防护：同一 request_id 正在处理中时拒绝重复提交，
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
    - 最新一条 assistant 回复：保留前 2000 字（先前轮次的决策/下一步与当前追问最相关）；
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
    （直接发 Skill 名也要能绑定），再回退项目 usedSkills 末位
    （后续轮次不带 Skill 导致执行器「未注册」）。
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
    """前奏时间线（只登记真实发生的事件，不得用假操作冒充工具动作）。

    只保留「加载 Skill 流程基线」——它对应 prompt_builder 每轮真实注入当前 Skill 的
    <planner> 章节；「读取/存档上传文档」由 read_uploaded_doc 工具真实发生时记录，
    前奏不冒充读取。"""
    notes: List[tuple] = []
    if resolved_skill:
        notes.append(("system", f"加载 Skill「{resolved_skill}」流程规范进上下文"))
    return notes


def _resolve_summary_adapter(body, candidates: List[tuple]) -> Optional[BaseChatAdapter]:
    """解析会话压缩摘要专用 adapter：摘要无需主模型能力，固定走便宜模型省 token。

    优先级（策略表化）：模型策略表 summary 角色（provider:model）>
    fallback 链末位 > None（跟随主模型）。
    解析失败静默回落 None（摘要仍走主模型，功能不中断）。
    """
    try:
        from src.video_agent.core import model_policy

        role = model_policy.resolve_role("summary")
        if role and role.get("model"):
            return _create_chat_adapter(role["provider"], role["model"])
        if role:
            return _create_chat_adapter(role["provider"], body.model)
        if settings.model_fallback_enabled and len(candidates) > 1:
            cand_provider, cand_model = candidates[-1]
            return _create_chat_adapter(cand_provider, cand_model)
    except Exception as e:
        logger.warning(f"[ChatService] 压缩摘要模型解析失败，回落主模型: {e}")
    return None


def _create_chat_adapter(provider_id: str, model: str):
    """按供应商协议创建 chat adapter。

    CLI 协议仅保留生图职能；选中 CLI 供应商聊天直接报
    人话错误（错误分层气泡展示）。
    """
    cfg = get_provider_config(provider_id)
    if cfg and cfg.get("protocol") in ("gemini-cli", "codex", "jimeng"):
        raise AdapterError(
            f"供应商「{provider_id}」是 CLI 通道，不支持聊天（仅可用于生图）；"
            "请在对话栏改用 OpenAI 兼容供应商的模型"
        )
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


def _record_active_skill(svc, body: ChatRequest) -> None:
    """当前技能三本账收敛——本轮实际激活了 Skill（skill_name/skill_slug
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


async def _prepare_chat_opening(svc, body: ChatRequest, user_text: str, use_studio_context: bool):
    """开场公共编排（流式/非流式双路径单一实现，消除双份复制）。

    暂停闭环（消费上轮暂停态）+ 规格定稿/向导消费 + 附件降级注入，
    返回 (拼好的 LLM 用户消息文本, 轮始客观推进信号, 向导落盘文档名)。
    信号供输入类 decision 消费与闸预检分诊（runtime 不据此自主行动）；
    仅流程推进轮（暂停消费/向导回应/继续选项点选/带附件）产生。
    落盘文档名供调用方于用户消息后投影文档卡（提交结果同源）。
    调用方需保证同一请求只调一次。
    """
    pending_confirm_note = ""
    spec_finalize_note = ""
    spec_wizard_note = ""
    wiz_doc = ""
    pause_value = str((getattr(body, "pause_response", None) or {}).get("value") or "")
    if use_studio_context:
        async with svc.lock:
            # 三通道分离 C：点选回携 value 传入，命中系统继续选项时机械生成下一步指令；
            # 三态消费（ADR-0006）：用户原文与结构化回携同传，供
            # accept/decline/cancel-supersede 分类与 trace 留痕
            _pr = getattr(body, "pause_response", None) or {}
            pending_confirm_note = _consume_pending_confirmation(
                svc, user_text, pause_value=str(_pr.get("value") or ""),
                pause_response=_pr)
            spec_finalize_note = _finalize_spec_params(svc, user_text)
            spec_wizard_note, wiz_doc = _consume_spec_wizard(svc, user_text)
    # 聊天通道均为 FC，附件统一走清单+read_uploaded_doc 渐进式披露
    attachment_note = (
        attachment_context(body.attachments) if body.attachments else ""
    )
    llm_user_text = user_text + pending_confirm_note + spec_finalize_note + spec_wizard_note
    if attachment_note:
        llm_user_text = f"{llm_user_text}\n\n{attachment_note}"
    # 轮始客观推进信号（零语料：只认消费结果/附件/继续选项行格式）
    if pending_confirm_note:
        advance_signal = "pause"
    elif spec_wizard_note:
        advance_signal = "wizard"
    elif prompt_gates.is_flow_continue_value(pause_value):
        advance_signal = "continue"
    elif body.attachments:
        advance_signal = "attachment"
    else:
        advance_signal = ""
    return llm_user_text, advance_signal, wiz_doc


def _store_gate_overrides(svc, overrides) -> None:
    """把用户「本次放行」的 rule_id 列表写入 interaction，
    由本次请求的 Planner 消费一次即清除（单次生效、全程留痕）。
    调用方需持有 svc.lock。"""
    cleaned = [r for r in (overrides or []) if isinstance(r, str) and r.strip()]
    if not cleaned:
        return
    interaction = svc.state_dict.setdefault("interaction", {})
    interaction["gate_overrides"] = cleaned
    svc.save()
    logger.info(f"[GateOverride] 已登记 {len(cleaned)} 条一次性闸机豁免: {cleaned}")
