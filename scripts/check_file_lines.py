"""文件行数门禁（R4c/F58 落地；八轮 B1 升级双水位）。

- 红线：src/ 下任何 .py 不得超过 1200 行，超限即 CI 失败；
  确需例外时在 WHITELIST 登记（附理由，只减不增）。
- 体检线（八轮 B1 新增）：≥800 行的文件输出 WARN 体检单（不影响退出码），
  让临界文件在离红线还有 30% 时就进入视野，而不是撞线才立项。
- 棘轮（八轮 B1 新增）：>900 行的文件数量只降不升，基线值写死在
  OVER_900_BASELINE，清偿拆分后随降，禁止上调。

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
# 九轮 B3b prompt_gates 拆分清偿（gates_cards 切出）：4→3
OVER_900_BASELINE = 3

# 白名单：文件相对路径 -> 理由（只减不增；拆分清偿后移除条目）
WHITELIST = {}

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"


def count_lines(p: Path) -> int:
    return len(p.read_text(encoding="utf-8").splitlines())


def iter_src_py():
    for p in sorted(SRC.rglob("*.py")):
        if "__pycache__" in p.parts:
            continue
        yield p


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
    sys.exit(main())
