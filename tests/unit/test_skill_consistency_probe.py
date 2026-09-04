# -*- coding: utf-8 -*-
"""P3-15 一致性诊断探针：scan_skills.manifest_consistency_issues 命中与不误报。

探针为报告性质（不进 acceptance GATES）；本测试钉死口径：
① 未声明/一致 → 空清单（不误报）；
② 声明执行器无章节支撑 / schema 非法 → 命中；
③ 存量 15 skill 实数据全绿。
（C1b 裁决 2026-08-31：custom_sections 探针随通道退役删除。）
"""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

_spec = importlib.util.spec_from_file_location(
    "scan_skills_probe", ROOT / "scripts" / "scan_skills.py")
scan_skills = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(scan_skills)

_DOC_FULL = (
    "# 全章节\n"
    "<planner>\n流程\n</planner>\n"
    "<storyboard_key_elements>\nKE\n</storyboard_key_elements>\n"
    "<storyboard_shots>\n分镜\n</storyboard_shots>\n"
    "<storyboard_audio>\n音频\n</storyboard_audio>\n"
    "<write_media_prompt>\n提示词\n</write_media_prompt>\n"
    "<generation>\n生成\n</generation>\n"
    "<video_assembler>\n组装\n</video_assembler>\n"
    "<tone_design>\n音色章节\n</tone_design>\n"
)


# ---------- ① 不误报 ----------


def test_probe_undeclared_manifest_clean():
    assert scan_skills.manifest_consistency_issues("s", _DOC_FULL, None) == []
    assert scan_skills.manifest_consistency_issues("s", _DOC_FULL, {}) == []


def test_probe_consistent_declaration_clean():
    manifest = {
        "flow": {
            "stage_executors": {
                "1": ["storyboard_key_elements", "image_generate"],
                "2": ["video_assembler"],
            },
        },
    }
    # 僵尸键（stage_executors）声明仅产生 WARN 过渡告警，错误级为零；
    # 执行器章节支撑探针不误报（一致性语义不变）。
    from src.video_agent.skill_runtime.manifest_schema import split_issue_warnings

    errors, warnings = split_issue_warnings(
        scan_skills.manifest_consistency_issues("s", _DOC_FULL, manifest))
    assert errors == []
    assert any("stage_executors" in w for w in warnings)


# ---------- ② 命中 ----------


def test_probe_hits_executor_without_section_support():
    doc = "# 缺组装\n<planner>\n流程\n</planner>\n"
    manifest = {"flow": {"stage_executors": {"1": ["video_assembler"]}}}
    issues = scan_skills.manifest_consistency_issues("s", doc, manifest)
    assert any("video_assembler" in i and "无文档章节支撑" in i for i in issues)


def test_probe_hits_unknown_executor_and_reused_exempt():
    manifest = {"flow": {"stage_executors": {
        "1": ["不存在的执行器", "document_write", "read_skill"]}}}
    issues = scan_skills.manifest_consistency_issues("s", _DOC_FULL, manifest)
    assert any("不存在的执行器" in i for i in issues)
    # 复用工具豁免：不误报
    assert not any("document_write" in i or "read_skill" in i for i in issues)


# ---------- ③ 存量实数据全绿 ----------


def test_probe_real_skills_all_consistent():
    """任务#5：声明已迁入文档头部 frontmatter（外置 JSON 目录已删除），
    探针直接读同目录 frontmatter。"""
    from src.video_agent.skill_runtime import frontmatter

    skills_dir = ROOT / "data" / "skills"
    total = 0
    # 批3 单一包形态遍历：<slug>/SKILL.md 目录包（_iter 同口径）
    for stem, f in scan_skills._iter_skill_docs(skills_dir):
        content = f.read_text(encoding="utf-8")
        manifest = frontmatter.load_manifest(stem, directory=skills_dir)
        issues = scan_skills.manifest_consistency_issues(stem, content, manifest)
        assert issues == [], f"Skill「{stem}」探针不一致: {issues}"
        total += 1
    assert total >= 15
