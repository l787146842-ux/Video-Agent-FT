# -*- coding: utf-8 -*-
"""Q8 统计：按「轮(step)」统计 reasoning 字数 vs 工具调用数（只读）。

口径：
- 轮 = assistant/message 记录（每次 LLM 响应 = 1 个 step）。
- 该轮 reasoning 字数 = assistant/message.reasoning_content 的长度
  （与同 step 的 assistant/partial(kind=reasoning) 拼接**逐字相等**，已验证）；
  缺 reasoning_content 时回落拼接 partial。
- 该轮工具调用数 = len(assistant/message.tool_calls)。
- 该轮正文长度 = len(content)。
- 该轮墙钟耗时 = 下一轮首条记录 time − 本轮首发 partial time（末轮用本记录 time）。
输出：每项目每会话的逐步明细 + 汇总。
"""
import io
import json
import os
import sys
from collections import Counter

SESS = os.path.join("workspace", "sessions")
TARGETS = [
    ("2222", "proj-1790091531-97d20b2d"),
    ("3333", "proj-1790092267-a9abcb25"),
]


def load(path):
    recs = []
    with io.open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                recs.append(json.loads(line))
            except Exception:
                pass
    return recs


def analyze(path, name):
    recs = load(path)
    if not recs:
        return None
    # 按 step 归组（保留出现顺序）
    steps = {}
    order = []
    for r in recs:
        st = r.get("step")
        if st is None:
            continue
        if st not in steps:
            steps[st] = {"partials": [], "msg": None, "results": [], "feedback": None,
                         "first_time": None, "lines": 0}
            order.append(st)
        s = steps[st]
        s["lines"] += 1
        if s["first_time"] is None and r.get("time"):
            s["first_time"] = r.get("time")
        t = r.get("type")
        if t == "assistant/partial":
            s["partials"].append(r)
        elif t == "assistant/message":
            s["msg"] = r
        elif t == "tool/result":
            s["results"].append(r)
        elif t == "step/feedback":
            s["feedback"] = r

    rows = []
    for st in order:
        s = steps[st]
        m = s["msg"] or {}
        rc = m.get("reasoning_content")
        if rc is None:
            rc = "".join(str(p.get("text") or "") for p in s["partials"]
                         if p.get("kind") == "reasoning")
        txt = m.get("content") or ""
        calls = m.get("tool_calls") or []
        names = []
        for c in calls:
            fn = (c or {}).get("function") or {}
            names.append(str(fn.get("name") or "?"))
        usage = m.get("usage") or {}
        rows.append({
            "step": st,
            "reason_chars": len(str(rc or "")),
            "text_chars": len(str(txt)),
            "n_calls": len(calls),
            "tool_names": names,
            "n_results": len(s["results"]),
            "result_names": [str(r.get("name") or "?") for r in s["results"]],
            "feedback_tool_count": (s["feedback"] or {}).get("tool_count"),
            "completion_tokens": usage.get("completion_tokens"),
            "prompt_tokens": usage.get("prompt_tokens"),
            "t0": s["first_time"],
            "t1": m.get("time"),
            "lines": s["lines"],
            "had_msg": s["msg"] is not None,
        })
    # 墙钟
    times = [r.get("time") for r in recs if r.get("time")]
    for i, row in enumerate(rows):
        nxt = rows[i + 1]["t0"] if i + 1 < len(rows) else row["t1"]
        if row["t0"] and nxt:
            row["wall"] = round(nxt - row["t0"], 1)
        else:
            row["wall"] = None
    tot_reason = sum(r["reason_chars"] for r in rows)
    tot_calls = sum(r["n_calls"] for r in rows)
    tot_wall = (max(times) - min(times)) if times else 0
    n_turns = sum(1 for r in recs if r.get("type") == "turn/start")
    summary = {
        "file": name,
        "records": len(recs),
        "n_steps": len(rows),
        "n_turns": n_turns,
        "total_tool_calls": tot_calls,
        "avg_calls_per_step": round(tot_calls / len(rows), 2) if rows else 0,
        "total_reason_chars": tot_reason,
        "max_reason_chars": max((r["reason_chars"] for r in rows), default=0),
        "max_reason_step": max(rows, key=lambda r: r["reason_chars"])["step"] if rows else None,
        "wall_seconds": round(tot_wall, 1),
        "tool_name_counter": dict(Counter(n for r in rows for n in r["tool_names"]).most_common()),
    }
    # 前 5 大推理轮占全部推理字数的比例
    top = sorted(rows, key=lambda r: -r["reason_chars"])[:5]
    summary["top5_reason_share"] = (
        round(sum(r["reason_chars"] for r in top) / tot_reason, 3) if tot_reason else 0)
    summary["top5_steps"] = [(r["step"], r["reason_chars"], r["n_calls"]) for r in top]
    return rows, summary


def main():
    out = []
    allsum = []
    for proj, pid in TARGETS:
        d = os.path.join(SESS, pid)
        if not os.path.isdir(d):
            out.append(f"!! missing {d}")
            continue
        out.append("=" * 110)
        out.append(f"PROJECT {proj} ({pid})")
        for fn in sorted(os.listdir(d)):
            if not fn.endswith(".jsonl"):
                continue
            got = analyze(os.path.join(d, fn), fn)
            if not got:
                continue
            rows, summary = got
            allsum.append((proj, summary))
            role = "MAIN" if fn == "conv-main.jsonl" else "SUB"
            out.append("-" * 110)
            out.append(f"[{proj}/{role}] {fn}  steps={summary['n_steps']} "
                       f"turns={summary['n_turns']} calls={summary['total_tool_calls']} "
                       f"avg/step={summary['avg_calls_per_step']} "
                       f"reason_total={summary['total_reason_chars']} "
                       f"wall={summary['wall_seconds']}s")
            out.append(f"{'step':>5} {'reason':>7} {'text':>6} {'calls':>5} {'res':>4} "
                       f"{'wall':>6} {'comp_tok':>8}  tools")
            for r in rows:
                out.append(f"{r['step']:>5} {r['reason_chars']:>7} {r['text_chars']:>6} "
                           f"{r['n_calls']:>5} {r['n_results']:>4} "
                           f"{str(r['wall']):>6} {str(r['completion_tokens']):>8}  "
                           f"{','.join(r['tool_names'][:8])}")
    out.append("=" * 110)
    out.append("SUMMARY (per session)")
    out.append(f"{'proj':>5} {'file':>34} {'steps':>6} {'turns':>6} {'calls':>6} "
               f"{'avg':>5} {'reason':>8} {'maxR':>7} {'maxR@':>6} {'wall_s':>8} "
               f"{'top5share':>9}")
    for proj, s in allsum:
        out.append(f"{proj:>5} {s['file']:>34} {s['n_steps']:>6} {s['n_turns']:>6} "
                   f"{s['total_tool_calls']:>6} {s['avg_calls_per_step']:>5} "
                   f"{s['total_reason_chars']:>8} {s['max_reason_chars']:>7} "
                   f"{str(s['max_reason_step']):>6} {s['wall_seconds']:>8} "
                   f"{s['top5_reason_share']:>9}")
        out.append(f"        top5 steps (step,reason_chars,calls) = {s['top5_steps']}")
        out.append(f"        tool histogram = {s['tool_name_counter']}")
    text = "\n".join(out)
    dest = os.path.join("reports", "2222-3333-事故根因-20260923", "_work", "stats_steps.txt")
    with io.open(dest, "w", encoding="utf-8") as f:
        f.write(text)
    sys.stdout.write(text[:200] + "\n...\n(written to %s, %d chars)\n" % (dest, len(text)))


if __name__ == "__main__":
    main()
