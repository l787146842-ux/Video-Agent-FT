"""语义色收口门禁（任务#4 落地；防硬编码色值回潮）。

规则：
- 扫描 src/web/styles/*.css（tokens.css 为 token 定义源，豁免）；
- 任何 #hex / rgb()/rgba() 硬编码色值都计入违规；
- 存量无法即时清偿的残留登记在 WHITELIST（文件 -> 允许上限，棘轮只减不增）：
  实际计数超过登记值即 FAIL；未在 WHITELIST 的文件出现硬编码色即 FAIL
  （即新文件零容忍）；清偿一件随降一件，登记值禁止上调。
- 语义状态色一律改用 tokens.css 的 --color-danger/success/warning/info 族
  （透明档用 color-mix(in srgb, var(--token) N%, transparent) 现调）。

白名单存量性质（清偿路径）：
- 中性黑白灰：rgba(0,0,0,*) 阴影/遮罩、rgba(255,255,255,*) 提亮、
  #fff/#ffffff 彩底白字与亮色面板底、深灰面板底（#1f2430/#1e293b/#0b0c10 等）；
- code-block.css：hljs 语法高亮色板（第三方配色规范，不随主题语义走）；
- chat-cards.css / chat-feed-timeline.css：planning/confirm 橙色规范色板
  （体验规范刻意设计，注释已明示）；
- chat-input-picker.css：skill-use-btn 装饰渐变（#6366f1 系品牌渐变）。

退役条件（宪法 §13.7 同步登记）：
WHITELIST 全部清偿归零后，本闸降级为「styles/ 下任何新增硬编码色即 FAIL」
的零白名单硬门禁继续值守；仅当样式体系整体迁移至 CSS-in-JS 或主题引擎、
tokens.css 不再是唯一色值源时，方可裁决整体退役（§13.14(c)）。
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STYLES = ROOT / "src" / "web" / "styles"
# token 定义源：语义色值的合法定义地，豁免扫描
EXEMPT = {"tokens.css"}

COLOR_RE = re.compile(r"#[0-9a-fA-F]{3,8}\b|rgba?\([^)]*\)")

# 白名单：文件 -> 允许的硬编码色计数上限（任务#4 首查登记，棘轮只减不增；
# 清偿一处随降一处，禁止上调；条目归零后移除）
WHITELIST = {
    "chat-cards.css": 38,            # planning/confirm 橙色规范色板 + 中性黑白灰
    "chat-feed-cards.css": 4,        # 中性白提亮档
    "chat-feed-core.css": 5,         # 中性灰状态点/白底
    "chat-feed-search.css": 2,       # 中性白提亮档
    "chat-feed-timeline.css": 9,     # planning 橙色徽章 + 中性白档
    "chat-input-composer.css": 5,    # 气泡内白字/白底托 + 音频浅色
    "chat-input-core.css": 11,       # 白字彩底 + 深灰浮层底（含 light 覆盖）
    "chat-input-lightbox.css": 8,    # 遮罩/深色面板底 + 白字
    "chat-input-mention.css": 5,     # 阴影/黑底视频角标 + 白字
    "chat-input-picker.css": 13,     # 阴影/白提亮 + skill-use-btn 装饰渐变
    "code-block.css": 19,            # hljs 语法高亮色板（第三方规范配色）
    "genlog.css": 3,                 # 白字彩底 + 阴影
    "health-banner.css": 2,          # 白字 + 阴影（banner 语义色已 token 化）
    "layout.css": 8,                 # 中性黑白灰/阴影
    "left-panel.css": 10,            # 中性黑白灰/阴影/开关白拇指
    "middle-panel.css": 31,          # 预览深色底/遮罩/白字/深灰占位底
    "overlays-core.css": 7,          # 遮罩/阴影/白字
    "overlays-menu.css": 2,          # 阴影
    "overlays-modal.css": 8,         # 遮罩/阴影/白字
    "overlays-panel.css": 8,         # 阴影/白提亮/白字
    "skill-structured.css": 2,       # 白字 + 阴影
}
# 全量计数棘轮基线（随白名单清偿只降不升，禁止上调）
TOTAL_BASELINE = sum(WHITELIST.values())


def count_colors(p: Path) -> int:
    return len(COLOR_RE.findall(p.read_text(encoding="utf-8")))


def main() -> int:
    violations, over, total = [], [], 0
    for p in sorted(STYLES.glob("*.css")):
        if p.name in EXEMPT:
            continue
        n = count_colors(p)
        total += n
        if n == 0:
            continue
        if p.name not in WHITELIST:
            violations.append(f"  {p.name}: {n} hardcoded color(s) (not whitelisted)")
        elif n > WHITELIST[p.name]:
            over.append(f"  {p.name}: {n} > baseline {WHITELIST[p.name]}")
    if violations:
        print("[check_semantic_colors] FAIL - hardcoded colors in unwhitelisted file:")
        print("\n".join(violations))
        print("payoff: use --color-danger/success/warning/info tokens from tokens.css")
        return 1
    if over:
        print("[check_semantic_colors] FAIL - whitelisted count increased (only-down):")
        print("\n".join(over))
        return 1
    if total > TOTAL_BASELINE:
        print(f"[check_semantic_colors] FAIL - total {total} > baseline "
              f"{TOTAL_BASELINE} (ratchet only-down)")
        return 1
    print(f"[check_semantic_colors] PASS - styles/*.css hardcoded colors "
          f"{total} <= baseline {TOTAL_BASELINE}; new additions forbidden")
    return 0


if __name__ == "__main__":
    sys.exit(main())
