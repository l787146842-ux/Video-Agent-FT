"""会话事件流（v4 主刀批 E1）：LLM 历史唯一事实源 = append-only JSONL。

设计依据 docs/会话层append-only化细案.md（已获批）：
- 事件词汇表（首版最小集）：surface 三事件（user/message / assistant/message /
  tool/result）+ log-only（step/feedback / log/rewind / log/imported）。
  turn/*、compaction/* 随批 E3 引入；tool_calls 内嵌 assistant 事件（细案 D1）。
- 「已提交事件绝不重写」：修剪/压缩（E2/E3）以追加替换事件表达，
  截断重答以 log/rewind 标记表达（细案 D6）。
- 失败回落（细案 D4）：本模块任何异常静默降级（record_degradation），
  调用方回落现行 chatMessages 装载路径，不阻断对话。
- 落盘口径：workspace/sessions/<project_id>/<conversation_id>.jsonl，
  逐事件一行、append 即 flush；与 chatMessages 同 conversation 归属
  （解析顺序对齐 conversation_ops.target_chat_messages：显式 id →
  bound_conversation_id → activeConversationId）。
"""
import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from loguru import logger

from src.video_agent.config import settings
from src.video_agent.core.token_budget import (
    _is_real_user_msg,
    estimate_messages_tokens,
)
from src.video_agent.core.tracer import AgentTracer
from src.video_agent.state import conversation_ops
from src.video_agent.utils.live_metrics import record_cache_usage, record_degradation
from src.video_agent.utils.paths import WORKSPACE_DIR
from src.video_agent.utils.prompts import load_prompt_section

# surface 事件：参与推导 LLM 可见消息
EV_USER = "user/message"
EV_ASSISTANT = "assistant/message"
EV_TOOL_RESULT = "tool/result"
# log-only 事件
EV_STEP_FEEDBACK = "step/feedback"
EV_REWIND = "log/rewind"
EV_IMPORTED = "log/imported"
# log-only 事件（批 E3 引入：轮边界 + 压缩事务括号）
EV_TURN_START = "turn/start"
EV_TURN_END = "turn/end"
# 完成盖章（dsh A2）：模型经 task_complete 显式宣告本轮交付时落一条，
# 使「谁在何时声称完成」成为可审计事实（与客观账本同点入流，事后对账用）
EV_TURN_STAMP = "turn/stamp"
EV_COMPACTION_START = "compaction/start"
EV_COMPACTION_SUMMARY = "compaction/summary"
EV_COMPACTION_END = "compaction/end"

# user/message 事件来源（二期 G1，dsh inject 同款形态）：真人输入 / 状态注入
# （G3）/ 压缩检查点 / 媒体回喂（G4，view_storyboard_media 图片 parts 的
# user 多模态消息）。「真实用户消息」判定唯一源 = _ev_source（老事件无
# source 字段：带 replaces_seqs 视为 checkpoint，其余视为 user，向后兼容）
SOURCE_USER = "user"
SOURCE_STATE = "state"
SOURCE_CHECKPOINT = "checkpoint"
SOURCE_MEDIA = "media"


def _ev_source(ev: Dict[str, Any]) -> str:
    """user/message 事件的来源标签（单一判定源，rewind/压缩范围共用）。"""
    src = str(ev.get("source") or "")
    if src:
        return src
    return SOURCE_CHECKPOINT if ev.get("replaces_seqs") else SOURCE_USER

# 会话 id 文件名白名单（id 为平台生成：conv-main / hex；防御性替换异形字符）
_SAFE_CID_RE = re.compile(r"[^A-Za-z0-9_\-]")
# seq 缓存（进程内单写者口径，同 cache_metrics）：键 = 事件流文件绝对路径
# （workspace 跟随 StateManager 实例，测试注入多实例互不串扰）
_SEQ_CACHE: Dict[str, int] = {}


def _resolve_cid(svc: Any, conversation_id: str) -> str:
    """会话归属解析（对齐 conversation_ops.target_chat_messages 顺序）：
    显式 conversation_id → 实例绑定会话 → 活跃会话。"""
    cid = str(conversation_id or getattr(svc, "bound_conversation_id", "") or "")
    if not cid:
        cid = str((svc._raw_state.get("activeConversationId") if hasattr(svc, "_raw_state") else "")
                  or (svc.state_dict.get("activeConversationId") if hasattr(svc, "state_dict") else "")
                  or "conv-main")
    return cid


def log_path(svc: Any, conversation_id: str = "") -> Path:
    """事件流文件路径：<workspace>/sessions/<project_id>/<cid>.jsonl。
    workspace 跟随 StateManager 实例（测试注入隔离目录；缺省回落全局）。"""
    cid = _resolve_cid(svc, conversation_id)
    project_id = str(getattr(svc, "active_project_id", "") or "_global")
    ws = Path(getattr(svc, "_workspace_dir", None) or WORKSPACE_DIR)
    return ws / "sessions" / _SAFE_CID_RE.sub("_", project_id) / (_SAFE_CID_RE.sub("_", cid) + ".jsonl")


def _cache_key(svc: Any, conversation_id: str) -> str:
    """seq 缓存键 = 事件流文件绝对路径（实例级隔离，多 workspace 不串扰）。"""
    return str(log_path(svc, conversation_id))


def load_events(svc: Any, conversation_id: str = "") -> List[Dict[str, Any]]:
    """读全量事件（容错：断行/损坏 JSON 止于最后完整行并告警）。异常上抛给调用方。"""
    path = log_path(svc, conversation_id)
    if not path.exists():
        return []
    events: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                logger.warning(f"[SessionLog] 事件流存在损坏行，止于最后完整行: {path.name}")
                record_degradation("session_log.corrupt_line")
                break
            if isinstance(ev, dict) and ev.get("type"):
                events.append(ev)
    if events:
        _SEQ_CACHE[_cache_key(svc, conversation_id)] = int(events[-1].get("seq") or len(events))
    return events


def append_event(svc: Any, conversation_id: str, ev_type: str, **fields: Any) -> Optional[Dict[str, Any]]:
    """追加一条事件（seq/time 自动分配，append 即 flush）。

    失败静默降级（细案 D4）：告警 + record_degradation，返回 None；
    调用方一律把返回值当作可有可无（遥测不阻断主流程）。
    """
    try:
        path = log_path(svc, conversation_id)
        key = _cache_key(svc, conversation_id)
        if key not in _SEQ_CACHE:
            if path.exists():
                load_events(svc, conversation_id)
            else:
                _SEQ_CACHE[key] = 0
        seq = int(_SEQ_CACHE.get(key, 0)) + 1
        ev: Dict[str, Any] = {"seq": seq, "type": ev_type, "time": time.time(), **fields}
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(ev, ensure_ascii=False)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
            fh.flush()
        _SEQ_CACHE[key] = seq
        return ev
    except Exception as _e:
        logger.warning(f"[SessionLog] 事件追加失败（回落口径不受影响）: {_e}")
        record_degradation("session_log.append")
        return None


# ---------- 轮内镜像事件（与 agent_loop/turn_executor 的内存 append 一一对应） ----------


def append_user_message(
    svc: Any, conversation_id: str, content: str,
    source: str = SOURCE_USER,
) -> Optional[Dict[str, Any]]:
    """轮始用户消息落流（与 add_chat_message("user", ...) 同点同文）。
    source：二期 G1 来源标签（user 真人输入 / state 状态注入 G3）——
    推导均为 user 消息，标签仅供 rewind/压缩范围判定。"""
    content_val: Any = content
    if not isinstance(content_val, (str, list)):
        content_val = str(content_val or "")
    return append_event(svc, conversation_id, EV_USER,
                        content=content_val, source=str(source or SOURCE_USER))


def append_assistant_message(
    svc: Any, conversation_id: str, step: int, content: str,
    tool_calls: Optional[List[Dict[str, Any]]] = None,
    reasoning_content: str = "", usage: Optional[Dict[str, Any]] = None,
) -> None:
    """每步 assistant 响应落流（turn_executor.llm_call 单一镜像点）：
    content/tool_calls/reasoning/usage 与该步发给供应商的响应同源。"""
    fields: Dict[str, Any] = {"step": int(step), "content": str(content or "")}
    if tool_calls:
        fields["tool_calls"] = tool_calls
    if str(reasoning_content or "").strip():
        fields["reasoning_content"] = str(reasoning_content)
    if usage:
        fields["usage"] = usage
    return append_event(svc, conversation_id, EV_ASSISTANT, **fields)


def append_tool_result(
    svc: Any, conversation_id: str, step: int, call_id: str, name: str,
    content: str, ok: Optional[bool] = None,
) -> None:
    """单条工具结果回喂落流（agent_loop FC 分支镜像点）：content =
    实际回喂进模型的文本（消化/指针化后口径）；悬挂补位（未执行）同样落流。"""
    fields: Dict[str, Any] = {
        "step": int(step), "call_id": str(call_id or ""),
        "name": str(name or ""), "content": str(content or ""),
    }
    if ok is not None:
        fields["ok"] = bool(ok)
    return append_event(svc, conversation_id, EV_TOOL_RESULT, **fields)


def append_step_feedback(svc: Any, conversation_id: str, step: int, tool_count: int) -> Optional[Dict[str, Any]]:
    """步回喂事实落流（log-only，细案 D2）：不存原文，装载时按模板派生。"""
    return append_event(svc, conversation_id, EV_STEP_FEEDBACK,
                        step=int(step), tool_count=int(tool_count))


def rewind_last_turn(svc: Any, conversation_id: str = "") -> bool:
    """截断重答（细案 D6 + 二期 B 修复）：追加 log/rewind 标记，装载时忽略
    「最后一条真人用户消息起」的全部事件——标记非改写，已提交事件保持原样。
    二期 B：定位按 source 判定（跳过检查点/状态注入等合成事件——一期 bug
    为扫到伪装 user 消息的压缩检查点导致 to_seq 错位、回放丢全史）。"""
    try:
        events = load_events(svc, conversation_id)
        last_user_seq = 0
        for ev in events:
            if ev.get("type") == EV_USER and _ev_source(ev) == SOURCE_USER:
                last_user_seq = int(ev.get("seq") or 0)
        if last_user_seq <= 0:
            return False
        append_event(svc, conversation_id, EV_REWIND, to_seq=last_user_seq - 1)
        return True
    except Exception as _e:
        logger.warning(f"[SessionLog] 重答回退标记失败: {_e}")
        record_degradation("session_log.rewind")
        return False


# ---------- 迁移（细案 §六：chatMessages 名义消息一次性导入） ----------


def migrate_from_chat_messages(svc: Any, conversation_id: str = "") -> bool:
    """事件流文件不存在时，把该会话 chatMessages 名义消息导出为事件流。

    过滤口径与 _main_history_from_thread 一致（空正文跳过、mechanical 跳过、
    reasoning_content 透传）；一次性幂等（以文件存在为准）；原子写（tmp+rename）。
    返回 True = 执行了导入。"""
    try:
        path = log_path(svc, conversation_id)
        if path.exists():
            return False
        cid = _resolve_cid(svc, conversation_id)
        msgs = None
        try:
            msgs = conversation_ops.get_conversation_messages(svc, cid)
        except Exception:
            msgs = None
        if msgs is None:
            msgs = svc.get_chat_messages() or []
        lines: List[str] = []
        seq = 0

        def _emit(ev_type: str, **fields: Any) -> None:
            nonlocal seq
            seq += 1
            ev = {"seq": seq, "type": ev_type, "time": time.time(), **fields}
            lines.append(json.dumps(ev, ensure_ascii=False))

        for m in msgs:
            text = str((m or {}).get("text") or "").strip()
            if not text or (m or {}).get("kind") == "mechanical":
                continue
            role = "user" if (m or {}).get("sender") == "user" else "assistant"
            if role == "user":
                _emit(EV_USER, content=text)
            else:
                fields: Dict[str, Any] = {"step": 0, "content": text}
                rc = str((m or {}).get("reasoning_content") or "").strip()
                if rc:
                    fields["reasoning_content"] = rc
                _emit(EV_ASSISTANT, **fields)
        _emit(EV_IMPORTED, source="chatMessages", count=seq)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".jsonl.tmp")
        tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
        tmp.replace(path)
        _SEQ_CACHE[_cache_key(svc, cid)] = seq
        logger.info(f"[SessionLog] chatMessages 名义消息已导入事件流（{seq} 事件）: {path.name}")
        return True
    except Exception as _e:
        logger.warning(f"[SessionLog] 迁移导入失败（回落 chatMessages 装载）: {_e}")
        record_degradation("session_log.migrate")
        return False


# ---------- 装载（每请求全量回放，细案 §五） ----------


def render_step_feedback(step: int, tool_count: int) -> str:
    """步回喂文本派生（措辞唯一源 = feedback.md::STEP_FEEDBACK，细案 D2）；
    分节缺失回落最小占位（与 agent_loop 既有兜底同文）。"""
    tpl = load_prompt_section("planner/feedback.md", "STEP_FEEDBACK")
    if tpl:
        return tpl.replace("{{step}}", str(step)).replace("{{count}}", str(tool_count))
    return f"（系统）第 {step} 轮工具已执行完毕。"


def _suspended_tool_note() -> str:
    """悬挂调用占位回喂（措辞唯一源 = feedback.md::TOOL_RESULT_SUSPENDED）：
    用户停止/取消轮在日志中留下未配对的 assistant(tool_calls)，派生时补位
    满足供应商「每个 tool_call 必有对应 tool 消息」硬约束。"""
    return (load_prompt_section("planner/feedback.md", "TOOL_RESULT_SUSPENDED")
            or "（该调用未执行完成，会话在此中断）")


def _fold_surface(
    events: List[Dict[str, Any]],
    step_feedback_renderer: Optional[Callable[[int, int], str]] = render_step_feedback,
) -> List[Dict[str, Any]]:
    """事件流 fold + derive：返回 [{seq, msg}]（derive_messages 的内核）。

    二期 B 两遍 fold（修 rewind × 检查点交互丢史）：
    - 第一遍收集每条 log/rewind 的丢弃区间 (to_seq, 标记自身 seq]——
      标记**之后**的事件是新历史（重答轮），必须保留；嵌套多条 rewind
      区间自然叠加（append-only 从不复活）；
    - 第二遍正常 fold，命中任一丢弃区间的事件直接跳过（视为从未发生）——
      检查点若在区间外正常生效（继续遮蔽其 shadowed）；若被 rewind 丢弃
      则连同其 shadowed 一起从未进入 fold，原事件自然完整恢复（一期
      单遍过滤在 rewind 命中检查点时把被遮蔽原事件一并丢光）。
    其余语义：pruned_from 就地替换（E2）；replaces_seqs 压缩折叠（E3）；
    step/feedback 模板派生；turn/*、compaction/*、log/imported 跳过。
    """
    # 第一遍：收集 rewind 丢弃区间
    drop_ranges: List[tuple] = []
    for ev in events:
        if str(ev.get("type") or "") == EV_REWIND:
            try:
                to_seq = int(ev.get("to_seq") or 0)
                marker_seq = int(ev.get("seq") or 0)
            except (TypeError, ValueError):
                continue
            if marker_seq > to_seq:
                drop_ranges.append((to_seq, marker_seq))
    out: List[Dict[str, Any]] = []  # [{seq, msg}]
    for ev in events:
        ev_type = str(ev.get("type") or "")
        try:
            seq = int(ev.get("seq") or 0)
        except (TypeError, ValueError):
            seq = 0
        if any(lo < seq <= hi for lo, hi in drop_ranges):
            continue  # 丢弃区间内：从未发生（标记非改写）
        if ev_type == EV_USER:
            replaces = ev.get("replaces_seqs") or []
            raw_content = ev.get("content")
            content_val: Any = raw_content if isinstance(raw_content, list) else str(raw_content or "")
            node = {"seq": seq, "msg": {"role": "user", "content": content_val}}
            if replaces:
                # 压缩检查点（E3 语义）：替换节点落位 = 被替换区间的起点，
                # 其后紧跟保留尾（对齐 dsh：checkpoint 之后是 retained tail）
                drop = {int(x) for x in replaces}
                first_pos = next((idx for idx, e in enumerate(out)
                                  if e["seq"] in drop), len(out))
                out = [e for e in out if e["seq"] not in drop]
                out.insert(min(first_pos, len(out)), node)
            else:
                out.append(node)
        elif ev_type == EV_ASSISTANT:
            msg: Dict[str, Any] = {
                "role": "assistant", "content": str(ev.get("content") or "")}
            tool_calls = ev.get("tool_calls")
            if tool_calls:
                msg["tool_calls"] = tool_calls
            rc = str(ev.get("reasoning_content") or "").strip()
            if rc:
                msg["reasoning_content"] = rc
            out.append({"seq": seq, "msg": msg})
        elif ev_type == EV_TOOL_RESULT:
            src = ev.get("pruned_from")
            if src is not None:
                for e in out:
                    if e["seq"] == int(src):
                        e["msg"] = {**e["msg"], "content": str(ev.get("content") or "")}
                        break
            else:
                out.append({"seq": seq, "msg": {
                    "role": "tool",
                    "tool_call_id": str(ev.get("call_id") or ""),
                    "content": str(ev.get("content") or "")}})
        elif ev_type == EV_STEP_FEEDBACK:
            if step_feedback_renderer is not None:
                text = step_feedback_renderer(
                    int(ev.get("step") or 0), int(ev.get("tool_count") or 0))
                if text:
                    out.append({"seq": seq, "msg": {"role": "user", "content": text}})
        # 其余类型（turn/*、compaction/*、log/imported）：log-only，跳过
    _patch_dangling_tool_calls(out)
    return out


def derive_messages(
    events: List[Dict[str, Any]],
    step_feedback_renderer: Optional[Callable[[int, int], str]] = render_step_feedback,
) -> List[Dict[str, Any]]:
    """事件流 → LLM 可见消息（fold + derive 的薄壳）。"""
    return [e["msg"] for e in _fold_surface(events, step_feedback_renderer)]


def _patch_dangling_tool_calls(out: List[Dict[str, Any]]) -> None:
    """悬挂 tool_calls 补位（原位修改 out）：
    用户停止/取消/中断轮在日志中留下「assistant(tool_calls) 无配对 tool 结果」，
    直接回放会被供应商以「call 必有 result」拒收（400）；对每个未配对 call_id
    在其连续 tool 结果块之后补占位 tool 消息（措辞 = TOOL_RESULT_SUSPENDED）。"""
    i = 0
    while i < len(out):
        msg = out[i]["msg"]
        calls = msg.get("tool_calls") if msg.get("role") == "assistant" else None
        if not calls:
            i += 1
            continue
        answered: set = set()
        j = i + 1
        while j < len(out) and out[j]["msg"].get("role") == "tool":
            answered.add(str(out[j]["msg"].get("tool_call_id") or ""))
            j += 1
        fills = []
        for tc in calls:
            cid = str((tc or {}).get("id") or "")
            if cid and cid not in answered:
                fills.append({"seq": 0, "msg": {
                    "role": "tool", "tool_call_id": cid,
                    "content": _suspended_tool_note()}})
        if fills:
            out[j:j] = fills
            i = j + len(fills)
        else:
            i = j


def load_history(svc: Any, conversation_id: str = "") -> Optional[List[Dict[str, Any]]]:
    """装载历史（细案 §五）：事件流缺失先迁移，再全量回放推导。

    返回 None = 日志通道不可用（调用方回落现行 chatMessages 装载路径，
    细案 D4）；返回 List（可为空）= 日志推导结果。
    """
    try:
        migrate_from_chat_messages(svc, conversation_id)
        events = load_events(svc, conversation_id)
        msgs = derive_messages(events)
        return strip_prior_images_loaded(msgs)
    except Exception as _e:
        logger.warning(f"[SessionLog] 历史装载失败（回落 chatMessages）: {_e}")
        record_degradation("session_log.load_history")
        return None


# ---------- 装载层图片剥离（二期 G4：跨轮 vision token 治理归装载口径） ----------


def _has_image_part(msg: Dict[str, Any]) -> bool:
    content = msg.get("content")
    return (isinstance(content, list)
            and any(isinstance(p, dict) and p.get("type") == "image_url"
                    for p in content))


def strip_prior_images_loaded(
    messages: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """装载口径「上下文只保留最新画面」（二期 G4）：保留最后一条图片
    消息原样，更早图片消息的 image parts 移除（首个被剥离的消息附说明
    文本 part，文案单一源 = feedback.md::FEEDBACK_IMAGES_STRIPPED，与内存
    strip_prior_feedback_images 同文两口径）。日志原文永在（append-only），
    需要回看调 view_storyboard_media 重新加载。原位修改并返回。"""
    last_img = -1
    for i, m in enumerate(messages):
        if _has_image_part(m):
            last_img = i
    if last_img < 0:
        return messages
    note = load_prompt_section("planner/feedback.md", "FEEDBACK_IMAGES_STRIPPED")
    noted = False
    for i, m in enumerate(messages):
        if i >= last_img or not _has_image_part(m):
            continue
        new_parts = [p for p in m["content"] if p.get("type") != "image_url"]
        if not noted and note:
            new_parts.append({"type": "text", "text": note})
            noted = True
        m["content"] = new_parts
    return messages


# ---------- 工具结果修剪器（批 E2，抄 dsh tool-result-pruner，参数原样） ----------

# 参数原样（dsh compaction-tool-result-pruner 默认值；码点 = Unicode code point，
# Python len(str) 即码点计数，天然不劈 surrogate 对）
PRUNE_THRESHOLD_CHARS = 8192   # 超过即修剪（合并文本码点数）
PRUNE_HEAD_CHARS = 4096        # 保留头部码点
PRUNE_TAIL_CHARS = 1024        # 保留尾部码点
PRUNE_MARKER = "\n\n[... tool result middle pruned ...]\n\n"
# 压缩触发阈值（批 E3 compaction-basic，参数原样）：floor(context_window × 0.8)。
# 修剪器同用此阈值判定压力（低于压力绝不裁，dsh 口径）。
COMPACTION_THRESHOLD_RATIO = 0.8


def prune_text(text: str) -> str:
    """码点预算修剪：头 + 中省略标注 + 尾（head+marker+tail ≤ threshold，
    一次收敛，无重复改写）。"""
    head = text[:PRUNE_HEAD_CHARS]
    tail = text[len(text) - PRUNE_TAIL_CHARS:] if PRUNE_TAIL_CHARS > 0 else ""
    return head + PRUNE_MARKER + tail


def prune_pass(
    svc: Any, conversation_id: str, messages: List[Dict[str, Any]],
    context_window: int,
) -> List[Dict[str, Any]]:
    """压力触发的工具结果双面修剪（细案 §七）：

    - 触发：请求估算 ≥ floor(context_window × 0.8)；低于压力零动作（dsh 口径）；
    - 内存面：当前请求消息列表内超预算 tool role 消息就地改写（本轮后续请求
      立即收益；改写即幂等，后续 pass 自然空转）；
    - 日志面：对 surface 上仍为全文的 tool/result 事件追加替换事件
      （pruned_from 引用原文，原文永留日志），下轮全量回放直接见修剪版。
    返回修剪记账（[{call_id, chars_before, chars_after}]，含内存面 + 日志面）。
    异常静默降级（D4），不阻断主流程。
    """
    try:
        if context_window <= 0 or not messages:
            return []
        total = estimate_messages_tokens(messages)
        if total < int(context_window * COMPACTION_THRESHOLD_RATIO):
            return []

        entries: List[Dict[str, Any]] = []
        # 内存面：就地改写（tool role 消息与历史派生/轮内回喂共享同一 dict）
        for m in messages:
            if m.get("role") != "tool":
                continue
            content = str(m.get("content") or "")
            if len(content) <= PRUNE_THRESHOLD_CHARS:
                continue
            pruned = prune_text(content)
            entries.append({
                "call_id": str(m.get("tool_call_id") or ""),
                "chars_before": len(content), "chars_after": len(pruned),
            })
            m["content"] = pruned

        # 日志面：surface 原文事件中仍超阈值的追加替换事件
        #（含本轮内存面刚改写的调用——其全文镜像已在落流时定格为原文）
        events = load_events(svc, conversation_id)
        shadowed = {int(e.get("pruned_from")) for e in events
                    if e.get("type") == EV_TOOL_RESULT and e.get("pruned_from") is not None}
        for ev in events:
            if ev.get("type") != EV_TOOL_RESULT or ev.get("pruned_from") is not None:
                continue
            seq = int(ev.get("seq") or 0)
            if seq in shadowed:
                continue
            content = str(ev.get("content") or "")
            if len(content) <= PRUNE_THRESHOLD_CHARS:
                continue
            pruned = prune_text(content)
            append_event(svc, conversation_id, EV_TOOL_RESULT,
                         step=ev.get("step") or 0,
                         call_id=str(ev.get("call_id") or ""),
                         name=str(ev.get("name") or ""),
                         content=pruned, ok=ev.get("ok"),
                         pruned_from=seq,
                         chars_before=len(content), chars_after=len(pruned))
            entries.append({
                "call_id": str(ev.get("call_id") or ""),
                "chars_before": len(content), "chars_after": len(pruned),
            })
        if entries:
            logger.info(
                f"[SessionLog] 工具结果修剪 {len(entries)} 条"
                f"（-{sum(e['chars_before'] - e['chars_after'] for e in entries)} 码点）")
        return entries
    except Exception as _e:
        logger.warning(f"[SessionLog] 修剪 pass 失败（忽略）: {_e}")
        record_degradation("session_log.prune")
        return []


# ---------- 轮边界事件（批 E3：turn/start、turn/end，log-only） ----------


def append_turn_start(svc: Any, conversation_id: str) -> Optional[Dict[str, Any]]:
    """轮始标记（chatService 落 user/message 之前同点）：turn 号 =
    日志中既有 turn/start 计数 + 1（单调；与 user/message 计数解耦，
    压缩检查点也是 user/message 但不推进轮号）。"""
    try:
        events = load_events(svc, conversation_id)
        turn = sum(1 for e in events if e.get("type") == EV_TURN_START) + 1
        return append_event(svc, conversation_id, EV_TURN_START, turn=turn)
    except Exception:
        return None


def append_turn_end(svc: Any, conversation_id: str, reason: str = "done") -> None:
    """轮末标记（agent_loop finally 统一出口）：任何轮出口（正常/停止/
    取消/异常上抛）都闭合轮括号；崩溃中断留下的未闭合 turn/start 由
    下一条 turn/start 自然开启新轮（append-only 不回填）。"""
    turn = 0
    try:
        events = load_events(svc, conversation_id)
        for e in events:
            if e.get("type") == EV_TURN_START:
                turn = max(turn, int(e.get("turn") or 0))
        append_event(svc, conversation_id, EV_TURN_END, turn=turn, reason=str(reason or "done"))
    except Exception:
        return


def append_turn_stamp(
    svc: Any, conversation_id: str, receipt: str = "", step: int = 0,
) -> None:
    """完成盖章审计事件（agent_loop 收到 task_complete 回执时落）：
    只留痕迹不改行为（log-only，不参与消息面 fold）。落流失败静默（D4）。"""
    turn = 0
    try:
        events = load_events(svc, conversation_id)
        for e in events:
            if e.get("type") == EV_TURN_START:
                turn = max(turn, int(e.get("turn") or 0))
        append_event(svc, conversation_id, EV_TURN_STAMP, turn=turn, step=step,
                     receipt=str(receipt or "")[:2000])
    except Exception:
        return


# ---------- 子代理只读记录（B3 后端地基，事件流单一事实源） ----------


def thread_status(svc: Any, conversation_id: str = "") -> Dict[str, Any]:
    """隐藏线程运行态概览（供子任务卡）：turn/end 存在 = completed（子级
    在父本轮内联跑完，落流后即终结）；否则 running。steps = assistant 响应数。
    读不到事件流静默回落 unknown。"""
    try:
        events = load_events(svc, conversation_id)
    except Exception:
        return {"status": "unknown", "steps": 0, "events": 0}
    done = any(str(e.get("type") or "") == EV_TURN_END for e in events)
    steps = sum(1 for e in events if str(e.get("type") or "") == EV_ASSISTANT)
    return {"status": "completed" if done else "running", "steps": steps,
            "events": len(events)}


def project_readable_record(svc: Any, conversation_id: str = "") -> List[Dict[str, Any]]:
    """子代理隐藏线程事件流 → 只读执行记录条目（形状兼容 chatMessages entry：
    sender/text/ts/reasoning_content/actionLog）。

    只取面向人的表面：真人任务（source=user）+ assistant 正文/思考 + 工具活动
    名单 + 完成章（turn/stamp，「本轮宣告完成」及其客观账本）；跳过 state/feedback/
    media/checkpoint/turn-start-end/compaction 等模型向噪声（与 derive_messages 的
    LLM 口径不同，本函数专供 UI 只读回放）。只读、不改事件流。"""
    try:
        events = load_events(svc, conversation_id)
    except Exception:
        return []
    out: List[Dict[str, Any]] = []
    for ev in events:
        ev_type = str(ev.get("type") or "")
        ts_ms = int(float(ev.get("time") or 0) * 1000)
        if ev_type == EV_TURN_STAMP:
            # 完成章（dsh A2）：谁在何时宣告完成 + 当时客观账本，只读回放可见
            receipt = str(ev.get("receipt") or "").strip()
            out.append({"sender": "system", "text": receipt or "本轮已登记完成章。",
                        "ts": ts_ms, "stamp": True})
        elif ev_type == EV_USER and _ev_source(ev) == SOURCE_USER:
            content = ev.get("content")
            text = content if isinstance(content, str) else ""
            if text.strip():
                out.append({"sender": "user", "text": text, "ts": ts_ms})
        elif ev_type == EV_ASSISTANT:
            entry: Dict[str, Any] = {"sender": "assistant", "ts": ts_ms}
            text = str(ev.get("content") or "")
            rc = str(ev.get("reasoning_content") or "").strip()
            calls = ev.get("tool_calls") or []
            names = [str(((tc or {}).get("function") or {}).get("name") or "")
                     for tc in calls]
            names = [n for n in names if n]
            if text.strip():
                entry["text"] = text
            if rc:
                entry["reasoning_content"] = rc
            if names:
                entry["actionLog"] = names
            if text.strip() or rc or names:
                out.append(entry)
        # tool/result / step/feedback / turn/start|end / compaction/* / log/imported：不入只读记录
    return out


# ---------- 会话层阈值压缩（批 E3，抄 dsh compaction-basic，参数原样） ----------

# 参数原样（dsh compaction-basic 默认值）
SUMMARY_MAX_TOKENS = 8192   # 摘要请求输出上限（dsh maxTokens）
COMPACTION_RETRIES = 1      # 压缩后压力仍超阈值的额外尝试次数
RETAIN_RATIO = 0.16         # 逐字保留尾 = 已路由上下文窗口 × 0.16（dsh retainRatio）

# 二期 C：压缩摘要指纹缓存（round_compact 退役时的能力回归）——同 span
# 内容不重复烧摘要调用；上限 64 挤掉最旧（防遥测式自膨胀）
_COMPACT_CACHE: Dict[str, str] = {}
_COMPACT_CACHE_MAX = 64


def _span_fingerprint(span: List[Dict[str, Any]]) -> str:
    """span 内容指纹（序列化 md5；不可序列化对象回落空串 = 不缓存）。"""
    try:
        return hashlib.md5(json.dumps(
            span, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    except (TypeError, ValueError):
        return ""


def _turn_no(events: List[Dict[str, Any]]) -> int:
    """当前轮号 = 最后一条 turn/start 的 turn（旧会话无轮标记时 0）。"""
    turn = 0
    for e in events:
        if e.get("type") == EV_TURN_START:
            try:
                turn = max(turn, int(e.get("turn") or 0))
            except (TypeError, ValueError):
                continue
    return turn


def _retain_boundary(msgs: List[Dict[str, Any]], retain_tokens: int) -> int:
    """保留尾起点（轮组原子，细案 §八：复用 _is_real_user_msg 轮组边界；
    二期 D：检查点也是轮组锚——保留尾内检查点不被劈半）：
    从尾部往前按轮组累积 token，达到 retain_tokens 即停；全量不足 → 0
    （整段皆保留尾 = 无可压）。retain_tokens<=0 = 仅保最近一个轮组
    （溢出恢复口径：绕过保留策略的最大平衡缩减）。"""
    if not msgs:
        return 0
    if retain_tokens <= 0:
        retain_tokens = 1  # 首个轮组必命中
    boundary = len(msgs)
    acc = 0
    while boundary > 0:
        g_start = boundary - 1
        while g_start > 0 and not _is_span_anchor(msgs[g_start]):
            g_start -= 1
        acc += estimate_messages_tokens(msgs[g_start:boundary])
        if acc >= retain_tokens:
            return g_start
        boundary = g_start
    return 0


def _is_checkpoint_msg(msg: Dict[str, Any]) -> bool:
    """压缩检查点判定（二期 D）：content 以 COMPACTION_PREAMBLE 开头的
    user 消息（判定与构造读同一分节，单一事实源；分节缺失 → 无检查点
    可判，保守返回 False）。"""
    if msg.get("role") != "user":
        return False
    content = msg.get("content")
    if not isinstance(content, str):
        return False
    preamble = load_prompt_section("planner/feedback.md", "COMPACTION_PREAMBLE")
    return bool(preamble) and content.startswith(preamble)


def _is_span_anchor(msg: Dict[str, Any]) -> bool:
    """压缩范围/轮组锚（二期 D 统一判定）：真实用户消息或压缩检查点——
    检查点代表一段已压缩历史，可作为最旧平衡 span 的起点被再压缩（合并），
    而不是被 start 扫描永久跳过（一期缺口：检查点永不合并、逐次堆积）。"""
    return _is_real_user_msg(msg) or _is_checkpoint_msg(msg)


def _checkpoint_message(summary: str) -> Dict[str, Any]:
    """压缩检查点消息（dsh 口径：前导 + 空行 + <compacted-summary> 包裹；
    前导措辞唯一源 = feedback.md::COMPACTION_PREAMBLE）。"""
    preamble = (load_prompt_section("planner/feedback.md", "COMPACTION_PREAMBLE")
                or "（系统检查点：更早的对话区间已浓缩为下方摘要；直接继续任务即可。）")
    return {"role": "user",
            "content": f"{preamble}\n\n<compacted-summary>\n{summary}\n</compacted-summary>"}


async def _summarize_span(
    svc: Any, adapter: Any, system: str, span: List[Dict[str, Any]],
    tools_schema: Optional[List[Dict[str, Any]]],
) -> str:
    """摘要请求（热前缀复用，细案 §八）：system + 工具 schema + 被压缩
    区间消息逐字节重放 + 末尾压缩指令一条 user 消息——摘要调用是主对话
    的真前缀，只有尾部指令与摘要输出未命中缓存。

    返回空串 = 摘要失败（fail-closed：撞输出帽的半截摘要不入检查点）。"""
    instruction = load_prompt_section("planner/feedback.md", "COMPACTION_INSTRUCTION")
    if not instruction:
        logger.warning("[SessionLog] feedback.md::COMPACTION_INSTRUCTION 分节缺失，压缩跳过")
        return ""
    summarize_msgs: List[Dict[str, Any]] = (
        [{"role": "system", "content": system}] if system else [])
    summarize_msgs.extend(span)
    summarize_msgs.append({"role": "user", "content": instruction})
    try:
        resp = await adapter.chat(
            summarize_msgs, tools=tools_schema,
            max_tokens=SUMMARY_MAX_TOKENS, timeout=settings.llm_timeout)
    except Exception as _e:
        logger.warning(f"[SessionLog] 压缩摘要调用失败（回落截断链）: {_e}")
        return ""
    try:
        record_cache_usage(
            str(getattr(svc, "active_project_id", "") or ""),
            int(getattr(resp, "prompt_tokens", 0) or 0),
            int(getattr(resp, "cached_tokens", 0) or 0))
    except Exception:
        pass
    if str(getattr(resp, "finish_reason", "") or "") == "length":
        logger.warning("[SessionLog] 压缩摘要在输出上限处被截断（finish_reason=length），"
                       "半截摘要不入检查点")
        return ""
    return str(getattr(resp, "content", "") or "").strip()


def _match_surface_seqs(
    svc: Any, conversation_id: str,
    msgs: List[Dict[str, Any]], start: int, tail_start: int,
) -> Optional[List[int]]:
    """范围内消息与日志 surface 推导严格对齐 → seq 列表（replaces_seqs）。

    对不齐（日志通道回落装载 / digest 单面漂移 / 图片消息进入范围）→
    None = 放弃日志事务，仅做内存面替换（当轮收益；下轮回放原文，
    无损只是不省——dsh「摘要失败保留最新表层」同款 fail-open）。"""
    try:
        events = load_events(svc, conversation_id)
    except Exception:
        return None
    surface = _fold_surface(events)
    if len(surface) < tail_start:
        return None
    seqs: List[int] = []
    for i in range(start, tail_start):
        node = surface[i]
        if node["msg"] != msgs[i]:
            return None
        try:
            seqs.append(int(node["seq"]))
        except (TypeError, ValueError):
            return None
    return seqs


def _record_compaction_event(detail: str) -> None:
    """压缩遥测（trace 上下文事件，口径对齐 history_compact）。"""
    try:
        AgentTracer.get_instance().record_context_event("compact", detail)
    except Exception:
        pass


async def compact_pass(
    svc: Any, conversation_id: str,
    full_messages: List[Dict[str, Any]],
    adapter: Any, context_window: int,
    system: str = "",
    tools_schema: Optional[List[Dict[str, Any]]] = None,
    *, force: bool = False,
    mirror: Optional[List[Dict[str, Any]]] = None,
) -> bool:
    """阈值压缩（细案 §八，dsh compaction-basic 参数原样；批 E3 起唯一
    的循环内压缩机制）：

    - 触发：请求估算 ≥ floor(context_window × 0.8)；force=True 绕过阈值
      （溢出恢复口径：一次最大平衡缩减，仅保最近一个轮组）；
    - 保留尾：最近 floor(context_window × 0.16) tokens 逐字（轮组原子）；
    - 范围：首个真实用户消息起到保留尾起点的最旧平衡 span；孤立单条
      真实用户消息不压（用户原话逐字保留）；
    - 替换：compaction/start → summary → 检查点 user/message(replaces_seqs,
      source=checkpoint) → end 括号事务先落日志再动内存（崩溃 = 可检孤儿
      括号，不误报完成）；
    - 二期 C：mirror（= agent_loop 的 messages 列表）与 full_messages 同步
      splice——下一步组装自然含检查点，与日志 fold 对齐，不再逐步重烧
      摘要；指纹缓存兜底（同 span 内容直接复用，零模型调用）；
    - 压缩后压力仍超阈值 → COMPACTION_RETRIES 次重试；
    - 任何失败 fail-open：不动表层，截断链（truncate_messages）兜底。
    返回 True = 本 pass 发生过替换。异常静默降级（D4）。
    """
    try:
        if adapter is None or context_window <= 0 or len(full_messages) < 2:
            return False
        threshold = int(context_window * COMPACTION_THRESHOLD_RATIO)
        retain_tokens = int(context_window * RETAIN_RATIO)
        # 溢出恢复只压一次；常规路径 = 首压 + COMPACTION_RETRIES 次重试
        attempts = 1 if force else 1 + COMPACTION_RETRIES
        check_threshold = not force
        changed = False
        for _attempt in range(attempts):
            total = estimate_messages_tokens(full_messages)
            if check_threshold and total < threshold:
                break
            msgs = full_messages[1:]  # system 头永不被遮蔽（dsh 口径）
            # 保留尾（force：绕过保留策略 = 仅最近一个轮组）
            tail_start = _retain_boundary(
                msgs, retain_tokens if not force else 0)
            # 二期 D：范围锚 = 真实用户消息或检查点（旧检查点纳入 span
            # 起点被再压缩合并，不再永久跳过堆积）
            start = 0
            while start < tail_start and not _is_span_anchor(msgs[start]):
                start += 1
            # 孤立单条真实用户消息不压；空范围不压（dsh：不写日志不改表层）
            if start >= tail_start or tail_start - start < 2:
                break
            span = msgs[start:tail_start]
            span_tokens = estimate_messages_tokens(span)
            seqs = _match_surface_seqs(svc, conversation_id, msgs, start, tail_start)
            events = load_events(svc, conversation_id) if seqs else []
            turn_no = _turn_no(events) if events else 0
            if seqs:
                append_event(svc, conversation_id, EV_COMPACTION_START, turn=turn_no)
            # 指纹缓存：同 span 内容复用摘要，不重复烧模型调用（二期 C）
            fp = _span_fingerprint(span)
            summary = str(_COMPACT_CACHE.get(fp) or "").strip() if fp else ""
            if not summary:
                summary = await _summarize_span(svc, adapter, system, span, tools_schema)
                if summary and fp:
                    _COMPACT_CACHE[fp] = summary
                    if len(_COMPACT_CACHE) > _COMPACT_CACHE_MAX:
                        _COMPACT_CACHE.pop(next(iter(_COMPACT_CACHE)))
            if not summary:
                if seqs:
                    append_event(svc, conversation_id, EV_COMPACTION_END,
                                 turn=turn_no, ok=False)
                logger.warning("[SessionLog] 压缩摘要失败，保留原表层（截断链兜底）")
                return changed
            checkpoint = _checkpoint_message(summary)
            if seqs:
                append_event(svc, conversation_id, EV_COMPACTION_SUMMARY,
                             turn=turn_no, summary=summary,
                             shadowed_seqs=seqs, shadowed_token_count=span_tokens)
                append_event(svc, conversation_id, EV_USER,
                             replaces_seqs=seqs, content=str(checkpoint["content"]),
                             source=SOURCE_CHECKPOINT)
                append_event(svc, conversation_id, EV_COMPACTION_END,
                             turn=turn_no, ok=True)
            # 内存面替换（坐标 +1 偏移 system 头；原地 splice）；
            # mirror 同步 splice（二期 C：无 system 头坐标 -1）——下一步
            # [system]+messages 重组自然含检查点，与日志 fold 逐字节对齐
            full_messages[start + 1: tail_start + 1] = [checkpoint]
            if mirror is not None:
                mirror[start:tail_start] = [checkpoint]
            new_total = estimate_messages_tokens(full_messages)
            changed = True
            check_threshold = True
            logger.info(
                f"[SessionLog] 会话压缩：区间 {tail_start - start} 条 -> 检查点 1 条，"
                f"{total} -> {new_total} tokens（窗口 {context_window}）")
            _record_compaction_event(
                f"会话层压缩 {total}->{new_total} tokens"
                f"（{tail_start - start} 条->1 条检查点）")
        return changed
    except Exception as _e:
        logger.warning(f"[SessionLog] 压缩 pass 失败（回落截断链）: {_e}")
        record_degradation("session_log.compact")
        return False
