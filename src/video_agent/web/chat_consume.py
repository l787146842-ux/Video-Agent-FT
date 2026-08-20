"""消费/压缩域（自 chat_service.py 切出）：会话 compaction/暂停态消费/规格向导消费/卡片枚举压缩。"""
import asyncio
import re
import time
from typing import Any, Dict, List, Optional

from loguru import logger

from src.video_agent.web.action_executor import StudioActionExecutor
from src.video_agent.config import settings
from src.video_agent.core import live_metrics, prompt_gates
from src.video_agent.core import workflow_runtime
from src.video_agent.core.tracer import AgentTracer
from src.video_agent.core.sse_events import SSE_DOC_WRITTEN
from src.video_agent.web.attachments import bind_attachments, attachment_context, store_uploaded_docs
from src.video_agent.web.generation import resolve_openai_endpoint
from src.video_agent.web.mock_chat import mock_stream
from src.video_agent.web.mock_llm import mock_llm_reply
from src.video_agent.web.multimodal_builder import (
    build_multimodal_content,
)
from src.video_agent.web.sse import sse_event_generator  # noqa: 1 （保留 sse.py 为正常模块；本行仅兼容旧导入路径）
from src.video_agent.state.manager import StateManager
from src.video_agent.core.planner import Planner, PlannerContext
from src.video_agent.memory import MemoryManager
from src.video_agent.exceptions import AdapterError, GenerationError, VideoAgentError
from src.video_agent.adapters.base_chat import BaseChatAdapter
from src.video_agent.adapters.factory import AdapterFactory
from src.video_agent.tools.manager import ToolManager
from src.video_agent.core.tracer import AgentTracer
from src.video_agent.state.models import ALL_CATEGORIES_TUPLE

__all__ = ["stream_worker", "non_stream_worker", "build_multimodal_content"]



# 会话级 compaction（恢复）：压缩后仍完整保留的最近消息条数
_HISTORY_COMPACT_KEEP = 4


async def _maybe_compact_history(
    history: List[Dict[str, Any]], svc, adapter,
) -> List[Dict[str, Any]]:
    """会话级 compaction（恢复）：历史超阈值时用便宜模型把较早消息压成摘要。

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
            # 承重接线遥测（批 8）：compaction 失败回落原 history 不再是纯静默
            live_metrics.record_degradation("chat_consume.session_compact")
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


def consume_pause_response(svc, pause_response) -> Optional[Dict[str, str]]:
    """消费暂停回应结构化回携（对标 AskUserQuestion 范式）。

    用户点选暂停卡选项时请求携带 {"pause_id", "value", "label"}；与
    interaction.active_pause 登记匹配即清除登记并返回持久化标记
    {"pause_id", "value", "label"}；不匹配（旧卡/自由打字）返回 None。
    LLM 语义不变：消息正文仍照常入 history，本函数只产出展示层标记。
    调用方需持有 svc.lock。
    """
    pid = str((pause_response or {}).get("pause_id") or "").strip()
    if not pid:
        return None
    interaction = svc.state_dict.get("interaction") or {}
    active = interaction.get("active_pause") or {}
    if str(active.get("pause_id") or "") != pid:
        return None
    workflow_runtime.reduce_interaction(svc, pop_flags=("active_pause",))
    return {
        "pause_id": pid,
        "value": str((pause_response or {}).get("value") or ""),
        "label": str((pause_response or {}).get("label") or ""),
    }


def _consume_pending_confirmation(svc, user_text: str = "", pause_value: str = "") -> str:
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
        workflow_runtime.reduce_interaction(
            svc, set_flags={"spec_collected": True}, pop_flags=("pending_pause_kind",))
    else:
        # 暂停语义标记（summary/spec/collect）随回应消费清除，避免残留影响下一轮
        workflow_runtime.reduce_interaction(svc, pop_flags=("pending_pause_kind",))
    # 故事板待确认窗口（步骤3→步骤4 分界）：不依赖 awaiting_confirmation，
    # 用户任何新消息到达即视为已审阅故事板，解除提示词写入封锁
    if interaction.get("storyboard_pending"):
        workflow_runtime.reduce_interaction(
            svc, set_flags={"storyboard_pending": False}, flush=True)
    # 确认闭环：上一轮展示过提示词草案（drafts_presented）且用户新消息到达，
    # 将未被重写过的草稿晋升为「已确认」（生成闸的前置条件）；
    # 期间被重写的草稿 tag 已在写入时重置，不会被误晋升
    presented = [d for d in (interaction.get("drafts_presented") or []) if d]
    if presented:
        promoted = 0
        presented_set = set(presented)
        for cat in ALL_CATEGORIES_TUPLE:
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
    # 晋升兜底：处于暂停态但 presented 记录缺失（记录链路异常或
    # 草稿经未记录路径写入）时，用户对暂停的回应即视为对当前带提示词草稿的确认，
    # 否则 tag 永远停在 Agent，生成闸反复拦截造成「确认了也出不了图」
    if not presented and interaction.get("awaiting_confirmation"):
        fallback_promoted = 0
        for cat in ALL_CATEGORIES_TUPLE:
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
    workflow_runtime.reduce_interaction(svc, set_flags={
        "awaiting_confirmation": False, "confirmation_message": "",}, flush=True)
    # 提示按客观状态机械生成（去 prose 越权）：
    # 规格已存在就如实告知，绝不固定发「先写入规格文档」指令；
    # 暂停点归 Skill 阶段边界，平台不 prose 指定
    spec_note = (
        "规格文档已写入，不必重写；"
        if prompt_gates.has_spec_document(svc.state_dict) else ""
    )
    # 三通道分离 C：用户点选系统派生继续选项时，
    # 下一步指令机械生成（sidecar 流程唯一源），模型不再自行猜测；
    # 向导多组拼装 value 为逐行文本，走行格式判定
    flow_note = ""
    if prompt_gates.is_flow_continue_value(pause_value):
        _used = svc.state_dict.get("usedSkills") or []
        _skill = str(_used[-1] or "") if _used else ""
        flow_note = prompt_gates.flow_continue_note(svc.state_dict, _skill)
    return (
        "\n\n（系统提示：上一轮已通过 workflow_pause 暂停等待确认，"
        f"暂停内容：{paused_msg}。本条消息即对该暂停的回应：表示确认时，按当前 Skill 流程"
        f"把当前阶段产出物做完；{spec_note}{flow_note}暂停点以 Skill 阶段边界为准；"
        "已完成的步骤（已读文档/已写规格）不必重复；"
        "提出修改意见时按新要求执行，完成后重新请求确认。）"
    )


def _consume_spec_wizard(svc, user_text: str) -> str:
    """规格向导消费（/）：用户回应是规格收集暂停的候选项时，
    机械落盘为规格文档（系统拼装，模型不手写），返回附加系统提示。

    仅当：项目尚无规格文档 + 用户回应含可解析的制作参数/渠道选择或明确确认意图。
    调用方需持有 svc.lock。
    """
    import re
    from datetime import datetime, timezone

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
    workflow_runtime.apply_interaction(state, set_flags={"spec_collected": True})
    #机械落盘也发文档卡片； ：改为挂起，由用户消息落库后
    # flush_pending_doc_card 补落（修复卡片排在用户选择消息之前的顺序 bug）
    inter["spec_doc_card_pending"] = name
    # 产物账本一等条目（Rule2 v6 ArtifactCommitted）：机械写入进
    # workflow_run.artifacts，done 载荷经 documents_written 同轮下发
    workflow_runtime.record_artifact(state, skill_name, name)
    # 轮前机械动作落转录（Rule2 v6：start_trace 收养进当轮时间线）
    try:
        AgentTracer.get_instance().record_pre_turn(
            "write_document", f"写入文档 {name}", ok=True)
    except Exception:
        pass
    svc.save()
    logger.info("[SpecWizard] 用户选择已机械落盘为规格文档 Final_Video_Spec.md")
    # 回执不 prose 指定子步骤与暂停点（流程/暂停归 Skill 阶段边界）
    return (
        "\n\n（系统：已按你的选择拼装并写入 Final_Video_Spec.md 规格文档，不必再手写规格。"
        "接下来按当前 Skill 流程执行下一阶段；暂停点以 Skill『何时暂停』为准。）"
    )


def flush_pending_doc_card(svc, turn_id: str = "") -> str:
    """ ：用户消息落库后补落向导挂起的文档卡（顺序正确且同轮聚合）。

     ：返回补落的文档名（无挂起返回空串），供调用方发 doc_written
    即显事件（live 可见性双通道与模型写文档同构）。
    调用点：各落库路径 add_chat_message(user) 之后（四轨）。
    """
    inter = svc.state_dict.get("interaction") or {}
    name = str(inter.pop("spec_doc_card_pending", "") or "").strip()
    if not name:
        return ""
    if turn_id:
        svc.add_chat_message("agent", "", doc_card=name, turn_id=turn_id)
    else:
        svc.add_chat_message("agent", "", doc_card=name)
    svc.save()
    logger.info(f"[SpecWizard] 规格文档卡补落：{name}（用户消息之后）")
    return name


async def emit_pending_doc_card(svc, turn_id: str, emit) -> str:
    """ ：补落向导规格卡并发 doc_written 即显事件（live 可见）。

    前端实时渲染只认 doc_written SSE / done 载荷 documents_written 两通道，
    向导机械拼装此前两通道都不走 → 不刷新看不见卡（现场）。
    """
    name = flush_pending_doc_card(svc, turn_id)
    if name and emit is not None:
        await emit({"type": SSE_DOC_WRITTEN, "name": name, "turn_id": turn_id})
    return name


def _finalize_spec_params(svc, user_text: str) -> str:
    """规格暂停回应定稿：summary 暂停的「确认」不得定稿规格；
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
    """把「N 组 M 卡（名称）：…」式逐卡枚举压缩为一行（正文逐卡罗列
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


def _summary_thinking_level() -> str:
    """摘要/压缩调用思考档位（策略表化）：策略 summary 角色 > settings.aux_thinking_level。"""
    from src.video_agent.core import model_policy

    return model_policy.thinking_for("summary", getattr(settings, "aux_thinking_level", "") or "")


