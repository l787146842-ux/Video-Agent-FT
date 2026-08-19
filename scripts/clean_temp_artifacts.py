"""临时产物清理（阶段 5）。

.pytest_tmp / .playwright-cli 下的调试脚本、截图、日志会随审计会话堆积。
默认 dry-run 只列出候选删除项；加 --apply 才真正删除。

保留规则：
- .pytest_tmp：保留最近 7 天的文件；
- .playwright-cli：保留最近 30 天的 png/yml/log；
- 两个目录下的 __pycache__ 一律清。

用法：
    python scripts/clean_temp_artifacts.py            # dry-run
    python scripts/clean_temp_artifacts.py --apply    # 真删
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DAY = 86400

RULES = [
    (ROOT / ".pytest_tmp", 7),
    (ROOT / ".playwright-cli", 30),
]


def main() -> int:
    apply = "--apply" in sys.argv[1:]
    now = time.time()
    total = 0
    for directory, keep_days in RULES:
        if not directory.exists():
            continue
        for p in sorted(directory.rglob("*")):
            if not p.is_file():
                continue
            age_days = (now - p.stat().st_mtime) / DAY
            is_pycache = "__pycache__" in p.parts
            if is_pycache or age_days > keep_days:
                total += 1
                verb = "DELETE" if apply else "would delete"
                print(f"[clean_temp] {verb}: {p.relative_to(ROOT)} "
                      f"({age_days:.0f}d)")
                if apply:
                    p.unlink()
    mode = "applied" if apply else "dry-run (add --apply to delete)"
    print(f"[clean_temp] {total} candidate(s); {mode}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
