"""文件行数红线检查（R4c/F58 落地）：src/ 下任何 .py 不得超过 1200 行。

超限即 CI 失败；确需例外时在 WHITELIST 登记（附理由，只减不增）。
历史背景：executors.py 曾膨胀至 2222 行、prompt_gates.py 1404 行、
chat_service.py 1203 行，R4a/R4b/R4c 批次拆分清偿。
"""
import sys
from pathlib import Path

MAX_LINES = 1200

# 白名单：文件相对路径 -> 理由（只减不增；拆分清偿后移除条目）
WHITELIST = {}

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"


def main() -> int:
    violations = []
    for p in sorted(SRC.rglob("*.py")):
        if "__pycache__" in p.parts:
            continue
        rel = p.relative_to(ROOT).as_posix()
        n = len(p.read_text(encoding="utf-8").splitlines())
        if n > MAX_LINES and rel not in WHITELIST:
            violations.append(f"  {rel}: {n} 行（红线 {MAX_LINES}）")
    if violations:
        print("[check_file_lines] FAIL — 超出文件行数红线：")
        print("\n".join(violations))
        print("处置：按职责拆分（先例：R4a executors / R4b prompt_gates / R4c chat_service）")
        return 1
    print(f"[check_file_lines] PASS — src/ 全部 .py ≤ {MAX_LINES} 行")
    return 0


if __name__ == "__main__":
    sys.exit(main())
