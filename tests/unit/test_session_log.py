# -*- coding: utf-8 -*-
"""会话事件流（v4 主刀批 E1/E2/E3）回归：
- append/load 往返 + seq 单调；
- derive_messages：surface 推导顺序、步回喂模板派生、pruned_from 就地替换、
  replaces_seqs 压缩折叠、log/rewind 截面、悬挂 tool_calls 补位；
- migrate_from_chat_messages：一次性导入 + 幂等 + mechanical/卡片过滤；
- load_history D4 回落（日志通道异常 → None）；
- 批 E2 修剪器：码点预算 / 双面改写 / 低于压力零动作；
- 批 E3 阈值压缩：触发 / 保留尾轮组原子 / 检查点替换与回放闭环 /
  事务括号闭合 / 失败 fail-open / force 溢出口径 / turn 事件。
设计依据 docs/会话层append-only化细案.md。
"""
import json

import pytest

from src.video_agent.core import session_log
from src.video_agent.core.chat_port import ChatResponse
from src.video_agent.state.manager import StateManager


@pytest.fixture
def svc(tmp_path):
    StateManager.reset_instance()
    instance = StateManager(str(tmp_path / "ws"))
    StateManager._instance = instance
    # 清掉 demo 种子消息：迁移/装载口径确定性（chatMessages 指向活跃会话列表）
    instance._raw_state.get("chatMessages") or instance._raw_state.setdefault("chatMessages", [])
    if isinstance(instance._raw_state.get("chatMessages"), list):
        instance._raw_state["chatMessages"].clear()
    session_log._COMPACT_CACHE.clear()  # 指纹缓存隔离（同 span 跨用例不串）
    yield instance
    StateManager.reset_instance()
    session_log._SEQ_CACHE.clear()
    session_log._COMPACT_CACHE.clear()


def _write_raw(svc, events, cid="conv-main"):
    path = session_log.log_path(svc, cid)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in events) + "\n",
                    encoding="utf-8")


# ---------- append/load 往返 ----------


def test_append_load_roundtrip_and_seq_monotonic(svc):
    session_log.append_user_message(svc, "", "你好")  # cid 空 → 活跃会话
    session_log.append_assistant_message(svc, "", 1, "在", usage={"prompt_tokens": 10})
    session_log.append_tool_result(svc, "", 1, "c1", "read_skill", "全文…", ok=True)
    events = session_log.load_events(svc, "")
    assert [e["seq"] for e in events] == [1, 2, 3]
    assert events[1].get("tool_calls") in ([], None)
    assert events[2]["call_id"] == "c1" and events[2]["ok"] is True
    assert events[0]["type"] == "user/message"
    assert session_log.log_path(svc, "").exists()


# ---------- derive_messages ----------


def _base_events():
    return [
        {"seq": 1, "type": "user/message", "content": "开始"},
        {"seq": 2, "type": "assistant/message", "step": 1, "content": "", "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "read_skill", "arguments": "{}"}}]},
        {"seq": 3, "type": "tool/result", "step": 1, "call_id": "c1", "name": "read_skill",
         "content": "章节全文"},
        {"seq": 4, "type": "step/feedback", "step": 1, "tool_count": 1},
        {"seq": 5, "type": "assistant/message", "step": 2, "content": "完成"},
    ]


def test_derive_messages_surface_order_and_step_feedback(svc):
    msgs = session_log.derive_messages(_base_events())
    assert [m["role"] for m in msgs] == ["user", "assistant", "tool", "user", "assistant"]
    assert msgs[1]["tool_calls"][0]["id"] == "c1"
    assert msgs[2]["tool_call_id"] == "c1"
    assert "第 1 轮" in msgs[3]["content"] and "1 个 Tool" in msgs[3]["content"]
    assert msgs[4]["content"] == "完成"


def test_derive_pruned_from_replaces_in_place(svc):
    events = _base_events() + [
        {"seq": 6, "type": "tool/result", "step": 1, "pruned_from": 3,
         "content": "头…[... 中略 ...]…尾"},
    ]
    msgs = session_log.derive_messages(events)
    assert msgs[2]["content"] == "头…[... 中略 ...]…尾"
    assert len(msgs) == 5  # 不新增节点，只就地替换


def test_derive_replaces_seqs_compaction_checkpoint(svc):
    events = _base_events() + [
        {"seq": 6, "type": "user/message", "replaces_seqs": [1, 2, 3, 4],
         "content": "<compacted-summary>早期摘要</compacted-summary>"},
    ]
    msgs = session_log.derive_messages(events)
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert msgs[0]["content"] == "<compacted-summary>早期摘要</compacted-summary>"
    assert msgs[1]["content"] == "完成"  # 保留尾不受影响


def test_derive_rewind_drops_tail_from_marker(svc):
    events = [
        {"seq": 1, "type": "user/message", "content": "第一轮"},
        {"seq": 2, "type": "assistant/message", "step": 1, "content": "答1"},
        {"seq": 3, "type": "log/rewind", "to_seq": 0},
        {"seq": 4, "type": "user/message", "content": "第二轮（重答）"},
    ]
    msgs = session_log.derive_messages(events)
    assert [m["content"] for m in msgs] == ["第二轮（重答）"]


def test_derive_patches_dangling_tool_calls(svc):
    """用户停止/取消轮：assistant(tool_calls) 无配对结果 → 派生补占位
    （满足供应商「call 必有 result」硬约束），且补位紧跟连续 tool 块之后。"""
    events = [
        {"seq": 1, "type": "user/message", "content": "开始"},
        {"seq": 2, "type": "assistant/message", "step": 1, "content": "", "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "a", "arguments": "{}"}},
            {"id": "c2", "type": "function", "function": {"name": "b", "arguments": "{}"}}]},
        {"seq": 3, "type": "tool/result", "step": 1, "call_id": "c1", "name": "a", "content": "ok"},
        {"seq": 4, "type": "user/message", "content": "继续"},
    ]
    msgs = session_log.derive_messages(events)
    assert [m["role"] for m in msgs] == ["user", "assistant", "tool", "tool", "user"]
    assert msgs[2]["tool_call_id"] == "c1" and msgs[2]["content"] == "ok"
    assert msgs[3]["tool_call_id"] == "c2" and "未执行完成" in msgs[3]["content"]


# ---------- 迁移（细案 §六） ----------


def test_migrate_imports_nominal_messages_and_idempotent(svc):
    svc.add_chat_message("user", "第一问")
    svc.add_chat_message("agent", "第一答", reasoning_content="思考")
    svc.add_chat_message("agent", "", image_urls=["http://x/1.png"])  # 卡片：空正文跳过
    svc.add_chat_message("user", "机械流水", kind="mechanical")  # mechanical 跳过
    svc.add_chat_message("user", "第二问")

    assert session_log.migrate_from_chat_messages(svc, "") is True
    assert session_log.migrate_from_chat_messages(svc, "") is False  # 幂等（文件已存在）

    msgs = session_log.derive_messages(session_log.load_events(svc, ""))
    assert [m["content"] for m in msgs] == ["第一问", "第一答", "第二问"]
    assert msgs[1].get("reasoning_content") == "思考"
    marker = session_log.load_events(svc, "")[-1]
    assert marker["type"] == "log/imported" and marker["source"] == "chatMessages"


# ---------- 装载与 D4 回落 ----------


@pytest.mark.allow_degradation
def test_load_history_returns_list_and_none_on_channel_failure(svc):
    svc.add_chat_message("user", "历史问")
    svc.add_chat_message("agent", "历史答")
    hist = session_log.load_history(svc, "")
    assert hist is not None and [m["content"] for m in hist] == ["历史问", "历史答"]

    def _boom(*_a, **_k):
        raise RuntimeError("日志通道故障")

    monkey = pytest.MonkeyPatch()
    monkey.setattr(session_log, "migrate_from_chat_messages", _boom)
    try:
        assert session_log.load_history(svc, "") is None  # D4：回落信号
    finally:
        monkey.undo()


@pytest.mark.allow_degradation
def test_corrupt_line_stops_at_last_complete_event(svc, tmp_path):
    """写入中断（半行）止于最后完整事件；续写不重号。劣化告警为有意注入。"""
    _write_raw(svc, [
        {"seq": 1, "type": "user/message", "content": "完整事件"},
    ])
    path = session_log.log_path(svc, "")
    with path.open("a", encoding="utf-8") as fh:
        fh.write('{"seq":2,"type":"user/mess')  # 半行（写入中断）
    events = session_log.load_events(svc, "")
    assert [e["seq"] for e in events] == [1]
    # 后续 append 从最后完整事件续排，不重号
    ev = session_log.append_user_message(svc, "", "续写")
    assert ev["seq"] == 2


# ---------- 批 E2：工具结果修剪器（dsh 参数原样） ----------


def test_prune_text_codepoint_budgets():
    text = "甲" * 9000
    pruned = session_log.prune_text(text)
    assert len(pruned) == session_log.PRUNE_HEAD_CHARS + len(session_log.PRUNE_MARKER) \
        + session_log.PRUNE_TAIL_CHARS
    assert pruned.startswith("甲" * 100) and pruned.endswith("甲" * 100)
    assert "[... tool result middle pruned ...]" in pruned


def test_prune_text_astral_codepoints_whole():
    """emoji（Astral 码点）按码点整只保留，不劈半个。"""
    text = "🎬" * 9000
    pruned = session_log.prune_text(text)
    assert pruned.count("🎬") == session_log.PRUNE_HEAD_CHARS + session_log.PRUNE_TAIL_CHARS


def test_prune_pass_below_pressure_noop(svc):
    msgs = [{"role": "tool", "tool_call_id": "c1", "content": "x" * 9000}]
    entries = session_log.prune_pass(svc, "", msgs, 1_000_000)  # 巨窗 → 无压力
    assert entries == []
    assert msgs[0]["content"] == "x" * 9000  # 原文不动（低于压力绝不裁）


def test_prune_pass_at_pressure_rewrites_memory_and_log(svc):
    big = "y" * 9000
    # 日志面：全文已随 E1 镜像定格为原文事件
    session_log.append_tool_result(svc, "", 1, "c1", "read_skill", big, ok=True)
    msgs = [
        {"role": "user", "content": "z" * 600},  # 压力估算用（小窗口必命中）
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "read_skill", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "c1", "content": big},  # 内存面（历史派生同文）
    ]
    entries = session_log.prune_pass(svc, "", msgs, 200)
    assert len(entries) == 2  # 内存面 1 + 日志面 1
    assert entries[0]["chars_before"] == 9000
    assert len(msgs[2]["content"]) <= session_log.PRUNE_THRESHOLD_CHARS
    # 日志面：替换事件引用原文（原文永留日志）
    events = session_log.load_events(svc, "")
    assert len(events) == 2 and events[1]["pruned_from"] == 1
    # 派生面：下轮回放直接见修剪版（日志只有 tool/result 事件 → 派生单条）
    derived = session_log.derive_messages(events)
    assert derived[0]["content"] == events[1]["content"]
    # 幂等：二次 pass 不再追加替换事件
    session_log.prune_pass(svc, "", msgs, 200)
    assert len(session_log.load_events(svc, "")) == 2


# ---------- 批 E3：阈值压缩（dsh compaction-basic，参数原样） ----------


class _SummaryAdapter:
    """摘要假 adapter：记录每次请求，返回固定摘要（可注入失败）。"""

    def __init__(self, summary="结构化摘要正文", finish="stop", error=None):
        self.calls = []
        self._summary = summary
        self._finish = finish
        self._error = error

    async def chat(self, messages, **kwargs):
        self.calls.append({"messages": messages, "kwargs": kwargs})
        if self._error is not None:
            raise self._error
        return ChatResponse(content=self._summary, finish_reason=self._finish,
                            prompt_tokens=100, cached_tokens=50)


def _seed_two_rounds(svc, cid=""):
    """构造「两轮历史 + 本轮 user + 状态尾」的内存面与日志面（逐字节一致）。

    轮1（长，被压缩）+ 轮2（中，落保留尾）；窗口 2000 → 阈值 1600 token、
    保留尾 320 token（四字符启发式：轮1 ≈ 2000 token 超阈值，轮2 ≈ 550 ≥ 保留尾）。
    cid 可选：默认活跃会话；传显式 id 隔离日志文件（指纹缓存用例）。
    """
    r1_user = "第一问" + "甲" * 4000
    r1_asst = "第一答" + "乙" * 4000
    tc = {"id": "c1", "type": "function",
          "function": {"name": "read_skill", "arguments": "{}"}}
    session_log.append_user_message(svc, cid, r1_user)
    session_log.append_assistant_message(svc, cid, 1, r1_asst)
    session_log.append_user_message(svc, cid, "第二问")
    session_log.append_assistant_message(svc, cid, 1, "", tool_calls=[tc])
    session_log.append_tool_result(svc, cid, 1, "c1", "read_skill", "章节" + "丙" * 2000, ok=True)
    session_log.append_step_feedback(svc, cid, 1, 1)
    session_log.append_assistant_message(svc, cid, 2, "完成")
    session_log.append_user_message(svc, cid, "第三问")  # 本轮 user（已落流）
    history = session_log.derive_messages(session_log.load_events(svc, cid))
    # 内存面 = system 头 + 全量推导 + 状态尾（call_llm 装配口径）
    full = ([{"role": "system", "content": "系统提示"}] + list(history)
            + [{"role": "user", "content": "（系统）工作台状态 JSON"}])
    return full


@pytest.mark.allow_degradation
async def test_compact_pass_below_threshold_noop(svc):
    """低于压力零动作（dsh 口径）：无摘要调用、表层不动。"""
    full = _seed_two_rounds(svc)
    adapter = _SummaryAdapter()
    assert await session_log.compact_pass(
        svc, "", full, adapter, 1_000_000) is False
    assert adapter.calls == []
    assert full[1]["content"].startswith("第一问")  # 原文不动


@pytest.mark.allow_degradation
async def test_compact_pass_at_threshold_replaces_oldest_span(svc):
    """阈值命中：最旧平衡轮组换检查点，保留尾逐字；事务括号先落日志再动内存；
    回放推导与内存面逐字节一致（等价性硬口径）。"""
    full = _seed_two_rounds(svc)
    adapter = _SummaryAdapter(summary="轮一摘要")
    assert await session_log.compact_pass(
        svc, "", full, adapter, 2000, system="系统提示") is True
    # 内存面：[system, 检查点, 轮2 全组, 本轮 user, 状态尾]
    assert full[0]["role"] == "system"
    assert "<compacted-summary>" in full[1]["content"] and "轮一摘要" in full[1]["content"]
    assert full[2]["content"] == "第二问"           # 保留尾逐字（轮组原子）
    assert full[-1]["content"] == "（系统）工作台状态 JSON"
    assert not any(m.get("content", "").startswith("第一问") for m in full)
    # 摘要请求热前缀：[system] + 被压缩区间 + 末尾指令；max_tokens=dsh 默认 8192
    req = adapter.calls[0]
    assert [m["role"] for m in req["messages"]] == ["system", "user", "assistant", "user"]
    assert req["messages"][0]["content"] == "系统提示"
    assert req["messages"][1]["content"].startswith("第一问")
    assert req["kwargs"]["max_tokens"] == session_log.SUMMARY_MAX_TOKENS == 8192
    # 日志事务：start → summary(shadowed_seqs) → 检查点 user → end(ok)
    events = session_log.load_events(svc, "")
    tail_types = [e["type"] for e in events[-4:]]
    assert tail_types == ["compaction/start", "compaction/summary",
                          "user/message", "compaction/end"]
    summary_ev, checkpoint_ev, end_ev = events[-3], events[-2], events[-1]
    assert summary_ev["shadowed_seqs"] == [1, 2]
    assert checkpoint_ev["replaces_seqs"] == [1, 2]
    assert end_ev.get("ok") is True
    # 回放闭环：日志推导 = 内存面（去 system 头与状态尾——状态尾每轮重建
    # 不入流）逐字节一致（等价性硬口径）
    replayed = session_log.derive_messages(events)
    assert replayed == full[1:-1]


@pytest.mark.allow_degradation
async def test_compact_pass_summary_failure_fail_open(svc):
    """摘要失败：表层不动（截断链兜底）+ 括号闭合 end(ok=False)（无孤儿锁误报完成）。"""
    full = _seed_two_rounds(svc)
    before = [dict(m) for m in full]
    adapter = _SummaryAdapter(error=RuntimeError("上游 500"))
    assert await session_log.compact_pass(
        svc, "", full, adapter, 2000) is False
    assert full == before  # 表层原样
    events = session_log.load_events(svc, "")
    assert [e["type"] for e in events[-2:]] == ["compaction/start", "compaction/end"]
    assert events[-1].get("ok") is False


@pytest.mark.allow_degradation
async def test_compact_pass_truncated_summary_fail_closed(svc):
    """摘要撞输出帽（finish_reason=length）：半截摘要不入检查点。"""
    full = _seed_two_rounds(svc)
    adapter = _SummaryAdapter(summary="半截", finish="length")
    assert await session_log.compact_pass(
        svc, "", full, adapter, 2000) is False
    assert full[1]["content"].startswith("第一问")  # 表层不动
    events = session_log.load_events(svc, "")
    assert events[-1]["type"] == "compaction/end" and events[-1].get("ok") is False


@pytest.mark.allow_degradation
async def test_compact_pass_misaligned_memory_only_replacement(svc):
    """内存面与日志面错位（回落装载/digest 漂移同型）：放弃日志事务仅做
    内存面替换（当轮收益；日志无 compaction 事件）。"""
    full = _seed_two_rounds(svc)
    full[1]["content"] += "（已被单面改写）"  # 内存漂移：与日志推导不再逐字节一致
    adapter = _SummaryAdapter()
    assert await session_log.compact_pass(
        svc, "", full, adapter, 2000) is True
    assert "<compacted-summary>" in full[1]["content"]  # 内存面已替换
    events = session_log.load_events(svc, "")
    assert not any(e["type"].startswith("compaction/") for e in events)


@pytest.mark.allow_degradation
async def test_compact_pass_force_bypasses_threshold(svc):
    """溢出恢复口径（force）：绕过阈值与保留策略——仅保最近一个轮组
    （本轮 user + 状态尾），其余最旧平衡区间一次压平。"""
    full = _seed_two_rounds(svc)
    adapter = _SummaryAdapter(summary="溢出恢复摘要")
    assert await session_log.compact_pass(
        svc, "", full, adapter, 1_000_000, force=True) is True
    # 压后 = [system, 检查点(轮1+轮2), 本轮 user, 状态尾]
    assert "<compacted-summary>" in full[1]["content"]
    assert full[2]["content"] == "第三问"
    assert full[-1]["content"] == "（系统）工作台状态 JSON"
    assert len(full) == 4
    # 溢出恢复只压一次（attempts=1，不进常规重试循环）
    assert len(adapter.calls) == 1


@pytest.mark.allow_degradation
async def test_compact_pass_stops_when_under_threshold_after_compact(svc):
    """压后低于阈值即停（COMPACTION_RETRIES 循环空转即 break）：
    压缩范围一次覆盖到保留尾边界，压后剩余=检查点+保留尾，通常即刻收敛。"""
    assert session_log.COMPACTION_RETRIES == 1  # dsh compactionRetries 默认
    full = _seed_two_rounds(svc)
    adapter = _SummaryAdapter(summary="一次收敛摘要")
    assert await session_log.compact_pass(svc, "", full, adapter, 2000) is True
    assert len(adapter.calls) == 1  # 压后低于阈值，不追加第二次摘要调用


@pytest.mark.allow_degradation
async def test_compact_pass_isolated_turn_not_compressed(svc):
    """范围 < 2 条（孤立单条真实用户消息）：不压、不写日志（用户原话逐字保留）。"""
    session_log.append_user_message(svc, "", "唯一一句用户原话")
    history = session_log.derive_messages(session_log.load_events(svc, ""))
    full = [{"role": "system", "content": "S"}] + list(history) + [
        {"role": "user", "content": "（系统）状态"}]
    adapter = _SummaryAdapter()
    # 窗口 1 → 阈值 0：压力必命中，但保留尾吞掉唯一轮组 → 范围空 → 不压
    assert await session_log.compact_pass(svc, "", full, adapter, 1) is False
    assert adapter.calls == []
    events = session_log.load_events(svc, "")
    assert not any(e["type"].startswith("compaction/") for e in events)


def test_retain_boundary_round_group_atomic():
    """保留尾轮组原子：从尾往前按轮组累积，边界必落在真实用户消息上。"""
    msgs = [
        {"role": "user", "content": "问1"},
        {"role": "assistant", "content": "答1"},
        {"role": "user", "content": "问2"},
        {"role": "assistant", "content": "答2" + "字" * 800},  # ≈200 token
        {"role": "user", "content": "问3"},
        {"role": "assistant", "content": "答3"},
    ]
    # 保留 150 token：从尾往前第一轮组（问3+答3）不足 → 并入第二轮组 → 命中
    b = session_log._retain_boundary(msgs, 150)
    assert b == 2 and msgs[b]["content"] == "问2"  # 轮组边界（不劈 assistant）
    # 保留 0（force 口径）：仅保最近一个轮组
    assert session_log._retain_boundary(msgs, 0) == 4
    # 全量不足保留预算 → 0（整段皆保留尾）
    assert session_log._retain_boundary(msgs, 10_000_000) == 0


def test_turn_events_open_close_and_derive_skip(svc):
    """turn/start 计数单调；turn/end 闭合；derive 跳过 turn/*（log-only）。"""
    session_log.append_turn_start(svc, "")
    session_log.append_user_message(svc, "", "第一轮")
    session_log.append_turn_end(svc, "", reason="stop")
    session_log.append_turn_start(svc, "")
    session_log.append_user_message(svc, "", "第二轮")
    session_log.append_turn_end(svc, "")
    events = session_log.load_events(svc, "")
    starts = [e for e in events if e["type"] == "turn/start"]
    ends = [e for e in events if e["type"] == "turn/end"]
    assert [e["turn"] for e in starts] == [1, 2]
    assert [e["turn"] for e in ends] == [1, 2]
    assert ends[0]["reason"] == "stop"
    msgs = session_log.derive_messages(events)
    assert [m["content"] for m in msgs] == ["第一轮", "第二轮"]  # turn/* 不入推导


# ---------- 二期 G1：B（rewind × 检查点）+ C（mirror 同步 + 指纹缓存） ----------


def _seed_compacted_round(svc):
    """构造「B bug 场景」日志：轮1(被压缩遮蔽) + 检查点 + 轮2(将被重答)。"""
    session_log.append_user_message(svc, "", "第一问" + "甲" * 100)
    session_log.append_assistant_message(svc, "", 1, "第一答" + "乙" * 100)
    events = session_log.load_events(svc, "")
    seqs = [int(e["seq"]) for e in events]
    session_log.append_event(svc, "", "user/message", replaces_seqs=seqs,
                             content="<compacted-summary>轮一摘要</compacted-summary>",
                             source=session_log.SOURCE_CHECKPOINT)
    session_log.append_user_message(svc, "", "第二问")
    session_log.append_assistant_message(svc, "", 1, "第二答")


def test_rewind_locates_real_user_skipping_checkpoint(svc):
    """B 修复之一：rewind 定位按 source 跳过检查点（老扫描会命中伪装
    user 消息的检查点，to_seq 错位导致回放丢全史）。"""
    _seed_compacted_round(svc)
    # 日志：seq1 user(第一问) seq2 asst seq3 检查点 seq4 user(第二问) seq5 asst
    # 老行为：最后 user/message = 检查点(seq3) → to_seq=2 → 丢弃区间吞掉检查点
    # 且其 shadowed(1,2) 已被 fold 消费 → 回放历史全空（丢史）
    assert session_log.rewind_last_turn(svc, "") is True
    events = session_log.load_events(svc, "")
    rw = [e for e in events if e["type"] == "log/rewind"][-1]
    assert rw["to_seq"] == 4 - 1  # 定位「第二问」(seq4)，跳过检查点(seq3) → 3


def test_rewind_after_compaction_keeps_earlier_checkpoint(svc):
    """B 修复之二：重答压缩轮之后的轮次 → 检查点（代表更早历史）存活，
    回放 = [检查点]——既不丢史也不双重呈现。"""
    _seed_compacted_round(svc)
    assert session_log.rewind_last_turn(svc, "") is True  # 丢弃 (3, marker]
    msgs = session_log.derive_messages(session_log.load_events(svc, ""))
    assert [m["content"] for m in msgs] == ["<compacted-summary>轮一摘要</compacted-summary>"]


def test_rewind_dropping_checkpoint_inside_range_restores_originals(svc):
    """B 修复之三（丢史主场景）：检查点落在丢弃区间内 → 原事件完整恢复。
    构造：轮1 + 检查点(遮蔽轮1) + 轮2 步骤后压缩又把轮1+检查点再压——
    简化直测 fold 语义：检查点 seq 在丢弃区间内。"""
    events = [
        {"seq": 1, "type": "user/message", "content": "第一问"},
        {"seq": 2, "type": "assistant/message", "step": 1, "content": "第一答"},
        {"seq": 3, "type": "user/message", "replaces_seqs": [1, 2],
         "content": "<compacted-summary>摘要</compacted-summary>",
         "source": "checkpoint"},
        {"seq": 4, "type": "user/message", "content": "第二问"},
        {"seq": 5, "type": "log/rewind", "to_seq": 0},  # 丢弃区间 (0,5]：全含
        {"seq": 6, "type": "user/message", "content": "重答新消息"},
    ]
    msgs = session_log.derive_messages(events)
    # 检查点(seq3)与轮2(seq4)都在丢弃区间 → 原事件 seq1/2 也被 rewind 丢弃
    # （to_seq=0）→ 回放只剩标记后的重答消息
    assert [m["content"] for m in msgs] == ["重答新消息"]
    # 变体：rewind 只弃轮2 → 检查点存活遮蔽轮1（恢复语义不双重呈现）
    events2 = [
        {"seq": 1, "type": "user/message", "content": "第一问"},
        {"seq": 2, "type": "assistant/message", "step": 1, "content": "第一答"},
        {"seq": 3, "type": "user/message", "replaces_seqs": [1, 2],
         "content": "<compacted-summary>摘要</compacted-summary>",
         "source": "checkpoint"},
        {"seq": 4, "type": "user/message", "content": "第二问"},
        {"seq": 5, "type": "log/rewind", "to_seq": 3},  # 丢弃 (3,5]：仅轮2
        {"seq": 6, "type": "user/message", "content": "重答新消息"},
    ]
    msgs2 = session_log.derive_messages(events2)
    assert [m["content"] for m in msgs2] == [
        "<compacted-summary>摘要</compacted-summary>", "重答新消息"]


def test_nested_rewinds_ranges_stack(svc):
    """嵌套多条 rewind：丢弃区间自然叠加，标记后新历史保留。"""
    events = [
        {"seq": 1, "type": "user/message", "content": "A"},
        {"seq": 2, "type": "assistant/message", "step": 1, "content": "a"},
        {"seq": 3, "type": "log/rewind", "to_seq": 0},   # 弃 (0,3]
        {"seq": 4, "type": "user/message", "content": "B"},
        {"seq": 5, "type": "assistant/message", "step": 1, "content": "b"},
        {"seq": 6, "type": "log/rewind", "to_seq": 3},   # 弃 (3,6]
        {"seq": 7, "type": "user/message", "content": "C"},
    ]
    msgs = session_log.derive_messages(events)
    assert [m["content"] for m in msgs] == ["C"]


@pytest.mark.allow_degradation
async def test_compact_pass_mirror_splices_agent_messages(svc):
    """C 修复：mirror（agent_loop 的 messages）与 full_messages 同步 splice——
    下一步 [system]+messages 重组自然含检查点（不再逐步重烧摘要的结构前提）。"""
    full = _seed_two_rounds(svc)
    mirror = full[1:-1]  # agent_loop messages（无 system 头、无状态尾）
    mirror = [dict(m) for m in mirror]  # 独立副本模拟两列表并存
    adapter = _SummaryAdapter(summary="轮一摘要")
    assert await session_log.compact_pass(
        svc, "", full, adapter, 2000, system="系统提示",
        mirror=mirror) is True
    # mirror 已含检查点（同步 splice）
    assert "<compacted-summary>" in mirror[0]["content"]
    assert mirror[0] is full[1]  # 共享同一 checkpoint dict（不复制）
    # 步 2 重组：[system]+mirror+[新状态尾] 与 full 前缀逐字节一致
    rebuilt = [{"role": "system", "content": "系统提示"}] + mirror
    assert rebuilt == full[:len(full) - 1]
    assert full[-1]["content"] == "（系统）工作台状态 JSON"  # 状态尾未被波及


@pytest.mark.allow_degradation
async def test_compact_pass_fingerprint_cache_reuses_summary(svc):
    """C 修复：同 span 内容（另一会话/重放同构场景）指纹命中，零模型调用。"""
    full1 = _seed_two_rounds(svc, "")
    adapter = _SummaryAdapter(summary="唯一摘要")
    assert await session_log.compact_pass(
        svc, "", full1, adapter, 2000, system="系统提示") is True
    assert len(adapter.calls) == 1
    # 同内容、另一会话日志（span 逐字节相同 → 指纹命中）
    full2 = _seed_two_rounds(svc, "conv-cache-b")
    assert await session_log.compact_pass(
        svc, "conv-cache-b", full2, adapter, 2000, system="系统提示") is True
    assert len(adapter.calls) == 1  # 无新增模型调用（缓存复用）
    assert "<compacted-summary>" in full2[1]["content"]  # 检查点照常落地


# ---------- 二期 G2：D（检查点合并——纳入压缩范围 + 摘要合并指令） ----------


@pytest.mark.allow_degradation
async def test_compact_pass_merges_prior_checkpoint_into_new_span(svc):
    """D：旧检查点作为 span 起点被再压缩（合并）——shadowed 含旧检查点
    seq，fold 后仅存单一检查点（不再逐次堆积）。"""
    # 轮1（小）→ 检查点 ckpt1（replaces 1,2）
    session_log.append_user_message(svc, "", "第一问" + "甲" * 100)
    session_log.append_assistant_message(svc, "", 1, "第一答" + "乙" * 100)
    evs = session_log.load_events(svc, "")
    seqs = [int(e["seq"]) for e in evs]
    ckpt1_content = session_log._checkpoint_message("旧摘要")["content"]
    session_log.append_event(svc, "", "user/message", replaces_seqs=seqs,
                             content=ckpt1_content,
                             source=session_log.SOURCE_CHECKPOINT)
    ckpt1_seq = session_log.load_events(svc, "")[-1]["seq"]
    # 轮2（小，与 ckpt1 同落 span）+ 轮3（大，落保留尾）+ 本轮 user
    session_log.append_user_message(svc, "", "第二问" + "乙" * 50)
    session_log.append_assistant_message(svc, "", 1, "第二答" + "乙" * 50)
    session_log.append_user_message(svc, "", "第三问" + "丙" * 4000)
    session_log.append_assistant_message(svc, "", 1, "完成")
    session_log.append_user_message(svc, "", "第四问")
    history = session_log.derive_messages(session_log.load_events(svc, ""))
    full = ([{"role": "system", "content": "系统提示"}] + list(history)
            + [{"role": "user", "content": "（系统）工作台状态 JSON"}])
    adapter = _SummaryAdapter(summary="合并摘要")
    assert await session_log.compact_pass(
        svc, "", full, adapter, 2000, system="系统提示") is True
    # 新检查点的 shadowed 含旧检查点 seq（合并而非堆积）
    events = session_log.load_events(svc, "")
    summary_ev = [e for e in events if e["type"] == "compaction/summary"][-1]
    assert ckpt1_seq in summary_ev["shadowed_seqs"]
    # 摘要请求包含旧检查点原文（合并素材）
    span_contents = [m["content"] for m in adapter.calls[0]["messages"]]
    assert any(c.startswith(ckpt1_content[:20]) for c in span_contents)
    # fold 后仅存单一检查点（旧的被合并遮蔽）
    msgs = session_log.derive_messages(events)
    ckpt_count = sum(1 for m in msgs if "<compacted-summary>" in str(m.get("content", "")))
    assert ckpt_count == 1
    assert "合并摘要" in msgs[0]["content"]
    assert msgs[1]["content"].startswith("第三问")


def test_compaction_instruction_has_merge_clause():
    """D：摘要指令含 prior-checkpoint 合并条款（dsh 原文意译）。"""
    from src.video_agent.utils.prompts import load_prompt_section
    instruction = load_prompt_section("planner/feedback.md", "COMPACTION_INSTRUCTION")
    assert "compacted-summary" in instruction
    assert "合并为单一摘要" in instruction


# ---------- 二期 G4：E（parts 落流 + 媒体镜像 + 装载剥离） ----------


def test_user_message_parts_roundtrip(svc):
    """E：多模态 user 消息 parts 原样落流 + 回放透传（回放=请求逐字节）。"""
    parts = [
        {"type": "text", "text": "看这张图"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,AA"}},
    ]
    session_log.append_user_message(svc, "", parts)
    msgs = session_log.derive_messages(session_log.load_events(svc, ""))
    assert len(msgs) == 1
    assert msgs[0]["role"] == "user"
    assert msgs[0]["content"] == parts  # list 原样透传（不 str 化）


def test_rewind_skips_media_events(svc):
    """E：media 事件不被 rewind 当真人消息（source 判定统一收编）。"""
    session_log.append_user_message(svc, "", "第一问")
    session_log.append_user_message(svc, "", [
        {"type": "text", "text": "（系统）图片"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,BB"}},
    ], source=session_log.SOURCE_MEDIA)
    assert session_log.rewind_last_turn(svc, "") is True
    events = session_log.load_events(svc, "")
    rw = [e for e in events if e["type"] == "log/rewind"][-1]
    assert rw["to_seq"] == 1 - 1  # 定位「第一问」(seq1)，跳过 media(seq2)


def test_strip_prior_images_loaded_keeps_latest_only(svc):
    """E：装载层剥离——仅最后一条图片消息原样保留，更早图片 parts 移除
    且首条附说明（跨轮 vision token 治理归装载口径；日志原文永在）。"""
    def _img_msg(tag):
        return {"role": "user", "content": [
            {"type": "text", "text": f"（系统）{tag}"},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{tag}"}},
        ]}
    msgs = [
        {"role": "user", "content": "第一问"},
        _img_msg("A"),
        {"role": "assistant", "content": "答1"},
        _img_msg("B"),
        {"role": "assistant", "content": "答2"},
    ]
    out = session_log.strip_prior_images_loaded(msgs)
    # 旧图片消息 A：image part 剥离 + 附说明；文本 part 保留
    a_parts = out[1]["content"]
    assert not any(p.get("type") == "image_url" for p in a_parts)
    assert any("已从上下文移除" in str(p.get("text", "")) for p in a_parts)
    # 最新图片消息 B：原样保留
    assert any(p.get("type") == "image_url" for p in out[3]["content"])
    # 非图片消息不动
    assert out[0]["content"] == "第一问"
    # 只有一条被附说明（不重复）
    notes = sum(1 for m in out if isinstance(m.get("content"), list)
                and any("已从上下文移除" in str(p.get("text", "")) for p in m["content"]))
    assert notes == 1


def test_strip_prior_images_loaded_noop_without_images(svc):
    """E：无图片消息零动作（纯文本会话行为不变）。"""
    msgs = [
        {"role": "user", "content": "问"},
        {"role": "assistant", "content": "答"},
    ]
    out = session_log.strip_prior_images_loaded(msgs)
    assert out == msgs


@pytest.mark.allow_degradation
def test_load_history_strips_prior_images(svc):
    """E 集成：load_history 回放后应用装载剥离（media 事件回放 → 仅最新画面）。"""
    session_log.append_user_message(svc, "", "第一问")
    session_log.append_user_message(svc, "", [
        {"type": "text", "text": "（系统）图片A"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,A"}},
    ], source=session_log.SOURCE_MEDIA)
    session_log.append_assistant_message(svc, "", 1, "答1")
    session_log.append_user_message(svc, "", [
        {"type": "text", "text": "（系统）图片B"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,B"}},
    ], source=session_log.SOURCE_MEDIA)
    hist = session_log.load_history(svc, "")
    assert hist is not None
    # 旧画面（A）已剥离，最新画面（B）保留
    flat = [p for m in hist if isinstance(m.get("content"), list) for p in m["content"]]
    urls = [p["image_url"]["url"] for p in flat if p.get("type") == "image_url"]
    assert urls == ["data:image/png;base64,B"]
