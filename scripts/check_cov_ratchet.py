"""后端覆盖率棘轮门禁（任务 #11 度量与卫生专项设立）。

- 度量口径：`pytest --cov=src/video_agent/core --cov-report=xml` 产出的
  coverage.xml 总行覆盖率（line-rate × 100，保留两位小数）；
- 棘轮规则（对齐 check_file_lines.py「只降不升」基线机制，方向相反）：
  覆盖率**只许升不许降**——当前值低于基线即 CI 失败；
- 基线文件：scripts/cov_baseline.txt（单行百分比数值）；首次运行且基线
  文件不存在时自动记录当前值为基线（需随提交入仓）；
- 回写纪律：基线只在覆盖率实质提升后通过显式参数回写上调：
  `python scripts/check_cov_ratchet.py --update-baseline`；
  禁止手工下调基线文件（棘轮只升不降）。

退役条件（宪法 §13.14(c)）：当 core 覆盖率升至 90% 以上且连续两个季度
无回退争议时，本门禁可裁决下账，度量转为纯观测。
"""
import argparse
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASELINE_FILE = Path(__file__).resolve().parent / "cov_baseline.txt"
DEFAULT_COV_XML = ROOT / "coverage.xml"


def read_current(xml_path: Path, require: bool) -> float | None:
    if not xml_path.exists():
        if not require:
            print(f"[check_cov_ratchet] SKIP - {xml_path} 不存在（本地无覆盖率产物，"
                  "跳过；CI 以 --require-xml 硬门禁）")
            return None
        print(f"[check_cov_ratchet] FAIL - {xml_path} 不存在；"
              "请先运行: python -m pytest tests/ -q "
              "--cov=src/video_agent/core --cov-report=xml")
        raise SystemExit(1)
    root = ET.parse(xml_path).getroot()
    rate = root.get("line-rate")
    if rate is None:
        print("[check_cov_ratchet] FAIL - coverage.xml 缺少 line-rate 属性")
        raise SystemExit(1)
    return round(float(rate) * 100, 2)


def read_baseline() -> float | None:
    if not BASELINE_FILE.exists():
        return None
    text = BASELINE_FILE.read_text(encoding="utf-8").strip()
    try:
        return float(text.splitlines()[0].strip())
    except (ValueError, IndexError):
        print(f"[check_cov_ratchet] FAIL - 基线文件损坏: {BASELINE_FILE}")
        raise SystemExit(1)


def write_baseline(value: float) -> None:
    BASELINE_FILE.write_text(f"{value:.2f}\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="core 覆盖率棘轮（只升不降）")
    parser.add_argument("--cov-xml", default=str(DEFAULT_COV_XML),
                        help="coverage.xml 路径（默认仓库根目录）")
    parser.add_argument("--update-baseline", action="store_true",
                        help="显式回写基线为当前值（仅限覆盖率提升后）")
    parser.add_argument("--require-xml", action="store_true",
                        help="coverage.xml 缺失即 FAIL（CI 用；本地默认缺失 SKIP）")
    args = parser.parse_args()

    current = read_current(Path(args.cov_xml), args.require_xml)
    if current is None:
        if args.update_baseline:
            # P2 修复：回写意图下 coverage.xml 缺失不得静默放行，
            # 否则操作者会误以为基线已上调（实际未回写）。
            print("[check_cov_ratchet] FAIL - --update-baseline 需要覆盖率实测值，"
                  "但 coverage.xml 缺失，基线未回写；"
                  "请先运行: python -m pytest tests/ -q "
                  "--cov=src/video_agent/core --cov-report=xml 再重试")
            return 1
        return 0
    baseline = read_baseline()

    if baseline is None:
        if args.require_xml:
            # CI 模式下基线缺失不得静默自动记录，否则全新 checkout 每次
            # 都走「记录→exit 0」分支，覆盖率硬门禁永久空转。
            print("[check_cov_ratchet] FAIL - CI 模式基线缺失：scripts/cov_baseline.txt "
                  "未入仓，覆盖率门禁将空转；请把基线文件随本批提交入仓")
            return 1
        write_baseline(current)
        print(f"[check_cov_ratchet] BASELINE RECORDED - core 覆盖率基线首次记录 "
              f"{current:.2f}%（{BASELINE_FILE.relative_to(ROOT)}，请随提交入仓）")
        return 0

    if args.update_baseline:
        if current < baseline:
            print(f"[check_cov_ratchet] FAIL - 拒绝回写：当前 {current:.2f}% "
                  f"低于基线 {baseline:.2f}%（棘轮只升不降）")
            return 1
        write_baseline(current)
        print(f"[check_cov_ratchet] BASELINE UPDATED - {baseline:.2f}% → {current:.2f}%")
        return 0

    if current < baseline:
        print(f"[check_cov_ratchet] FAIL - core 覆盖率回退 "
              f"({current:.2f}% < baseline {baseline:.2f}%, ratchet only-up)；"
              "补测试回升或显式裁决后 --update-baseline")
        return 1
    print(f"[check_cov_ratchet] PASS - core 覆盖率 {current:.2f}% >= baseline {baseline:.2f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
