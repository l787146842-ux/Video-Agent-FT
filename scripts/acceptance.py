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

# 组件清单：(名称, 命令行) —— 新增/修改门禁脚本必须同步本表（宪法 §13.7 登记）；
# 每条存量门禁附退役条件一行（§13.14(c) 登记义务，格式对齐 cov_ratchet）
GATES: List[Tuple[str, List[str]]] = [
    # 退役条件：前后端类型同源（不再依赖生成产物桥接）时方可裁决下账。
    ("contract", [sys.executable, "scripts/gen_api_types.py", "--check"]),
    # 退役条件：模型可见禁令存量清零、预算降为 0 硬闸后，指令治理完全数据化时裁决下账。
    ("prompt_budget", [sys.executable, "scripts/check_prompt_budget.py"]),
    # 退役条件：超红线文件全部拆分归零且行数红线内化为开发惯例时裁决下账。
    ("file_lines", [sys.executable, "scripts/check_file_lines.py"]),
    # 退役条件：前端超红线文件全部拆分归零且行数红线内化为开发惯例时裁决下账。
    ("file_lines_frontend", [sys.executable, "scripts/check_file_lines.py", "--frontend"]),
        # 任务 #4：语义色收口闸——styles/ 硬编码色值棘轮只减不增（白名单见脚本内）；
        # 退役条件：白名单清偿归零后降级为零白名单硬门禁，样式体系迁离 tokens.css
        # 时方可裁决整体退役（详见脚本头部注释，§13.14(c)）。
        ("semantic_colors", [sys.executable, "scripts/check_semantic_colors.py"]),
    # 退役条件：合法存量清单自然缩减至空并删除基线文件后裁决下账（宪法 §六 禁令内化；
    # 存量均为合法 lazy import 已裁决长期保留，本闸为纯防新增断言，基线只减不增）。
    ("func_imports", [sys.executable, "scripts/check_func_imports.py"]),
    # 退役条件：类别 Key 硬编码字面量清零、CAT_* 单一事实源全域收敛时裁决下账。
    ("category_keys", [sys.executable, "scripts/check_category_keys.py"]),
    # 退役条件：退役编排符号在长期演进中证实无复活风险（登记清单可整体清退）时裁决下账。
    ("legacy_orchestration", [sys.executable, "scripts/check_legacy_orchestration.py"]),
    # 批 3.3：层间导入方向闸——core/tools 禁止 import src.video_agent.web.*；
    # web 能力经 core/ports 端口（D-01）或 storage/core 公开 API（下沉先例）消费。
    # 退役条件：反向依赖连续两季零检出、端口与公开 API 模式内化为开发惯例时裁决下账。
    ("layer_imports", [sys.executable, "scripts/check_layer_imports.py"]),
    # 治理瘦身第一批：doc_pointers 与 arch_anchors 合并为引用完整性闸，
    # 脚本本体保留 check_doc_pointers.py（ADR 双边注记 / 宪法文件地图 /
    # 代码与 docs 模块指针 / 退役符号防复述 / 宪法锚点路径+不变量符号）。
    # 退役条件：指针/锚点漂移连续两季零检出、双边注记与修宪同批更新锚点内化为
    # 惯例时裁决下账；或宪法条款全面数据化（锚点并入机器可读登记表且
    # ANCHORS 清单清空）时裁决锚点部分下账。
    ("ref_integrity", [sys.executable, "scripts/check_doc_pointers.py"]),
    # 退役条件：脚手架类全部退役、注册计数归零时裁决下账（详见脚本头部注释）。
    ("scaffold_registry", [sys.executable, "scripts/check_scaffold_registry.py"]),
    # 任务 #11：core 覆盖率棘轮（只升不降，基线 scripts/cov_baseline.txt）；
    # 本地无 coverage.xml 时 SKIP，CI 以 --require-xml 硬门禁。
    # 退役条件：core 覆盖率 >= 90% 且连续两季无回退争议时裁决下账（§13.14(c)）。
    ("cov_ratchet", [sys.executable, "scripts/check_cov_ratchet.py"]),
    # 任务 #13 F-6：前端整体覆盖率棘轮（只升不降，基线 scripts/fe_cov_baseline.txt
    # 首钉 63.00，读 vitest json-summary）；本地无 coverage-summary.json 时 SKIP，
    # CI 已接线 --require-summary 硬门禁（FIX-3：frontend-check vitest 之后）；
    # 基线文件缺失即 FAIL 防永久空转。已知局限：GATES 先于 SUITES 执行，
    # 此处读的是上一轮 vitest 产物（详见 check_fe_cov_ratchet.py 头部注释）。
    # 退役条件：前端整体行覆盖率 >= 90% 且连续两季无回退争议时裁决下账（§13.14(c)）。
    ("fe_cov_ratchet", [sys.executable, "scripts/check_fe_cov_ratchet.py"]),
    # executor_skill_drift 闸已随任务#36 B5 执行器一步退役删除（执行器族不复存在，
    # 工具名/能力覆盖改由 scan_skills --gate 与 tool_risk 门禁承接）
    # 退役条件：Skill 工具名与平台工具注册表完全对齐、漂移计数连续两季为零时裁决下账。
    ("skill_tool_names", [sys.executable, "scripts/scan_skills.py", "--gate"]),
    # 任务 #9：CSS 体积棘轮（只减不增，度量 static/dist 全部 stylesheet 产物，
    # 基线 scripts/css_size_baseline.txt 首钉 153007 字节 = 149.42 kB，
    # 度量口径与 check_bundle_size.mjs 同框）。
    # 退役条件：实测体积降至 100 kB 以下且连续两季无回弹时裁决下账；
    # 或样式体系迁离单文件汇总（按路由懒加载分包）致本口径失效时一并裁决。
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
    if "--quick" in args:
        steps += [("tsc", ["npx", "tsc", "--noEmit"])]
    if "--with-eval" in args:
        steps += EVAL
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
