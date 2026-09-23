# -*- coding: utf-8 -*-
import json, io, sys
f = r"data\sse_capture\sse-1790055387-442383df-deepseek-v4-flash-0731.jsonl"
deltas = []   # list of (chunk_idx, text)
for l in open(f, encoding="utf-8"):
    l = l.strip()
    if not l: continue
    o = json.loads(l)
    if "__chunk__" not in o: continue
    r = o.get("raw", "")
    if not r.startswith("{"): continue
    try: d = json.loads(r)
    except: continue
    for ch in d.get("choices") or []:
        dl = ch.get("delta") or {}
        if "reasoning_content" in dl and dl["reasoning_content"]:
            deltas.append((o["__chunk__"], dl["reasoning_content"]))

acc = ""
needle = "为了效率"
found_at = None
for idx, (ci, t) in enumerate(deltas):
    prev = len(acc)
    acc += t
    if needle in acc and found_at is None and acc.find(needle) >= prev - 5:
        found_at = (idx, ci, prev, acc.find(needle), t)

out = io.StringIO()
out.write("reasoning delta 段数 = %d\n" % len(deltas))
out.write("拼接总长 = %d\n" % len(acc))
out.write("\n定位「为了效率」（跨 delta 边界处）：\n")
pos = acc.find(needle)
out.write("  在拼接串中的下标 = %d\n" % pos)
for idx, (ci, t) in enumerate(deltas):
    start = sum(len(x[1]) for x in deltas[:idx])
    end = start + len(t)
    if start <= pos < end or start < pos + 4 <= end:
        out.write("  delta#%d (chunk=%d) 覆盖 [%d,%d)：%r\n" % (idx, ci, start, end, t))
out.write("\n含「为了效率」的 delta 是否单独含完整四字？\n")
hit = [ (idx,ci,t) for idx,(ci,t) in enumerate(deltas) if needle in t ]
out.write("  逐 delta 内完整含该四字的 delta 数 = %d\n" % len(hit))
out.write("\n前 6 个 reasoning delta：\n")
for idx,(ci,t) in enumerate(deltas[:6]):
    out.write("  delta#%d chunk=%d len=%d %r\n" % (idx, ci, len(t), t))
out.write("\n【关键】拼接串 == jsonl LINE8.reasoning_content ? 需另比对\n")
# 找 8 号 LINE 的 reasoning 拼接切点
import json as J
P = r"workspace\sessions\proj-1790055373-bf5a358b\conv-main.jsonl"
lines=[x for x in open(P,encoding="utf-8").read().split("\n") if x.strip()]
o8=J.loads(lines[7]); rc=o8["reasoning_content"]
out.write("  jsonl LINE8.reasoning_content len=%d ; SSE 拼接 len=%d ; 相等=%s\n" % (len(rc), len(acc), rc==acc))
o5=J.loads(lines[4]); o6=J.loads(lines[5])
a,b=o5["text"],o6["text"]
out.write("  LINE5.text(%d)+LINE6.text(%d)=%d == rc ? %s\n" % (len(a),len(b),len(a)+len(b), (a+b)==rc))
out.write("  LINE5.text 在 SSE 拼接中的边界 = [0,%d)\n" % len(a))
# 该边界处是哪个 delta
for idx,(ci,t) in enumerate(deltas):
    start = sum(len(x[1]) for x in deltas[:idx]); end=start+len(t)
    if start < len(a) <= end:
        out.write("  → LINE5/LINE6 切点落在 delta#%d (chunk=%d, 覆盖[%d,%d)) 内部，delta 原文=%r\n" % (idx,ci,start,end,t))
sys.stdout.reconfigure(encoding="utf-8")
print(out.getvalue())
