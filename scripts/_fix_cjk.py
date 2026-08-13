# -*- coding: utf-8 -*-
"""一次性修正：宣言式概念短片 manifest 的 cjk_min_ratio 0.01 → 0（关闭语言闸）。"""
import pathlib

f = pathlib.Path(__file__).parent.parent / "data" / "skills" / "宣言式概念短片.md"
c = f.read_text(encoding="utf-8")
c2 = c.replace('"cjk_min_ratio": 0.01', '"cjk_min_ratio": 0')
assert c2 != c, "未找到待替换文本"
f.write_text(c2, encoding="utf-8")
print("fixed")
