# -*- coding: utf-8 -*-
import json, io, sys
out=io.StringIO()
# 1) 9999 执行铁律.md 字符数核对
p=r"reports\规格精简-20260922\9999-文档-执行铁律.md"
c=open(p,encoding="utf-8").read()
out.write("9999-文档-执行铁律.md 字符数 = %d （state JSON 声明 char_count=161）\n" % len(c))
out.write("首行逐字：%s\n\n" % c.split("\n")[0])
# 2) 8888 该轮是否真的合并问了
P2=r"workspace\sessions\proj-1789839470-bbbc8d91\conv-main.jsonl"
ls=[x for x in open(P2,encoding="utf-8").read().split("\n") if x.strip()]
out.write("=== 8888 (proj-1789839470-bbbc8d91) 前 20 行 ===\n")
for n,l in enumerate(ls[:20],1):
    o=json.loads(l); t=o.get("type")
    if t=="user/message":
        out.write("LINE %d user[%s]: %s\n" % (n,o.get("source"),(o.get("content") or "")[:100].replace("\n"," ")))
    elif t=="assistant/message":
        tc=o.get("tool_calls") or []
        out.write("LINE %d assistant tools=%s : %s\n" % (n,[x["function"]["name"] for x in tc],(o.get("content") or "")[:80].replace("\n"," ")))
        for x in tc:
            if x["function"]["name"]=="workflow_pause":
                a=json.loads(x["function"]["arguments"])
                out.write("      PAUSE q=%r\n" % a.get("question"))
                out.write("      PAUSE opts=%r\n" % [y.get("label") for y in a.get("options",[])])
sys.stdout.reconfigure(encoding="utf-8")
print(out.getvalue())
