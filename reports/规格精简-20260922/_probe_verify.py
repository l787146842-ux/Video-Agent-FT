# -*- coding: utf-8 -*-
import json, io, sys, datetime, os
P = r"workspace\sessions\proj-1790055373-bf5a358b\conv-main.jsonl"
lines=[x for x in open(P,encoding="utf-8").read().split("\n") if x.strip()]
o4=json.loads(lines[3]); c=o4["content"]
out=io.StringIO()
# 1) 执行偏好转写
pref=open(r"prompts\planner\execution_preference.md",encoding="utf-8").read().split("\n")
p12=pref[11]
out.write("执行偏好 L12 逐字：\n%s\n" % p12)
out.write("LINE4 是否逐字包含该行（不改一字节）？ %s\n" % (p12 in c))
# 2) UNAVAILABLE 渲染
te=open(r"prompts\shared\turn_excluded.md",encoding="utf-8").read().rstrip("\n").split("\n")
names="script_analysis_report, storyboard_add_draft, storyboard_create_group, storyboard_delete_group, storyboard_patch_draft"
route="经委派（run_subagent）执行对应阶段"
rend="\n".join(x.replace("{{names}}",names).replace("{{route}}",route) for x in te)
out.write("\nturn_excluded.md 渲染结果：\n%s\n" % rend)
out.write("LINE4 是否逐字包含该渲染结果？ %s\n" % (rend in c))
# 3) 铁律头部
ir=open(r"prompts\shared\iron_rules_header.md",encoding="utf-8").read().rstrip("\n")
out.write("\niron_rules_header.md 是否出现在 LINE4/state 中？ %s\n" % (ir in c))
out.write("iron_rules_header.md L2 逐字：%s\n" % ir.split(chr(10))[1])
# 4) DISCIPLINE
sr=open(r"prompts\planner\skill_runtime.md",encoding="utf-8").read()
d=sr.split("## DISCIPLINE")[1].split("## DISABLED")[0].strip()
out.write("\nDISCIPLINE 分节首行：%s\n" % d.split(chr(10))[0])
out.write("DISCIPLINE 是否出现在任何 jsonl 记录中？ %s\n" % (d[:60] in open(P,encoding='utf-8').read()))
out.write("DISCIPLINE 中是否含「效率」？ %s ；含「一次性」？ %s\n" % ("效率" in d, "一次性" in d))
# 5) 各 jsonl 中「效率」出现的 4 处
whole=open(P,encoding="utf-8").read()
import re
for n,l in enumerate(lines,1):
    if "效率" in l:
        o=json.loads(l)
        for k in ("text","content","reasoning_content"):
            v=o.get(k)
            if isinstance(v,str) and "效率" in v:
                for m in re.finditer("效率", v):
                    out.write("  LINE %d field=%s 上下文：…%s…\n" % (n,k,v[max(0,m.start()-24):m.start()+24].replace("\n"," ")))
# 6) 跨项目时间跨度
out.write("\n=== 跨项目「为了效率」时间跨度（取各会话首条 time）===\n")
root=r"workspace\sessions"
hits=[]
for dp,dn,fn in os.walk(root):
    for f in fn:
        if not f.endswith(".jsonl"): continue
        fp=os.path.join(dp,f)
        try: t=open(fp,encoding="utf-8").read()
        except: continue
        if "为了效率" not in t: continue
        first=None
        for l in t.split("\n"):
            if l.strip():
                try: first=json.loads(l).get("time")
                except: pass
                break
        if first: hits.append((first, os.path.basename(dp), f))
hits.sort()
for t,p,f in hits:
    out.write("  %s  %s / %s\n" % (datetime.datetime.fromtimestamp(t, datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), p, f))
out.write("  共 %d 个会话文件，时间跨度 %s → %s\n" % (len(hits),
    datetime.datetime.fromtimestamp(hits[0][0], datetime.timezone.utc).strftime("%Y-%m-%d"),
    datetime.datetime.fromtimestamp(hits[-1][0], datetime.timezone.utc).strftime("%Y-%m-%d")))
sys.stdout.reconfigure(encoding="utf-8")
print(out.getvalue())
