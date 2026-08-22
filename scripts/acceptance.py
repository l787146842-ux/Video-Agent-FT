"""一键验收（六轮 S3/N3：五轮 M6 清偿，元教训机制化）。

验收只认进程退出码，不人眼读输出文本——Windows GBK 终端乱码曾把契约门禁的
「不一致」伪装成「一致」（六轮 N1，N7 勘误机制第四例）。本脚本串行执行全部
验收组件，收集退出码，输出纯 ASCII 汇总表；任一组件失败 → 进程退出码 1。

用法：
    python scripts/acceptance.py              # 全量（四件套 + 四门禁）
    python scripts/acceptance.py --quick      # 快验（仅四门禁 + tsc）
    python scripts/acceptance.py --with-eval  # 全量 + 评测管线（终验用，较慢）

宪法口径（六轮 S6 修订）：§5.5/§10 验收 = 本脚本全 PASS；CI Job 拆分不变，
本地与 CI 组件同构。子进程统一注入 LOG_FILE_ENABLED=false（六轮 S4 联动），
验收过程本身不触发日志文件争用。
"""
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Tuple

ROOT = Path(__file__).resolve().parent.parent

# 组件清单：(名称, 命令行) —— 新增/修改门禁脚本必须同步本表（宪法 §13.7 登记）
GATES: List[Tuple[str, List[str]]] = [
    ("contract", [sys.executable, "scripts/gen_api_types.py", "--check"]),
    ("prompt_budget", [sys.executable, "scripts/check_prompt_budget.py"]),
    ("file_lines", [sys.executable, "scripts/check_file_lines.py"]),
    ("file_lines_frontend", [sys.executable, "scripts/check_file_lines.py", "--frontend"]),
    ("func_imports", [sys.executable, "scripts/check_func_imports.py"]),
    ("governance_refs", [sys.executable, "scripts/check_governance_refs.py"]),
    ("category_keys", [sys.executable, "scripts/check_category_keys.py"]),
    ("legacy_orchestration", [sys.executable, "scripts/check_legacy_orchestration.py"]),
    ("scaffold_registry", [sys.executable, "scripts/check_scaffold_registry.py"]),
    # 任务 #11：core 覆盖率棘轮（只升不降，基线 scripts/cov_baseline.txt）；
    # 本地无 coverage.xml 时 SKIP，CI 以 --require-xml 硬门禁。
    # 退役条件：core 覆盖率 >= 90% 且连续两季无回退争议时裁决下账（§13.14(c)）。
    ("cov_ratchet", [sys.executable, "scripts/check_cov_ratchet.py"]),
    # executor_skill_drift 闸已随任务#36 B5 执行器一步退役删除（执行器族不复存在，
    # 工具名/能力覆盖改由 scan_skills --gate 与 tool_risk 门禁承接）
    ("skill_tool_names", [sys.executable, "scripts/scan_skills.py", "--gate"]),
]
SUITES: List[Tuple[str, List[str]]] = [
    # --cov 产出 coverage.xml，供下一轮 cov_ratchet 闸对比（与 CI 度量口径同构）
    ("pytest", [sys.executable, "-m", "pytest", "tests/", "-q", "--tb=line",
                "--cov=src/video_agent/core", "--cov-report=xml"]),
    ("vitest", ["npx", "vitest", "run", "--silent"]),
    ("tsc", ["npx", "tsc", "--noEmit"]),
    ("eslint", ["npx", "eslint", "src/web/", "--quiet"]),
]
EVAL: List[Tuple[str, List[str]]] = [
    ("eval_pipeline", [sys.executable, "scripts/run_eval_pipeline.py"]),
]


def run_step(name: str, cmd: List[str], env: dict) -> Tuple[bool, float]:
    t0 = time.monotonic()
    try:
        proc = subprocess.run(
            cmd, cwd=str(ROOT), env=env,
            capture_output=True, shell=(os.name == "nt"),
        )
        ok = proc.returncode == 0
    except Exception:
        ok = False
    return ok, time.monotonic() - t0


def main() -> int:
    args = set(sys.argv[1:])
    steps = GATES + ([] if "--quick" in args else SUITES)
    if "--quick" in args:
        steps += [("tsc", ["npx", "tsc", "--noEmit"])]
    if "--with-eval" in args:
        steps += EVAL

    env = dict(os.environ)
    env["LOG_FILE_ENABLED"] = "false"  # S4：验收子进程不写生产日志文件

    results = []
    for name, cmd in steps:
        ok, dur = run_step(name, cmd, env)
        results.append((name, ok, dur))
        # 逐项即时回显（ASCII，防乱码误读）
        print(f"[acceptance] {'PASS' if ok else 'FAIL'}: {name} ({dur:.1f}s)")

    print("")
    print("[acceptance] ===== SUMMARY =====")
    for name, ok, dur in results:
        print(f"[acceptance] {'PASS' if ok else 'FAIL'}  {name:<14} {dur:6.1f}s")
    failed = [n for n, ok, _ in results if not ok]
    if failed:
        print(f"[acceptance] FAIL: {len(failed)} step(s) failed: {', '.join(failed)}")
        return 1
    print("[acceptance] OK: all steps passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
