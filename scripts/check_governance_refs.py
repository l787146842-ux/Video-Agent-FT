"""治理叙事门禁（宪法 §9 事故注释约定的机械兜底；七轮 S3/F3 落地）。

统计产品代码中的「治理叙事标记」总量并设预算（棘轮，只降不升）：
事故编号引用/轮次批注会随审计轮次复利膨胀，把「为什么这么做」的叙事留在代码里；
§9 已约定「新注释只写结论，事故叙事归台账」，但约定无门禁终将反弹——
本脚本复制 check_prompt_budget 的成功经验：有预算、有门禁、只认退出码。

模式口径（收紧，防误伤端口号/超时值等非事故数字）：
1. 「事故」字样；
2. 814 系列批注编号（814[A-Z]）；
3. 四位重复数字事故号（如 2222/8888，\\b(\\d)\\1{3}\\b）；
4. 「X轮」轮次批注（一至七轮）。

预算 = 36（任务#12 E8 前端残余与 fc_tool_runner 拆分产物域清扫后实测下调：
56→45→36；棘轮只降不升）。
输出纯 ASCII（防 Windows 终端乱码把失败误读成通过）。

用法：python scripts/check_governance_refs.py   （退出码非 0 即失败）
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCAN_DIRS = ["src/video_agent", "src/web"]
EXTS = {".py", ".ts", ".tsx"}
BUDGET = 36
PATTERN = re.compile(r"事故|814[A-Z][0-9]?|\b(\d)\1{3}\b|[一二三四五六七]轮")


def iter_source_files():
    for d in SCAN_DIRS:
        base = ROOT / d
        for p in base.rglob("*"):
            if p.is_file() and p.suffix in EXTS:
                yield p


def main() -> int:
    total = 0
    per_file = {}
    for p in iter_source_files():
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        n = len(PATTERN.findall(text))
        if n:
            rel = p.relative_to(ROOT).as_posix()
            per_file[rel] = n
            total += n

    print(f"[check_governance_refs] governance narrative markers: {total} (budget {BUDGET})")
    if total > BUDGET:
        worst = sorted(per_file.items(), key=lambda kv: -kv[1])[:10]
        for rel, n in worst:
            print(f"[check_governance_refs]   {n:4d}  {rel}")
        print(
            f"[check_governance_refs] FAIL: {total} > budget {BUDGET}. "
            "New comments must state conclusions only (ARCH_RULES S9); "
            "incident narrative belongs outside the codebase "
            "(GOVERNANCE S13.8/13.10 external ledger). "
            "After cleaning existing markers, lower BUDGET (ratchet)."
        )
        return 1
    print("[check_governance_refs] PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
