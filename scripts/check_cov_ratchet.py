"""后端覆盖率棘轮门禁（任务 #11 度量与卫生专项设立）。

- 度量口径：`pytest --cov=src/video_agent/core --cov-report=xml` 产出的
  coverage.xml 总行覆盖率（line-rate × 100，保留两位小数）；
- 棘轮规则（对齐 check_file_lines.py「只降不升」基线机制，方向相反）：
  覆盖率**只许升不许降**——当前值低于基线即 CI 失败；
- 基线文件：scripts/cov_baseline.txt（单行百分比数值）；首次运行且基线
  文件不存在时自动记录当前值为基线（需随提交入仓）；
- 回写纪律（显式上调，2026-09-02 裁决）：仅显式传 --update-baseline 才覆写基线；
  日常门禁 PASS 且实测高于基线时只提示、不写文件（防验收流程静默上调）；
  禁止手工下调基线文件（棘轮只升不降）。

退役条件：当 core 覆盖率升至 90% 以上且连续两个季度
无回退争议时，本门禁可裁决下账，度量转为纯观测。
"""
import argparse
import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASELINE_FILE = Path(__file__).resolve().parent / "cov_baseline.txt"
DEFAULT_COV_XML = ROOT / "coverage.xml"


def read_current(xml_path: Path, require: bool) -> float | None:
    if not xml_path.exists():
        if not require:
            print(f"[check_cov_ratchet] SKIP - {xml_path} not found "
                  "(no local coverage artifact, skipped; CI uses --require-xml hard gate)")
            return None
        print(f"[check_cov_ratchet] FAIL - {xml_path} not found; "
              "run first: python -m pytest tests/ -q "
              "--cov=src/video_agent/core --cov-report=xml")
        raise SystemExit(1)
    root = ET.parse(xml_path).getroot()
    rate = root.get("line-rate")
    if rate is None:
        print("[check_cov_ratchet] FAIL - coverage.xml missing line-rate attribute")
        raise SystemExit(1)
    return round(float(rate) * 100, 2)


def read_baseline() -> float | None:
    if not BASELINE_FILE.exists():
        return None
    text = BASELINE_FILE.read_text(encoding="utf-8").strip()
    try:
        return float(text.splitlines()[0].strip())
    except (ValueError, IndexError):
        print(f"[check_cov_ratchet] FAIL - baseline file corrupted: {BASELINE_FILE}")
        raise SystemExit(1)


def write_baseline(value: float) -> None:
    # 临时文件 + os.replace 原子替换，防写一半崩溃留下损坏基线
    tmp = BASELINE_FILE.with_name(BASELINE_FILE.name + ".tmp")
    tmp.write_text(f"{value:.2f}\n", encoding="utf-8")
    os.replace(tmp, BASELINE_FILE)


def main() -> int:
    parser = argparse.ArgumentParser(description="core coverage ratchet (only-up)")
    parser.add_argument("--cov-xml", default=str(DEFAULT_COV_XML),
                        help="coverage.xml path (default repo root)")
    parser.add_argument("--update-baseline", action="store_true",
                        help="explicitly write baseline to current value (only after coverage improves)")
    parser.add_argument("--require-xml", action="store_true",
                        help="FAIL if coverage.xml missing (CI use; locally SKIP by default when missing)")
    args = parser.parse_args()

    current = read_current(Path(args.cov_xml), args.require_xml)
    if current is None:
        if args.update_baseline:
            # P2 修复：回写意图下 coverage.xml 缺失不得静默放行，
            # 否则操作者会误以为基线已上调（实际未回写）。
            print("[check_cov_ratchet] FAIL - --update-baseline needs a measured coverage value, "
                  "but coverage.xml is missing, baseline not written; "
                  "run first: python -m pytest tests/ -q "
                  "--cov=src/video_agent/core --cov-report=xml then retry")
            return 1
        return 0
    baseline = read_baseline()

    if baseline is None:
        if args.require_xml:
            # CI 模式下基线缺失不得静默自动记录，否则全新 checkout 每次
            # 都走「记录→exit 0」分支，覆盖率硬门禁永久空转。
            print("[check_cov_ratchet] FAIL - CI mode baseline missing: scripts/cov_baseline.txt "
                  "not committed, coverage gate would idle; commit the baseline file with this batch")
            return 1
        write_baseline(current)
        print(f"[check_cov_ratchet] BASELINE RECORDED - core coverage baseline first recorded "
              f"{current:.2f}% ({BASELINE_FILE.relative_to(ROOT)}, commit it with the batch)")
        return 0

    if args.update_baseline:
        if current < baseline:
            print(f"[check_cov_ratchet] FAIL - refuse writeback: current {current:.2f}% "
                  f"below baseline {baseline:.2f}% (ratchet only-up)")
            return 1
        write_baseline(current)
        print(f"[check_cov_ratchet] BASELINE UPDATED - {baseline:.2f}% -> {current:.2f}%")
        return 0

    if current < baseline:
        print(f"[check_cov_ratchet] FAIL - core coverage regression "
              f"({current:.2f}% < baseline {baseline:.2f}%, ratchet only-up); "
              "add tests to recover or --update-baseline after explicit ruling")
        return 1
    if current > baseline:
        # 显式上调纪律：不传 --update-baseline 绝不写基线文件，仅提示
        #（NOTE 纯 ASCII：Windows GBK 终端乱码纪律）
        print(f"[check_cov_ratchet] NOTE - current {current:.2f}% > baseline "
              f"{baseline:.2f}%, baseline untouched; run "
              "scripts/check_cov_ratchet.py --update-baseline to raise")
    print(f"[check_cov_ratchet] PASS - core coverage {current:.2f}% >= baseline {baseline:.2f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
