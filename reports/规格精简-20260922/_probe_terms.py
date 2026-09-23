# -*- coding: utf-8 -*-
"""只读取证探针 C：在指定目录树中逐词逐行检索并输出 文件+行号+逐字行。"""
import os, sys, io

TERMS = ["效率", "一次性", "一起问", "打包", "预收", "合并"]
ROOTS = [r"prompts", r"src\video_agent"]
EXTS = {".md", ".py", ".txt", ".json", ".yaml", ".yml", ".toml"}
SKIP_DIRS = {"__pycache__", ".git", "node_modules"}

out = io.StringIO()
summary = {}
for root in ROOTS:
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in sorted(filenames):
            if os.path.splitext(fn)[1].lower() not in EXTS:
                continue
            fp = os.path.join(dirpath, fn)
            try:
                with open(fp, "r", encoding="utf-8", errors="replace") as f:
                    lines = f.read().split("\n")
            except Exception as e:
                out.write("!! read fail %s : %s\n" % (fp, e)); continue
            for i, ln in enumerate(lines, 1):
                for t in TERMS:
                    if t in ln:
                        summary.setdefault(t, []).append((fp, i))
                        out.write("[%s] %s : LINE %d\n    %s\n" % (t, fp.replace("\\", "/"), i, ln.strip()))

out.write("\n=========== 逐词命中统计 ===========\n")
for t in TERMS:
    hits = summary.get(t, [])
    files = sorted({h[0].replace("\\", "/") for h in hits})
    out.write("词「%s」：命中 %d 行，涉及 %d 个文件 -> %s\n" % (t, len(hits), len(files), files))
    per = {}
    for fp, i in hits:
        per.setdefault(fp.replace("\\", "/"), []).append(i)
    for fp, ns in sorted(per.items()):
        out.write("      %s : %s\n" % (fp, ns))

sys.stdout.reconfigure(encoding="utf-8")
print(out.getvalue())
