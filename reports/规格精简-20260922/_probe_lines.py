# -*- coding: utf-8 -*-
"""只读取证探针：打印 conv-main.jsonl 指定行的字段与逐字原文。只读，不改任何源文件。"""
import json, io, sys

P = r"workspace\sessions\proj-1790055373-bf5a358b\conv-main.jsonl"

def main():
    out = io.StringIO()
    with open(P, "r", encoding="utf-8") as f:
        lines = f.read().split("\n")
    # 去掉尾部空行
    while lines and lines[-1] == "":
        lines.pop()
    out.write("TOTAL_LINES=%d\n" % len(lines))
    for n in range(1, len(lines) + 1):
        o = json.loads(lines[n - 1])
        keys = list(o.keys())
        t = o.get("type")
        step = o.get("step")
        kind = o.get("kind")
        ts = o.get("time")
        lens = {}
        for k, v in o.items():
            if isinstance(v, str):
                lens[k] = len(v)
        out.write("LINE %d | type=%s | step=%s | kind=%s | time=%s | keys=%s | strlens=%s\n"
                  % (n, t, step, kind, ts, keys, lens))
    out.write("\n")
    for n in [int(x) for x in sys.argv[1:]]:
        o = json.loads(lines[n - 1])
        out.write("\n===================== LINE %d RAW FIELDS =====================\n" % n)
        for k, v in o.items():
            if isinstance(v, str):
                out.write("--- field %s (len=%d) VERBATIM BEGIN ---\n%s\n--- field %s VERBATIM END ---\n" % (k, len(v), v, k))
            else:
                out.write("--- field %s (non-str) = %r\n" % (k, v))
        raw = lines[n - 1]
        out.write("--- raw json line len = %d ---\n" % len(raw))
    sys.stdout.reconfigure(encoding="utf-8")
    print(out.getvalue())

if __name__ == "__main__":
    main()
