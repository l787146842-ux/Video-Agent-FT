# -*- coding: utf-8 -*-
"""Q8 补充：轮/步墙钟与「超长推理」占比（只读）。

输出：
- 每个 turn 的起止时间与总时长；
- 每步 LLM 响应耗时（= 下一步首条记录时刻 − 本步首发 partial 时刻；末步用
  turn/end 或最终记录时刻兜底）；
- 每步「净输出 token 速率」估计（completion_tokens / 耗时）。
"""
import io
import json
import os
import sys

SESS = os.path.join("workspace", "sessions")
TARGETS = [
    ("2222", "proj-1790091531-97d20b2d"),
    ("3333", "proj-1790092267-a9abcb25"),
]


def load(path):
    out = []
    with io.open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except Exception:
                    pass
    return out


def fmt(t):
    if not t:
        return "-"
    import time
    return time.strftime("%H:%M:%S", time.localtime(t))


def main():
    lines = []
    for proj, pid in TARGETS:
        d = os.path.join(SESS, pid)
        for fn in sorted(os.listdir(d)):
            if not fn.endswith(".jsonl"):
                continue
            recs = load(os.path.join(d, fn))
            if not recs:
                continue
            role = "MAIN" if fn == "conv-main.jsonl" else "SUB"
            # 轮边界
            turns = []
            cur = None
            for r in recs:
                if r.get("type") == "turn/start":
                    cur = {"turn": r.get("turn"), "t0": r.get("time"),
                           "steps": [], "t1": None}
                    turns.append(cur)
                elif r.get("type") == "turn/end":
                    if cur is not None:
                        cur["t1"] = r.get("time")
                    else:
                        turns.append({"turn": r.get("turn"), "t0": None,
                                      "steps": [], "t1": r.get("time")})
                        cur = turns[-1]
            if not turns:
                turns = [{"turn": None, "t0": None, "steps": [], "t1": None}]
            # 步归属：按顺序把 assistant/message 分配到当前 turn
            idx = 0
            for r in recs:
                if r.get("type") == "assistant/message":
                    while idx < len(turns) - 1 and turns[idx].get("t1") is not None:
                        idx += 1
                    turns[idx]["steps"].append(r)
            # 每步耗时：用全局时间序中下一条 step 的首发 partial 或 turn/end
            all_msgs = [(i, r) for i, r in enumerate(recs)
                        if r.get("type") == "assistant/message"]
            # 首发 partial 映射 step -> time
            first_partial = {}
            for r in recs:
                if r.get("type") == "assistant/partial":
                    st = r.get("step")
                    if st not in first_partial and r.get("time"):
                        first_partial[st] = r.get("time")
            lines.append("=" * 104)
            lines.append(f"[{proj}/{role}] {fn}")
            for t in turns:
                if t["t0"] and t["t1"]:
                    lines.append(f"  turn={t['turn']}  {fmt(t['t0'])}→{fmt(t['t1'])}  "
                                 f"墙钟={round(t['t1']-t['t0'],1)}s  steps={len(t['steps'])}")
                for i, m in enumerate(t["steps"]):
                    st = m.get("step")
                    usage = m.get("usage") or {}
                    ct = usage.get("completion_tokens")
                    # 下一步起始
                    nxt = None
                    gi = [j for j, r in all_msgs if r is m]
                    if gi:
                        k = gi[0]
                        if k + 1 < len(all_msgs):
                            nm = all_msgs[k + 1][1]
                            nxt = first_partial.get(nm.get("step"))
                    t0 = first_partial.get(st) or m.get("time")
                    lat = round(nxt - t0, 1) if (nxt and t0) else None
                    tps = round(ct / lat, 1) if (lat and ct) else None
                    calls = [c.get("function", {}).get("name") for c in (m.get("tool_calls") or [])]
                    lines.append(
                        f"    step={st:<3} 起={fmt(t0)} LLM耗时≈{str(lat):>6}s "
                        f"reason={len(m.get('reasoning_content') or ''):>6} "
                        f"text={len(m.get('content') or ''):>5} "
                        f"calls={len(calls):>2} comp_tok={ct} tok/s={tps}  {','.join(x or '?' for x in calls)[:70]}")
    text = "\n".join(lines)
    dest = os.path.join("reports", "2222-3333-事故根因-20260923", "_work", "stats_turns.txt")
    with io.open(dest, "w", encoding="utf-8") as f:
        f.write(text)
    sys.stdout.write(text[:150] + "\n...\n(written %s, %d chars)\n" % (dest, len(text)))


if __name__ == "__main__":
    main()
