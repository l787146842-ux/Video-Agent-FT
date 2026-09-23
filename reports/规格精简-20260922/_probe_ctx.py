# -*- coding: utf-8 -*-
import json, sys, io
P = r"workspace\sessions\proj-1790055373-bf5a358b\conv-main.jsonl"
with open(P, "r", encoding="utf-8") as f:
    lines = f.read().split("\n")
while lines and lines[-1] == "":
    lines.pop()
out = io.StringIO()
for n in range(1, 12):
    o = json.loads(lines[n-1])
    out.write("=" * 90 + "\n")
    out.write("RAW LINE %d  (raw bytes len=%d)\n" % (n, len(lines[n-1].encode("utf-8"))))
    out.write("FULL RAW JSON LINE:\n%s\n" % lines[n-1])
    out.write("-" * 40 + " decoded fields " + "-" * 40 + "\n")
    for k, v in o.items():
        out.write("  %s = %s\n" % (k, repr(v)))
sys.stdout.reconfigure(encoding="utf-8")
print(out.getvalue())
