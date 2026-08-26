"""pre-commit 钩子的受影响测试选择器（纯工具，非门禁）。

输入：git 暂存区改动（git diff --cached --name-only --diff-filter=ACMR）。
输出：
- stdout 首两行机器可读模式：PYTEST_MODE=<subset|full|skip> / VITEST_MODE=...
- 清单文件 .pytest_tmp/precommit_pytest.txt / precommit_vitest.txt（每行一路径）
- 其余为人类可读摘要。

映射规则：
- Python 侧：
  * 暂存的 tests/**/*.py 直接入选；
  * 暂存的 src/video_agent/**/*.py 取模块 stem，在 tests/unit 与
    tests/integration 中 grep 该 stem 的 import/引用（整词）或测试文件名
    包含 stem，命中测试入选；去重输出。
- 前端侧：
  * 暂存的 src/web/**/*.test.ts(x) 直接入选；
  * 暂存的 src/web/** 源文件取 stem，在 src/web 的 __tests__ 下 grep
    引用该 stem 的测试文件（整词或文件名包含），命中入选。

保守规则（宁可多跑不漏跑；CI 每提交全量兜底）：
- 有暂存 Python 源码但 pytest 清单为空 → FULL_PYTEST；
- 有暂存前端源码但 vitest 清单为空 → FULL_VITEST；
- 暂存高影响基建文件（tests/conftest.py、pytest.ini、tests/fixtures/**、
  src/**/__init__.py、vitest.config.ts、tsconfig.json）→ 对应侧直接全量；
- 无对应侧暂存改动 → 该侧跳过（skip）。

用法：python scripts/select_affected_tests.py   （退出码恒 0，选择器不拦截）
"""
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / ".pytest_tmp"
PY_LIST = OUT_DIR / "precommit_pytest.txt"
VITEST_LIST = OUT_DIR / "precommit_vitest.txt"

# 高影响基建文件：命中即对应侧全量（子集映射不足以覆盖）
PY_INFRA = re.compile(r"^(tests/conftest\.py|pytest\.ini|tests/fixtures/|src/.*__init__\.py)")
FE_INFRA = re.compile(r"^(vitest\.config\.ts|tsconfig\.json|package\.json)")


def staged_files() -> list:
    try:
        out = subprocess.run(
            ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
            cwd=ROOT, capture_output=True, text=True, check=True,
        ).stdout
    except (subprocess.CalledProcessError, OSError) as e:
        print(f"[select_affected] WARN: git 调用失败（{e}），两侧保守全量")
        return None  # None = git 不可用 → 双侧全量
    return [l.strip() for l in out.splitlines() if l.strip()]


def grep_py_tests(stems: set) -> list:
    """在 tests/unit 与 tests/integration 中找引用任一 stem 的测试文件。"""
    hits = set()
    pat = {s: re.compile(rf"\b{re.escape(s)}\b") for s in stems}
    for d in ("tests/unit", "tests/integration"):
        for p in (ROOT / d).glob("test_*.py"):
            name = p.name
            if any(s in name for s in stems):
                hits.add(p.relative_to(ROOT).as_posix())
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if any(r.search(text) for r in pat.values()):
                hits.add(p.relative_to(ROOT).as_posix())
    return sorted(hits)


def grep_fe_tests(stems: set) -> list:
    """在 src/web 的 __tests__ 目录下找引用任一 stem 的测试文件。"""
    hits = set()
    pat = {s: re.compile(rf"\b{re.escape(s)}\b") for s in stems}
    for p in (ROOT / "src" / "web").rglob("__tests__/*.test.ts*"):
        name = p.name
        if any(s in name for s in stems):
            hits.add(p.relative_to(ROOT).as_posix())
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if any(r.search(text) for r in pat.values()):
            hits.add(p.relative_to(ROOT).as_posix())
    return sorted(hits)


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    files = staged_files()
    if files is None:
        PY_LIST.write_text("", encoding="utf-8")
        VITEST_LIST.write_text("", encoding="utf-8")
        print("PYTEST_MODE=full")
        print("VITEST_MODE=full")
        return 0

    # ---- 分侧归集暂存改动 ----
    py_tests, py_src_stems, py_infra = set(), set(), False
    fe_tests, fe_src_stems, fe_infra = set(), set(), False
    py_side, fe_side = False, False

    for f in files:
        if PY_INFRA.match(f):
            py_infra = True
            py_side = True
            continue
        if FE_INFRA.match(f):
            fe_infra = True
            fe_side = True
            continue
        if f.startswith("tests/") and f.endswith(".py"):
            py_tests.add(f)
            py_side = True
        elif f.startswith("src/video_agent/") and f.endswith(".py"):
            stem = pathlib.Path(f).stem
            if stem != "__init__":
                py_src_stems.add(stem)
            py_side = True
        elif f.startswith("src/web/"):
            fe_side = True
            if re.search(r"\.test\.tsx?$", f):
                fe_tests.add(f)
            elif re.search(r"\.(ts|tsx)$", f):
                fe_src_stems.add(pathlib.Path(f).stem)

    # ---- pytest 决策 ----
    if not py_side:
        py_mode = "skip"
        py_list = []
    elif py_infra:
        py_mode = "full"
        py_list = []
        print("[select_affected] 暂存高影响 Python 基建文件 → pytest 全量")
    else:
        mapped = grep_py_tests(py_src_stems) if py_src_stems else []
        py_list = sorted(py_tests | set(mapped))
        if py_src_stems and not py_list:
            py_mode = "full"
            print(f"[select_affected] 暂存 Python 源码 {sorted(py_src_stems)} 无映射测试"
                  " → pytest 保守全量")
        else:
            py_mode = "subset" if py_list else "skip"

    # ---- vitest 决策 ----
    if not fe_side:
        fe_mode = "skip"
        fe_list = []
    elif fe_infra:
        fe_mode = "full"
        fe_list = []
        print("[select_affected] 暂存高影响前端基建文件 → vitest 全量")
    else:
        mapped = grep_fe_tests(fe_src_stems) if fe_src_stems else []
        fe_list = sorted(fe_tests | set(mapped))
        if fe_src_stems and not fe_list:
            fe_mode = "full"
            print(f"[select_affected] 暂存前端源码 {sorted(fe_src_stems)} 无映射测试"
                  " → vitest 保守全量")
        else:
            fe_mode = "subset" if fe_list else "skip"

    PY_LIST.write_text("\n".join(py_list) + ("\n" if py_list else ""),
                       encoding="utf-8", newline="\n")
    VITEST_LIST.write_text("\n".join(fe_list) + ("\n" if fe_list else ""),
                           encoding="utf-8", newline="\n")
    print(f"PYTEST_MODE={py_mode}")
    print(f"VITEST_MODE={fe_mode}")
    if py_mode == "subset":
        print(f"[select_affected] pytest 子集 {len(py_list)} 个文件")
        for t in py_list:
            print(f"  - {t}")
    if fe_mode == "subset":
        print(f"[select_affected] vitest 子集 {len(fe_list)} 个文件")
        for t in fe_list:
            print(f"  - {t}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
