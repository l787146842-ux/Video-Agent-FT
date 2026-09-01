"""前端覆盖率棘轮门禁（任务 #13 批次 F-6 设立，与后端 cov_ratchet 完全同构）。

- 度量口径：vitest v8 coverage 的 json-summary 产物（coverage/coverage-summary.json）
  中 total.lines.pct（行覆盖率，保留两位小数）。口径说明：批次方案钉 63% 基线，
  该数值对应现状整体行覆盖（63.01%）；v8 的 statements 计数含未执行声明体，
  口径偏严且不可比，故与后端 line-rate 同构选用行覆盖。
- 棘轮规则（对齐 check_cov_ratchet.py，方向同「只升不降」）：
  覆盖率**只许升不许降**——当前值低于基线即 CI 失败；
- 基线文件：scripts/fe_cov_baseline.txt（单行百分比数值，首钉 63.00）；
  基线文件缺失即 FAIL（防门禁永久空转，与后端 CI 模式同构），不做自动记录；
- 回写纪律（半自动上调）：PASS 且实测值高于基线时自动覆写基线为实测值（进步即时存档）；
  禁止手工下调基线文件（棘轮只升不降）；
- 与七文件阈值闸的关系：vitest.config.ts thresholds 的 80% 行覆盖闸针对对话
  核心模块逐文件硬门禁，本棘轮管整体面，两者并存互不替代。
- CI 接线（影响面审查 FIX-3 落地）：ci.yml frontend-check 已在 vitest 之后
  显式执行 `--require-summary` 硬门禁（产物缺失即 FAIL），与本脚本注释一致。
- 已知限制（acceptance 内顺序）：acceptance.py 的 GATES 先于 SUITES 执行，
  故 acceptance 场景下本闸读取的是「上一轮」vitest 产出的
  coverage-summary.json（而非当轮新产物）；只要本地曾跑过 vitest 即口径有效，
  CI 侧不存在此局限（vitest 与本闸同 job 串行）。

退役条件（宪法 §13.14(c)）：当前端整体行覆盖率升至 90% 以上且连续两个季度
无回退争议时，本门禁可裁决下账，度量转为纯观测。
"""
import argparse
import json
import math
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASELINE_FILE = Path(__file__).resolve().parent / "fe_cov_baseline.txt"
DEFAULT_SUMMARY = ROOT / "coverage" / "coverage-summary.json"


def read_current(summary_path: Path, require: bool) -> float | None:
    if not summary_path.exists():
        if not require:
            print(f"[check_fe_cov_ratchet] SKIP - {summary_path} 不存在"
                  "（本地无覆盖率产物，跳过；CI 以 --require-summary 硬门禁）")
            return None
        print(f"[check_fe_cov_ratchet] FAIL - 覆盖率摘要文件缺失: {summary_path}；"
              "请重跑前端覆盖率: npx vitest run（vitest.config.ts 已常开 v8 "
              "coverage 与 json-summary 报告器）")
        raise SystemExit(1)
    # 完整性校验：产物损坏（编码/JSON/字段/数值任一环节）一律判红并给出
    # 具体成因，不因解析异常误红或静默通过。
    try:
        raw = summary_path.read_bytes()
    except OSError as exc:
        print(f"[check_fe_cov_ratchet] FAIL - 覆盖率摘要文件损坏或不可读"
              f"（读取失败: {exc}）: {summary_path}；请重跑前端覆盖率: npx vitest run")
        raise SystemExit(1)
    try:
        data = json.loads(raw.decode("utf-8"))
        pct = data["total"]["lines"]["pct"]
    except UnicodeDecodeError:
        cause = "非 UTF-8 文本"
    except json.JSONDecodeError:
        cause = "JSON 解析失败"
    except (KeyError, TypeError):
        cause = "必需字段 total.lines.pct 缺失"
    else:
        # 有限性检查：json.loads/float 均接受裸 Infinity/NaN，null 则转换报
        # TypeError；三者一并归入「非有效数值」判红，防 inf 污染基线或
        # NaN 比较恒假误判 PASS。
        try:
            value = float(pct)
        except (TypeError, ValueError):
            cause = "total.lines.pct 非有效数值（null 等不可接受）"
        else:
            if not math.isfinite(value):
                cause = "total.lines.pct 非有效数值（Infinity/NaN 不可接受）"
            else:
                return round(value, 2)
    print(f"[check_fe_cov_ratchet] FAIL - 覆盖率摘要文件损坏或缺失（{cause}）: "
          f"{summary_path}；请重跑前端覆盖率: npx vitest run 重新生成产物后重试")
    raise SystemExit(1)


def read_baseline() -> float | None:
    if not BASELINE_FILE.exists():
        return None
    text = BASELINE_FILE.read_text(encoding="utf-8").strip()
    try:
        return float(text.splitlines()[0].strip())
    except (ValueError, IndexError):
        print(f"[check_fe_cov_ratchet] FAIL - 基线文件损坏: {BASELINE_FILE}")
        raise SystemExit(1)


def write_baseline(value: float) -> None:
    # 临时文件 + os.replace 原子替换，防写一半崩溃留下损坏基线
    tmp = BASELINE_FILE.with_name(BASELINE_FILE.name + ".tmp")
    tmp.write_text(f"{value:.2f}\n", encoding="utf-8")
    os.replace(tmp, BASELINE_FILE)


def main() -> int:
    parser = argparse.ArgumentParser(description="前端整体覆盖率棘轮（只升不降）")
    parser.add_argument("--summary", default=str(DEFAULT_SUMMARY),
                        help="coverage-summary.json 路径（默认 coverage/ 目录）")
    parser.add_argument("--update-baseline", action="store_true",
                        help="显式回写基线为当前值（仅限覆盖率提升后）")
    parser.add_argument("--require-summary", action="store_true",
                        help="coverage-summary.json 缺失即 FAIL（CI 用；本地默认缺失 SKIP）")
    args = parser.parse_args()

    current = read_current(Path(args.summary), args.require_summary)
    if current is None:
        if args.update_baseline:
            # 与后端同构：回写意图下产物缺失不得静默放行，
            # 否则操作者会误以为基线已上调（实际未回写）。
            print("[check_fe_cov_ratchet] FAIL - --update-baseline 需要覆盖率实测值，"
                  "但 coverage-summary.json 缺失，基线未回写；"
                  "请先运行: npx vitest run 再重试")
            return 1
        return 0
    baseline = read_baseline()

    if baseline is None:
        # 基线文件缺失即 FAIL（防永久空转）：首钉基线随批次入仓，不做自动记录。
        print("[check_fe_cov_ratchet] FAIL - 基线缺失：scripts/fe_cov_baseline.txt "
              "未入仓，覆盖率门禁将空转；请把基线文件随提交入仓（首钉 63.00）")
        return 1

    if args.update_baseline:
        if current < baseline:
            print(f"[check_fe_cov_ratchet] FAIL - 拒绝回写：当前 {current:.2f}% "
                  f"低于基线 {baseline:.2f}%（棘轮只升不降）")
            return 1
        write_baseline(current)
        print(f"[check_fe_cov_ratchet] BASELINE UPDATED - {baseline:.2f}% → {current:.2f}%")
        return 0

    if current < baseline:
        print(f"[check_fe_cov_ratchet] FAIL - 前端覆盖率回退 "
              f"({current:.2f}% < baseline {baseline:.2f}%, ratchet only-up)；"
              "补测试回升或显式裁决后 --update-baseline")
        return 1
    if current > baseline:
        # 半自动上调：PASS 且实测高于基线 → 覆写基线存档进步（防静默回退）
        write_baseline(current)
        print(f"[check_fe_cov_ratchet] BASELINE RAISED - {baseline:.2f}% -> {current:.2f}% (semi-auto)")
    print(f"[check_fe_cov_ratchet] PASS - 前端覆盖率 {current:.2f}% >= baseline {baseline:.2f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
