# -*- coding: utf-8 -*-
"""扫描 data/skills/<slug>/SKILL.md（单一包形态），输出每个 Skill 的结构摘要，
用于诊断指令冲突。

P3-15 新增：frontmatter 声明 vs 文档实际章节一致性探针
（诊断先行，报告性质，不进 acceptance GATES）。
任务 #5：声明源改文档头部 frontmatter（扫描前先剥离）；
tools_required 存在性探针已随 C1b 裁决 2026-08-31 退役删除（机械工作流层整体退役）。
P1 整改（任务 #9）：--gate 追加内容卫生防回潮校验：frontmatter 剥离后
正文再现 skill_name:/skill_description: 残留行或「最高/第一优先级」宣称
（词序无关，直连形态双向拦截）即 FAIL。
P2-4 新增：目录包资源探针（WARN，诊断性质）：正文 read_skill(resource=…)
指针悬空 / scripts 声明路径不存在 / references/ 孤儿资源 → WARN 清单，
不阻断退出码（注册期形状校验在 manifest_schema，此处只做存在性核对）。
批6 扩展：assets/ 素材孤儿（文件在场但 frontmatter resources 未声明）/
悬空（resources 声明了但文件不存在）同口径 WARN；已声明 sha256 不符的
硬拒归注册期版本锁，探针不重复拦截。
任务#2 新增：正文语言声明探针（--gate）：产物提示词语言统一以
prompt_gates.resolve_prompt_language（用户选择 > frontmatter language
声明 > 平台默认）为唯一裁决源；正文再现声明性语言规则即 FAIL。
"""
import re
import sys
import pathlib
from datetime import date

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from src.video_agent.web.skill_docs import split_skill_sections, parse_pause_rules  # noqa: E402
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

# （C1b 裁决 2026-08-31：tools_required 存在性探针退役，
# PENDING_ROUTE_EXEMPT_TOOLS 待补齐豁免清单同批删除。）

# ============================================================
# P1 防回潮校验（任务 #9）：frontmatter 是唯一元数据源，正文不得
# 再现 skill_name:/skill_description: 残留行；优先级宣称已改写为
# 「强制基线」式正向表述，正文再现即 FAIL。
# ============================================================
_RESIDUE_META_RE = re.compile(
    r"^\s*(skill_name|skill_description)\s*:", re.M)
# 优先级宣称检测（整改批 1.2 词序无关化）：直连形态双向拦截
# （最高/第一优先级 与 优先级最高/优先级第一）。仅收紧连宣称，
# 不拦带间隔的领域语句（如「参考图优先级为最高级别」），防误伤。
_PRIORITY_CLAIM_RE = re.compile(r"(?:最高|第一)优先级|优先级(?:最高|第一)")


def content_hygiene_issues(body: str) -> list:
    """正文卫生防回潮校验（frontmatter 剥离后的 body）：
    ① 出现 skill_name:/skill_description: 残留行（元数据双源回潮）；
    ② 出现「最高/第一优先级」宣称（词序无关；应使用「强制基线」式正向表述）。
    返回问题清单（空 = 通过）。"""
    issues = []
    for m in _RESIDUE_META_RE.finditer(body or ""):
        line_no = (body or "").count("\n", 0, m.start()) + 1
        issues.append(f"第 {line_no} 行：正文元数据残留行 "
                      f"{m.group(0).strip()!r}（frontmatter 为唯一元数据源）")
    for m in _PRIORITY_CLAIM_RE.finditer(body or ""):
        line_no = (body or "").count("\n", 0, m.start()) + 1
        issues.append(f"第 {line_no} 行：优先级宣称 {m.group(0)!r}"
                      f"（应改写为「强制基线」式正向表述）")
    return issues


# ============================================================
# 任务#2：正文语言声明探针。产物提示词语言的唯一裁决源 =
# prompt_gates.resolve_prompt_language（用户选择 > frontmatter language
# 声明 > 平台默认），Skill 正文不得再重复声明。判定目标是「声明性语言规则」
#（提示词/正文该用哪种语言书写）；引用示例提示词内容、英文双引号/英文标签等
# 格式与术语要求、旁白语言等创意约束不属提示词语言声明（防误伤）。
# ============================================================
_LANG_CLAIM_RES = (
    # 提示词/正文 + 书写类动词 + 语言词（如「提示词写成英文描述」
    #「提示词正文用中文书写」「prompt 输出英文」）
    re.compile(
        r"(?:提示词|prompt|正文)[^。\n]{0,40}?"
        r"(?:写成|书写|撰写|输出|使用|用)[^。\n]{0,20}?"
        r"(?:中文|英文|英语)",
        re.I),
    # 倒装书写式（如「用中文书写」「以英文输出」）
    re.compile(r"(?:用|以|使用)(?:中文|英文|英语)[^。\n]{0,12}?(?:书写|写成|撰写|输出)"),
    # 「提示词正文必须为…英文描述」式断定（任务#11 放宽：裸「为」字断定，
    # 允许 (必须|须|均|一律)?为 / 裸「一律」；负向后视防「分为/作为/称为/
    # 视为/改为」等事实描述误伤，如「正文分为中文、英文双语」放行；
    # 「提示词环境」指工作环境而非产物，主语后接「环境」不判声明）
    re.compile(
        r"(?:提示词|正文|prompt)(?!环境)[^。\n]{0,40}?"
        r"(?:(?:必须|须|均|一律)?(?<![分成作称译改记视为当])为|一律)[^。\n]{0,20}?"
        r"(?:中文|英文|英语)",
        re.I),
    # 任务#11：「通常/默认/一般 + 语言词」弱倾向断定（如「提示词通常英文」）
    re.compile(
        r"(?:提示词|正文|prompt)(?!环境)[^。，；\n]{0,20}?"
        r"(?:通常|默认|一般|多为)[^。，；\n]{0,12}?"
        r"(?:中文|英文|英语)",
        re.I),
    # 任务#11：「均/一律/全部/统一/始终 + 语言词」全称断定（如「提示词一律英文」）
    re.compile(
        r"(?:提示词|正文|prompt)(?!环境)[^。，；\n]{0,20}?"
        r"(?:均|一律|全部|统一|始终)[^。，；\n]{0,12}?"
        r"(?:中文|英文|英语)",
        re.I),
    # 语言用途分配（如「中文仅用于字段标题」）
    re.compile(r"(?:中文|英文|英语)(?:仅|只|一律)?用于"),
    # 语言词直接修饰产物名词（如「英文正向提示词」「英文描述」「英文正文」；
    # 任务#11 放宽：覆盖「英文正向视觉描述」类偏正句式）
    re.compile(r"(?:中文|英文|英语)(?:正向)?(?:视觉)?(?:的)?(?:提示词|正文|描述)"),
    # 键值式声明（如「语言：中文」）
    re.compile(r"语言[:：]\s*(?:中文|英文|英语)", re.I),
)
# 豁免后缀：语言词紧接格式/术语类名词 = 格式要求（如「英文双引号」
#「特定英文标签」），不是书写语言声明。
_LANG_CLAIM_EXEMPT_SUFFIX_RE = re.compile(r"^(?:双引号|单引号|引号|括号|标签|指令|字体|字符)")


def language_claim_issues(body: str) -> list:
    """正文语言声明收口校验（任务#2，frontmatter 剥离后的 body）：
    产物提示词语言统一以 resolve_prompt_language 为唯一裁决源，
    正文出现声明性语言规则即问题。返回问题清单（空 = 通过）。"""
    hits = []
    for pat in _LANG_CLAIM_RES:
        for m in pat.finditer(body or ""):
            seg = m.group(0)
            lang = re.search(r"中文|英文|英语", seg)
            if lang:
                after = (body or "")[m.start() + lang.end():]
                if _LANG_CLAIM_EXEMPT_SUFFIX_RE.match(after):
                    continue
            hits.append((m.start(), m.end(), seg))
    hits.sort()
    issues = []
    last_end = -1
    for start, end, seg in hits:
        if start < last_end:
            continue  # 与已报告片段重叠，去重
        last_end = end
        line_no = (body or "").count("\n", 0, start) + 1
        issues.append(
            f"第 {line_no} 行：声明性语言规则 {seg.strip()!r}"
            f"（产物提示词语言统一由 frontmatter language 声明经 "
            f"resolve_prompt_language 裁决，见 prompts/shared/language.md）")
    return issues


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


def _is_external_source(manifest) -> bool:
    """外部源判定（探针按 source 分口径）：frontmatter source 声明了非
    platform 取值（如 imported|community|用户导入）= 外部源；
    未声明或声明 platform = 平台源（维持现有严口径）。"""
    src = (manifest or {}).get("source")
    return isinstance(src, str) and bool(src.strip()) and src.strip().lower() != "platform"


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
    """--gate 模式（纯诊断脚本，手动运行；无 acceptance/CI 门禁调用点，
    2026-08-29 用户裁决退役工具名白名单后随批 A 降级）：
    P1 防回潮校验：正文元数据残留行 / 优先级宣称即诊断 FAIL（任务 #9）；
    frontmatter name/description 存在性探针缺失输出 WARN 清单
    （P1-10 裁决 R1：级别 WARN 不升 FAIL，不触门禁冻结）；
    目录包资源探针输出 WARN 清单（P2-4：指针悬空/孤儿资源，批6 追加
    assets/ 素材孤儿/悬空；诊断性质，不阻断退出码）；
    正文语言声明探针：正文再现声明性语言规则即 FAIL（任务#2：
    产物提示词语言唯一裁决源 = resolve_prompt_language）。

    探针按 source 分口径（批 3）：platform（存量，含未声明）维持上述
    严口径；外部源（imported|community 等非 platform 声明）的 2 条
    FAIL 探针（内容卫生/语言声明）降为 WARN，不阻断退出码。
    2026-08-29 用户裁决：工具名白名单探针退役（Skill 系统修复批 A）。
    （C1b 裁决 2026-08-31：tools_required 存在性探针同批退役。）"""
    d = pathlib.Path(__file__).parent.parent / "data" / "skills"
    hygiene_failed = []
    lang_failed = []
    meta_warned = []
    pkg_warned = []
    ext_warned = []
    for slug, f in _iter_skill_docs(d):
        content = f.read_text(encoding="utf-8", errors="replace")
        # 扫描前先剥离 frontmatter：YAML 声明键（schema_version 等）不参与正文探针
        manifest, body, _err = frontmatter.split_frontmatter(content)
        external = _is_external_source(manifest)
        hygiene = content_hygiene_issues(body)
        if hygiene:
            if external:
                ext_warned.append(slug)
                for it in hygiene:
                    print(f"[skill_content_hygiene] WARN {f.name}: （外部源）{it}")
            else:
                hygiene_failed.append(slug)
                for it in hygiene:
                    print(f"[skill_content_hygiene] FAIL {f.name}: {it}")
        lang_issues = language_claim_issues(body)
        if lang_issues:
            if external:
                ext_warned.append(slug)
                for it in lang_issues:
                    print(f"[skill_lang_claim] WARN {f.name}: （外部源）{it}")
            else:
                lang_failed.append(slug)
                for it in lang_issues:
                    print(f"[skill_lang_claim] FAIL {f.name}: {it}")
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
    if hygiene_failed:
        print(f"[skill_content_hygiene] FAIL: {len(hygiene_failed)} skill(s) "
              f"正文元数据残留或优先级宣称回潮")
    if lang_failed:
        print(f"[skill_lang_claim] FAIL: {len(lang_failed)} skill(s) "
              f"正文再现声明性语言规则（语言声明唯一源 = frontmatter language）")
    if hygiene_failed or lang_failed:
        return 1
    print("[skill_content_hygiene] OK: 无元数据残留行与优先级宣称")
    print("[skill_lang_claim] OK: 正文无声明性语言规则")
    if meta_warned:
        print(f"[skill_frontmatter_meta] WARN: {len(meta_warned)} skill(s) "
              f"frontmatter name/description 缺失（{'、'.join(meta_warned)}；"
              f"诊断性质，不阻断门禁）")
    if pkg_warned:
        print(f"[skill_package_resource] WARN: {len(pkg_warned)} skill(s) "
              f"目录包资源指针/孤儿资源问题（{'、'.join(pkg_warned)}；"
              f"诊断性质，不阻断门禁）")
    if ext_warned:
        print(f"[skill_source_split] WARN: {len(set(ext_warned))} 个外部源 skill "
              f"（{'、'.join(sorted(set(ext_warned)))}）2 条 FAIL 探针按 source "
              f"分口径降为 WARN（观察项，不阻断门禁）")
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
        pause = parse_pause_rules(body)
        lines.append("=" * 70)
        lines.append(f"SKILL: {slug}  ({f.stat().st_size} 字节)")
        lines.append(f"  章节(stage): {sorted(k for k, v in sections.items() if v.strip()) or '无'}")
        lines.append(f"  pause_rules: {pause}")
        # 关键条款探针：与系统硬编码闸机可能冲突的词
        probes = {
            "要求中文正文": "中文" in body and ("最高优先级" in body or "必须" in body),
            "提到字幕后期/no subtitles": ("no subtitles" in body.lower()) or ("字幕" in body),
            "提到时长(秒)": bool(re.search(r"\d+\s*秒|时长", body)),
            "提到音频层/音效": ("音效" in body) or ("音频" in body),
            "提到规格文档": ("规格" in body) or ("spec" in body.lower()),
            "要求英文提示词": bool(re.search(r"(提示词|prompt)[^\n]{0,40}(英语|英文|English)", body, re.I)),
            "提到分辨率": ("分辨率" in body) or ("resolution" in body.lower()),
            "何时暂停字样": ("何时暂停" in body) or ("强制暂停点" in body),
        }
        hits = [k for k, v in probes.items() if v]
        lines.append(f"  探针命中: {hits or '无'}")
        # P3-15：frontmatter 声明 vs 文档实际章节一致性
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
