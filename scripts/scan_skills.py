# -*- coding: utf-8 -*-
"""扫描 data/skills/*.md，输出每个 Skill 的结构摘要，用于诊断指令冲突。

P3-15 新增：sidecar 声明（含 custom_sections）vs 文档实际章节一致性探针
（诊断先行，报告性质，不进 acceptance GATES）。
"""
import re
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from src.video_agent.web.skill_docs import split_skill_sections, parse_pause_rules  # noqa: E402
from src.video_agent.core.prompt_gates import parse_gate_rules  # noqa: E402
from src.video_agent.skill_runtime import sidecar  # noqa: E402
from src.video_agent.skill_runtime.registry import (  # noqa: E402
    CUSTOM_SECTION_EXECUTOR,
    SKILL_EXECUTOR_TOOLS,
    TOOL_STAGES,
    SkillEntry,
)

# 复用现有工具（非 Skill 执行器，不要求文档章节支撑；
# 口径与 registry.py 头注「复用现有工具不在此列」一致）
REUSED_TOOL_NAMES = (
    "document_write", "read_uploaded_doc", "image_generate",
    "generate_video", "workflow_pause", "read_skill",
    CUSTOM_SECTION_EXECUTOR,
)


def sidecar_consistency_issues(slug: str, content: str, manifest) -> list:
    """sidecar 声明 vs 文档实际章节一致性探针；返回不一致清单（空 = 一致）。

    未声明 manifest = 零声明回落合法（与 schema「未声明键合法」同构）。
    检测口径（报告性质，不做门禁）：
    ① schema 校验问题（与注册期 fail-closed 告警同源）；
    ② custom_sections 声明标识在文档解析链（stage/tag/标题/任意 <tag>）落空；
    ③ flow 声明的执行器（stage_executors / stages.*.executors）无文档章节支撑
       ——只查已知 Skill 执行器；复用工具与自定义通道豁免。
    """
    issues = list(sidecar.validate_sidecar(manifest) or [])
    if not isinstance(manifest, dict):
        return issues
    sections = split_skill_sections(content or "")
    entry = SkillEntry(
        slug=slug, name=slug, content=content or "", sections=sections)
    # ② custom_sections 声明可用性（与 registry 注册预检同口径）
    custom = manifest.get("custom_sections")
    if isinstance(custom, dict):
        for key in sorted(str(k) for k in custom):
            if key.strip() and not entry.custom_section_text(key):
                issues.append(
                    f"custom_sections 声明「{key}」在文档无对应章节"
                    f"（stage/tag/标题解析链全落空）")
    # ③ 声明执行器 × 文档章节支撑
    doc_tools = {
        t for t in SKILL_EXECUTOR_TOOLS
        if any((sections.get(s) or "").strip() for s in TOOL_STAGES.get(t, ()))
    }
    flow = manifest.get("flow") or {}
    declared = []
    for v in (flow.get("stage_executors") or {}).values():
        if isinstance(v, list):
            declared += [t for t in v if isinstance(t, str)]
    for ov in (flow.get("stages") or {}).values():
        if isinstance(ov, dict) and isinstance(ov.get("executors"), list):
            declared += [t for t in ov["executors"] if isinstance(t, str)]
    for t in sorted(set(declared)):
        if t in REUSED_TOOL_NAMES:
            continue
        if t not in SKILL_EXECUTOR_TOOLS:
            issues.append(f"声明执行器 {t} 不是已知 Skill 执行器")
        elif t not in doc_tools:
            issues.append(
                f"声明执行器 {t} 无文档章节支撑（TOOL_STAGES 对应章节落空）")
    return issues


def main() -> None:
    OUT = pathlib.Path(__file__).parent / "skill_scan_report.md"
    d = pathlib.Path(__file__).parent.parent / "data" / "skills"

    lines = []
    mismatched = []
    total = 0
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
        # P3-15：sidecar 声明（含 custom_sections）vs 文档实际章节一致性
        manifest = sidecar.load_sidecar(f.stem)
        consistency = sidecar_consistency_issues(f.stem, content, manifest)
        total += 1
        if consistency:
            mismatched.append(f.stem)
        lines.append(f"  sidecar 一致性: {'一致' if not consistency else consistency}")
        # 提取 <planner> 流程前 500 字，看流程是否与「剧本→规格→KE→分镜→提示词」不同
        flow = sections.get("planning", "").strip()
        if flow:
            lines.append(f"  <planner> 流程预览(前600字): {flow[:600].replace(chr(10), ' | ')}")
        else:
            lines.append("  <planner> 流程预览: （无 planner 章节）")
        lines.append("")

    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"written: {OUT}")
    tail = f"（{'、'.join(mismatched)}）" if mismatched else ""
    print(f"[scan_skills] sidecar 一致性探针: 共 {total} 个 skill，"
          f"{len(mismatched)} 个不一致{tail}")


if __name__ == "__main__":
    main()
