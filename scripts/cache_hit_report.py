# -*- coding: utf-8 -*-
"""前缀缓存命中率报告（指令收拢与缓存稳定批 D1，只读诊断）。

读 data/cache_metrics.jsonl（live_metrics._persist_cache_sample 落盘的
{ts, project_id, prompt_tokens, cached_tokens}），按项目分组输出：
- 全量命中率（cached/prompt token 加权）；
- 稳态命中率：剔除每项目首个请求（首调缓存全冷是设计内代价）与
  稳态未形成前的预热请求（prompt 不足预热门槛时前缀占比过高的噪声）；
- 逐请求明细（最近 --tail 条/项目）。

验收口径（计划书 §批 D）：新项目连跑 5+ 轮后，稳态命中率 ≥95%，人工判定。
不做 CI 机械闸：命中率依赖真实流量，CI 无数据可判。

用法：
    python scripts/cache_hit_report.py                # 全项目汇总
    python scripts/cache_hit_report.py --tail 8       # 每项目最近 8 条明细
    python scripts/cache_hit_report.py --project proj-xxx
"""
import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.video_agent.utils.paths import CACHE_METRICS_FILE  # noqa: E402

# 稳态预热门槛：prompt 低于该值的请求视为预热噪声（system 静态核心尚未
# 被历史稀释，命中率天然偏低，不计入稳态口径）
WARMUP_PROMPT_TOKENS = 12_000


def _load_rows(path: Path):
    if not path.exists():
        print(f"[cache_hit_report] 未找到指标文件：{path}（先跑一轮真实对话再来看）")
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if r.get("prompt_tokens"):
            rows.append(r)
    rows.sort(key=lambda r: r.get("ts", 0))
    return rows


def _weighted_hit(samples):
    total = sum(r["prompt_tokens"] for r in samples)
    hit = sum(r["cached_tokens"] for r in samples)
    return (100.0 * hit / total) if total else 0.0, len(samples)


def main() -> int:
    ap = argparse.ArgumentParser(description="前缀缓存命中率报告（只读）")
    ap.add_argument("--tail", type=int, default=0, help="每项目最近 N 条逐请求明细")
    ap.add_argument("--project", default="", help="只看指定 project_id")
    args = ap.parse_args()

    rows = [r for r in _load_rows(CACHE_METRICS_FILE)
            if not args.project or r.get("project_id") == args.project]
    if not rows:
        return 1

    by_project = defaultdict(list)
    for r in rows:
        by_project[r["project_id"]].append(r)

    overall, _ = _weighted_hit(rows)
    print(f"=== 前缀缓存命中率报告（{CACHE_METRICS_FILE.name}，{len(rows)} 样本）===")
    print(f"全量命中率：{overall:.1f}%\n")

    steady_all = []
    for pid, rs in by_project.items():
        steady = [r for r in rs[1:] if r["prompt_tokens"] >= WARMUP_PROMPT_TOKENS]
        rate, n = _weighted_hit(steady)
        steady_all.extend(steady)
        flag = "PASS" if (n >= 5 and rate >= 95.0) else ("WARM" if n < 5 else "MISS")
        print(f"[{flag}] {pid}  样本 {len(rs)}（稳态 {n}）  "
              f"全量 {(_weighted_hit(rs))[0]:.1f}%  稳态 {rate:.1f}%")
        if args.tail:
            for r in rs[-args.tail:]:
                rate1 = 100.0 * r["cached_tokens"] / r["prompt_tokens"]
                print(f"    ts={r.get('ts', 0):.0f}  prompt={r['prompt_tokens']:>6}  "
                      f"cached={r['cached_tokens']:>6}  ({rate1:5.1f}%)")
        if flag == "MISS":
            misses = [(r["prompt_tokens"], r["cached_tokens"]) for r in steady
                      if r["cached_tokens"] == 0]
            if misses:
                print(f"    ↳ 稳态 0 命中 {len(misses)} 次（prompt={misses[:3]}...），"
                      "检查是否前缀被改写：tools_fp / system 条件段 / 历史装载")
        print()

    s_rate, s_n = _weighted_hit(steady_all)
    print(f"稳态总口径（剔除每项目首调与 <{WARMUP_PROMPT_TOKENS} tokens 预热）："
          f"{s_rate:.1f}%（{s_n} 样本）  验收线 ≥95%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
