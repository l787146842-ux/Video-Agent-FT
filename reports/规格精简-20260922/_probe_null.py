# -*- coding: utf-8 -*-
import io, sys
ir = open(r"prompts\shared\iron_rules_header.md", encoding="utf-8").read()
sr = open(r"prompts\planner\skill_runtime.md", encoding="utf-8").read()
disc = sr.split("## DISCIPLINE")[1].split("## DISABLED")[0]
probes = [
 "分析结论标注为待用户补充的项",
 "未确认的创作选择不得写成既定规格",
 "互相独立的委派放同一条消息一起发",
 "读取本身没有限制，但按任务分工决定由谁读",
 "第 6 条",
 "第 3 条",
]
out = io.StringIO()
for s in probes:
    out.write("%-40s iron_rules=%-5s DISCIPLINE=%-5s\n" % (s, s in ir, s in disc))
sys.stdout.reconfigure(encoding="utf-8")
print(out.getvalue())
