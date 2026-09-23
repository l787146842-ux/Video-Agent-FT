# -*- coding: utf-8 -*-
"""复算：闸机拒收文案 → compose_failure_feedback 的 [:120] 截断点。只读。"""
import io, os, sys

reject_full = (
    "storyboard_add_draft 被拒收：本阶段（故事板设计）新建草稿卡只允许 "
    "mediaType=audio/video，收到 'image'。"
    "本次调用未执行、工作台保持原样。"
    "本阶段（故事板设计）产出关键元素分组、角色音色卡"
    "（key_element_audio，mediaType=audio）与分镜卡（mediaType=video）；"
    "角色/场景/道具的图像卡与提示词属提示词撰写阶段，"
    "请在委派 write_media_prompt 阶段时创建。"
)

lines = []
lines.append("闸机完整拒收文案（card_media_gate 返回，allowed={audio,video}）:")
lines.append("  len = %d" % len(reject_full))
lines.append("  全文 = %r" % reject_full)
lines.append("")
cut = reject_full[:120]
lines.append("compose_failure_feedback 取 raw = error_text[:120]：")
lines.append("  len(raw) = %d" % len(cut))
lines.append("  截断后 = %r" % cut)
lines.append("  被截掉的余量 = %r" % reject_full[120:])
lines.append("")
lines.append("2026-09-22 实跑 seq=31 工具结果里模型看到的原文：")
actual = ("storyboard_add_draft 被拒收：本阶段（故事板设计）新建草稿卡只允许 mediaType=audio/video，"
          "收到 'image'。本次调用未执行、工作台保持原样。本阶段（故事板设计）产出关键元素分组、"
          "角色音色卡（ke")
lines.append("  len = %d" % len(actual))
lines.append("  repr = %r" % actual)
lines.append("")
lines.append("截断前缀 == 实跑原文？ %s" % (cut == actual))
lines.append("实跑原文是否以截断结果开头？ %s" % actual.startswith(cut[:100]))
lines.append("")
# 关键：被截掉的'该去哪里做'指引
tail = reject_full[120:]
for kw in ["write_media_prompt", "图像卡", "提示词撰写阶段"]:
    lines.append("关键字 %r 是否落在 [:120] 内？ %s" % (kw, kw in cut))
lines.append("")
lines.append("整条回喂（compose_failure_feedback 输出，fail_count=1, kind='other'）：")
lines.append("  [other] %s（既有工作台状态未被本次失败改动）。建议：%s" % (cut, "<FAILURE_HINT>"))

out = os.path.join(os.path.dirname(__file__), "probe_truncate_out.txt")
io.open(out, "w", encoding="utf-8").write("\n".join(lines))
print("written", out)
