# -*- coding: utf-8 -*-
"""扫描 data/skills/*.md，输出每个 Skill 的结构摘要，用于诊断指令冲突。

P3-15 新增：frontmatter 声明（含 custom_sections）vs 文档实际章节一致性探针
（诊断先行，报告性质，不进 acceptance GATES）。
任务 #9 新增：工具名白名单门禁（--gate）：Skill 流程文本出现名单外
工具名即报错退出；名单从 src 注册表动态提取（防漂移）。
任务 #5：声明源改文档头部 frontmatter（扫描前先剥离，防 YAML 键误判工具名）；
--gate 追加 tools_required 存在性探针（任务#5 B-2）：声明工具不在
平台工具注册表（tools/manager.py 注册清单）且不在待补齐豁免清单时
输出 WARN 清单（先诊断，不升门禁失败/不阻断退出码）。
P1 整改（任务 #9）：--gate 追加内容卫生防回潮校验：frontmatter 剥离后
正文再现 skill_name:/skill_description: 残留行或「最高/第一优先级」宣称
（词序无关，直连形态双向拦截）即 FAIL。
"""
import re
import sys
import pathlib
from datetime import date

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from src.video_agent.web.skill_docs import split_skill_sections, parse_pause_rules  # noqa: E402
from src.video_agent.core.prompt_gates import parse_gate_rules  # noqa: E402
from src.video_agent.skill_runtime import frontmatter  # noqa: E402
from src.video_agent.skill_runtime.registry import (  # noqa: E402
    CAPABILITY_TOOL_STAGES,
    CUSTOM_SECTION_EXECUTOR,
    PIPELINE_CAPABILITY_TOOLS,
    SkillEntry,
)

# 平台既有工具（非管线能力词汇，不要求文档章节支撑）
REUSED_TOOL_NAMES = (
    "document_write", "read_uploaded_doc", "image_generate",
    "generate_video", "workflow_pause", "read_skill",
    CUSTOM_SECTION_EXECUTOR,
)

# ============================================================
# 任务 #9：工具名白名单校验（接入 acceptance GATES，--gate 模式）
# ============================================================
_TOOL_NAME_RE = re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b")
# 生成通道式 PascalCase 名（XxxToYyy）；供应商/模型名（ElevenLabs 等）不含 To 不受检
_CHANNEL_NAME_RE = re.compile(r"\b[A-Z][a-zA-Z]*To[A-Z][a-zA-Z]*\b")
_TAG_RE = re.compile(r"</?([a-z][a-z0-9_]*)>")
_PENDING_MARK = "待平台补齐"

# 已被平台生成通道覆盖的渠道/模式术语（非独立工具）：
# 归属 web/generation.py 已实现的 generate_video / image_generate / audio_generate
# 内部模式名。防漂移：generation.py 新增对外渠道名时同步登记。
COVERED_CHANNEL_TERMS = frozenset({
    "TextToImage", "ImageToImage",              # image_generate 文生图/图生图模式
    "FirstFrameToVideo", "MultiModalToVideo",   # generate_video 首帧/多模态参考模式
    "text_to_instrumental", "text_to_narration",  # audio_generate BGM/旁白模式
})

# 平台暂无对应能力、文档已就地标注「待平台补齐工具」的名称。
# 防漂移：文档标注与本名单同一约定，两边必须同步增删；
# 平台落地新工具后应从本名单移除并改文档为真实工具名。
PENDING_PLATFORM_TOOLS = frozenset({
    "ImageToVideoByAudio",  # 音频驱动口型同步视频生成
    "super_resolution",     # 视频超分/高帧率（MediaKit）
})

# tools_required 存在性探针的「待补齐豁免」清单（任务#5 B-2）：
# 路线图工具尚未在平台注册为真实 FC 工具，Skill 声明它们是有意的
# 前瞻声明，探针跳过不计 WARN；平台落地对应工具后应从本名单移除。
# （整改批 2.1 清偿：script_analyze / write_media_prompt / audio_generate /
# video_assembler 四项已随 Skill 正文清洗移除——文档不再声明、门禁不再
# 豁免；storyboard_key_elements/shots/audio 等管线能力词汇由
# PIPELINE_CAPABILITY_TOOLS 统一识别，属已退役工具的阶段能力标记。）
PENDING_ROUTE_EXEMPT_TOOLS = frozenset({
    "super_resolution",    # 视频超分（路线图工具，同 PENDING_PLATFORM_TOOLS）
    # 音频驱动图生视频（路线图前瞻能力，同 PENDING_PLATFORM_TOOLS；
    # 平台落地后移除）
    "ImageToVideoByAudio",
})

# 非工具的业务标识符（故事板字段/资产 ID/参数名等），形似工具名但不是工具引用
DOMAIN_TOKENS = frozenset({
    "audio_layer", "audio_layers", "audio_id", "audio_infos",
    "key_element", "key_elements", "key_element_audio", "key_frame",
    "asset_id", "element_id", "scene_id", "resource_id",
    "shot_list", "start_ms", "end_ms", "start_frame", "final_shot",
    "all_shots", "reference_image", "reference_video", "reference_audio",
    "voice_reference", "video_track", "layout_instruction",
    "skill_name", "skill_description", "narration_speaker_profile",
    "text_to_speak",  # TTS 输入文本参数名，非工具
})

# studio-actions（action_executor 支持的动作，非 FC 工具，执行器产物同口径）
KNOWN_ACTIONS = frozenset({
    "bind_asset", "reply_to_user", "update_draft", "add_draft",
    "select_draft", "insert_chat_media",
})

# 提示词占位符式标识（如 <<<image_1>>>）
_PLACEHOLDER_RES = (
    re.compile(r"^image_(\d+|[xyz]|prop_.+|reference_frame)$"),
    re.compile(r"^code\d+$"),
    re.compile(r"^keyframe_\d+$"),
)

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


def real_tool_names() -> frozenset:
    """真实存在的工具名集合：唯一源 = src 注册表（防漂移）。

    不维护第二份硬编码工具清单：import 即触发 ToolManager 注册
    （平台工具），画布工具在 web 侧按需注册，此处补注册凑全集
    （register 幂等）。新增/下线工具时本门禁口径自动跟随。
    整改批 2.1 清偿：管线能力词汇（已退役工具的阶段标记）不再注入
    本白名单——正文清洗后 Skill 流程文本一律使用真实工具名，散文再现
    能力词即 FAIL（防回潮）；能力词仅作为 <章节标签>（_TAG_RE 豁免）
    与 frontmatter/代码侧阶段标记存续，模型可见对照表见
    prompts/planner/system_fc.md「Skill 文档能力词对照」段。
    """
    from loguru import logger
    logger.disable("src.video_agent")  # 注册期日志对门禁无意义，保持输出干净
    from src.video_agent.tools import ToolManager  # noqa: 触发注册
    from src.video_agent.tools.canvas_tools import register_canvas_tools
    register_canvas_tools()
    names = set(ToolManager._tools)
    names.add(CUSTOM_SECTION_EXECUTOR)
    return frozenset(names)


def platform_tool_names() -> frozenset:
    """平台工具注册表真实清单（tools/manager.py 注册口径，任务#5 B-2）：
    tools_required 存在性探针的权威基准——不含管线能力词汇豁免注入
    （那是 Skill 文本白名单口径，不是工具存在性口径）。"""
    from loguru import logger
    logger.disable("src.video_agent")
    from src.video_agent.tools import ToolManager  # noqa: 触发注册
    from src.video_agent.tools.canvas_tools import register_canvas_tools
    register_canvas_tools()
    return frozenset(ToolManager._tools)


def tool_whitelist_issues(content: str, real_names: frozenset) -> list:
    """扫描流程文本中的工具名式 token，返回名单外问题清单（空 = 通过）。"""
    issues = []
    # 文档内 <tag> 章节标识（含自定义章节如 storyboard_designer）非工具引用
    exempt = set(_TAG_RE.findall(content or ""))
    lines = (content or "").splitlines()

    def check(tok: str, pos: int) -> None:
        line_no = (content or "").count("\n", 0, pos) + 1
        if _PENDING_MARK in (lines[line_no - 1] if line_no <= len(lines) else ""):
            return  # 该行已就地标注「待平台补齐」，与门禁名单同一约定
        issues.append(f"第 {line_no} 行：名单外工具名 {tok!r}")

    for m in _TOOL_NAME_RE.finditer(content or ""):
        tok = m.group(0)
        if (tok in real_names or tok in DOMAIN_TOKENS or tok in KNOWN_ACTIONS
                or tok in COVERED_CHANNEL_TERMS or tok in PENDING_PLATFORM_TOOLS
                or tok in exempt):
            continue
        if any(p.match(tok) for p in _PLACEHOLDER_RES):
            continue
        check(tok, m.start())
    for m in _CHANNEL_NAME_RE.finditer(content or ""):
        tok = m.group(0)
        if tok in COVERED_CHANNEL_TERMS or tok in PENDING_PLATFORM_TOOLS:
            continue
        check(tok, m.start())
    return issues


def manifest_consistency_issues(slug: str, content: str, manifest) -> list:
    """frontmatter 声明 vs 文档实际章节一致性探针；返回不一致清单（空 = 一致）。

    未声明 manifest = 零声明回落合法（与 schema「未声明键合法」同构）。
    检测口径（报告性质，不做门禁）：
    ① schema 校验问题（与注册期 fail-closed 告警同源）；
    ② custom_sections 声明标识在文档解析链（stage/tag/标题/任意 <tag>）落空；
    ③ flow 声明的执行器（stage_executors / stages.*.executors）无文档章节支撑
       ——只查已知 Skill 执行器；复用工具与自定义通道豁免。
    """
    issues = list(frontmatter.validate_manifest(manifest) or [])
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
        t for t in PIPELINE_CAPABILITY_TOOLS
        if any((sections.get(s) or "").strip()
               for s in CAPABILITY_TOOL_STAGES.get(t, ()))
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
        if t not in PIPELINE_CAPABILITY_TOOLS:
            issues.append(f"声明执行器 {t} 不是已知管线能力词汇")
        elif t not in doc_tools:
            issues.append(
                f"声明执行器 {t} 无文档章节支撑（CAPABILITY_TOOL_STAGES 对应章节落空）")
    return issues


def _iter_skill_docs(d: pathlib.Path):
    """遍历 Skill 主文档（插件包约定双形态）：单文件 *.md 优先，
    目录包 <slug>/<slug>.md 次之；yield (slug, path)。"""
    for f in sorted(d.glob("*.md")):
        yield f.stem, f
    for p in sorted(d.iterdir(), key=lambda x: x.name):
        if not p.is_dir() or p.name.startswith("."):
            continue
        main = p / f"{p.name}.md"
        if main.exists():
            yield p.name, main


def tools_required_warn_probe(slug: str, manifest, platform_names: frozenset) -> list:
    """tools_required 存在性探针（任务#5 B-2）：声明工具不在平台工具
    注册表（manager.py 注册清单）、不在管线能力词汇表（已退役工具的
    阶段能力标记，有意保留）且不在待补齐豁免清单（路线图工具的有意
    豁免）时计入 WARN 清单；先诊断不升门禁失败，不阻断退出码。"""
    declared = (manifest or {}).get("tools_required")
    if not isinstance(declared, list):
        return []
    return [
        t for t in declared
        if isinstance(t, str) and t.strip()
        and t not in platform_names
        and t not in PIPELINE_CAPABILITY_TOOLS
        and t not in PENDING_ROUTE_EXEMPT_TOOLS
    ]


def run_gate() -> int:
    """--gate 模式：工具名白名单校验，有问题退出码 1（acceptance 门禁项）；
    P1 防回潮校验：正文元数据残留行 / 优先级宣称即 FAIL（任务 #9）；
    tools_required 存在性探针缺失输出 WARN 清单（任务#5 B-2：先诊断
    不升门禁失败，不阻断退出码）。"""
    d = pathlib.Path(__file__).parent.parent / "data" / "skills"
    real = real_tool_names()
    platform = platform_tool_names()
    failed = []
    hygiene_failed = []
    warned = []
    for slug, f in _iter_skill_docs(d):
        content = f.read_text(encoding="utf-8", errors="replace")
        # 扫描前先剥离 frontmatter：YAML 声明键（schema_version 等）非工具引用
        manifest, body, _err = frontmatter.split_frontmatter(content)
        issues = tool_whitelist_issues(body, real)
        if issues:
            failed.append(slug)
            for it in issues:
                print(f"[skill_tool_names] FAIL {f.name}: {it}")
        hygiene = content_hygiene_issues(body)
        if hygiene:
            hygiene_failed.append(slug)
            for it in hygiene:
                print(f"[skill_content_hygiene] FAIL {f.name}: {it}")
        missing = tools_required_warn_probe(slug, manifest, platform)
        if missing:
            warned.append(slug)
            print(f"[skill_tools_required] WARN {slug}: 声明工具不在平台注册表"
                  f"且不在待补齐豁免清单：{'、'.join(missing)}")
    if failed:
        print(f"[skill_tool_names] FAIL: {len(failed)} skill(s) off-whitelist")
    if hygiene_failed:
        print(f"[skill_content_hygiene] FAIL: {len(hygiene_failed)} skill(s) "
              f"正文元数据残留或优先级宣称回潮")
    if failed or hygiene_failed:
        return 1
    print("[skill_tool_names] OK: all skill docs on tool whitelist")
    print("[skill_content_hygiene] OK: 无元数据残留行与优先级宣称")
    if warned:
        print(f"[skill_tools_required] WARN: {len(warned)} skill(s) 声明工具未入平台注册表"
              f"（{'、'.join(warned)}；诊断性质，不阻断门禁）")
    return 0


def _install_ports_once() -> None:
    """报表入口独立运行时装配 core 端口（幂等）：custom_sections 探针
    经 SkillEntry.custom_section_text 走 skill_docs 端口，脚本场景不在
    web/app.py lifespan 与 tests/conftest.py 既有装配点覆盖内。"""
    from src.video_agent.web.port_wiring import install_core_ports
    install_core_ports()


def main() -> None:
    _install_ports_once()
    OUT = pathlib.Path(__file__).parent / "skill_scan_report.md"
    d = pathlib.Path(__file__).parent.parent / "data" / "skills"

    lines = []
    lines.append(f"生成日期: {date.today()}  "
                 "生成方式: python scripts/scan_skills.py（报表入口；"
                 "--gate 为门禁入口）")
    lines.append("")
    mismatched = []
    whitelist_failed = []
    real = real_tool_names()
    platform = platform_tool_names()
    total = 0
    for slug, f in _iter_skill_docs(d):
        content = f.read_text(encoding="utf-8", errors="replace")
        # frontmatter 剥离：正文供章节/工具扫描，声明供一致性探针
        manifest, body, fm_err = frontmatter.split_frontmatter(content)
        sections = split_skill_sections(body)
        pause = parse_pause_rules(body)
        gates = parse_gate_rules(body)
        has_gate_block = bool(re.search(r"```(?:json|js)?\s*gate_rules\s*\n", body))
        lines.append("=" * 70)
        lines.append(f"SKILL: {slug}  ({f.stat().st_size} 字节)")
        lines.append(f"  章节(stage): {sorted(k for k, v in sections.items() if v.strip()) or '无'}")
        lines.append(f"  pause_rules: {pause}")
        lines.append(f"  gate_rules 块存在: {has_gate_block}")
        if has_gate_block:
            lines.append(f"  gate_rules 解析结果: {gates}")
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
        # P3-15：frontmatter 声明（含 custom_sections）vs 文档实际章节一致性
        if fm_err:
            consistency = [fm_err]
        else:
            consistency = manifest_consistency_issues(slug, body, manifest)
        total += 1
        if consistency:
            mismatched.append(slug)
        lines.append(f"  frontmatter 一致性: {'一致' if not consistency else consistency}")
        # 任务 #9：工具名白名单校验（同步写入报告；扫剥离后正文）
        wl_issues = tool_whitelist_issues(body, real)
        if wl_issues:
            whitelist_failed.append(slug)
        lines.append(
            f"  工具名白名单: {'通过' if not wl_issues else wl_issues}")
        # 任务 #5 B-2：tools_required 存在性探针（WARN 报告，诊断性质）
        missing = tools_required_warn_probe(slug, manifest, platform)
        if missing:
            lines.append(f"  tools_required 未入平台注册表(WARN): {missing}")
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
    print(f"[scan_skills] frontmatter 一致性探针: 共 {total} 个 skill，"
          f"{len(mismatched)} 个不一致{tail}")
    wl_tail = f"（{'、'.join(whitelist_failed)}）" if whitelist_failed else ""
    print(f"[scan_skills] 工具名白名单: 共 {total} 个 skill，"
          f"{len(whitelist_failed)} 个名单外{wl_tail}")


if __name__ == "__main__":
    if "--gate" in sys.argv[1:]:
        raise SystemExit(run_gate())
    main()
