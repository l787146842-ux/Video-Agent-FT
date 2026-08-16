"""四轮 R0（N7 漂移清偿的机制化落点）：方法内 import 防新增门禁。

背景：宪法第六章「禁止方法内 import」，台账 N7 曾宣称清零——四轮审核 AST 实测
实际存量 177 处，其中绝大多数是防循环依赖的合法 lazy import（routes↔web↔core
等），盲目顶层化会破坏分层。故本门禁策略为：

- 存量 177 处固化进白名单快照（func_imports_baseline.txt），合法豁免；
- 任何「新增」方法内 import 即失败（防增量漂移，杜绝再次宣称清零）；
- 白名单条目减少（清偿）随时允许，脚本 --refresh 重建快照。

用法：
    python scripts/check_func_imports.py            # 门禁检查（CI 用）
    python scripts/check_func_imports.py --refresh  # 清偿后刷新基线
"""
import ast
import glob
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASELINE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "func_imports_baseline.txt")


def scan() -> list:
    hits = []
    for f in glob.glob(os.path.join(ROOT, "src", "video_agent", "**", "*.py"), recursive=True):
        rel = os.path.relpath(f, ROOT).replace(os.sep, "/")
        src = open(f, encoding="utf-8-sig").read()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for sub in ast.walk(node):
                    if isinstance(sub, (ast.Import, ast.ImportFrom)) and sub.col_offset > 0:
                        mod = getattr(sub, "module", "") or ",".join(a.name for a in sub.names)
                        hits.append(f"{rel}:{sub.lineno}:{mod}")
    return sorted(set(hits))


def main() -> int:
    current = scan()
    if "--refresh" in sys.argv:
        with open(BASELINE, "w", encoding="utf-8") as fh:
            fh.write("\n".join(current) + "\n")
        print(f"[check_func_imports] 基线已刷新：{len(current)} 条")
        return 0
    baseline = []
    if os.path.exists(BASELINE):
        baseline = [ln.strip() for ln in open(BASELINE, encoding="utf-8") if ln.strip()]
    base_keys = {ln.rsplit(":", 2)[0] + ":" + ln.rsplit(":", 1)[-1] for ln in baseline}
    cur_keys = {ln.rsplit(":", 2)[0] + ":" + ln.rsplit(":", 1)[-1] for ln in current}
    new = sorted(cur_keys - base_keys)
    if new:
        print(f"[check_func_imports] FAIL：新增 {len(new)} 处方法内 import（宪法第六章禁止）：")
        for ln in new:
            print(f"  + {ln}")
        print("顶层化后重跑，或确属必要豁免时 python scripts/check_func_imports.py --refresh（需同批登记台账）")
        return 1
    print(f"[check_func_imports] PASS（存量 {len(cur_keys)} 处白名单，无新增）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
