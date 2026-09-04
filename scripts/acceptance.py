"""一键验收（三阶段架构：GATES → SUITES → RATCHETS）。

验收只认进程退出码，不人眼读输出文本——Windows GBK 终端乱码曾把契约门禁的
「不一致」伪装成「一致」（六轮 N1，N7 勘误机制第四例）。本脚本串行执行全部
验收组件，收集退出码，输出纯 ASCII 汇总表；任一组件失败 → 进程退出码 1。

三阶段编排语义（I-4 覆盖率关卡时序修复，2026-09-03）：
  Phase 1 GATES   —— 静态架构扫描，不依赖测试产物（任何模式均跑）。
  Phase 2 SUITES  —— 测试四件套，生成覆盖率产物（--quick 模式跳过）。
  Phase 3 RATCHETS—— 覆盖率后置断言，读本轮 SUITES 刚生成的新鲜产物
                      （--quick 模式跳过——无新鲜产物 = 不假装校验）。

用法：
    python scripts/acceptance.py              # 全量（GATES + SUITES + RATCHETS）
    python scripts/acceptance.py --quick      # 快验（GATES + tsc，无 SUITES/RATCHETS）
    python scripts/acceptance.py --with-eval  # 全量 + 评测管线（终验用，较慢）
    python scripts/acceptance.py --with-e2e   # 追加 playwright e2e 精简集（任务 P2-7
                                              # 可选档；不改 GATES 表、不改 --quick/默认档）

宪法口径（六轮 S6 修订）：§5.5/§10 验收 = 本脚本全 PASS；CI Job 拆分不变，
本地与 CI 组件同构。子进程统一注入 LOG_FILE_ENABLED=false（六轮 S4 联动），
验收过程本身不触发日志文件争用。
"""
import datetime
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Tuple

ROOT = Path(__file__).resolve().parent.parent

# ===== Phase 1: GATES — 静态架构扫描（不依赖测试产物） =====
# 新增/修改门禁脚本必须同步本表。
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
    # 2026-09-03 I-2 旁路面拆除（裁决 Q1）：web/** 禁止直接构造 *ChatAdapter
    # 绕过 Planner（聊天 adapter 唯一合法构造点 = adapters/factory.py）。
    ("web_chat_bypass", [sys.executable, "scripts/check_web_chat_bypass.py"]),
    # 2026-09-03 I-3 provider 注入声明驱动（裁决 Q1）：core/fc_tool_runner.py
    # 禁止硬编码 provider 工具名（image_generate/generate_video），注入必经
    # provider_kind 声明 → core/provider_injection 统一分派。
    ("fc_tool_name_literals", [sys.executable, "scripts/check_fc_tool_name_literals.py"]),
    # 层间导入方向闸——core/tools 禁止 import src.video_agent.web.*；
    # web 能力经 core/ports 端口（D-01）或 storage/core 公开 API（下沉先例）消费。
    ("layer_imports", [sys.executable, "scripts/check_layer_imports.py"]),
    # 治理瘦身第一批：doc_pointers 与 arch_anchors 合并为引用完整性闸
    # （ADR 双边注记 / 宪法文件地图 / 代码与 docs 模块指针 / 退役符号防复述 /
    # 宪法锚点路径+不变量符号）。
    ("ref_integrity", [sys.executable, "scripts/check_doc_pointers.py"]),
    # 2026-09-03 R-4 裁决：A3 硬编码 prose 完整性闸——core/state/web/tools/
    # adapters 五目录 AST 扫描 CJK 且长度≥8 的硬编码 prose（进模型上下文/
    # 用户可见气泡），非 DECLARED_DATA 登记即拒收（约束下沉 P2，提示词外置 Rule 6）。
    ("prompt_literals", [sys.executable, "scripts/check_prompt_literals.py"]),
    # 批 4 · 漂移 lint（V3-3 收窄口径）：Skill 章节锚点存在性——
    # 只查 planner 必备 / 锚点合法 / 开闭配对；暂停行与依赖行不查（必误报）。
    ("skill_anchor_lint", [sys.executable, "scripts/check_skill_anchor_lint.py"]),
]
# ===== Phase 2: SUITES — 测试四件套（生成覆盖率产物供 RATCHETS 消费） =====
SUITES: List[Tuple[str, List[str]]] = [
    # --cov 产出 coverage.xml，供 RATCHETS 阶段 cov_ratchet 消费（本轮新鲜产物）
    ("pytest", [sys.executable, "-m", "pytest", "tests/", "-n", "8", "-q", "--tb=line",
                "--cov=src/video_agent/core", "--cov-report=xml"]),
    # vitest 产出 coverage/coverage-summary.json，供 RATCHETS 阶段 fe_cov_ratchet 消费
    ("vitest", ["npx", "vitest", "run", "--silent"]),
    ("tsc", ["npx", "tsc", "--noEmit"]),
    ("eslint", ["npx", "eslint", "src/web/", "--quiet"]),
]

# ===== Phase 3: RATCHETS — 覆盖率后置断言（读 SUITES 本轮新鲜产物） =====
# I-4 修复（2026-09-03）：覆盖率关卡本质是「对测试产物的后置断言」，
# 必须在 SUITES 之后执行以读取本轮新鲜产物，而非 GATES 阶段读上一轮旧产物。
# --quick 模式跳过本阶段——无 SUITES 运行 = 无新鲜产物 = 不假装校验。
# 2026-09-02「治理闸机减负」裁决不变：固定容差地板，低于地板才 FAIL；
# 本地无产物时 SKIP，CI 用 --require-xml / --require-summary 硬闸。
RATCHETS: List[Tuple[str, List[str]]] = [
    ("cov_ratchet", [sys.executable, "scripts/check_cov_ratchet.py"]),
    ("fe_cov_ratchet", [sys.executable, "scripts/check_fe_cov_ratchet.py"]),
]
# RATCHETS 产物路径登记表：(关卡名, 产物相对路径) —— 用于新鲜度校验日志。
RATCHET_ARTIFACTS: List[Tuple[str, Path]] = [
    ("cov_ratchet", ROOT / "coverage.xml"),
    ("fe_cov_ratchet", ROOT / "coverage" / "coverage-summary.json"),
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


def _artifact_mtime_str(path: Path) -> str:
    """返回产物 mtime 的 ISO 字符串，产物不存在时返回 'MISSING'。"""
    if not path.exists():
        return "MISSING"
    ts = path.stat().st_mtime
    return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


def main() -> int:
    args = set(sys.argv[1:])
    quick = "--quick" in args

    # 三阶段编排：
    #   --quick: GATES + tsc（跳过 SUITES 与 RATCHETS——无新鲜覆盖率产物）
    #   全量:    GATES → SUITES → RATCHETS（覆盖率读本轮刚生成的产物）
    gate_steps = list(GATES)
    suite_steps: List[Tuple[str, List[str]]] = []
    ratchet_steps: List[Tuple[str, List[str]]] = []

    if quick:
        gate_steps += [("tsc", ["npx", "tsc", "--noEmit"])]
        # --quick 不跑 SUITES → 无新鲜覆盖率产物 → RATCHETS 整体跳过。
        # 语义：快验只负责静态架构扫描 + 类型安全，覆盖率归全量验收。
        print("[acceptance] --quick mode: RATCHETS phase skipped "
              "(no fresh coverage artifacts without SUITES)")
    else:
        suite_steps = list(SUITES)
        ratchet_steps = list(RATCHETS)

    warn_steps: List[Tuple[str, List[str]]] = []
    if "--with-eval" in args:
        # eval 追加在 RATCHETS 之后（最慢，放末尾）
        ratchet_steps += EVAL
        warn_steps += EVAL_WARN
    if "--with-e2e" in args:
        ratchet_steps += E2E

    env = dict(os.environ)
    env["LOG_FILE_ENABLED"] = "false"  # S4：验收子进程不写生产日志文件

    results = []

    # --- Phase 1: GATES ---
    print("[acceptance] ===== Phase 1: GATES (static checks) =====")
    for name, cmd in gate_steps:
        ok, dur = run_step(name, cmd, env)
        results.append((name, ok, dur))
        print(f"[acceptance] {'PASS' if ok else 'FAIL'}: {name} ({dur:.1f}s)")

    # --- Phase 2: SUITES ---
    if suite_steps:
        print("[acceptance] ===== Phase 2: SUITES (tests, generate coverage) =====")
        for name, cmd in suite_steps:
            ok, dur = run_step(name, cmd, env)
            results.append((name, ok, dur))
            print(f"[acceptance] {'PASS' if ok else 'FAIL'}: {name} ({dur:.1f}s)")

    # --- Phase 3: RATCHETS ---
    if ratchet_steps:
        print("[acceptance] ===== Phase 3: RATCHETS (post-test assertions) =====")
        # 新鲜度证据：打印本轮产物 mtime，证明读的是 SUITES 刚生成的新鲜文件
        for gate_name, artifact_path in RATCHET_ARTIFACTS:
            mtime_str = _artifact_mtime_str(artifact_path)
            print(f"[acceptance:ratchet] {gate_name} artifact={artifact_path.name} "
                  f"mtime={mtime_str}")
        for name, cmd in ratchet_steps:
            ok, dur = run_step(name, cmd, env)
            results.append((name, ok, dur))
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
        print(f"[acceptance] {'PASS' if ok else 'FAIL'}  {name:<20} {dur:6.1f}s")
    failed = [n for n, ok, _ in results if not ok]
    if failed:
        print(f"[acceptance] FAIL: {len(failed)} step(s) failed: {', '.join(failed)}")
        return 1
    print("[acceptance] OK: all steps passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
