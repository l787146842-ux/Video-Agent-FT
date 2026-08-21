# -*- coding: utf-8 -*-
"""门禁触发盘点（审核整改批 7：治理资产折旧，只读报表）。

防「治理机器自身成为臃肿源」：统计每个闸机规则/门禁最近实际拦到过什么，
为折旧决策（连续 N 轮零触发 → 降级软警告）提供数据。本脚本只读、幂等，
不修改任何门禁行为。

两类门禁：
1. 运行时闸机（GATE_RULES，trace 可观测）：从 data/agent_traces.jsonl 的
   steps[].gates 聚合 rule_id × (判定总数/拦截数/放行覆盖数)；
2. CI 棘轮门禁（scripts/check_*.py）：触发计数不自动持久化，输出清单表，
   由季度审计按 acceptance 运行记录人工补录「近 N 轮触发次数」。

用法：python scripts/audit_gate_triggers.py   （输出 markdown 盘点表）
"""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
TRACES = ROOT / "data" / "agent_traces.jsonl"
SCRIPTS = ROOT / "scripts"


def runtime_gate_stats() -> dict:
    """rule_id → {total, blocked, overridden}（只读扫描 trace 账本）。"""
    stats: dict = {}
    if not TRACES.exists():
        return stats
    with TRACES.open("r", encoding="utf-8", errors="ignore") as f:
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
                    rid = str(g.get("rule_id") or "?")
                    s = stats.setdefault(
                        rid, {"total": 0, "blocked": 0, "overridden": 0})
                    s["total"] += 1
                    if not g.get("ok", True):
                        s["blocked"] += 1
                    if g.get("overridden"):
                        s["overridden"] += 1
    return stats


def ci_gate_inventory() -> list:
    """scripts/check_*.py 棘轮门禁清单（触发计数待季度审计人工补录）。"""
    return sorted(p.name for p in SCRIPTS.glob("check_*.py"))


def main() -> int:
    print("# 门禁触发盘点（只读报表）")
    print()
    print("## 一、运行时闸机（数据源：data/agent_traces.jsonl）")
    print()
    stats = runtime_gate_stats()
    if not stats:
        print("（trace 账本无闸机判定记录）")
    else:
        print("| rule_id | 判定总数 | 拦截数 | 放行覆盖数 | 折旧提示 |")
        print("|---|---|---|---|---|")
        for rid in sorted(stats):
            s = stats[rid]
            hint = "零拦截，候选降级评估" if s["blocked"] == 0 else ""
            print(f"| {rid} | {s['total']} | {s['blocked']} "
                  f"| {s['overridden']} | {hint} |")
    print()
    print("## 二、CI 棘轮门禁清单（触发计数按季度审计人工补录）")
    print()
    print("| 门禁脚本 | 近 N 轮触发次数（人工补录） |")
    print("|---|---|")
    for name in ci_gate_inventory():
        print(f"| scripts/{name} | |")
    print()
    print("> 折旧规则见 docs/脚手架折旧规程.md 第五节：连续 N 轮零触发的门禁"
          "降级为软警告（保留不删）并下账 scaffold_registry。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
