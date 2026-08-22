# -*- coding: utf-8 -*-
"""P3-15 一致性诊断探针：scan_skills.manifest_consistency_issues 命中与不误报。

探针为报告性质（不进 acceptance GATES）；本测试钉死口径：
① 未声明/一致 → 空清单（不误报）；
② custom_sections 落空 / 声明执行器无章节支撑 / schema 非法 → 命中；
③ 存量 16 skill 实数据全绿（含试点 多人对话访谈 的音色设计声明）。
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
        "custom_sections": {"tone_design": "skill_section_run"},
    }
    assert scan_skills.manifest_consistency_issues("s", _DOC_FULL, manifest) == []


def test_probe_heading_style_section_no_false_positive():
    """标题式文档：声明标识命中标题关键字解析链不误报。"""
    content = "# 分镜设计\n镜头正文\n"
    manifest = {"custom_sections": {"分镜设计": "skill_section_run"}}
    assert scan_skills.manifest_consistency_issues("s", content, manifest) == []


# ---------- ② 命中 ----------


def test_probe_hits_unresolvable_custom_section():
    manifest = {"custom_sections": {"不存在章节": "skill_section_run"}}
    issues = scan_skills.manifest_consistency_issues("s", _DOC_FULL, manifest)
    assert any("custom_sections 声明「不存在章节」" in i for i in issues)


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


def test_probe_carries_schema_issues():
    manifest = {"custom_sections": {"音色设计": "script_analyze"}}
    issues = scan_skills.manifest_consistency_issues("s", _DOC_FULL, manifest)
    assert any("custom_sections" in i for i in issues)


# ---------- ③ 存量实数据全绿（含试点声明） ----------


def test_probe_real_skills_all_consistent():
    """任务#5：声明已迁入文档头部 frontmatter（外置 JSON 目录已删除），
    探针直接读同目录 frontmatter。"""
    from src.video_agent.skill_runtime import frontmatter

    skills_dir = ROOT / "data" / "skills"
    total = 0
    for f in sorted(skills_dir.glob("*.md")):
        content = f.read_text(encoding="utf-8")
        manifest = frontmatter.load_manifest(f.stem, directory=skills_dir)
        issues = scan_skills.manifest_consistency_issues(f.stem, content, manifest)
        assert issues == [], f"Skill「{f.stem}」探针不一致: {issues}"
        total += 1
    assert total >= 16


def test_probe_pilot_skill_custom_section_registered():
    """试点 多人对话访谈：音色设计声明可解析 → skill_section_run 进注册清单。"""
    from src.video_agent.skill_runtime import registry

    registry.reset_registry()
    try:
        entry = registry.resolve_entry("多人对话访谈")
        assert entry is not None
        assert entry.custom_sections == {"音色设计": "skill_section_run"}
        assert "skill_section_run" in entry.available_tools
        assert "音色档案" in registry.tool_sections("多人对话访谈", "skill_section_run")
    finally:
        registry.reset_registry()
