# -*- coding: utf-8 -*-
import os, json, glob, io, sys, re
root = r"workspace\sessions"
out = io.StringIO()
hits = []
for dirpath, dirnames, filenames in os.walk(root):
    for fn in filenames:
        if not fn.endswith(".jsonl"): continue
        fp = os.path.join(dirpath, fn)
        try:
            txt = open(fp, encoding="utf-8").read()
        except Exception: continue
        if "为了效率" not in txt: continue
        proj = os.path.basename(dirpath)
        # 逐行定位
        recs = []
        for i, l in enumerate(txt.split("\n"), 1):
            if not l.strip(): continue
            if "为了效率" in l:
                try: o = json.loads(l)
                except: o = {}
                for k in ("text", "content", "reasoning_content"):
                    v = o.get(k)
                    if isinstance(v, str) and "为了效率" in v:
                        j = v.find("为了效率")
                        recs.append((i, o.get("type"), k, v[max(0,j-70):j+90].replace("\n"," ")))
        hits.append((proj, fn, recs))

out.write("含「为了效率」的会话文件数 = %d\n\n" % len(hits))
for proj, fn, recs in sorted(hits):
    out.write("### %s / %s  （命中记录 %d 条）\n" % (proj, fn, len(recs)))
    for i, t, k, ctx in recs:
        out.write("    LINE %-4s type=%-18s field=%-18s …%s…\n" % (i, t, k, ctx))
    out.write("\n")
sys.stdout.reconfigure(encoding="utf-8")
print(out.getvalue())
