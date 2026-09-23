# -*- coding: utf-8 -*-
import json, io, sys, os
P = r"workspace\sessions\proj-1790055373-bf5a358b\conv-main.jsonl"
whole = open(P, encoding="utf-8").read()

def load(rel):
    return open(rel, encoding="utf-8").read()

proto = load(r"prompts\planner\protocol.md")
iron  = load(r"prompts\shared\iron_rules_header.md")
sr    = load(r"prompts\planner\skill_runtime.md")
disc  = sr.split("## DISCIPLINE")[1].split("## DISABLED")[0].strip()
pref  = load(r"prompts\planner\execution_preference.md")
mode  = load(r"prompts\planner\execution_mode.md")
adj   = load(r"prompts\planner\adjust.md")
sub   = load(r"prompts\planner\subagent.md")

out = io.StringIO()
# 关键片段：模型思考里出现的、可回指到某个 prompt 文件的逐字引文
probes = [
    ("protocol.md L4 总纲片段", "读取本身没有限制，但按任务分工决定由谁读"),
    ("protocol.md L11 防虚报指针", "《Skill 流程纪律》第 3 条"),
    ("protocol.md L7 停轮指针", "《Skill 流程纪律》第 6 条"),
    ("DISCIPLINE 标题", "【Skill 流程纪律（平台流程层"),
    ("DISCIPLINE 第6条特征串", "停轮契约唯一出口"),
    ("DISCIPLINE 第5条特征串", "主代理是纯编排角色"),
    ("iron_rules L2 优先级链", "用户最新指令 > 本文档 + 制片规格 > Skill/系统默认"),
    ("iron_rules L3 缺信息处置", "先问再做，不擅自补全"),
    ("execution_preference L12", "当前执行偏好：生成前确认"),
    ("SKILL.md L8 启动协议", "用户触发本 Skill 时，按顺序确认以下信息后再推进"),
    ("SKILL.md L27 关键暂停点", "绝不一口气输出全部步骤"),
]
for label, s in probes:
    out.write("%-34s 在 prompts/ 源文件内存在=%-5s | 在 conv-main.jsonl 全文中出现=%s\n"
              % (label, (s in proto) or (s in iron) or (s in disc) or (s in pref) or (s in mode) or (s in adj) or (s in sub), s in whole))

# 在模型思考里找「Skill 流程纪律」的全部引用
lines = [x for x in open(P, encoding="utf-8").read().split("\n") if x.strip()]
out.write("\n=== 模型思考中对《Skill 流程纪律》的逐条引用 ===\n")
for n, l in enumerate(lines, 1):
    o = json.loads(l)
    for k in ("text", "reasoning_content", "content"):
        v = o.get(k)
        if isinstance(v, str) and "流程纪律" in v:
            i = 0
            while True:
                j = v.find("流程纪律", i)
                if j < 0: break
                out.write("  LINE %d [%s] …%s…\n" % (n, k, v[max(0,j-30):j+46].replace("\n"," ")))
                i = j + 4

out.write("\n=== 模型思考中对《执行铁律》的引用 ===\n")
for n, l in enumerate(lines, 1):
    o = json.loads(l)
    for k in ("text", "reasoning_content", "content"):
        v = o.get(k)
        if isinstance(v, str) and "铁律" in v:
            j = v.find("铁律")
            out.write("  LINE %d [%s] …%s…\n" % (n, k, v[max(0,j-40):j+50].replace("\n"," ")))

out.write("\n=== execution_mode.md 是否被注入（PREF 之外）===\n")
out.write("execution_mode.md 分节键：%s\n" % [x for x in mode.split("\n") if x.startswith("## ")])
out.write("其任一非空分节正文是否出现在 LINE4？ %s\n" % any(
    seg.strip() and seg.strip() in json.loads(lines[3])["content"]
    for seg in mode.split("## MODE_")[1:]))
out.write("\n=== adjust.md / subagent.md 是否可能注入本轮 ===\n")
out.write("adjust.md 首行：%s\n" % adj.split("\n")[0])
out.write("其正文首个实质句是否出现在 LINE4？ %s\n" % (adj.split("\n")[7][:30] in json.loads(lines[3])["content"]))
sys.stdout.reconfigure(encoding="utf-8")
print(out.getvalue())
