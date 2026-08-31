# -*- coding: utf-8 -*-
"""audit_gate_triggers 轮转扫描单测（任务#10）+ 遥测闭环（任务#3）。

钉死契约：
- trace 账本写满即轮转（agent_traces.jsonl → .1 → .2），盘点必须扫描全部
  轮转份，防只读主文件导致闸机触发统计系统性低估（误拆活跃闸）；
- 读取顺序按轮转序号从旧到新：.2 → .1 → 主文件；
- 聚合计数逻辑（total/blocked/overridden）不变，脏行跳过；
- P5：统计口径经 normalize_rule_id 归一，原始签发值留痕在 raw_ids（防口径断裂）。
- 任务#3：判定出口（audit_verdicts）遥测旁路每次判定 append 一行到
  gate_trigger_counts.jsonl；写入失败吞异常不影响主链路；汇总侧
  trigger_count_stats 按归一 rule_id 统计（脏行跳过，兼容 .N 轮转份）。
- 任务#4：超期未裁决点名口径钉死——观测窗不足半年不得点名降级候选（
  数据不足不虚构超期）；安全类闸机永不进候选（折旧规程 §5.4）；
  待裁决台账登记超半年才点名，日期不可解析的条目跳过。
"""
import datetime
import json
import pathlib

from scripts.audit_gate_triggers import (
    MIN_OBSERVATION_DAYS,
    SAFE_RUNTIME_RULES,
    count_files,
    pending_rulings_overdue,
    runtime_gate_stats,
    telemetry_window,
    trace_files,
    trigger_count_stats,
    zero_trigger_candidates,
)

from src.video_agent.core import guard_pipeline
from src.video_agent.core.guard_pipeline import GateVerdict


def _write(path: pathlib.Path, gates_per_trace: list) -> None:
    """每个元素为一组 gates，写一行 trace（steps[0].gates）。"""
    with path.open("w", encoding="utf-8") as f:
        for gates in gates_per_trace:
            f.write(json.dumps(
                {"steps": [{"gates": gates}]}, ensure_ascii=False) + "\n")


def _gate(rule_id: str, ok: bool = True, overridden: bool = False) -> dict:
    return {"rule_id": rule_id, "layer": "skill", "ok": ok,
            "overridden": overridden}


def test_trace_files_rotation_order(tmp_path: pathlib.Path):
    """轮转份按旧→新排序：.2 → .1 → 主文件；无关文件被过滤。"""
    base = tmp_path / "agent_traces.jsonl"
    for name in ("agent_traces.jsonl", "agent_traces.jsonl.1",
                 "agent_traces.jsonl.2"):
        (tmp_path / name).write_text("", encoding="utf-8")
    # 干扰项：非正规轮转命名不得混入
    (tmp_path / "agent_traces.jsonl.bak").write_text("", encoding="utf-8")
    (tmp_path / "agent_traces.jsonl.10x").write_text("", encoding="utf-8")

    names = [p.name for p in trace_files(base)]
    assert names == [
        "agent_traces.jsonl.2", "agent_traces.jsonl.1", "agent_traces.jsonl",
    ]


def test_trace_files_missing_dir(tmp_path: pathlib.Path):
    """目录不存在返回空清单（不抛异常）。"""
    assert trace_files(tmp_path / "nope" / "agent_traces.jsonl") == []


def test_stats_include_all_rotations(tmp_path: pathlib.Path):
    """聚合计数必须覆盖 .2 / .1 / 主文件三份（修复前只读主文件漏计）。"""
    base = tmp_path / "agent_traces.jsonl"
    # 最旧（.2）：2 次判定含 1 拦截
    _write(tmp_path / "agent_traces.jsonl.2", [
        [_gate("skill.flow.spec_gate", ok=False),
         _gate("platform.gen_confirm")],
    ])
    # 次旧（.1）：1 次放行覆盖
    _write(tmp_path / "agent_traces.jsonl.1", [
        [_gate("skill.flow.spec_gate", ok=True, overridden=True)],
    ])
    # 主文件（最新）：1 次普通判定
    _write(base, [[_gate("platform.gen_confirm")]])

    stats = runtime_gate_stats(base)
    # spec_gate：.2 拦 1 次 + .1 放行覆盖 1 次 = 2；若只读主文件则完全漏计
    assert stats["skill.flow.spec_gate"] == {
        "total": 2, "blocked": 1, "overridden": 1,
        "raw_ids": {"skill.flow.spec_gate"}}
    assert stats["platform.gen_confirm"] == {
        "total": 2, "blocked": 0, "overridden": 0,
        "raw_ids": {"platform.gen_confirm"}}


def test_stats_only_main_present(tmp_path: pathlib.Path):
    """无轮转份时行为与旧版一致：仅扫主文件。"""
    base = tmp_path / "agent_traces.jsonl"
    _write(base, [[_gate("platform.tool_risk", ok=False)]])
    assert runtime_gate_stats(base) == {
        "platform.tool_risk": {"total": 1, "blocked": 1, "overridden": 0,
                               "raw_ids": {"platform.tool_risk"}}}


def test_stats_dirty_lines_skipped(tmp_path: pathlib.Path):
    """脏行（非 JSON）与空行跳过，不中断后续文件扫描。"""
    base = tmp_path / "agent_traces.jsonl"
    old = tmp_path / "agent_traces.jsonl.1"
    old.write_text("not-json\n\n", encoding="utf-8")
    _write(base, [[_gate("skill.cjk_min_ratio", ok=False)]])
    assert runtime_gate_stats(base) == {
        "skill.cjk_min_ratio": {"total": 1, "blocked": 1, "overridden": 0,
                                "raw_ids": {"skill.cjk_min_ratio"}}}


def test_stats_normalize_identity_after_alias_retirement(tmp_path: pathlib.Path):
    """别名表已随 skill/session 层闸机退役清空：归一为恒等映射，
    各历史写法独立统计，raw_ids 留痕语义不变。"""
    base = tmp_path / "agent_traces.jsonl"
    _write(base, [
        [_gate("storyboard_prompt_structure", ok=False)],  # 历史写法（各自成行）
        [_gate("platform.prompt_write", ok=False)],        # 现役正式 ID
    ])
    stats = runtime_gate_stats(base)
    assert stats["storyboard_prompt_structure"] == {
        "total": 1, "blocked": 1, "overridden": 0,
        "raw_ids": {"storyboard_prompt_structure"}}
    assert stats["platform.prompt_write"] == {
        "total": 1, "blocked": 1, "overridden": 0,
        "raw_ids": {"platform.prompt_write"}}


# ---------- 任务#3：遥测旁路落盘（写入侧） ----------

def test_telemetry_append_format(tmp_path, monkeypatch):
    """判定出口每次 audit_verdicts 逐条 append，字段齐全且 rule_id 已归一。"""
    path = tmp_path / "gate_trigger_counts.jsonl"
    monkeypatch.setattr(guard_pipeline, "GATE_TRIGGER_COUNTS", path)
    guard_pipeline.audit_verdicts(
        [GateVerdict("platform.gen_confirm", "platform", True),
         GateVerdict("platform.prompt_write", "platform", False, "硬伤")],
        skill_name="李安美学", action="storyboard_prompt_write",
        overridden=True,
    )
    lines = [json.loads(x) for x in
             path.read_text(encoding="utf-8").splitlines() if x.strip()]
    assert len(lines) == 2
    rec = lines[0]
    # 必备字段：时间戳 / rule_id / 判定结果 / skill
    assert rec["ts"] and rec["epoch"] > 0
    assert rec["rule_id"] == "platform.gen_confirm" and rec["ok"] is True
    assert rec["skill"] == "李安美学" and rec["layer"] == "platform"
    assert rec["action"] == "storyboard_prompt_write"
    assert rec["overridden"] is True
    assert lines[1]["rule_id"] == "platform.prompt_write"
    assert lines[1]["ok"] is False


def test_telemetry_appends_not_overwrites(tmp_path, monkeypatch):
    """多次判定累加追加，不覆写历史行（遥测账本只增）。"""
    path = tmp_path / "gate_trigger_counts.jsonl"
    monkeypatch.setattr(guard_pipeline, "GATE_TRIGGER_COUNTS", path)
    for _ in range(3):
        guard_pipeline.audit_verdicts(
            [GateVerdict("platform.tool_risk", "platform", False)])
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3


def test_telemetry_write_failure_never_raises(tmp_path, monkeypatch):
    """写入失败（路径是目录）吞异常，audit_verdicts 正常返回不影响主链路。"""
    bad = tmp_path / "gate_trigger_counts.jsonl"
    bad.mkdir()  # open(目录, "a") 必抛 IsADirectoryError
    monkeypatch.setattr(guard_pipeline, "GATE_TRIGGER_COUNTS", bad)
    # 不抛即通过（判定逻辑与 tracer 审计不受旁路故障影响）
    guard_pipeline.audit_verdicts(
        [GateVerdict("platform.gen_confirm", "platform", True)])


# ---------- 任务#3：遥测汇总（读取侧） ----------

def _count_line(rule_id: str, ok: bool = True, overridden: bool = False,
                skill: str = "") -> str:
    return json.dumps({"ts": "2026-08-25T00:00:00+00:00", "epoch": 1.0,
                       "rule_id": rule_id, "ok": ok, "skill": skill,
                       "layer": "skill", "action": "", "overridden": overridden},
                      ensure_ascii=False)


def test_trigger_count_stats_aggregate(tmp_path):
    """按归一 rule_id 统计 total/blocked/overridden（别名表已退役，归一恒等）。"""
    base = tmp_path / "gate_trigger_counts.jsonl"
    base.write_text(
        _count_line("platform.prompt_write", ok=False)
        + "\n" + _count_line("platform.shot_min_chars", ok=False)
        + "\n" + _count_line("skill.flow.spec_gate", overridden=True)
        + "\nnot-json\n\n"           # 脏行/空行跳过
        + json.dumps({"ok": True})   # 缺 rule_id 行跳过
        + "\n", encoding="utf-8")
    stats = trigger_count_stats(base)
    assert stats["platform.prompt_write"] == {
        "total": 1, "blocked": 1, "overridden": 0}
    assert stats["platform.shot_min_chars"] == {
        "total": 1, "blocked": 1, "overridden": 0}
    assert stats["skill.flow.spec_gate"] == {
        "total": 1, "blocked": 0, "overridden": 1}


def test_trigger_count_stats_rotations(tmp_path):
    """兼容 .N 轮转份：旧→新全部纳入，无关文件过滤。"""
    base = tmp_path / "gate_trigger_counts.jsonl"
    (tmp_path / "gate_trigger_counts.jsonl.1").write_text(
        _count_line("platform.gen_confirm", ok=False), encoding="utf-8")
    (tmp_path / "gate_trigger_counts.jsonl.bak").write_text(
        _count_line("platform.gen_confirm"), encoding="utf-8")
    base.write_text(_count_line("platform.gen_confirm"), encoding="utf-8")
    names = [p.name for p in count_files(base)]
    assert names == ["gate_trigger_counts.jsonl.1", "gate_trigger_counts.jsonl"]
    assert trigger_count_stats(base)["platform.gen_confirm"]["total"] == 2


def test_trigger_count_stats_missing_file(tmp_path):
    """账本不存在时返回空 dict（落盘刚启用/未产生判定，不报错）。"""
    assert trigger_count_stats(tmp_path / "gate_trigger_counts.jsonl") == {}


def test_trigger_count_stats_dirty_ok_semantics(tmp_path):
    """脏数据口径收紧（任务#12）：仅显式 ok=False 计拦截。

    ok 缺失/None/脏值按放行计（计入 total 不计 blocked），
    防脏数据系统性虚高拦截数导致活跃闸被误判折旧信号。
    """
    base = tmp_path / "gate_trigger_counts.jsonl"

    def _dirty(ok_value=None, include_ok=True):
        rec = {"ts": "2026-08-25T00:00:00+00:00", "epoch": 1.0,
               "rule_id": "platform.gen_confirm", "layer": "platform",
               "action": "", "overridden": False}
        if include_ok:
            rec["ok"] = ok_value
        return json.dumps(rec, ensure_ascii=False)

    base.write_text(
        _count_line("platform.gen_confirm", ok=False)  # 唯一真拦截
        + "\n" + _dirty(include_ok=False)              # ok 缺失 → 放行
        + "\n" + _dirty(ok_value=None)                 # ok=null → 放行
        + "\n" + _dirty(ok_value="no")                 # 脏值 → 放行
        + "\n", encoding="utf-8")
    stats = trigger_count_stats(base)
    assert stats["platform.gen_confirm"] == {
        "total": 4, "blocked": 1, "overridden": 0}


# ---------- 任务#4：超期未裁决点名口径 ----------

def _epoch_line(rule_id: str, epoch: float) -> str:
    return json.dumps({"ts": "2026-01-01T00:00:00+00:00", "epoch": epoch,
                       "rule_id": rule_id, "ok": True, "layer": "skill",
                       "action": "", "overridden": False},
                      ensure_ascii=False)


def test_telemetry_window_short_span_insufficient(tmp_path):
    """遥测只有数天数据 → 数据不足，不得据零点名单降级候选。"""
    base = tmp_path / "gate_trigger_counts.jsonl"
    day = 86400.0
    base.write_text(_epoch_line("platform.gen_confirm", 1_700_000_000.0)
                    + "\n" + _epoch_line("platform.gen_confirm",
                                         1_700_000_000.0 + 2 * day)
                    + "\n", encoding="utf-8")
    win = telemetry_window(base)
    assert 1.9 < win["days"] < 2.1
    assert win["sufficient"] is False


def test_telemetry_window_long_span_sufficient(tmp_path):
    """观测窗满两季审计周期（≥ 182 天）→ 降级候选可计算。"""
    base = tmp_path / "gate_trigger_counts.jsonl"
    day = 86400.0
    base.write_text(_epoch_line("platform.gen_confirm", 1_700_000_000.0)
                    + "\n" + _epoch_line("platform.gen_confirm",
                                         1_700_000_000.0 + 200 * day)
                    + "\n", encoding="utf-8")
    win = telemetry_window(base)
    assert win["days"] >= MIN_OBSERVATION_DAYS
    assert win["sufficient"] is True


def test_telemetry_window_empty_ledger_insufficient(tmp_path):
    """账本不存在/无有效记录 → days=0 且数据不足（不报错不虚构）。"""
    win = telemetry_window(tmp_path / "gate_trigger_counts.jsonl")
    assert win == {"days": 0.0, "start": "", "end": "", "sufficient": False}


def test_zero_trigger_candidates_excludes_safe_and_active():
    """降级候选 = 注册表 − 有触发 − 安全豁免；安全类永不进候选。"""
    registry = {"skill.a": 1, "skill.b": 2, "platform.tool_risk": 3}
    cstats = {"skill.a": {"total": 3, "blocked": 0, "overridden": 0}}
    cands = zero_trigger_candidates(
        cstats, registry=registry,
        safe=frozenset({"platform.tool_risk"}))
    assert cands == ["skill.b"]  # skill.a 有触发；安全类豁免；只剩 skill.b


def test_zero_trigger_candidates_all_safe_is_empty():
    """零触发清单全是安全类闸 → 候选为空（零触发是常态非折旧信号）。"""
    registry = {rid: rid for rid in SAFE_RUNTIME_RULES}
    assert zero_trigger_candidates({}, registry=registry) == []


def test_pending_rulings_overdue_threshold():
    """登记超半年点名、未满半年不点名、日期不可解析跳过（不虚构）。"""
    today = datetime.date(2026, 8, 28)
    items = (
        ("gate.x 退役复核", "2025-12-01", "复设条件 X"),   # 270 天前 → 超期
        ("gate.y 退役复核", "2026-08-20", "复设条件 Y"),   # 8 天前 → 未超
        ("gate.z 登记日脏值", "not-a-date", "复设条件 Z"),  # 跳过
    )
    overdue = pending_rulings_overdue(items=items, today=today)
    assert [name for name, _, _ in overdue] == ["gate.x 退役复核"]


def test_pending_rulings_default_registry_empty():
    """生产登记台账为空属正常态（存量已随既有退役/合并裁决清偿），不虚构超期。"""
    assert pending_rulings_overdue() == []
