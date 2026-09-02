"""后端覆盖率容差地板门禁（2026-09-02「治理闸机减负」裁决：棘轮改固定地板）。

- 度量口径：`pytest --cov=src/video_agent/core --cov-report=xml` 产出的
  coverage.xml 总行覆盖率（line-rate × 100，保留两位小数）；
- 判定规则：脚本内写死宽松固定地板 COVERAGE_FLOOR，当前值低于地板即 FAIL；
  不再读基线文件、不再要求每批显式 --update-baseline 上调（镜像仪式已退役）；
- 本地板为纯兜底信号（防覆盖率断崖式坍塌），非精确逐批棘轮。

退役条件：core 覆盖率长期稳定在地板之上且不再需要兜底信号时裁决下账。
"""
import argparse
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_COV_XML = ROOT / "coverage.xml"

# 固定容差地板（2026-09-02 裁决）：取历史实测基线 88.08 减约 3 个百分点，
# 只作断崖兜底，不再逐批镜像上调。
COVERAGE_FLOOR = 85.0


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


def main() -> int:
    parser = argparse.ArgumentParser(description="core coverage tolerance floor")
    parser.add_argument("--cov-xml", default=str(DEFAULT_COV_XML),
                        help="coverage.xml path (default repo root)")
    parser.add_argument("--require-xml", action="store_true",
                        help="FAIL if coverage.xml missing (CI use; locally SKIP by default when missing)")
    args = parser.parse_args()

    current = read_current(Path(args.cov_xml), args.require_xml)
    if current is None:
        return 0

    if current < COVERAGE_FLOOR:
        print(f"[check_cov_ratchet] FAIL - core coverage {current:.2f}% below "
              f"floor {COVERAGE_FLOOR:.2f}%; add tests to recover")
        return 1
    print(f"[check_cov_ratchet] PASS - core coverage {current:.2f}% "
          f">= floor {COVERAGE_FLOOR:.2f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
