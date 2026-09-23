# -*- coding: utf-8 -*-
import json, sys, io, os
P = r"workspace\sessions\proj-1790055373-bf5a358b\conv-main.jsonl"
with open(P, "r", encoding="utf-8") as f:
    lines = [l for l in f.read().split("\n") if l.strip()]
out = io.StringIO()
out.write("conv-main.jsonl 全部记录类型统计 + 是否含 system/prompt 类字段\n")
from collections import Counter
c = Counter()
allsys = 0
for n, l in enumerate(lines, 1):
    o = json.loads(l)
    c[o.get("type")] += 1
    for k, v in o.items():
        if isinstance(v, str) and ("执行铁律" in v or "Skill 流程纪律" in v or "DISCIPLINE" in v):
            out.write("  !! LINE %d field %s 含铁律/纪律关键词\n" % (n, k))
        if k in ("system", "system_prompt", "prompt", "prompts"):
            out.write("  !! LINE %d 含字段 %s\n" % (n, k))
for k, v in c.most_common():
    out.write("  type=%s : %d\n" % (k, v))
out.write("\n LINE 3/4 的 source 值：\n")
for n in (3, 4):
    o = json.loads(lines[n-1]); out.write("  LINE %d source=%r\n" % (n, o.get("source")))
out.write("\n 各 jsonl 记录类型：\n")
import glob
for p in sorted(glob.glob(r"workspace\sessions\proj-1790055373-bf5a358b\*.jsonl")):
    cc = Counter()
    with open(p, "r", encoding="utf-8") as f:
        for l in f:
            if l.strip():
                cc[json.loads(l).get("type")] += 1
    out.write("  %s -> %s\n" % (os.path.basename(p), dict(cc)))
sys.stdout.reconfigure(encoding="utf-8")
print(out.getvalue())
