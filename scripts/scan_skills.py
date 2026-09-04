# -*- coding: utf-8 -*-
"""Skill 客观结构/资源诊断脚本：扫描 data/skills/<slug>/SKILL.md（单一包形态）。

两个入口：
- 报表入口（默认）：输出每个 Skill 的结构摘要（章节/frontmatter
  一致性/资源探针），报告性质。
- --gate 入口：仅客观结构问题决定 FAIL 退出码（frontmatter 解析失败 /
  schema 一致性 / 声明执行器无文档章节支撑）；name/description 存在性与
  目录包资源探针（指针悬空/scripts 路径/references 孤儿/assets 版本锁
  孤儿/悬空）恒为 WARN 清单，不阻断退出码。

scripts/acceptance.py 以 EVAL_WARN 档（--with-eval）调用 --gate，
打印告警、不计入验收退出码。
正文句式扫描（语言宣称/优先级宣称探针）已按用户裁决 R-3 退役：
不检查、不消音 Skill 正文任何句式，禁止新增正文扫描。
"""
import re
import sys
import pathlib
from datetime import date

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from src.video_agent.web.skill_docs import split_skill_sections  # noqa: E402
from src.video_agent.skill_runtime import frontmatter  # noqa: E402
from src.video_agent.skill_runtime.registry import (  # noqa: E402
    CAPABILITY_TOOL_STAGES,
    PIPELINE_CAPABILITY_TOOLS,
    SkillEntry,
)

# 平台既有工具（非管线能力词汇，不要求文档章节支撑）
REUSED_TOOL_NAMES = (
    "document_write", "read_uploaded_doc", "image_generate",
    "generate_video", "workflow_pause", "read_skill",
)

# （正文句式扫描——内容卫生/优先级宣称/语言宣称探针——已按用户裁决 R-3
# 退役删除：Skill 正文句式不检查、不消音；本脚本只做客观结构/资源诊断。）


def manifest_consistency_issues(slug: str, content: str, manifest) -> list:
    """frontmatter 声明 vs 文档实际章节一致性探针；返回不一致清单（空 = 一致）。

    未声明 manifest = 零声明回落合法（与 schema「未声明键合法」同构）。
    检测口径（报告性质，不做门禁）：
    ① schema 校验问题（与注册期 fail-closed 告警同源）；
    ③ flow 声明的执行器（stage_executors / stages.*.executors）无文档章节支撑
       ——只查已知 Skill 执行器；复用工具豁免。
    （C1b 裁决 2026-08-31：② custom_sections 探针随通道退役删除。）
    """
    issues = list(frontmatter.validate_manifest(manifest) or [])
    if not isinstance(manifest, dict):
        return issues
    sections = split_skill_sections(content or "")
    entry = SkillEntry(
        slug=slug, name=slug, content=content or "", sections=sections)
    # ③ 声明执行器 × 文档章节支撑
    doc_tools = {
        t for t in PIPELINE_CAPABILITY_TOOLS
        if any((sections.get(s) or "").strip()
               for s in CAPABILITY_TOOL_STAGES.get(t, ()))
    }
    flow = manifest.get("flow") or {}
    declared = []
    for v in (flow.get("stage_executors") or {}).values():
        if isinstance(v, list):
            declared += [t for t in v if isinstance(t, str)]
    # （C1b 裁决 2026-08-31：flow.stages.*.executors 覆盖声明退役，消费删除）
    for t in sorted(set(declared)):
        if t in REUSED_TOOL_NAMES:
            continue
        if t not in PIPELINE_CAPABILITY_TOOLS:
            issues.append(f"声明执行器 {t} 不是已知管线能力词汇")
        elif t not in doc_tools:
            issues.append(
                f"声明执行器 {t} 无文档章节支撑（CAPABILITY_TOOL_STAGES 对应章节落空）")
    return issues


def _iter_skill_docs(d: pathlib.Path):
    """遍历 Skill 主文档（单一包形态 <slug>/SKILL.md）；yield (slug, path)。"""
    for p in sorted(d.iterdir(), key=lambda x: x.name):
        if not p.is_dir() or p.name.startswith("."):
            continue
        main = p / frontmatter.SKILL_DOC_NAME
        if main.exists():
            yield p.name, main


def frontmatter_meta_warn_probe(slug: str, manifest) -> list:
    """frontmatter name/description 存在性探针（P1-10 裁决 R1）：
    渐进披露第一层（Skill 目录摘要）的权威声明缺失时计入 WARN 清单；
    级别 WARN 不升 FAIL——不触门禁冻结，不阻断退出码（诊断性质）。"""
    return [
        key for key in ("name", "description")
        if not (isinstance((manifest or {}).get(key), str)
                and str((manifest or {}).get(key)).strip())
    ]


# 正文 read_skill(resource=…) 按需加载指针（P2-4 目录包）
_RESOURCE_POINTER_RE = re.compile(
    r"read_skill\s*\([^)]*resource\s*=\s*[\"']([^\"']+)[\"']")


def package_resource_warn_probe(slug: str, path: pathlib.Path,
                                body: str, manifest) -> list:
    """目录包资源探针（P2-4）：诊断性质，WARN 不阻断退出码（外部源同维持
    WARN，对齐批3 source 分口径纪律）。
    ① 正文 read_skill(resource=…) 指针必须落在包内实际存在的文件上，
       悬空 = 文档与资源漂移（含路径穿越）；
    ② scripts 键声明路径必须在目录包内实际存在（平台只做静态校验，
       绝不执行；形状非法在注册期 manifest_schema 已 fail-hard，此处只
       做存在性核对）；
    ③ references/ 下实际资源无正文指针引用 = 孤儿资源（渐进披露第三层
       入口缺失，模型永远发现不了该资源）；
    ④ assets/ 素材孤儿/悬空（批6）：frontmatter resources 声明了但文件不存在 =
       悬空；assets/ 下文件在场但未在 resources 声明 = 孤儿（版本锁盲区）。
       sha256 不符归注册期硬拒，探针只管存在性。"""
    warns = []
    pkg_root = path.parent  # 单一包形态：主文档恒在 <slug>/ 包内
    pointed = set()
    for m in _RESOURCE_POINTER_RE.finditer(body or ""):
        rel = m.group(1).strip().replace("\\", "/")
        parts = [p for p in rel.split("/") if p and p != "."]
        if not parts or ".." in parts:
            warns.append(f"resource 指针非法 {rel!r}（只允许包内相对路径）")
            continue
        pointed.add("/".join(parts))
        if not (pkg_root / "/".join(parts)).is_file():
            warns.append(f"resource 指针悬空 {rel!r}（包内文件不存在）")
    scripts = (manifest or {}).get("scripts")
    if isinstance(scripts, dict) and scripts:
        for name in sorted(scripts):
            rel = scripts[name]
            if not isinstance(rel, str) or not rel.strip():
                continue  # 形状非法归注册期 fail-hard，此处不重复报
            if not (pkg_root / rel.replace("\\", "/")).is_file():
                warns.append(f"scripts 声明 {name!r} 文件不存在：{rel!r}")
    if pkg_root is not None:
        ref_dir = pkg_root / "references"
        if ref_dir.is_dir():
            for rf in sorted(ref_dir.rglob("*")):
                if not rf.is_file() or rf.name.startswith("."):
                    continue
                rel = rf.relative_to(pkg_root).as_posix()
                if rel not in pointed:
                    warns.append(f"孤儿资源 references/ 下 {rel!r} 无正文"
                                 f" read_skill(resource=…) 指针引用")
    # ④ assets/ 素材孤儿/悬空（批6）：版本锁声明（resources）与实际文件对账；
    # 形状非法归注册期/manifest_schema WARN，此处只收有效条目做存在性核对。
    declared = set()
    resources = (manifest or {}).get("resources")
    if isinstance(resources, dict):
        declared = {
            str(k).strip().replace("\\", "/")
            for k, v in resources.items()
            if isinstance(k, str) and k.strip() and isinstance(v, dict)
        }
    for rel in sorted(declared):
        parts = [p for p in rel.split("/") if p and p != "."]
        if not parts or ".." in parts:
            continue  # 非法形状归 manifest_schema WARN，不重复报
        if not (pkg_root / rel).is_file():
            warns.append(f"resources 声明 {rel!r} 文件不存在（悬空）")
    asset_dir = pkg_root / "assets"
    if asset_dir.is_dir():
        for af in sorted(asset_dir.rglob("*")):
            if not af.is_file() or af.name.startswith("."):
                continue
            rel = af.relative_to(pkg_root).as_posix()
            if rel not in declared:
                warns.append(f"孤儿素材 assets/ 下 {rel!r} 未在 frontmatter "
                             f"resources 声明（版本锁盲区）")
    return warns


def run_gate() -> int:
    """--gate 模式：仅客观结构问题决定 FAIL 退出码。

    FAIL：frontmatter 解析失败 / schema 校验与声明执行器章节支撑一致性
    （manifest_consistency_issues，与报表入口同一实现）。
    WARN（诊断清单，不阻断退出码）：frontmatter name/description 存在性；
    目录包资源探针（指针悬空 / scripts 声明路径 / references 孤儿 /
    assets 版本锁孤儿/悬空）。
    正文句式不参与判定（用户裁决 R-3：句式扫描退役）；
    scripts/acceptance.py 以 EVAL_WARN 档调用本入口，不计入验收退出码。"""
    d = pathlib.Path(__file__).parent.parent / "data" / "skills"
    struct_failed = []
    meta_warned = []
    pkg_warned = []
    for slug, f in _iter_skill_docs(d):
        content = f.read_text(encoding="utf-8", errors="replace")
        # 扫描前先剥离 frontmatter：YAML 声明键（schema_version 等）不参与正文探针
        manifest, body, fm_err = frontmatter.split_frontmatter(content)
        issues = [fm_err] if fm_err else manifest_consistency_issues(
            slug, body, manifest)
        if issues:
            struct_failed.append(slug)
            for it in issues:
                print(f"[skill_structure] FAIL {slug}: {it}")
        meta_missing = frontmatter_meta_warn_probe(slug, manifest)
        if meta_missing:
            meta_warned.append(slug)
            print(f"[skill_frontmatter_meta] WARN {slug}: frontmatter 缺 "
                  f"{'、'.join(meta_missing)}（渐进披露第一层摘要声明）")
        pkg_issues = package_resource_warn_probe(slug, f, body, manifest)
        if pkg_issues:
            pkg_warned.append(slug)
            for it in pkg_issues:
                print(f"[skill_package_resource] WARN {slug}: {it}")
    if struct_failed:
        print(f"[skill_structure] FAIL: {len(struct_failed)} skill(s) "
              f"frontmatter 结构问题（{'、'.join(struct_failed)}）")
        return 1
    print("[skill_structure] OK: frontmatter 结构一致")
    if meta_warned:
        print(f"[skill_frontmatter_meta] WARN: {len(meta_warned)} skill(s) "
              f"frontmatter name/description 缺失（{'、'.join(meta_warned)}；"
              f"诊断性质，不阻断门禁）")
    if pkg_warned:
        print(f"[skill_package_resource] WARN: {len(pkg_warned)} skill(s) "
              f"目录包资源指针/孤儿资源问题（{'、'.join(pkg_warned)}；"
              f"诊断性质，不阻断门禁）")
    return 0


def _install_ports_once() -> None:
    """报表入口独立运行时装配 core 端口（幂等）；脚本场景不在
    web/app.py lifespan 与 tests/conftest.py 既有装配点覆盖内。"""
    from src.video_agent.web.port_wiring import install_core_ports
    install_core_ports()


def main() -> None:
    _install_ports_once()
    d = pathlib.Path(__file__).parent.parent / "data" / "skills"

    lines = []
    lines.append(f"生成日期: {date.today()}  "
                 "生成方式: python scripts/scan_skills.py（报表入口；"
                 "--gate 为门禁入口）")
    lines.append("")
    mismatched = []
    total = 0
    for slug, f in _iter_skill_docs(d):
        content = f.read_text(encoding="utf-8", errors="replace")
        # frontmatter 剥离：正文供章节/工具扫描，声明供一致性探针
        manifest, body, fm_err = frontmatter.split_frontmatter(content)
        sections = split_skill_sections(body)
        lines.append("=" * 70)
        lines.append(f"SKILL: {slug}  ({f.stat().st_size} 字节)")
        lines.append(f"  章节(stage): {sorted(k for k, v in sections.items() if v.strip()) or '无'}")
        # frontmatter 声明 vs 文档实际章节一致性（客观结构诊断）
        if fm_err:
            consistency = [fm_err]
        else:
            consistency = manifest_consistency_issues(slug, body, manifest)
        total += 1
        if consistency:
            mismatched.append(slug)
        lines.append(f"  frontmatter 一致性: {'一致' if not consistency else consistency}")
        # P1-10（裁决 R1）：frontmatter name/description 存在性探针（WARN，诊断性质）
        meta_missing = frontmatter_meta_warn_probe(slug, manifest)
        if meta_missing:
            lines.append(f"  frontmatter name/description 缺失(WARN): {meta_missing}")
        # P2-4：目录包资源探针（WARN 报告，诊断性质）
        pkg_issues = package_resource_warn_probe(slug, f, body, manifest)
        if pkg_issues:
            lines.append(f"  目录包资源探针(WARN): {pkg_issues}")
        # 提取 <planner> 流程前 500 字，看流程是否与「剧本→规格→KE→分镜→提示词」不同
        flow = sections.get("planning", "").strip()
        if flow:
            lines.append(f"  <planner> 流程预览(前600字): {flow[:600].replace(chr(10), ' | ')}")
        else:
            lines.append("  <planner> 流程预览: （无 planner 章节）")
        lines.append("")

    print("\n".join(lines))
    tail = f"（{'、'.join(mismatched)}）" if mismatched else ""
    print(f"[scan_skills] frontmatter 一致性探针: 共 {total} 个 skill，"
          f"{len(mismatched)} 个不一致{tail}")


if __name__ == "__main__":
    if "--gate" in sys.argv[1:]:
        raise SystemExit(run_gate())
    main()
