# -*- coding: utf-8 -*-
"""一致性诊断探针：scan_skills.manifest_consistency_issues 命中与不误报。

2026-11-11 通用 skill 口径：探针只查 frontmatter 解析/schema；
流程执行器 / 章节 tag 不再是平台声明，不做一致性比对。
"""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

_spec = importlib.util.spec_from_file_location(
    "scan_skills_probe", ROOT / "scripts" / "scan_skills.py")
scan_skills = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(scan_skills)

_DOC_FULL = (
    "# 全章节\n\n"
    "## 制作流程\n流程\n\n"
    "## 关键元素\nKE\n\n"
    "## 分镜\n分镜\n\n"
    "## 音频层\n音频\n\n"
    "## 提示词写法\n提示词\n\n"
    "## 媒体生成\n生成\n\n"
    "## 组装导出\n组装\n"
)


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
    from src.video_agent.skill_runtime.manifest_schema import split_issue_warnings

    errors, warnings = split_issue_warnings(
        scan_skills.manifest_consistency_issues("s", _DOC_FULL, manifest))
    assert errors == []
    assert any("stage_executors" in w for w in warnings)


def test_probe_reports_deprecated_flow_steps():
    """声明已废除的 flow.steps → schema 错误（与注册期同源）。"""
    manifest = {"flow": {"steps": [{"key": "1"}]}}
    issues = scan_skills.manifest_consistency_issues("s", _DOC_FULL, manifest)
    assert any("flow.steps 已废除" in i for i in issues)


def test_probe_ignores_executor_names():
    """执行器名不再要求文档章节支撑（通用 skill 没有标签章节）。"""
    manifest = {"flow": {"stage_executors": {
        "1": ["不存在的执行器", "document_write", "read_skill"]}}}
    issues = scan_skills.manifest_consistency_issues("s", _DOC_FULL, manifest)
    assert not any("无文档章节支撑" in i for i in issues)
    assert not any("不是已知管线能力词汇" in i for i in issues)


def test_probe_real_skills_all_consistent():
    from src.video_agent.skill_runtime import frontmatter

    skills_dir = ROOT / "data" / "skills"
    total = 0
    for stem, f in scan_skills._iter_skill_docs(skills_dir):
        content = f.read_text(encoding="utf-8")
        manifest = frontmatter.load_manifest(stem, directory=skills_dir)
        issues = scan_skills.manifest_consistency_issues(stem, content, manifest)
        assert issues == [], f"Skill「{stem}」探针不一致: {issues}"
        total += 1
    assert total >= 15
