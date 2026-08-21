# -*- coding: utf-8 -*-
"""审计各 Skill 的 prompt_draft 章节条款，为 skill_manifest gates 决策提供依据。"""
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from src.video_agent.web.skill_docs import split_skill_sections  # noqa: E402

OUT = pathlib.Path(__file__).parent / "skill_gate_audit.md"
d = pathlib.Path(__file__).parent.parent / "data" / "skills"

CAMERA = ("镜头", "景别", "推", "拉", "摇", "camera", "shot", "close-up", "wide", "pan", "orbit")
AUDIO = ("音效", "音频", "对白", "台词", "旁白", "音乐", "<", "{", "no music")
SUBTITLE = ("no subtitles", "无字幕", "不加字幕", "后期加字幕", "字幕后期")
DURATION = (r"\d+\s*秒", "时长", "duration")

lines = []
for f in sorted(d.glob("*.md")):
    content = f.read_text(encoding="utf-8", errors="replace")
    sections = split_skill_sections(content)
    pd = sections.get("prompt_draft", "")
    low = pd.lower()
    has = {
        "镜头语言标记": any(m in pd or m in low for m in CAMERA),
        "音频层标记": any(m in pd or m in low for m in AUDIO),
        "字幕负面约束": any(m in low for m in SUBTITLE),
        "时长要求": bool(re.search(r"\d+\s*秒|时长|duration", pd, re.I)),
        "要求英文提示词": bool(re.search(r"(提示词|prompt)[^\n]{0,60}(英语|英文|English)", pd, re.I)),
        "要求中文正文": ("中文" in pd) and ("必须" in pd or "最高优先级" in pd),
    }
    hits = [k for k, v in has.items() if v]
    lines.append(f"{f.name}: prompt_draft={len(pd)}字 | {hits or '章节为空/无标记'}")
    # 旁白语言锁定等特殊条款（宣言式）
    if "英文锁定" in content or "禁中文旁白" in content:
        lines.append("  !! 英文锁定条款（cjk 应调低）")
    if "不预锁绝对秒数" in content:
        lines.append("  !! 时长不预锁条款（require_duration 应关闭）")

OUT.write_text("\n".join(lines), encoding="utf-8")
print(f"written: {OUT}")
