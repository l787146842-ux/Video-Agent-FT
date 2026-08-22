# -*- coding: utf-8 -*-
"""扫描 data/skills/*.md，输出每个 Skill 的结构摘要，用于诊断指令冲突。

P3-15 新增：sidecar 声明（含 custom_sections）vs 文档实际章节一致性探针
（诊断先行，报告性质，不进 acceptance GATES）。
任务 #9 新增：工具名白名单门禁（--gate）：Skill 流程文本出现名单外
工具名即报错退出；名单从 src 注册表动态提取（防漂移）。
"""
import re
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from src.video_agent.web.skill_docs import split_skill_sections, parse_pause_rules  # noqa: E402
from src.video_agent.core.prompt_gates import parse_gate_rules  # noqa: E402
from src.video_agent.skill_runtime import sidecar  # noqa: E402
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


def real_tool_names() -> frozenset:
    """真实存在的工具名集合：唯一源 = src 注册表（防漂移）。

    不维护第二份硬编码工具清单：import 即触发 ToolManager 注册
    （平台工具），画布工具在 web 侧按需注册，此处补注册凑全集
    （register 幂等）。新增/下线工具时本门禁口径自动跟随。
    管线能力词汇（任务#36 B5 执行器退役，同名工具已删除）仍在
    sidecar 声明与 Skill 流程文本中出现，白名单保留豁免。
    """
    from loguru import logger
    logger.disable("src.video_agent")  # 注册期日志对门禁无意义，保持输出干净
    from src.video_agent.tools import ToolManager  # noqa: 触发注册
    from src.video_agent.tools.canvas_tools import register_canvas_tools
    register_canvas_tools()
    names = set(ToolManager._tools)
    names.update(PIPELINE_CAPABILITY_TOOLS)
    names.add(CUSTOM_SECTION_EXECUTOR)
    return frozenset(names)


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


def run_gate() -> int:
    """--gate 模式：只跑工具名白名单校验，有问题退出码 1（acceptance 门禁项）。"""
    d = pathlib.Path(__file__).parent.parent / "data" / "skills"
    real = real_tool_names()
    failed = []
    for f in sorted(d.glob("*.md")):
        content = f.read_text(encoding="utf-8", errors="replace")
        issues = tool_whitelist_issues(content, real)
        if issues:
            failed.append(f.stem)
            for it in issues:
                print(f"[skill_tool_names] FAIL {f.name}: {it}")
    if failed:
        print(f"[skill_tool_names] FAIL: {len(failed)} skill(s) off-whitelist")
        return 1
    print("[skill_tool_names] OK: all skill docs on tool whitelist")
    return 0


def main() -> None:
    OUT = pathlib.Path(__file__).parent / "skill_scan_report.md"
    d = pathlib.Path(__file__).parent.parent / "data" / "skills"

    lines = []
    mismatched = []
    whitelist_failed = []
    real = real_tool_names()
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
        # 任务 #9：工具名白名单校验（同步写入报告）
        wl_issues = tool_whitelist_issues(content, real)
        if wl_issues:
            whitelist_failed.append(f.stem)
        lines.append(
            f"  工具名白名单: {'通过' if not wl_issues else wl_issues}")
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
    wl_tail = f"（{'、'.join(whitelist_failed)}）" if whitelist_failed else ""
    print(f"[scan_skills] 工具名白名单: 共 {total} 个 skill，"
          f"{len(whitelist_failed)} 个名单外{wl_tail}")


if __name__ == "__main__":
    if "--gate" in sys.argv[1:]:
        raise SystemExit(run_gate())
    main()
