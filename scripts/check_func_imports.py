"""方法内 import 防新增门禁（宪法第六章禁令的机械强制）。

语义：存量方法内 import 均为防循环依赖的合法 lazy import（routes↔web↔core
等），已裁决长期保留，故本闸不是「存量清零」台账，而是纯防新增断言：

- func_imports_baseline.txt = 合法存量清单（白名单），只许减少不许增加；
- 任何白名单之外的方法内 import 即失败（防增量漂移）；
- 白名单随文件删除/顶层化自然缩减，--refresh 只剔除已消失条目（不收编新增；
  基线缺失/为空时拒绝刷新，防产出空白名单）。

退役条件见 acceptance.py GATES 表本闸条目（单一事实源，不在此复述）。
用法：
    python scripts/check_func_imports.py            # 门禁检查（CI 用）
    python scripts/check_func_imports.py --refresh  # 清偿后剔除已消失的存量条目（只减）
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
    baseline = []
    if os.path.exists(BASELINE):
        baseline = [ln.strip() for ln in open(BASELINE, encoding="utf-8") if ln.strip()]
    base_keys = {ln.rsplit(":", 2)[0] + ":" + ln.rsplit(":", 1)[-1] for ln in baseline}
    cur_keys = {ln.rsplit(":", 2)[0] + ":" + ln.rsplit(":", 1)[-1] for ln in current}
    if "--refresh" in sys.argv:
        # 基线缺失/为空时拒绝刷新：空白名单会让后续门禁把全部存量误判为新增，
        # 且不覆写文件（从 git 恢复后重试）
        if not baseline:
            print(f"[check_func_imports] WARNING: 基线文件缺失或为空（{BASELINE}），"
                  "拒绝生成空白名单（会把全部存量误判为新增违规）；"
                  "请先从 git 恢复：git checkout HEAD -- scripts/func_imports_baseline.txt")
            return 1
        # 只减不增：仅剔除已自然消失的存量条目，绝不收编新增违规
        kept = [ln for ln in baseline if ln.rsplit(":", 2)[0] + ":" + ln.rsplit(":", 1)[-1] in cur_keys]
        with open(BASELINE, "w", encoding="utf-8") as fh:
            fh.write("\n".join(kept) + "\n")
        print(f"[check_func_imports] 白名单清偿：{len(baseline)} -> {len(kept)} 条（只减不增）")
        return 0
    new = sorted(cur_keys - base_keys)
    if new:
        print(f"[check_func_imports] FAIL：新增 {len(new)} 处方法内 import（宪法第六章禁止）：")
        for ln in new:
            print(f"  + {ln}")
        print("顶层化后重跑（合法存量只减不增，--refresh 不收编新增）")
        return 1
    print(f"[check_func_imports] PASS（合法存量 {len(cur_keys)} 处，无新增）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
