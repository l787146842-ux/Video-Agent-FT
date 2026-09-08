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
import json
import re
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from loguru import logger

from src.video_agent.core.token_budget import estimate_messages_tokens
from src.video_agent.state import conversation_ops
from src.video_agent.utils.live_metrics import record_degradation
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


def append_user_message(svc: Any, conversation_id: str, content: str) -> Optional[Dict[str, Any]]:
    """轮始用户消息落流（与 add_chat_message("user", ...) 同点同文）。"""
    return append_event(svc, conversation_id, EV_USER, content=str(content or ""))


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
    """截断重答（细案 D6）：追加 log/rewind 标记，装载时忽略「最后一条
    user/message 起」的全部事件——标记非改写，已提交事件保持原样。"""
    try:
        events = load_events(svc, conversation_id)
        last_user_seq = 0
        for ev in events:
            if ev.get("type") == EV_USER:
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


def derive_messages(
    events: List[Dict[str, Any]],
    step_feedback_renderer: Optional[Callable[[int, int], str]] = render_step_feedback,
) -> List[Dict[str, Any]]:
    """事件流 → LLM 可见消息（fold + derive）。

    - log/rewind：丢弃 seq > to_seq 的已产出节点（标记非改写）；
    - tool/result.pruned_from：就地替换被引用节点的文本（E2 修剪语义）；
    - user/message.replaces_seqs：移除被引用节点后追加（E3 压缩检查点语义）；
    - step/feedback：按模板派生 user 文本；turn/*、compaction/*、log/imported 跳过。
    """
    out: List[Dict[str, Any]] = []  # [{seq, msg}]
    for ev in events:
        ev_type = str(ev.get("type") or "")
        try:
            seq = int(ev.get("seq") or 0)
        except (TypeError, ValueError):
            seq = 0
        if ev_type == EV_REWIND:
            keep = int(ev.get("to_seq") or 0)
            out = [e for e in out if e["seq"] <= keep]
        elif ev_type == EV_USER:
            replaces = ev.get("replaces_seqs") or []
            node = {"seq": seq, "msg": {
                "role": "user", "content": str(ev.get("content") or "")}}
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
    return [e["msg"] for e in out]


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
        return derive_messages(events)
    except Exception as _e:
        logger.warning(f"[SessionLog] 历史装载失败（回落 chatMessages）: {_e}")
        record_degradation("session_log.load_history")
        return None


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
