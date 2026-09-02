"""一键验收（六轮 S3/N3：五轮 M6 清偿，元教训机制化）。

验收只认进程退出码，不人眼读输出文本——Windows GBK 终端乱码曾把契约门禁的
「不一致」伪装成「一致」（六轮 N1，N7 勘误机制第四例）。本脚本串行执行全部
验收组件，收集退出码，输出纯 ASCII 汇总表；任一组件失败 → 进程退出码 1。

用法：
    python scripts/acceptance.py              # 全量（四件套 + 四门禁）
    python scripts/acceptance.py --quick      # 快验（仅四门禁 + tsc）
    python scripts/acceptance.py --with-eval  # 全量 + 评测管线（终验用，较慢）
    python scripts/acceptance.py --with-e2e   # 追加 playwright e2e 精简集（任务 P2-7
                                              # 可选档；不改 GATES 表、不改 --quick/默认档）

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

# 组件清单：(名称, 命令行) —— 新增/修改门禁脚本必须同步本表。
GATES: List[Tuple[str, List[str]]] = [
    ("contract", [sys.executable, "scripts/gen_api_types.py", "--check"]),
        # 任务 #4：语义色收口闸——styles/ 硬编码值只减不增（白名单见脚本内）
        ("semantic_colors", [sys.executable, "scripts/check_semantic_colors.py"]),
    # 合法存量清单自然缩减，本闸为纯防新增断言（存量均为合法 lazy import）。
    ("func_imports", [sys.executable, "scripts/check_func_imports.py"]),
    # 类别 Key 防硬编码：CAT_* 常量为单一事实源。
    ("category_keys", [sys.executable, "scripts/check_category_keys.py"]),
    # 退役编排符号防复活。
    ("legacy_orchestration", [sys.executable, "scripts/check_legacy_orchestration.py"]),
    # 层间导入方向闸——core/tools 禁止 import src.video_agent.web.*；
    # web 能力经 core/ports 端口（D-01）或 storage/core 公开 API（下沉先例）消费。
    ("layer_imports", [sys.executable, "scripts/check_layer_imports.py"]),
    # 治理瘦身第一批：doc_pointers 与 arch_anchors 合并为引用完整性闸
    # （ADR 双边注记 / 宪法文件地图 / 代码与 docs 模块指针 / 退役符号防复述 /
    # 宪法锚点路径+不变量符号）。
    ("ref_integrity", [sys.executable, "scripts/check_doc_pointers.py"]),
    # 2026-09-02「治理闸机减负」裁决：core 覆盖率由逐批棘轮改为固定容差地板
    # （脚本内写死 COVERAGE_FLOOR，低于地板才 FAIL；不再读基线文件/不再要求每批
    # --update-baseline 上调）；本地无 coverage.xml 时 SKIP，CI 以 --require-xml 硬门禁。
    ("cov_ratchet", [sys.executable, "scripts/check_cov_ratchet.py"]),
    # 2026-09-02「治理闸机减负」裁决：前端整体覆盖率由逐批棘轮改为固定容差地板
    # （脚本内写死 COVERAGE_FLOOR，读 vitest json-summary）；本地无 coverage-summary.json
    # 时 SKIP，CI 已接线 --require-summary 硬门禁（frontend-check vitest 之后）。
    # 已知局限：GATES 先于 SUITES 执行，此处读的是上一轮 vitest 产物
    # （详见 check_fe_cov_ratchet.py 头部注释）。
    ("fe_cov_ratchet", [sys.executable, "scripts/check_fe_cov_ratchet.py"]),
    # 任务 #9：CSS 体积闸（度量 static/dist 全部 stylesheet 产物，
    # 基线 scripts/css_size_baseline.txt 首钉 153007 字节 = 149.42 kB，
    # 度量口径与 check_bundle_size.mjs 同框）。
    # 基线上调记录：152752 → 157356（第 5-3 批容量卡样式 +15 行未同批更新基线；
    # 用户裁决 2026-09-01 批 6-1 同批回填登记）；157356 → 157584（批 6-2 对话标签
    # 运行中/未读角标样式 +4 行，同批登记；后续批只许减）。
    # 157584 → 160470（批 S4 微调浮动子对话浮窗新增 adjust-dialog.css 21 条组件级规则，
    # 同批回填登记；后续批只许减）。
    # 160470 → 161853（二期子对话批 3 浮窗参考素材清单/附件入口/输入行
    # adjust-dialog.css +12 行，同批回填登记；后续批只许减）。
    ("css_size", ["node", "scripts/check_css_size.mjs"]),
]
SUITES: List[Tuple[str, List[str]]] = [
    # --cov 产出 coverage.xml，供下一轮 cov_ratchet 闸对比（与 CI 度量口径同构）；
    # 审查修复批：并发度显式指定（addopts 不再硬编码 -n），本地稳妥值 -n 8
    ("pytest", [sys.executable, "-m", "pytest", "tests/", "-n", "8", "-q", "--tb=line",
                "--cov=src/video_agent/core", "--cov-report=xml"]),
    ("vitest", ["npx", "vitest", "run", "--silent"]),
    ("tsc", ["npx", "tsc", "--noEmit"]),
    ("eslint", ["npx", "eslint", "src/web/", "--quiet"]),
]
EVAL: List[Tuple[str, List[str]]] = [
    ("eval_pipeline", [sys.executable, "scripts/run_eval_pipeline.py"]),
]
# 正文卫生 WARN（--with-eval 档运行，打印告警不影响退出码、不进 GATES 表）
EVAL_WARN: List[Tuple[str, List[str]]] = [
    ("skill_hygiene_warn", [sys.executable, "scripts/scan_skills.py", "--gate"]),
]
# 任务 P2-7：playwright e2e 精简集可选档（--with-e2e 显式传入才追加）。
# 非 GATES 条目、非默认验收组成部分：不碰 --quick/全量既有行为，
# 不引入新门禁（闸门只减不增）；只跑最稳的刷新重建/流式聊天两条 spec。
E2E: List[Tuple[str, List[str]]] = [
    ("playwright_e2e", ["npx", "playwright", "test",
                        "tests/e2e/refresh-rebuild.spec.ts",
                        "tests/e2e/chat-stream.spec.ts"]),
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
    warn_steps: List[Tuple[str, List[str]]] = []
    if "--quick" in args:
        steps += [("tsc", ["npx", "tsc", "--noEmit"])]
    if "--with-eval" in args:
        steps += EVAL
        warn_steps += EVAL_WARN
    if "--with-e2e" in args:
        steps += E2E

    env = dict(os.environ)
    env["LOG_FILE_ENABLED"] = "false"  # S4：验收子进程不写生产日志文件

    results = []
    for name, cmd in steps:
        ok, dur = run_step(name, cmd, env)
        results.append((name, ok, dur))
        # 逐项即时回显（ASCII，防乱码误读）
        print(f"[acceptance] {'PASS' if ok else 'FAIL'}: {name} ({dur:.1f}s)")

    # WARN 步骤：运行并打印输出，不影响退出码
    for name, cmd in warn_steps:
        try:
            proc = subprocess.run(
                cmd, cwd=str(ROOT), env=env,
                capture_output=True, text=True, shell=(os.name == "nt"),
            )
            if proc.stdout.strip():
                print(f"[acceptance:warn] {name}:\n{proc.stdout.rstrip()}")
            if proc.returncode != 0:
                print(f"[acceptance:warn] {name}: exit={proc.returncode}"
                      f" (WARN only, not blocking)")
        except Exception as e:
            print(f"[acceptance:warn] {name}: exception {e} (WARN only)")

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
