"""消费/压缩域：会话 compaction/暂停态消费/规格向导消费/卡片枚举压缩。"""
import hashlib
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from src.video_agent.core.action_executor import StateOperationExecutor
from src.video_agent.config import settings
from src.video_agent.core import live_metrics, prompt_gates
from src.video_agent.core import workflow_runtime
from src.video_agent.core.token_budget import (
    context_window_for_model,
    estimate_messages_tokens,
    estimate_tokens,
)
from src.video_agent.core.tracer import AgentTracer
from src.video_agent.web.attachments import bind_attachments, attachment_context, store_uploaded_docs
from src.video_agent.web.generation import resolve_openai_endpoint
from src.video_agent.web.multimodal_builder import (
    build_multimodal_content,
)
from src.video_agent.state.manager import StateManager
from src.video_agent.core.planner import Planner, PlannerContext
from src.video_agent.exceptions import AdapterError, GenerationError, VideoAgentError
from src.video_agent.adapters.base_chat import BaseChatAdapter
from src.video_agent.adapters.factory import AdapterFactory
from src.video_agent.tools.manager import ToolManager
from src.video_agent.state.models import ALL_CATEGORIES_TUPLE

__all__ = ["build_multimodal_content"]



# 会话级 compaction：压缩后仍完整保留的最近消息条数
_HISTORY_COMPACT_KEEP = 4
# 分层采样预算：摘要输入最多采样的较早消息条数（头 6 + 中段跨步 + 尾 10）
_HISTORY_SAMPLE_CAP = 24


def _history_fingerprint(older: List[Dict[str, Any]]) -> str:
    """摘要失效键：较早消息的**内容指纹**而非消息条数。

    条数键的缺陷：编辑重发/截断重答不改变总数时命中陈旧摘要；内容指纹
    对任何增删改都失效重建。对全文计算（不受采样截断影响）。"""
    h = hashlib.sha1()
    for m in older:
        role = str(m.get("role") or "")
        content = m.get("content", "")
        h.update(role.encode("utf-8", "ignore"))
        h.update(b"\x00")
        if isinstance(content, str):
            h.update(content.encode("utf-8", "ignore"))
        else:  # 多模态 list content：稳定序列化
            h.update(repr(content).encode("utf-8", "ignore"))
        h.update(b"\x1e")
    return h.hexdigest()


def _set_summary_active(svc, active: bool) -> None:
    """摘要注入形态标记：system prompt 的专用摘要段
    （prompt_builder session_summary 段，位于全局设置段之后、
    状态 JSON 段之前）按
    interaction.session_summary.active 决定本轮是否注入。
    压缩生效置 True；未触发/失败回落原 history 时置 False
    （防先前轮次残留标记把陈旧摘要注入未压缩的完整历史）。
    只动标记位，异常不影响压缩主链。"""
    try:
        if svc is None:
            return
        interaction = svc.state_dict.setdefault("interaction", {})
        cached = interaction.get("session_summary")
        if not isinstance(cached, dict):
            if not active:
                return
            cached = {}
            interaction["session_summary"] = cached
        if bool(cached.get("active")) == bool(active):
            return
        cached["active"] = bool(active)
        svc.save_debounced()
    except Exception as _e:
        logger.debug("[ChatService] summary active 标记设置失败（忽略）: {}", _e)


def _extract_artifact_names(state: Dict[str, Any], older: List[Dict[str, Any]],
                            cap: int = 20) -> List[str]:
    """关键产物名基线候选（探针口径）：取当前工作台已有
    产物的标识（文档名/上传文档名/分组标题/草稿 label）为候选池，
    与被压缩段正文求交集——只有实际在被压缩对话中出现过的才算基线项，
    避免把从未谈论过的产物误判为摘要漏保留。短于 2 字符的候选舍弃
    （单字符易在摘要中偶然子串命中）。"""
    blob = "\n".join(str(m.get("content") or "") for m in older)
    names: List[str] = []
    for key in ("documents", "uploadedDocs"):
        for d in state.get(key) or []:
            n = str(d.get("name") or "").strip()
            if n:
                names.append(n)
    for cat in ALL_CATEGORIES_TUPLE:
        for g in state.get(cat) or []:
            t = str(g.get("title") or "").strip()
            if t:
                names.append(t)
            for dr in g.get("drafts") or []:
                lb = str(dr.get("label") or "").strip()
                if lb:
                    names.append(lb)
    seen: set = set()
    out: List[str] = []
    for n in names:
        if len(n) < 2 or n in seen:
            continue
        seen.add(n)
        if n in blob:
            out.append(n)
            if len(out) >= cap:
                break
    return out


def _compact_probe_metrics(state: Dict[str, Any], older: List[Dict[str, Any]],
                           summary: str) -> str:
    """压缩结果客观探针：指标拼入 compact 上下文事件 detail
    入 trace。① 摘要长度（字符数 + token 近似，与截断体系共用
    estimate_tokens 口径）；② 关键产物名命中率（基线 = 被压缩段中
    实际出现过的产物标识，见 _extract_artifact_names）。只记录不阻断：
    任何异常返回空串，压缩主流程照常。"""
    try:
        text = summary or ""
        chars = len(text)
        tokens = estimate_tokens(text)
        base = _extract_artifact_names(state or {}, older or [])
        if base:
            hits = sum(1 for n in base if n in text)
            artifact = f"artifact_name_hit={hits}/{len(base)}"
        else:
            artifact = "artifact_name_hit=无基线"
        return f"summary_chars={chars} summary_tokens≈{tokens} {artifact}"
    except Exception as _e:
        logger.debug("[ChatService] compaction 探针计算失败（忽略）: {}", _e)
        return ""


def _sample_older_dialog(older: List[Dict[str, Any]],
                         cap: int = _HISTORY_SAMPLE_CAP) -> str:
    """分层采样拼装摘要输入（分层采样而非只取尾部窗口）。

    头部定锚（任务起点）+ 中段等距跨步 + 尾部贴近期保留窗，超预算时
    中段均匀抽稀——任意位置的决策都有机会进入摘要，而不是只有最近 20 条。

    采样前过滤系统回喂型消息（信息密度治理）：工具回喂/压缩占位/
    暂停回应提示等「（系统）」前缀条目是运行时模板，不承载用户决策，
    采入只会稀释摘要；步间注入的用户引导消息解包还原用户原文后保留
    （真实用户意图，不丢）。过滤只作用于采样视角，不改 history 本体
    与指纹（_history_fingerprint 仍对全量计算，失效语义不变）。"""
    items: List[Tuple[str, str]] = []
    for m in older:
        text = _dialog_sample_text(m)
        if not text:
            continue
        items.append(("user" if m.get("role") == "user" else "agent", text))
    n = len(items)
    if n <= cap:
        idx = list(range(n))
    else:
        head, tail = 6, 10
        mid_budget = max(1, cap - head - tail)
        span = n - head - tail
        step = max(1, span // mid_budget)
        mid = list(range(head, n - tail, step))[:mid_budget]
        idx = sorted(set(list(range(head)) + mid + list(range(n - tail, n))))
    return "\n".join(f"{role}: {text[:300]}" for role, text in (items[i] for i in idx))


# 系统回喂型消息签名（compaction 采样过滤单一事实源）：
# 「（系统）」前缀条目均为系统回喂进 LLM 上下文的运行时模板
# （prompts/planner/feedback.md：FEEDBACK_MARKER/FEEDBACK_COMPRESSED/
# STEP_FEEDBACK/BAD_OUTPUT_NUDGE，含暂停回应提示与规格向导回执），
# 非真实用户/助手对话，不进采样
_SYSTEM_REFEED_PREFIXES = ("（系统）", "（系统提示：", "（系统：")

# 步间注入的用户引导包装（agent_loop pending_injector）：
# 外层是系统包装，内层是真实用户指令——解包取原文进采样
_GUIDANCE_WRAP_RE = re.compile(
    r"^（任务执行期间收到您的指令：(.*?)）"
    r"请优先处理；若为提问先回答，处理完继续原任务。$",
    re.S,
)


def _dialog_sample_text(msg: Dict[str, Any]) -> str:
    """单条消息的采样视角文本：系统回喂型消息返回空串（过滤）；
    步间引导消息解包还原用户原文；多模态 content 保持 repr 采样口径。"""
    content = msg.get("content", "")
    if not isinstance(content, str):
        return str(content).strip()
    text = content.strip()
    if not text:
        return ""
    m = _GUIDANCE_WRAP_RE.match(text)
    if m:
        return m.group(1).strip()
    if text.startswith(_SYSTEM_REFEED_PREFIXES):
        return ""
    return text


async def _maybe_compact_history(
    history: List[Dict[str, Any]], svc, adapter,
) -> List[Dict[str, Any]]:
    """会话级 compaction：历史超阈值时用便宜模型把较早消息压成摘要。

    触发双条件（token 驱动 + 条数兜底）：estimate_messages_tokens(history)
    超过窗口 0.6 倍，或条数达 history_compact_threshold（阈值 0 = 整体关闭）；
    长消息少条数的历史（大段回喂/附件）靠 token 条件命中，反之靠条数。
    对齐 Anthropic compaction 实践：保留决策与约束、丢弃冗余过程，
    并保留可回溯引用（文档名/任务 ID/草稿编号——丢内容留路径）。
    摘要按较早消息的**内容指纹**缓存于 interaction.session_summary
    （任何增删改即失效重建）；失败静默回落
    原 history（compaction 是优化不是前置条件）。

    注入形态：摘要不伪装成 history 首条 user
    消息，而是经 interaction.session_summary.active 每请求标记，由
    system prompt 的专用摘要段（prompt_builder session_summary 段，
    位于全局设置段之后、状态 JSON 段之前）注入；history 本体只留最近
    KEEP 条。压缩事件连同
    客观探针（摘要长度/产物名命中率）全量事件化入 trace。"""
    threshold = int(getattr(settings, "history_compact_threshold", 0) or 0)
    if threshold <= 0 or adapter is None:
        _set_summary_active(svc, False)
        return history
    # token 条件：按窗口 0.6 倍；窗口与 planner 截断同源（按模型查表，
    # 消除大窗口模型摘要过早/小窗口模型 token 条件空转的口径偏差）；
    # adapter 无 model 属性（测试替身）时回落 settings 口径，threshold=0 关闭语义不变
    model = getattr(adapter, "model", "") or ""
    if model:
        window = int(context_window_for_model(model) or 0) or 128000
    else:
        window = int(getattr(settings, "context_window_size", 128000) or 128000)
    token_limit = int(window * 0.6)
    over_tokens = estimate_messages_tokens(history) > token_limit
    if len(history) < threshold and not over_tokens:
        _set_summary_active(svc, False)
        return history
    interaction = svc.state_dict.setdefault("interaction", {})
    cached = interaction.get("session_summary") or {}
    keep = _HISTORY_COMPACT_KEEP
    older = history[:-keep] if len(history) > keep else []
    if not older:
        _set_summary_active(svc, False)
        return history
    fp = _history_fingerprint(older)
    summary = ""
    if cached.get("fp") == fp and str(cached.get("text") or "").strip():
        summary = str(cached["text"])
    else:
        dialog = _sample_older_dialog(older)
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
            # 承重接线遥测：compaction 失败回落原 history 不再是纯静默
            live_metrics.record_degradation("chat_consume.session_compact")
            logger.warning(f"[ChatService] 会话 compaction 失败，保留原 history: {e}")
            _set_summary_active(svc, False)
            return history
        if not summary:
            _set_summary_active(svc, False)
            return history
        interaction["session_summary"] = {"fp": fp, "text": summary[:1000]}
        svc.save_debounced()
        logger.info(
            f"[ChatService] 会话 compaction（{'token' if over_tokens else '条数'}触发）："
            f"{len(history)} 条 history 压缩为摘要+{keep} 条（采样较早 {len(older)} 条）")
    # 注入形态标记：压缩生效 → system 专用摘要段本轮注入
    _set_summary_active(svc, True)
    # 降级事件化：compaction 成功命中记入上下文事件流（旁路
    # 失败路径的 live_metrics.record_degradation，不重复）；失败仅 log 不干扰主链；
    # 客观探针（摘要长度/产物名命中率）拼入同一事件 detail
    try:
        detail = f"会话 compaction：{len(history)} 条 -> 摘要+{_HISTORY_COMPACT_KEEP} 条"
        probe = _compact_probe_metrics(svc.state_dict, older, summary)
        if probe:
            detail += f" | {probe}"
        AgentTracer.get_instance().record_context_event("compact", detail)
    except Exception as _e:
        logger.debug("[ChatService] compact 事件记录失败（忽略）: {}", _e)
    return history[-_HISTORY_COMPACT_KEEP:]


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
    # review decision 解析（审阅卡确认即解除 review_spec 挂起）
    try:
        _used = svc.state_dict.get("usedSkills") or []
        _sk = str(_used[-1] or "") if _used else ""
        _tok = str(((svc.state_dict.get("workflow_run") or {})
                    .get("pending_decision") or {}).get("token") or "")
        if _sk and _tok.startswith("review:"):
            workflow_runtime.WorkflowRuntime(svc, _sk).resolve_decision(
                _tok, str((pause_response or {}).get("value") or "confirm"))
    except Exception as _e:
        logger.debug("[WorkflowRuntime] review decision 解析跳过: {}", _e)
    return {
        "pause_id": pid,
        "value": str((pause_response or {}).get("value") or ""),
        "label": str((pause_response or {}).get("label") or ""),
    }


def _consume_pending_confirmation(svc, user_text: str = "", pause_value: str = "") -> str:
    """消费「等待确认」暂停态：用户的新消息即是对先前轮次暂停的回应。

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
        # 暂停语义标记（summary/spec/collect）随回应消费清除，避免残留影响后续轮次
        workflow_runtime.reduce_interaction(svc, pop_flags=("pending_pause_kind",))
    # 故事板待确认窗口（步骤3→步骤4 分界）：不依赖 awaiting_confirmation，
    # 用户任何新消息到达即视为已审阅故事板，解除提示词写入封锁
    if interaction.get("storyboard_pending"):
        workflow_runtime.reduce_interaction(
            svc, set_flags={"storyboard_pending": False}, flush=True)
    # 确认闭环：先前轮次展示过提示词草案（drafts_presented）且用户新消息到达，
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
    # 下一步指令机械生成（frontmatter 声明流程唯一源），模型不再自行猜测；
    # 向导多组拼装 value 为逐行文本，走行格式判定
    flow_note = ""
    if prompt_gates.is_flow_continue_value(pause_value):
        _used = svc.state_dict.get("usedSkills") or []
        _skill = str(_used[-1] or "") if _used else ""
        flow_note = prompt_gates.flow_continue_note(svc.state_dict, _skill)
    return (
        "\n\n（系统提示：先前轮次已通过 workflow_pause 暂停等待确认，"
        f"暂停内容：{paused_msg}。本条消息即对该暂停的回应：表示确认时，按当前 Skill 流程"
        f"把当前阶段产出物做完；{spec_note}{flow_note}暂停点以 Skill 阶段边界为准；"
        "已完成的步骤（已读文档/已写规格）不必重复；"
        "提出修改意见时按新要求执行，完成后重新请求确认。）"
    )


def _consume_spec_wizard(svc, user_text: str) -> Tuple[str, str]:
    """规格向导消费：用户回应是规格收集暂停的候选项时，
    经 write_spec 节点提交机械落盘为规格文档（系统拼装，模型不手写），
    返回 (附加系统提示, 落盘文档名)；文档名供调用方在用户消息后投影文档卡。

    仅当：项目尚无规格文档 + 用户回应含可解析的制作参数/渠道选择或明确确认意图。
    调用方需持有 svc.lock。
    """
    import re

    from src.video_agent.utils import gen_id

    state = svc.state_dict
    if prompt_gates.has_spec_document(state):
        return "", ""
    text = str(user_text or "").strip()
    if not text:
        return "", ""
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
        return "", ""
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
        return "", ""
    name = "Final_Video_Spec.md"
    workflow_runtime.apply_interaction(state, set_flags={"spec_collected": True})
    # review decision token 需 run_id：无 run 时先轻量同步（幂等）
    _run_id = str((state.get("workflow_run") or {}).get("run_id") or "")
    if not _run_id and skill_name:
        _run_id = str(workflow_runtime.sync_run(state, skill_name).get("run_id") or "")
    _review_req = None
    if _run_id:
        _review_req = {
            "token": f"review:{_run_id}",
            "prompt": "请审阅规格文档，确认后进入下一阶段",
            "options": [], "node_id": "review_spec"}
    # write_spec 节点提交——文档 artifact 与阶段推进进 reducer
    # 单事务（ArtifactCommitted + StageSucceeded(write_spec) +
    # current_node→review_spec）；卡片投影由调用方按提交结果于用户消息后落库（顺序同轮聚合）。
    try:
        workflow_runtime.commit_turn(
            state, workflow_runtime.TurnResult(
                turn_id=f"write_spec:{gen_id('wf')}",
                node_id="write_spec",
                artifacts=[{"name": name, "kind": "document", "content": content}],
                timeline_events=[{"event_type": "StageStarted",
                                  "payload": {"node_id": "write_spec"}}],
                decision_request=_review_req,
                next_transition={"completed_node": "write_spec",
                                 "next_node": "review_spec",
                                 "status": "waiting_user"}),
            skill=skill_name, persist=False)
    except Exception as e:
        logger.warning("[SpecWizard] write_spec 节点提交失败（本轮不落盘）: {}", e)
        return "", ""
    # 轮前机械动作落转录（start_trace 收养进当轮时间线）
    try:
        AgentTracer.get_instance().record_pre_turn(
            "write_document", f"写入文档 {name}", ok=True)
    except Exception:
        pass
    svc.save()
    logger.info("[SpecWizard] 用户选择已机械落盘为规格文档 Final_Video_Spec.md（write_spec 节点提交）")
    # 回执不 prose 指定子步骤与暂停点（流程/暂停归 Skill 阶段边界）
    return (
        "\n\n（系统：已按你的选择拼装并写入 Final_Video_Spec.md 规格文档，不必再手写规格。"
        "接下来按当前 Skill 流程执行下一阶段；暂停点以 Skill『何时暂停』为准。）",
        name,
    )


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


