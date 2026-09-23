# -*- coding: utf-8 -*-
import json, sys, io
P = r"workspace\sessions\proj-1790055373-bf5a358b\conv-main.jsonl"
ls=[x for x in open(P,encoding="utf-8").read().split("\n") if x.strip()]
out=io.StringIO()
out.write("=== 用户与助手各轮正文（不含思考）===\n")
for n,l in enumerate(ls,1):
    o=json.loads(l); t=o.get("type")
    if t=="user/message":
        out.write("LINE %d user[%s]: %s\n" % (n, o.get("source"), o.get("content")[:120].replace("\n"," ")))
    elif t=="assistant/message":
        tc=o.get("tool_calls") or []
        names=[c["function"]["name"] for c in tc]
        out.write("LINE %d assistant: %s  || tools=%s\n" % (n, (o.get("content") or "")[:110].replace("\n"," "), names))
        for c in tc:
            if c["function"]["name"]=="workflow_pause":
                a=json.loads(c["function"]["arguments"])
                out.write("        PAUSE q=%r\n" % a.get("question"))
                out.write("        PAUSE options=%r\n" % [x.get("label") for x in a.get("options",[])])
    elif t=="tool/result":
        out.write("LINE %d tool[%s]: %s\n" % (n, o.get("name"), (o.get("content") or "")[:110].replace("\n"," ")))
out.write("\n=== 「画幅」「时长」「风格」在 conv-main 中出现情况 ===\n")
whole=open(P,encoding="utf-8").read()
for k in ("画幅","时长","影像风格","9:16"):
    out.write("  %s : %d 次\n" % (k, whole.count(k)))
sys.stdout.reconfigure(encoding="utf-8")
print(out.getvalue())
