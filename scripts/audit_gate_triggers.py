# -*- coding: utf-8 -*-
"""门禁触发盘点（审核整改批 7：治理资产折旧，只读报表）。

防「治理机器自身成为臃肿源」：统计每个闸机规则/门禁最近实际拦到过什么，
为折旧决策（连续 N 轮零触发 → 降级软警告）提供数据。本脚本只读、幂等，
不修改任何门禁行为。

两类门禁：
1. 运行时闸机（GATE_RULES，trace 可观测）：从 data/agent_traces.jsonl 的
   steps[].gates 聚合 rule_id × (判定总数/拦截数/放行覆盖数)；
   trace 账本写满即轮转（agent_traces.jsonl.1 / .2 …），本脚本 glob
   agent_traces.jsonl* 扫描全部轮转份，按轮转序号从旧到新
   （.2 → .1 → 主文件）顺序读取，防只读主文件导致触发统计系统性低估。
2. 遥测自动落盘（任务#3）：闸机判定出口（guard_pipeline.audit_verdicts）
   每次判定轻量 append 一行到 data/gate_trigger_counts.jsonl（字段：
   ts/rule_id/ok/skill/layer/action/overridden），替代原「每季度人工
   补录」；本脚本按 rule_id 汇总计数并输出注册表覆盖率，使「连续 N 轮
   零触发降档」成为可计算判定。脏行跳过，只读不写。
3. CI 棘轮门禁（scripts/check_*.py）：不在遥测旁路覆盖范围，仍输出清单表
   （触发情况由 CI 运行记录佐证，不再要求人工补录进本表）。

用法：python scripts/audit_gate_triggers.py   （输出 markdown 盘点表）
"""
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
TRACES = ROOT / "data" / "agent_traces.jsonl"
COUNTS = ROOT / "data" / "gate_trigger_counts.jsonl"
SCRIPTS = ROOT / "scripts"

# P5：注册表与归一化口径接入（统计侧归一，历史 trace 原始值不改写）
sys.path.insert(0, str(ROOT))
from src.video_agent.core.prompt_gates import (  # noqa: E402
    GATE_RULES,
    normalize_rule_id,
)

# 轮转份命名：主文件 agent_traces.jsonl + agent_traces.jsonl.N（N 越大越旧）
_ROTATION_RE = re.compile(r"^.*?\.jsonl\.(\d+)$")


def trace_files(traces: pathlib.Path = TRACES) -> list:
    """返回 trace 账本全部轮转份，按从旧到新排序（.2 → .1 → 主文件）。

    主文件（无 .N 后缀）是最新数据，排最后；轮转序号越大越旧，排越前。
    仅保留「主文件名 + 可选 .数字后缀」的正规轮转命名，过滤无关文件。
    """
    if not traces.parent.exists():
        return []
    base = traces.name
    found: list = []
    for p in traces.parent.glob(base + "*"):
        if not p.is_file():
            continue
        if p.name == base:
            found.append((0, p))  # 主文件：最新
            continue
        m = _ROTATION_RE.match(p.name) if p.name.startswith(base + ".") else None
        if m:
            found.append((int(m.group(1)), p))
    # 序号大的（更旧）排前；主文件序号记 0 排最后
    found.sort(key=lambda t: -t[0])
    return [p for _, p in found]


def runtime_gate_stats(traces: pathlib.Path = TRACES) -> dict:
    """归一 rule_id → {total, blocked, overridden, raw_ids}。

    只读扫描 trace 账本全部轮转份；统计口径经 normalize_rule_id 归一
    （P5），原始签发值保留在 raw_ids 供报表并列展示，防口径断裂。"""
    stats: dict = {}
    files = trace_files(traces)
    if not files:
        return stats
    for path in files:
        _accumulate_from_file(path, stats)
    return stats


def _accumulate_from_file(path: pathlib.Path, stats: dict) -> None:
    """逐行解析单个 trace 文件并累计闸机判定计数（脏行跳过）。"""
    with path.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                trace = json.loads(line)
            except json.JSONDecodeError:
                continue
            for step in trace.get("steps") or []:
                for g in step.get("gates") or []:
                    raw = str(g.get("rule_id") or "?")
                    rid = normalize_rule_id(raw)
                    s = stats.setdefault(
                        rid, {"total": 0, "blocked": 0, "overridden": 0,
                              "raw_ids": set()})
                    s["raw_ids"].add(raw)
                    s["total"] += 1
                    if not g.get("ok", True):
                        s["blocked"] += 1
                    if g.get("overridden"):
                        s["overridden"] += 1


def ci_gate_inventory() -> list:
    """scripts/check_*.py 棘轮门禁清单（不在遥测旁路覆盖范围）。"""
    return sorted(p.name for p in SCRIPTS.glob("check_*.py"))


def count_files(counts: pathlib.Path = COUNTS) -> list:
    """遥测计数文件全部份（主文件 + 可选 .N 轮转份，旧→新）。

    当前旁路只写主文件无轮转；兼容 .N 命名以防后续引入轮转时
    统计口径再次断裂（同 trace_files 思路）。"""
    if not counts.parent.exists():
        return []
    base = counts.name
    found: list = []
    for p in counts.parent.glob(base + "*"):
        if not p.is_file():
            continue
        if p.name == base:
            found.append((0, p))
            continue
        m = _ROTATION_RE.match(p.name) if p.name.startswith(base + ".") else None
        if m:
            found.append((int(m.group(1)), p))
    found.sort(key=lambda t: -t[0])
    return [p for _, p in found]


def trigger_count_stats(counts: pathlib.Path = COUNTS) -> dict:
    """遥测旁路汇总：归一 rule_id → {total, blocked, overridden}。

    数据源 = data/gate_trigger_counts.jsonl（闸机判定出口自动落盘）；
    脏行/缺字段行跳过，rule_id 经 normalize_rule_id 归一（同 trace 口径）。"""
    stats: dict = {}
    for path in count_files(counts):
        with path.open("r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(rec, dict) or not rec.get("rule_id"):
                    continue
                rid = normalize_rule_id(str(rec["rule_id"]))
                s = stats.setdefault(
                    rid, {"total": 0, "blocked": 0, "overridden": 0})
                s["total"] += 1
                # 脏数据口径收紧：仅显式 ok=False 计拦截，缺字段/脏值按放行
                if rec.get("ok") is False:
                    s["blocked"] += 1
                if rec.get("overridden"):
                    s["overridden"] += 1
    return stats


def main() -> int:
    print("# 门禁触发盘点（只读报表）")
    print()
    print("## 一、运行时闸机（数据源：data/agent_traces.jsonl 全部轮转份）")
    print()
    files = trace_files()
    if files:
        print(f"> 扫描 {len(files)} 个 trace 文件（旧→新）："
              + " → ".join(p.name for p in files))
        print()
    stats = runtime_gate_stats()
    if not stats:
        print("（trace 账本无闸机判定记录）")
    else:
        print("| rule_id（归一） | 原始签发值 | 判定总数 | 拦截数 "
              "| 放行覆盖数 | 折旧提示 |")
        print("|---|---|---|---|---|---|")
        for rid in sorted(stats):
            s = stats[rid]
            hint = "零拦截，候选降级评估" if s["blocked"] == 0 else ""
            raw = " / ".join(sorted(s.get("raw_ids") or {rid}))
            print(f"| {rid} | {raw} | {s['total']} | {s['blocked']} "
                  f"| {s['overridden']} | {hint} |")
    print()
    print("### 注册表对账（GATE_RULES vs trace 实际活跃）")
    print()
    registry_ids = set(GATE_RULES)
    active_ids = set(stats)
    unregistered = sorted(active_ids - registry_ids)
    zero_sample = sorted(registry_ids - active_ids)
    if unregistered:
        print(f"- ⚠ 实际活跃但未登记进注册表：{', '.join(unregistered)}")
    else:
        print("- 实际活跃规则全部在注册表内（对账通过）")
    print(f"- 零样本清单（注册表 {len(registry_ids)} 条，活跃 "
          f"{len(active_ids & registry_ids)} 条，零触发 "
          f"{len(zero_sample)} 条）：")
    for rid in zero_sample:
        meta = GATE_RULES[rid]
        print(f"  - {rid}（{meta.layer}）：{meta.description}")
    print()
    print("## 二、遥测自动落盘（数据源：data/gate_trigger_counts.jsonl，"
          "guard_pipeline.audit_verdicts 判定出口自动 append）")
    print()
    cfiles = count_files()
    if cfiles:
        print(f"> 扫描 {len(cfiles)} 个计数文件（旧→新）："
              + " → ".join(p.name for p in cfiles))
        print()
    cstats = trigger_count_stats()
    if not cstats:
        print("（遥测账本无记录：尚未产生判定，或落盘刚启用）")
    else:
        print("| rule_id（归一） | 判定总数 | 拦截数 | 放行覆盖数 | 折旧提示 |")
        print("|---|---|---|---|---|")
        for rid in sorted(cstats):
            s = cstats[rid]
            hint = "零拦截，候选降级评估" if s["blocked"] == 0 else ""
            print(f"| {rid} | {s['total']} | {s['blocked']} "
                  f"| {s['overridden']} | {hint} |")
    print()
    registry_ids = set(GATE_RULES)
    covered = set(cstats) & registry_ids
    total_rules = len(registry_ids)
    rate = (len(covered) * 100.0 / total_rules) if total_rules else 0.0
    print(f"- 注册表覆盖率：{len(covered)}/{total_rules}"
          f"（{rate:.1f}%）条规则在遥测账本中有判定记录")
    zero = sorted(registry_ids - set(cstats))
    if zero:
        print(f"- 遥测零触发清单（{len(zero)} 条）：" + "、".join(zero))
    print()
    print("## 三、CI 棘轮门禁清单（不在遥测旁路覆盖范围，触发情况"
          "由 CI 运行记录佐证，不再人工补录进本表）")
    print()
    print("| 门禁脚本 |")
    print("|---|")
    for name in ci_gate_inventory():
        print(f"| scripts/{name} |")
    print()
    print("> 折旧规则见 docs/脚手架折旧规程.md 第五节：连续 N 轮零触发的门禁"
          "降级为软警告（保留不删）并下账 scaffold_registry。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
