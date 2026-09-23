# -*- coding: utf-8 -*-
"""Q8 统计 v2（只读）：按「消息段」统计每步 reasoning 字数 / 工具调用 / 生成耗时。

口径（稳健定义，避免 step 号跨轮重复导致归并）：
- **段** = 相邻两条 `assistant/message` 之间的全部记录。一条 `assistant/message`
  即一次 LLM 响应 = 一个 step；其 reasoning 字数取 `reasoning_content` 长度
  （与同段 `assistant/partial(kind=reasoning)` 拼接**逐字相等**，已抽样验证），
  缺失时回落拼接 partial；工具调用数 = `tool_calls` 条数。
- LLM 生成耗时 ≈ `assistant/message.time` − 本段首条 partial 的 `time`
  （首 token 到消息结束）。
- 步间隔（工具执行 + 框架开销）≈ 下一步首条 partial 的 `time` − 本步 `message.time`。
- 轮（turn）边界取 `turn/start` / `turn/end`。
"""
import io
import json
import os
import sys
import time as _time

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
    return _time.strftime("%H:%M:%S", _time.localtime(t)) if t else "-"


def analyze(path, name, proj):
    recs = load(path)
    out = []
    role = "MAIN" if name == "conv-main.jsonl" else "SUB"

    # 分段
    segs = []
    cur = {"recs": [], "msg": None}
    for r in recs:
        if r.get("type") == "assistant/message":
            cur["msg"] = r
            cur["recs"].append(r)
            segs.append(cur)
            cur = {"recs": [], "msg": None}
        else:
            cur["recs"].append(r)
    if cur["recs"]:
        segs.append(cur)

    # 轮边界
    turns = []
    for i, r in enumerate(recs):
        if r.get("type") == "turn/start":
            turns.append({"n": r.get("turn"), "t0": r.get("time"), "t1": None,
                          "seg_idx": []})
        elif r.get("type") == "turn/end" and turns:
            turns[-1]["t1"] = r.get("time")
    # 段 → 轮：按时间落位
    ti = 0
    rows = []
    for si, s in enumerate(segs):
        m = s["msg"]
        if m is None:
            continue
        partials = [r for r in s["recs"] if r.get("type") == "assistant/partial"
                    and r.get("time")]
        t_first = partials[0]["time"] if partials else m.get("time")
        t_msg = m.get("time")
        rc = m.get("reasoning_content")
        if rc is None:
            rc = "".join(str(p.get("text") or "") for p in partials
                         if p.get("kind") == "reasoning")
        calls = m.get("tool_calls") or []
        names = [str((c.get("function") or {}).get("name") or "?") for c in calls]
        results = [r for r in s["recs"] if r.get("type") == "tool/result"]
        usage = m.get("usage") or {}
        # 归属轮
        while ti < len(turns) - 1 and turns[ti]["t1"] and t_first and t_first > turns[ti]["t1"]:
            ti += 1
        turn = turns[ti]["n"] if turns else None
        if turns:
            turns[ti]["seg_idx"].append(si)
        rows.append({
            "si": si, "turn": turn, "t_first": t_first, "t_msg": t_msg,
            "reason": len(str(rc or "")), "text": len(str(m.get("content") or "")),
            "calls": len(calls), "names": names, "results": len(results),
            "comp": usage.get("completion_tokens"),
        })
    # 后处理耗时
    for i, r in enumerate(rows):
        r["gen"] = round(r["t_msg"] - r["t_first"], 1) if (r["t_msg"] and r["t_first"]) else None
        nxt = rows[i + 1]["t_first"] if i + 1 < len(rows) else None
        r["gap"] = round(nxt - r["t_msg"], 1) if (nxt and r["t_msg"]) else None
        r["tps"] = round(r["comp"] / r["gen"], 1) if (r["gen"] and r["comp"]) else None
    times = [r.get("time") for r in recs if r.get("time")]
    wall = round(max(times) - min(times), 1) if times else 0
    tot_reason = sum(r["reason"] for r in rows)
    tot_calls = sum(r["calls"] for r in rows)
    top5 = sorted(rows, key=lambda r: -r["reason"])[:5]

    out.append("=" * 112)
    out.append(f"[{proj}/{role}] {name}  段(步)={len(rows)} 轮={len(turns)} "
               f"总工具调用={tot_calls} 平均调用/步={round(tot_calls/len(rows),2) if rows else 0} "
               f"总推理字数={tot_reason} 会话墙钟={wall}s")
    out.append(f"  前 5 大推理步 = {[(r['si'], r['reason'], r['calls']) for r in top5]}"
               f"  占全部推理 {round(sum(r['reason'] for r in top5)/tot_reason, 3) if tot_reason else 0}")
    for t in turns:
        if t["t0"] and t["t1"]:
            out.append(f"  -- 轮 {t['n']}: {fmt(t['t0'])}→{fmt(t['t1'])} 墙钟={round(t['t1']-t['t0'],1)}s "
                       f"含步={len(t['seg_idx'])}")
    out.append(f"  {'段':>4} {'轮':>3} {'起':>9} {'reason':>7} {'text':>6} {'calls':>5} "
               f"{'res':>4} {'生成s':>7} {'步间隔s':>8} {'tok/s':>6}  工具")
    for r in rows:
        out.append(f"  {r['si']:>4} {str(r['turn']):>3} {fmt(r['t_first']):>9} "
                   f"{r['reason']:>7} {r['text']:>6} {r['calls']:>5} {r['results']:>4} "
                   f"{str(r['gen']):>7} {str(r['gap']):>8} {str(r['tps']):>6}  "
                   f"{','.join(r['names'])[:70]}")
    return out, {"proj": proj, "role": role, "file": name, "steps": len(rows),
                 "turns": len(turns), "calls": tot_calls, "reason": tot_reason,
                 "wall": wall,
                 "avg": round(tot_calls / len(rows), 2) if rows else 0,
                 "max_reason": max((r["reason"] for r in rows), default=0),
                 "top5_share": round(sum(r["reason"] for r in top5) / tot_reason, 3) if tot_reason else 0}


def main():
    lines, sums = [], []
    for proj, pid in TARGETS:
        d = os.path.join(SESS, pid)
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if not fn.endswith(".jsonl"):
                continue
            out, s = analyze(os.path.join(d, fn), fn, proj)
            lines.extend(out)
            sums.append(s)
    lines.append("=" * 112)
    lines.append("SUMMARY")
    lines.append(f"{'proj':>5} {'role':>5} {'file':>34} {'步':>4} {'轮':>4} {'调用':>5} "
                 f"{'均/步':>6} {'推理字数':>9} {'最大步':>7} {'墙钟s':>7} {'top5占比':>8}")
    for s in sums:
        lines.append(f"{s['proj']:>5} {s['role']:>5} {s['file']:>34} {s['steps']:>4} "
                     f"{s['turns']:>4} {s['calls']:>5} {s['avg']:>6} {s['reason']:>9} "
                     f"{s['max_reason']:>7} {s['wall']:>7} {s['top5_share']:>8}")
    text = "\n".join(lines)
    dest = os.path.join("reports", "2222-3333-事故根因-20260923", "_work", "stats_v2.txt")
    with io.open(dest, "w", encoding="utf-8") as f:
        f.write(text)
    sys.stdout.write(text[:120] + "\n...\n(written %s, %d chars)\n" % (dest, len(text)))


if __name__ == "__main__":
    main()
