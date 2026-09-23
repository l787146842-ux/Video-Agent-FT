# -*- coding: utf-8 -*-
import json, sys, io
P = r"workspace\sessions\proj-1790055373-bf5a358b\conv-main.jsonl"
ls=[x for x in open(P,encoding="utf-8").read().split("\n") if x.strip()]
out=io.StringIO()
for n in (9,10,11):
    out.write("RAW LINE %d: %s\n\n" % (n, ls[n-1]))
# 精确取 LINE6 的「为了效率」整句
o6=json.loads(ls[5]); t=o6["text"]
i=t.find("为了效率")
out.write("LINE6 命中句所在自然段（以 \\n\\n 切分）:\n")
paras=[p for p in t.split("\n\n") if "为了效率" in p]
for p in paras: out.write("  >>> %s\n" % p)
o8=json.loads(ls[7]); rc=o8["reasoning_content"]
paras8=[p for p in rc.split("\n\n") if "为了效率" in p]
out.write("\nLINE8 reasoning_content 命中段:\n")
for p in paras8: out.write("  >>> %s\n" % p)
# 字符级偏移
out.write("\nLINE6.text 中该段起止偏移: %d..%d\n" % (t.find(paras[0]), t.find(paras[0])+len(paras[0])))
out.write("LINE8.reasoning_content 中该段起止偏移: %d..%d\n" % (rc.find(paras8[0]), rc.find(paras8[0])+len(paras8[0])))
sys.stdout.reconfigure(encoding="utf-8")
print(out.getvalue())
