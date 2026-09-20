"""会话 compaction 域：历史压缩/摘要缓存/分层采样/客观探针。

从 chat_consume.py 按关注点切出（2026-09-03 拆分批）：原文件混装
「会话压缩」与「暂停态消费」两个零交关注点，本模块只承载压缩域。
触发双条件（token 驱动 + 条数兜底）、摘要按内容指纹缓存、失败静默
回落原 history（compaction 是优化不是前置条件）。
"""
import hashlib
import re
from typing import Any, Dict, List, Tuple

from loguru import logger

from src.video_agent.config import settings
from src.video_agent.utils import live_metrics
from src.video_agent.core import model_policy
from src.video_agent.core import workflow_runtime
from src.video_agent.core.token_budget import (
    context_window_for_model,
    estimate_messages_tokens,
    estimate_tokens,
)
from src.video_agent.core.tracer import AgentTracer
from src.video_agent.state.models import ALL_CATEGORIES_TUPLE

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
    选中草稿段之前）按
    interaction.session_summary.active 决定本轮是否注入。
    压缩生效置 True；未触发/失败回落原 history 时置 False
    （防先前轮次残留标记把陈旧摘要注入未压缩的完整历史）。
    只动标记位，异常不影响压缩主链。"""
    try:
        if svc is None:
            return
        workflow_runtime.reduce_session_summary(svc, active=active)
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
# （prompts/planner/feedback.md：FEEDBACK_MARKER/STEP_FEEDBACK 等，
# 含暂停回应提示），非真实用户/助手对话，不进采样
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
    位于全局设置段之后、选中草稿段之前）注入；history 本体只留最近
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
        # 2026-09-12 治理批：compaction.md 模板已删除（压缩指令唯一家 =
        # feedback.md::COMPACTION_INSTRUCTION，承载唯一活路径 session_log
        # .compact_pass）；本模块主路径已退役（chat_service 批 C1 注记），
        # 保留最小内联回落供 scope 域函数级测试。
        prompt = "请把以下对话压缩为不超过 300 字的摘要，保留决策与约束：\n" + dialog
        try:
            resp = await adapter.chat(
                [
                    {"role": "system", "content": "你是会话摘要助手。"},
                    {"role": "user", "content": prompt},
                ],
                timeout=settings.llm_timeout,
                thinking_level=_summary_thinking_level(),
            )
            # fail-closed：摘要调用撞输出帽（finish_reason=length）→ 半截摘要
            # 不落 interaction.session_summary，走既有失败回落（保留原 history）
            if getattr(resp, "finish_reason", "") == "length":
                live_metrics.record_degradation("chat_consume.session_compact")
                logger.warning(
                    "[ChatService] 会话 compaction 摘要在输出预算处被截断"
                    "（finish_reason=length），保留原 history"
                )
                _set_summary_active(svc, False)
                return history
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
        workflow_runtime.reduce_session_summary(svc, fp=fp, text=summary[:1000])
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


def _compact_card_enumeration(text: str) -> str:
    """把「N 组 M 卡（名称）：…」式逐卡枚举压缩为一行（正文逐卡罗列
    既耗 token 又撑长卡片）。少于 3 行枚举不触发。"""
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
    return model_policy.thinking_for("summary", getattr(settings, "aux_thinking_level", "") or "")
