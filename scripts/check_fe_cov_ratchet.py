"""前端覆盖率容差地板门禁（2026-09-02「治理闸机减负」裁决：棘轮改固定地板，与后端同构）。

- 度量口径：vitest v8 coverage 的 json-summary 产物（coverage/coverage-summary.json）
  中 total.lines.pct（行覆盖率，保留两位小数）；与后端 line-rate 同构选用行覆盖。
- 判定规则：脚本内写死宽松固定地板 COVERAGE_FLOOR，当前值低于地板即 FAIL；
  不再读基线文件、不再要求每批显式 --update-baseline 上调（镜像仪式已退役）；
- 产物完整性校验保留：损坏/缺字段/非有限数值一律判红并给明确诊断（不误红不静默放行）；
- 与七文件阈值闸的关系：vitest.config.ts thresholds 的逐文件行覆盖闸针对对话
  核心模块硬门禁，本地板管整体面兜底，两者并存互不替代；
- 已知限制（acceptance 内顺序）：acceptance.py 的 GATES 先于 SUITES 执行，
  故 acceptance 场景下本闸读取的是「上一轮」vitest 产物；CI 侧不存在此局限。
"""
import argparse
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SUMMARY = ROOT / "coverage" / "coverage-summary.json"

# 固定容差地板（2026-09-02 裁决）：取历史实测基线 71.54 减约 3 个百分点，
# 只作断崖兜底，不再逐批镜像上调。
COVERAGE_FLOOR = 68.0


def read_current(summary_path: Path, require: bool) -> float | None:
    if not summary_path.exists():
        if not require:
            print(f"[check_fe_cov_ratchet] SKIP - {summary_path} not found "
                  "(no local coverage artifact, skipped; CI uses --require-summary hard gate)")
            return None
        print(f"[check_fe_cov_ratchet] FAIL - coverage summary file missing: {summary_path}; "
              "rerun frontend coverage: npx vitest run (vitest.config.ts already enables v8 "
              "coverage and json-summary reporter)")
        raise SystemExit(1)
    # 完整性校验：产物损坏（编码/JSON/字段/数值任一环节）一律判红并给出
    # 具体成因，不因解析异常误红或静默通过。
    try:
        raw = summary_path.read_bytes()
    except OSError as exc:
        print(f"[check_fe_cov_ratchet] FAIL - coverage summary file corrupted or unreadable "
              f"(read error: {exc}): {summary_path}; rerun frontend coverage: npx vitest run")
        raise SystemExit(1)
    try:
        data = json.loads(raw.decode("utf-8"))
        pct = data["total"]["lines"]["pct"]
    except UnicodeDecodeError:
        cause = "non-UTF-8 text"
    except json.JSONDecodeError:
        cause = "JSON parse failed"
    except (KeyError, TypeError):
        cause = "required field total.lines.pct missing"
    else:
        # 有限性检查：json.loads/float 均接受裸 Infinity/NaN，null 则转换报
        # TypeError；三者一并归入「非有效数值」判红，防 inf/NaN 污染判定。
        try:
            value = float(pct)
        except (TypeError, ValueError):
            cause = "total.lines.pct not a valid number (null unacceptable)"
        else:
            if not math.isfinite(value):
                cause = "total.lines.pct not a valid number (Infinity/NaN unacceptable)"
            else:
                return round(value, 2)
    print(f"[check_fe_cov_ratchet] FAIL - coverage summary file corrupted or missing ({cause}): "
          f"{summary_path}; rerun frontend coverage: npx vitest run to regenerate artifact then retry")
    raise SystemExit(1)


def main() -> int:
    parser = argparse.ArgumentParser(description="frontend overall coverage tolerance floor")
    parser.add_argument("--summary", default=str(DEFAULT_SUMMARY),
                        help="coverage-summary.json path (default coverage/ dir)")
    parser.add_argument("--require-summary", action="store_true",
                        help="FAIL if coverage-summary.json missing (CI use; locally SKIP by default when missing)")
    args = parser.parse_args()

    current = read_current(Path(args.summary), args.require_summary)
    if current is None:
        return 0

    if current < COVERAGE_FLOOR:
        print(f"[check_fe_cov_ratchet] FAIL - frontend coverage {current:.2f}% below "
              f"floor {COVERAGE_FLOOR:.2f}%; add tests to recover")
        return 1
    print(f"[check_fe_cov_ratchet] PASS - frontend coverage {current:.2f}% "
          f">= floor {COVERAGE_FLOOR:.2f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
