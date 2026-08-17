"""类别 Key 字面量门禁（九轮 B2：P1 机械化根治）。

状态类别键（keyElements/shots/audioItems）的单一事实源是
src/video_agent/state/models.py 的 CAT_KEY_ELEMENTS / CAT_SHOTS / CAT_AUDIO_ITEMS
常量（宪法 §6 配置表纪律）。产品代码出现带引号的类别字面量即违规——
第九轮审核发现 3 处漏网硬编码（round_end_policies / chat_consume），
函数级测试照不出此类漂移，以 grep 门禁钉死（G4 同类全覆盖）。

白名单仅 models.py（常量定义处；pydantic alias 亦在彼）。
输出纯 ASCII（N1/N7 教训机制延续）。

用法：python scripts/check_category_keys.py   （退出码非 0 即失败）
"""
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCAN_DIR = ROOT / "src" / "video_agent"
WHITELIST = {"src/video_agent/state/models.py"}
PATTERN = re.compile(r"""["'](?:keyElements|shots|audioItems)["']""")


def main() -> int:
    violations = []
    for p in sorted(SCAN_DIR.rglob("*.py")):
        if "__pycache__" in p.parts:
            continue
        rel = p.relative_to(ROOT).as_posix()
        if rel in WHITELIST:
            continue
        for lineno, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if PATTERN.search(line):
                violations.append(f"  {rel}:{lineno}: {line.strip()[:90]}")
    if violations:
        print(f"[check_category_keys] FAIL - category-key literals outside models.py "
              f"({len(violations)} hit(s)):")
        print("\n".join(violations))
        print("payoff: use CAT_KEY_ELEMENTS / CAT_SHOTS / CAT_AUDIO_ITEMS "
              "from src.video_agent.state.models")
        return 1
    print("[check_category_keys] PASS - no category-key literals outside models.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
