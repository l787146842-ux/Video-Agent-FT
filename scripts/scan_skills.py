# -*- coding: utf-8 -*-
"""扫描 data/skills/*.md，输出每个 Skill 的结构摘要，用于诊断指令冲突。"""
import re
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from src.video_agent.web.skill_docs import split_skill_sections, parse_pause_rules  # noqa: E402
from src.video_agent.core.prompt_gates import parse_gate_rules  # noqa: E402

OUT = pathlib.Path(__file__).parent / "skill_scan_report.md"
d = pathlib.Path(__file__).parent.parent / "data" / "skills"

lines = []
for f in sorted(d.glob("*.md")):
    content = f.read_text(encoding="utf-8", errors="replace")
    sections = split_skill_sections(content)
    pause = parse_pause_rules(content)
    gates = parse_gate_rules(content)
    has_gate_block = bool(re.search(r"```(?:json|js)?\s*gate_rules\s*\n", content))
    lines.append("=" * 70)
    lines.append(f"SKILL: {f.name}  ({f.stat().st_size} 字节)")
    lines.append(f"  章节(stage): {sorted(k for k, v in sections.items() if v.strip()) or '无'}")
    lines.append(f"  pause_rules: {pause}")
    lines.append(f"  gate_rules 块存在: {has_gate_block}")
    if has_gate_block:
        lines.append(f"  gate_rules 解析结果: {gates}")
    # 关键条款探针：与系统硬编码闸机可能冲突的词
    probes = {
        "要求中文正文": "中文" in content and ("最高优先级" in content or "必须" in content),
        "提到字幕后期/no subtitles": ("no subtitles" in content.lower()) or ("字幕" in content),
        "提到时长(秒)": bool(re.search(r"\d+\s*秒|时长", content)),
        "提到音频层/音效": ("音效" in content) or ("音频" in content),
        "提到规格文档": ("规格" in content) or ("spec" in content.lower()),
        "要求英文提示词": bool(re.search(r"(提示词|prompt)[^\n]{0,40}(英语|英文|English)", content, re.I)),
        "提到分辨率": ("分辨率" in content) or ("resolution" in content.lower()),
        "何时暂停字样": ("何时暂停" in content) or ("强制暂停点" in content),
    }
    hits = [k for k, v in probes.items() if v]
    lines.append(f"  探针命中: {hits or '无'}")
    # 提取 <planner> 流程前 500 字，看流程是否与「剧本→规格→KE→分镜→提示词」不同
    flow = sections.get("planning", "").strip()
    if flow:
        lines.append(f"  <planner> 流程预览(前600字): {flow[:600].replace(chr(10), ' | ')}")
    else:
        lines.append("  <planner> 流程预览: （无 planner 章节）")
    lines.append("")

OUT.write_text("\n".join(lines), encoding="utf-8")
print(f"written: {OUT}")
