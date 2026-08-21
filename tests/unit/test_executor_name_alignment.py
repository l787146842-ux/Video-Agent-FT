# -*- coding: utf-8 -*-
"""执行器名对齐门禁（防回潮）。

背景（事故台账 L-0821C）：skill 文档曾沿用源平台虚构执行器名
（media_generator/storyboard_designer/text_editor 等），系统内无对应实体，
模型读到即被误导。2026-08-21 裁决：skill 内执行器名一律为本项目真实
执行器/工具名；本测试把该不变量机械钉死。

钉死内容：
① data/skills/*.md 与 data/skills_manifests/*.json 不得出现遗留虚构名
   （宣言式概念短片.md 的两个散文墙章节 tag 为登记豁免，仅 tag 行有效）；
② skill 文档章节 tag 必须全部在 SECTION_TAG_STAGES 登记（解析不静默丢节）；
③ sidecar flow.steps 的加粗执行器标注必须全部是真实执行器/工具名。
"""
import json
import re
from pathlib import Path

from src.video_agent.skill_runtime.exec_tools import EXECUTOR_TOOL_CLASSES
from src.video_agent.web.skill_docs import SECTION_TAG_STAGES

ROOT = Path(__file__).resolve().parents[2]
SKILLS_DIR = ROOT / "data" / "skills"
MANIFEST_DIR = ROOT / "data" / "skills_manifests"

# 复用平台工具（非 skill 执行器但可被流程引用，宪法 §2.8 注释同源）
REUSED_TOOLS = {
    "image_generate", "generate_video", "generate_image",
    "document_write", "read_uploaded_doc", "workflow_pause",
}
REAL_NAMES = set(EXECUTOR_TOOL_CLASSES) | REUSED_TOOLS

LEGACY_NAMES = (
    "media_generator", "Media Generator", "storyboard_designer",
    "text_editor", "write_the_prompt", "multimodal_analyze_tool",
    "resource_prepare_and_analyze", "Resource Prepare and Analyze",
)
LEGACY_RE = re.compile(
    r"\b(" + "|".join(re.escape(n) for n in LEGACY_NAMES) + r")\b", re.I)

# 登记豁免：散文墙章节无法在不重构内容的前提下拆分（台账 L-0821C）；
# 仅允许这两个名字以纯 tag 行形式存在于该文档（注入语义由兼容映射承重）
EXEMPT_DOC_TAGS = {"宣言式概念短片.md": {"storyboard_designer", "media_generator"}}

TAG_LINE_RE = re.compile(r"^\s*</?([a-z_]+)>\s*$")


def _iter_skill_docs():
    return sorted(SKILLS_DIR.glob("*.md"))


def test_no_legacy_executor_names_in_skill_docs():
    for p in _iter_skill_docs():
        allowed = EXEMPT_DOC_TAGS.get(p.name, set())
        for i, ln in enumerate(p.read_text(encoding="utf-8").split("\n"), 1):
            for m in LEGACY_RE.finditer(ln):
                tag_m = TAG_LINE_RE.match(ln)
                if tag_m and tag_m.group(1) in allowed:
                    continue  # 登记豁免的章节 tag 行
                raise AssertionError(
                    f"{p.name}:L{i} 遗留虚构执行器名 {m.group(0)!r}: {ln.strip()[:60]}")


def test_no_legacy_executor_names_in_sidecars():
    for js in sorted(MANIFEST_DIR.glob("*.json")):
        hits = LEGACY_RE.findall(js.read_text(encoding="utf-8"))
        assert not hits, f"{js.name} 遗留虚构执行器名: {sorted(set(hits))}"


def test_skill_doc_tags_all_registered():
    # 章节 tag 独占一行（flova 格式）；行内 <<<placeholder>>> 等不是章节 tag
    tag_re = re.compile(r"(?m)^\s*</?([a-z_]+)>\s*$")
    for p in _iter_skill_docs():
        for m in tag_re.finditer(p.read_text(encoding="utf-8")):
            tag = m.group(1)
            assert tag in SECTION_TAG_STAGES, (
                f"{p.name} 章节 tag <{tag}> 未在 SECTION_TAG_STAGES 登记"
                "（解析会静默丢节）")


def test_sidecar_steps_only_reference_real_names():
    for js in sorted(MANIFEST_DIR.glob("*.json")):
        data = json.loads(js.read_text(encoding="utf-8"))
        steps = (data.get("flow") or {}).get("steps") or {}
        for k, v in steps.items():
            for bold in re.findall(r"\*\*([A-Za-z_/ 、]+)\*\*", v):
                for token in re.split(r"[、/ ]+", bold):
                    token = token.strip()
                    if not token:
                        continue
                    # snake_case 才是执行器/工具名；PascalCase 为源平台能力名
                    #（audit-0819d batch2 裁决：外来工具名翻译归将来专用系统）
                    if not re.fullmatch(r"[a-z][a-z_]+", token):
                        continue
                    assert token in REAL_NAMES, (
                        f"{js.name} step{k} 引用不存在的执行器/工具 {token!r}"
                        f"（真实名单：{sorted(REAL_NAMES)}）")
