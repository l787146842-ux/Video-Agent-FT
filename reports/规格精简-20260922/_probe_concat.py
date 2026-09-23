# -*- coding: utf-8 -*-
import json, io, sys
P = r"workspace\sessions\proj-1790055373-bf5a358b\conv-main.jsonl"
with open(P, "r", encoding="utf-8") as f:
    lines = f.read().split("\n")
while lines and lines[-1] == "":
    lines.pop()
o5 = json.loads(lines[4]); o6 = json.loads(lines[5]); o8 = json.loads(lines[7])
a = o5["text"]; b = o6["text"]; rc = o8["reasoning_content"]
print("len(line5.text)      =", len(a))
print("len(line6.text)      =", len(b))
print("len(line8.reasoning) =", len(rc))
print("a+b == rc ?", (a+b) == rc)
print("rc.startswith(a) ?", rc.startswith(a))
print("rc.endswith(b) ?", rc.endswith(b))
# 定位「为了效率」
needle = "为了效率"
for name, s in (("line6.text", b), ("line8.reasoning_content", rc)):
    i = s.find(needle)
    print(f"{name}: first index of {needle} = {i}")
    if i >= 0:
        print("  context:", repr(s[max(0,i-40):i+60]))
print("occurrences in rc:", rc.count(needle), " in line6.text:", b.count(needle))
# 整文件出现次数
whole = "\n".join(lines)
print("occurrences of 为了效率 in whole jsonl:", whole.count(needle))
for n, ln in enumerate(lines, 1):
    if needle in ln:
        print("  appears in raw LINE", n)
