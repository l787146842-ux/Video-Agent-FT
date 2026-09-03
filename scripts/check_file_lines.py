"""文件行数体检工具（R4c/F58 落地；八轮 B1 升级双水位；P4-23 新增 --frontend 档）。

2026-09-02「治理闸机减负」裁决：本脚本已从 acceptance 门禁退役，现为
**信息工具**（手动运行出体检单）；行数治理口径：
- 红线参考：src/ 下 .py 超 1200 行 → 报告（立项拆分的触发信号）；
- 体检线：≥800 行输出 WARN 体检单（临界文件提前进入视野）；
- 前端档（--frontend）：src/web 下 .ts/.tsx/.css 超 250 行 → 报告
  （对齐 eslint max-lines 物理口径；存量超限在 FRONTEND_WHITELIST 登记）。
超限处置走 D-02 债务挂账与人工审查立项，不再有 CI 硬闸兜底。

历史背景：executors.py 曾膨胀至 2222 行、prompt_gates.py 1404 行、
chat_service.py 1203 行，R4a/R4b/R4c 批次拆分清偿。
"""
import sys
from pathlib import Path

MAX_LINES = 1200
WARN_LINES = 800
# 后端 >900 行文件数参考基线（信息工具口径，历次拆分清偿至 0：
# B1 实测四件 → prompt_gates/fc_tool_runner/planner/state/manager
# 依次拆分清偿，决策史见 CHANGELOG）
OVER_900_BASELINE = 0

# 白名单：文件相对路径 -> 理由（只减不增；拆分清偿后移除条目）
WHITELIST = {}

# ---------- 前端档（P4-23 新增：--frontend） ----------
FRONTEND_MAX_LINES = 250
# 存量超限白名单（P4-23 首查登记，只减不增；拆分清偿一件移除一条）
FRONTEND_WHITELIST = {
    # GlobalSettingsView.tsx 已拆至 global-settings/（任务 #15 清偿：条目删除）
    # LayoutShell.tsx 已清偿至 250 行内（整改批 1.1：滞留条目删除）
    # ProjectSwitcher.tsx 项目动作已切至 use-project-actions（任务 #15 清偿：条目删除）
    # SettingsView.tsx 验证域已切至 use-provider-verify（任务 #15 清偿：条目删除）
    # ParamBase.tsx 已拆出 ProviderModelSelects/ExportButton（任务 #15 清偿：条目删除）
    # PromptEditor.tsx 键盘处理已切至 prompt-editor-keys（任务 #15 清偿：条目删除）
    # ConfirmActions.tsx 自定义输入块已切至 ConfirmCustomInput（任务 #15 清偿：条目删除）
    # hooks/use-sse.ts 连接状态机已抽至 lib/sse-connection + sse-events（任务 #18 清偿：条目删除）
    # stores/chat.ts 已拆分为 chat/ 域组合出口（25 行：任务 #12 批次2 清偿：条目删除）
    "src/web/lib/locale.ts": "i18n 字典集中管理（词条自然增长）",
    "src/web/lib/rich-input.ts": "富文本编辑器 DOM 操作集中（拆分另行立项）",
    "src/web/types/api.generated.ts": "gen_api_types.py 生成物，随后端 schema 自然增长",
    "src/web/types/index.ts": "前后端契约类型集中单文件便于对照",
}
# 前端超限文件数参考基线（信息工具口径：只作报告对照，无 CI 棘轮强制；
# 2026-08-24 磁盘实测超限 13 件起账，历次拆分清偿：13→…→4）。
# 字面常量而非 len(FRONTEND_WHITELIST) 动态自算（整改批 1.1：动态自算
# 是恒真基线，与 scaffold 恒真问题同构）。
FRONTEND_OVER_BASELINE = 4

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"


def count_lines(p: Path) -> int:
    return len(p.read_text(encoding="utf-8").splitlines())


def iter_src_py():
    for p in sorted(SRC.rglob("*.py")):
        if "__pycache__" in p.parts:
            continue
        yield p


def iter_frontend():
    web = ROOT / "src" / "web"
    for pat in ("*.ts", "*.tsx", "*.css"):
        for p in sorted(web.rglob(pat)):
            yield p


def run_frontend() -> int:
    violations, over = [], []
    for p in iter_frontend():
        rel = p.relative_to(ROOT).as_posix()
        n = count_lines(p)
        if n <= FRONTEND_MAX_LINES:
            continue
        over.append((rel, n))
        if rel not in FRONTEND_WHITELIST:
            violations.append(f"  {rel}: {n} lines (max {FRONTEND_MAX_LINES})")
    if violations:
        print("[check_file_lines --frontend] FAIL - over FRONTEND_MAX_LINES (未登记白名单):")
        print("\n".join(violations))
        print("payoff: split by responsibility or reduce lines (only-down)")
        return 1
    if len(over) > FRONTEND_OVER_BASELINE:
        print("[check_file_lines --frontend] FAIL - over-limit files increased "
              f"({len(over)} > baseline {FRONTEND_OVER_BASELINE}, ratchet only-down):")
        for rel, n in over:
            print(f"  {rel}: {n} lines")
        return 1
    print(f"[check_file_lines --frontend] PASS - src/web/**/*.(ts|tsx|css) <= "
          f"{FRONTEND_MAX_LINES} lines or whitelisted; over-limit count "
          f"{len(over)} <= baseline {FRONTEND_OVER_BASELINE}")
    return 0


def main() -> int:
    violations = []
    warns = []
    over_900 = []
    for p in iter_src_py():
        rel = p.relative_to(ROOT).as_posix()
        n = count_lines(p)
        if n > MAX_LINES and rel not in WHITELIST:
            violations.append(f"  {rel}: {n} lines (max {MAX_LINES})")
        elif n >= WARN_LINES:
            warns.append(f"  {rel}: {n} lines")
        if n > 900:
            over_900.append((rel, n))
    if violations:
        print("[check_file_lines] FAIL - over MAX_LINES:")
        print("\n".join(violations))
        print("payoff: split by responsibility (R4a/R4b/R4c precedents)")
        return 1
    if len(over_900) > OVER_900_BASELINE:
        print("[check_file_lines] FAIL - files over 900 lines increased "
              f"({len(over_900)} > baseline {OVER_900_BASELINE}, ratchet only-down):")
        for rel, n in over_900:
            print(f"  {rel}: {n} lines")
        return 1
    if warns:
        print(f"[check_file_lines] WARN - checkup list (>= {WARN_LINES} lines):")
        print("\n".join(warns))
    print(f"[check_file_lines] PASS - all src/*.py <= {MAX_LINES} lines; "
          f"over-900 count {len(over_900)} <= baseline {OVER_900_BASELINE}")
    return 0


if __name__ == "__main__":
    if "--frontend" in sys.argv[1:]:
        sys.exit(run_frontend())
    sys.exit(main())
