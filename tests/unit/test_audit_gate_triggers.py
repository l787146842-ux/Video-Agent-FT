# -*- coding: utf-8 -*-
"""audit_gate_triggers 轮转扫描单测（任务#10）。

钉死契约：
- trace 账本写满即轮转（agent_traces.jsonl → .1 → .2），盘点必须扫描全部
  轮转份，防只读主文件导致闸机触发统计系统性低估（误拆活跃闸）；
- 读取顺序按轮转序号从旧到新：.2 → .1 → 主文件；
- 聚合计数逻辑（total/blocked/overridden）不变，脏行跳过；
- P5：统计口径经 normalize_rule_id 归一，原始签发值留痕在 raw_ids（防口径断裂）。
"""
import json
import pathlib

from scripts.audit_gate_triggers import runtime_gate_stats, trace_files


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


def test_stats_normalizes_alias_rule_ids(tmp_path: pathlib.Path):
    """P5：历史别名 rule_id 统计侧归一到注册表正式条目，原始值留痕 raw_ids。

    历史 trace 不改写：同一规则的新旧写法并入同一统计行，原始值并列可查。"""
    base = tmp_path / "agent_traces.jsonl"
    _write(base, [
        [_gate("storyboard_prompt_structure", ok=False)],  # 旧写法（历史留痕）
        [_gate("skill.prompt_structure", ok=False)],       # 正式 ID
    ])
    stats = runtime_gate_stats(base)
    assert "storyboard_prompt_structure" not in stats
    assert stats["skill.prompt_structure"] == {
        "total": 2, "blocked": 2, "overridden": 0,
        "raw_ids": {"storyboard_prompt_structure", "skill.prompt_structure"}}
