"""样式 token 收口门禁（任务#4 落地色值棘轮；任务#14 扩展为三台账）。

单脚本三台账（同一白名单+只降不升范式）：
1. 色值台账：#hex / rgb()/rgba() 硬编码；
2. 字阶台账：font-size 硬编码（未走 var(--font-*) 的 px/em/inherit 等均计入）；
3. 层级台账：z-index 硬编码（未走 var(--z-*) 的数值）。

规则：
- 扫描 src/web/styles/**/*.css（rglob 递归，子目录同样受守；tokens.css
  为 token 定义源，豁免）；
- 存量无法即时清偿的残留登记在各 WHITELIST（文件 -> 允许上限，
  棘轮只减不增）：实际计数超过登记值即 FAIL；未在 WHITELIST 的
  文件出现硬编码即 FAIL（即新文件零容忍）；清偿一件随降一件，
  登记值禁止上调。
- 语义状态色一律改用 tokens.css 的 --color-danger/success/warning/info 族
  （透明档用 color-mix(in srgb, var(--token) N%, transparent) 现调）；
  字阶一律走 --font-* 档；层级一律走 --z-* 档。

白名单存量性质（清偿路径）：
- 中性黑白灰：rgba(0,0,0,*) 阴影/遮罩、rgba(255,255,255,*) 提亮、
  #fff/#ffffff 彩底白字与亮色面板底、深灰面板底（#1f2430/#1e293b/#0b0c10 等）；
- code-block.css：hljs 语法高亮色板（第三方配色规范，不随主题语义走）；
- chat-cards.css / chat-feed-timeline.css：planning/confirm 橙色规范色板
  （体验规范刻意设计，注释已明示）；
- chat-input-picker.css：skill-use-btn 装饰渐变（#6366f1 系品牌渐变）。
字阶/层级台账的保留项：半像素档（10.5/11.5/12.5px）、em 相对档、
inherit 继承档等无法等值 token 化的特殊值，清偿至仅剩这些值后封顶。
另：tsx 组件内联硬编码（style 对象/SVG 属性）已同步等值清偿，
不在本门禁扫描范围（门禁只守 styles/*.css）。

退役条件（宪法 §13.7 同步登记）：
色值 WHITELIST 全部清偿归零后，本闸降级为「styles/ 下任何新增硬编码即 FAIL」
的零白名单硬门禁继续值守；仅当样式体系整体迁移至 CSS-in-JS 或主题引擎、
tokens.css 不再是唯一样式值源时，方可裁决整体退役（§13.14(c)）。
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STYLES = ROOT / "src" / "web" / "styles"
# token 定义源：语义色值的合法定义地，豁免扫描
EXEMPT = {"tokens.css"}

COLOR_RE = re.compile(r"#[0-9a-fA-F]{3,8}\b|rgba?\([^)]*\)")
# 字阶/层级硬编码：声明值未走 var(-- 即计入（含 px/em/inherit/裸数值）；
# 捕获后过滤（负向前瞻会被 \s* 回溯绕过）
FONT_SIZE_RE = re.compile(r"font-size:\s*([^;}]+)")
Z_INDEX_RE = re.compile(r"z-index:\s*([^;}]+)")


def count_decl(regex: re.Pattern, text: str) -> int:
    return sum(
        1 for m in regex.finditer(text)
        if not m.group(1).strip().startswith("var(--")
    )

# 白名单：文件 -> 允许的硬编码色计数上限（任务#4 首查登记，棘轮只减不增；
# 清偿一处随降一处，禁止上调；条目归零后移除）
WHITELIST = {
    "chat-cards.css": 26,            # planning/confirm 橙色规范色板（体验规范豁免）
    "chat-feed-timeline.css": 6,     # planning 橙色徽章（体验规范豁免）
    "chat-input-picker.css": 3,      # skill-use-btn 装饰渐变（#6366f1 系品牌渐变）
    "code-block.css": 19,            # hljs 语法高亮色板（第三方规范配色）
}
# 全量计数棘轮基线（随白名单清偿只降不升，禁止上调）
TOTAL_BASELINE = sum(WHITELIST.values())

# 字阶台账白名单（任务#14 首批登记 302；等值清偿后封顶 = 仅剩
# 无法等值 token 化的半像素/em/inherit 档，棘轮只减不增）
FONT_SIZE_WHITELIST = {
    "chat-cards.css": 2,            # 11.5px/12.5px 半像素档
    "chat-feed-cards.css": 2,       # 10.5px 半像素档 ×2
    "chat-feed-timeline.css": 1,    # inherit 继承档
    "chat-input-picker.css": 1,     # 12.5px 半像素档
    "left-panel.css": 1,            # inherit 继承档
    "middle-panel.css": 2,          # 0.8em/0.95em 相对档
    "overlays-core.css": 2,         # inherit 继承档 ×2
}
FONT_SIZE_TOTAL_BASELINE = sum(FONT_SIZE_WHITELIST.values())

# 层级台账白名单（任务#14 首批登记 25；已全量等值清偿至 --z-* 档，
# 归零退役为「任何新增 z-index 硬编码即 FAIL」；棘轮只减不增）
Z_INDEX_WHITELIST: dict[str, int] = {}
Z_INDEX_TOTAL_BASELINE = sum(Z_INDEX_WHITELIST.values())


def count_colors(p: Path) -> int:
    return len(COLOR_RE.findall(p.read_text(encoding="utf-8")))


def main() -> int:
    failures = 0
    ledger = [
        ("colors", COLOR_RE, WHITELIST, TOTAL_BASELINE,
         "use --color-* tokens from tokens.css", False),
        ("font-size", FONT_SIZE_RE, FONT_SIZE_WHITELIST, FONT_SIZE_TOTAL_BASELINE,
         "use --font-* tokens from tokens.css", True),
        ("z-index", Z_INDEX_RE, Z_INDEX_WHITELIST, Z_INDEX_TOTAL_BASELINE,
         "use --z-* tokens from tokens.css", True),
    ]
    for name, regex, whitelist, baseline, payoff, decl in ledger:
        violations, over, total = [], [], 0
        for p in sorted(STYLES.rglob("*.css")):
            if p.name in EXEMPT:
                continue
            text = p.read_text(encoding="utf-8")
            n = count_decl(regex, text) if decl else len(regex.findall(text))
            total += n
            if n == 0:
                continue
            if p.name not in whitelist:
                violations.append(
                    f"  {p.name}: {n} hardcoded {name} (not whitelisted)")
            elif n > whitelist[p.name]:
                over.append(f"  {p.name}: {n} > baseline {whitelist[p.name]}")
        if violations:
            print(f"[check_semantic_colors] FAIL - hardcoded {name} in "
                  f"unwhitelisted file:")
            print("\n".join(violations))
            print(f"payoff: {payoff}")
            failures += 1
            continue
        if over:
            print(f"[check_semantic_colors] FAIL - whitelisted {name} count "
                  f"increased (only-down):")
            print("\n".join(over))
            failures += 1
            continue
        if total > baseline:
            print(f"[check_semantic_colors] FAIL - {name} total {total} > "
                  f"baseline {baseline} (ratchet only-down)")
            failures += 1
            continue
        print(f"[check_semantic_colors] PASS - styles/*.css hardcoded {name} "
              f"{total} <= baseline {baseline}; new additions forbidden")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
