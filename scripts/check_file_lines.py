"""文件行数门禁（R4c/F58 落地；八轮 B1 升级双水位；P4-23 新增 --frontend 档）。

- 红线：src/ 下任何 .py 不得超过 1200 行，超限即 CI 失败；
  确需例外时在 WHITELIST 登记（附理由，只减不增）。
- 体检线（八轮 B1 新增）：≥800 行的文件输出 WARN 体检单（不影响退出码），
  让临界文件在离红线还有 30% 时就进入视野，而不是撞线才立项。
- 棘轮（八轮 B1 新增）：>900 行的文件数量只降不升，基线值写死在
  OVER_900_BASELINE，清偿拆分后随降，禁止上调。
- 前端档（P4-23 新增，--frontend）：src/web 下 .ts/.tsx/.css 物理行数红线 250
  （对齐架构铁律 10.1 与 eslint max-lines；物理口径严于 eslint 跳空行/注释口径），
  存量超限在 FRONTEND_WHITELIST 登记，只减不增且超限文件数棘轮只降不升。

历史背景：executors.py 曾膨胀至 2222 行、prompt_gates.py 1404 行、
chat_service.py 1203 行，R4a/R4b/R4c 批次拆分清偿。
"""
import sys
from pathlib import Path

MAX_LINES = 1200
WARN_LINES = 800
# 棘轮基线（八轮 B1 设立；每清偿一件随降，禁止上调）；
# B1 磁盘实测四件：planner 998 / prompt_gates 1036 / action_executor 1093 /
# generation 968（后两者此前台账 T24 未登记，棘轮首查即暴露——登记即事实）；
# 九轮 B3b prompt_gates 拆分清偿（gates_cards 切出）：4→3；
# 任务#23 fc_tool_runner 三段拆分清偿（fc_gates/fc_reconcile 切出）：3→2；
# D-02 第一件 planner 拆分清偿（turn_executor 切出）：2→1
# 任务 22 P7-1 state/manager.py 拆分清偿（conversation_ops/save_ops 切出，
# 快照组装并入 context_builder，905→653 行）：1→0（棘轮清零）
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
    "src/web/stores/studio/storyboard.ts": "故事板域集中本地编辑/同步/持久化属合理",
    "src/web/types/api.generated.ts": "gen_api_types.py 生成物，随后端 schema 自然增长",
    "src/web/types/index.ts": "前后端契约类型集中单文件便于对照",
}
# 超限文件数棘轮基线（P4-23 设立；清偿一件随降一件，禁止上调）。
# 字面常量而非 len(FRONTEND_WHITELIST) 动态自算（整改批 1.1：动态自算
# 是恒真基线，与 scaffold 恒真问题同构）；2026-08-24 磁盘实测超限
# 13 件，与白名单 13 条一致。只降不升；上调须书面裁决并同批修改本常量；
# 任务 #18 use-sse.ts 连接状态机抽至 lib/sse-connection + sse-events：7→6；
# 任务 #12 批次2 stores/chat.ts 拆分为 chat/ 域组合出口（存量条目陈旧销账）：6→5
FRONTEND_OVER_BASELINE = 5

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
