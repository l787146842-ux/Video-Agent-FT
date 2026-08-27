"""Skill 上传即注册：文档章节 → 注册表条目。

Skill 文档（data/skills/*.md 或目录包 data/skills/<slug>/<slug>.md）
仍是唯一数据源与下拉框数据源；平台声明随文档头部 YAML frontmatter
合一。本注册表保存每个 Skill
解析后的章节与能力声明清单（不对应已注册
工具，仅作阶段裁剪/闸机的客观探针）。
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import json
import re

from loguru import logger

from src.video_agent.core import ports
from src.video_agent.skill_runtime import frontmatter
from src.video_agent.skill_runtime.manifest_schema import (
    KIND_VALUES,
    LANGUAGE_EN_CATEGORY_VALUES,
    LANGUAGE_VALUES,
    REQUIRES_INPUT_TYPES,
    split_issue_warnings,
)

# 管线能力词汇表：「章节声明 → 阶段能力」标记，仅供
# stage_probes 阶段裁剪、prompt_gates 音频闸、skill_docs/scan_skills
# Skill lint 作客观探针；平台不注册同名工具。
# Skill 正文散文已全部清洗为真实工具名（scan_skills --gate
# 白名单不豁免本表词汇，散文再现即 FAIL）；模型可见的能力词→真实动作
# 对照表唯一表述源 = prompts/planner/system_fc.md「Skill 文档能力词对照」
# 段——本表增删词汇时须同批同步该段。
PIPELINE_CAPABILITY_TOOLS = (
    "script_analyze",
    "storyboard_key_elements",
    "storyboard_shots",
    "storyboard_audio",
    "write_media_prompt",
    "audio_generate",
    "video_assembler",
)

# 能力 → 需要的 Skill 章节（stage 键，与 skill_docs.split_skill_sections 对齐）
CAPABILITY_TOOL_STAGES: Dict[str, tuple] = {
    "script_analyze": ("planning",),
    "storyboard_key_elements": ("storyboard_ke",),
    "storyboard_shots": ("storyboard_shot",),
    "storyboard_audio": ("storyboard_audio",),
    "write_media_prompt": ("prompt_draft",),
    "audio_generate": ("generation",),
    "video_assembler": ("assembly",),
}

# 自定义章节通道：frontmatter 顶层声明 custom_sections（章节标识→通道名），
# 非管线类 Skill 不必套固定 7 章节模板也能声明自定义章节（
# 仅作章节声明探针；不参与固定章节词汇表与漂移门禁口径）。
CUSTOM_SECTION_EXECUTOR = "skill_section_run"

# 大阶段展示标签（后端权威下发，随 trace 条目 stage 字段持久化；
# 前端不再按工具名硬编码推断，工具改名不会导致卡片退化）
STAGE_LABELS: Dict[str, str] = {
    "script_analyze": "剧本分析",
    "storyboard_key_elements": "关键元素拆解",
    "storyboard_shots": "分镜设计",
    "storyboard_audio": "音频层设计",
    "write_media_prompt": "媒体提示词编写",
    "audio_generate": "音频生成",
    "video_assembler": "时间线组装",
    "image_generate": "设定图生成",
    "generate_image": "对话出图",
    "generate_video": "视频生成",
    "skill_section_run": "自定义章节执行",
}


def stage_label_for_tool(tool: str) -> str:
    """工具名 → 大阶段标签（未登记返回空串，前端回退「阶段完成」）。"""
    return STAGE_LABELS.get(str(tool or "").strip(), "")


@dataclass
class SkillEntry:
    """一个 Skill 文档解析后的注册表条目。"""

    slug: str
    name: str
    content: str
    # stage → 章节原文（split_skill_sections 产出）
    sections: Dict[str, str] = field(default_factory=dict)
    @property
    def manifest(self) -> Optional[Dict[str, dict]]:
        """manifest 声明活读：frontmatter 唯一源，注册不快照，
        声明后写/迁移更新后立即生效（每次从磁盘解析语义一致）。
        None = 未声明，平台回落最小闸。"""
        return frontmatter.load_manifest(self.slug)

    @property
    def custom_sections(self) -> Dict[str, str]:
        """frontmatter custom_sections 声明（活读）：章节标识 → 通用执行器名。

        未声明 = 空 dict（回落现行为：只走固定章节词汇表）；
        消费端 fail-closed：schema 未放行的形状（非对象/空键/白名单外
        执行器）整体忽略，非法声明不产生通道（注册期 fail-hard 拒注册，
        本清洗只兜注册后 frontmatter 被改坏的活读场景）。
        """
        raw = (self.manifest or {}).get("custom_sections")
        if not isinstance(raw, dict):
            return {}
        return {
            str(k): str(v) for k, v in raw.items()
            if isinstance(k, str) and k.strip() and v == CUSTOM_SECTION_EXECUTOR
        }

    def custom_section_text(self, section: str) -> str:
        """自定义章节标识 → 章节原文；未解析返回空串。

        解析链与 skill_section_run 同源（stage 键 → 章节 tag 映射 →
        标题关键字 → 任意 <tag> 直取），保证声明可用性预检与运行期
        注入同口径，不出现「注册了却注入不到」的半死通道。
        """
        sec = (section or "").strip()
        if not sec:
            return ""
        if sec in self.sections:
            return self.sections[sec]
        # 宪法铁律：skill_runtime 不 import web 层，经 skill_docs 端口访问
        sd = ports.skill_docs_port()

        low = sec.lower()
        for mapper in (sd.SECTION_TAG_STAGES.get(low, ""), sd._stage_from_heading(sec)):
            stages = mapper if isinstance(mapper, tuple) else (mapper,)
            for s in stages:
                if s and s in self.sections:
                    return self.sections[s]
        m = re.search(
            rf"<{re.escape(low)}>(.*?)</{re.escape(low)}>",
            self.content or "", re.S | re.I)
        return m.group(1).strip() if m else ""

    @property
    def available_tools(self) -> List[str]:
        """该 Skill 的管线能力声明清单（对应章节非空才成立）。

        名单是阶段裁剪/音频闸/lint 的客观探针（非已注册工具）。
        声明 custom_sections 且任一标识可解析出非空章节时，
        追加自定义章节通道标记。
        """
        tools = [t for t in PIPELINE_CAPABILITY_TOOLS if self.section_for(t)]
        if self.custom_sections and self.section_for(CUSTOM_SECTION_EXECUTOR):
            tools.append(CUSTOM_SECTION_EXECUTOR)
        return tools

    def section_for(self, tool: str) -> str:
        if tool == CUSTOM_SECTION_EXECUTOR:
            parts = [self.custom_section_text(k) for k in self.custom_sections]
            return "\n\n".join(p for p in parts if p and p.strip()).strip()
        stages = CAPABILITY_TOOL_STAGES.get(tool) or ()
        parts = [self.sections.get(s, "") for s in stages]
        return "\n\n".join(p for p in parts if p and p.strip()).strip()

    @property
    def package_root(self) -> Optional[Path]:
        """目录包根（data/skills/<slug>/）；单文件形态返回 None。

        与 frontmatter.resolve_doc_path 双形态口径同源：单文件优先，
        单文件存在时同名目录包不视为包（身份唯一）。"""
        doc = frontmatter.resolve_doc_path(self.slug)
        if doc is None or doc.parent.name != self.slug:
            return None
        return doc.parent

    @property
    def resource_manifest(self) -> List[str]:
        """目录包资源清单（P2-4 按需加载白名单，fail-closed）：
        references/ 下文本类资源的包内相对路径清单（排序）；
        单文件形态/无 references/ 目录 = 空清单（零资源合法）。

        清单即声明：read_skill（resource=…）只放行清单内资源，
        清单外一律拒绝；二进制资源不开放经文本工具读取；
        符号链接不收录（白名单后缀链接可读包外文件，fail-closed 排除）。"""
        root = self.package_root
        if root is None:
            return []
        refs = root / RESOURCE_DIR_NAME
        if not refs.is_dir():
            return []
        return sorted(
            f.relative_to(root).as_posix()
            for f in refs.rglob("*")
            if f.is_file() and not f.is_symlink()
            and f.suffix.lower() in _RESOURCE_TEXT_SUFFIXES
        )


_registry: Dict[str, SkillEntry] = {}
_synced: bool = False

# 目录包资源分层（P2-4）：附属资源唯一开放子目录 = references/；
# 资源清单只收录文本类后缀（二进制资源不经 read_skill 文本通道开放）。
RESOURCE_DIR_NAME = "references"
_RESOURCE_TEXT_SUFFIXES = frozenset(
    {".md", ".txt", ".json", ".yaml", ".yml", ".csv"})


def _load_entry(slug: str) -> Optional[SkillEntry]:
    """从磁盘读取一个 Skill 文档并解析章节；不存在返回 None。"""
    sd = ports.skill_docs_port()

    doc = sd.get_skill_doc(slug)
    if not doc:
        return None
    # 声明唯一源 = 文档头部 frontmatter；manifest 经
    # SkillEntry.manifest 属性活读，注册不快照。章节解析只对剥离声明块
    # 后的正文（YAML 头不是 Skill 正文，不得混入章节/探针）。
    content = frontmatter.strip_frontmatter(doc.get("content") or "")
    return SkillEntry(
        slug=slug,
        name=doc.get("name") or slug,
        content=content,
        sections=sd.split_skill_sections(content),
    )


def register_skill(slug: str) -> Optional[SkillEntry]:
    """解析并注册一个 Skill；文档不存在或无法解析时返回 None。

    fail-hard：frontmatter schema 校验失败拒绝注册——
    坏声明不能带病上线，修好 data/skills/<slug>.md
    头部 frontmatter 才能注册；单个坏 Skill 拒注册不截断 sync_all 批次。
    消费端 fail-closed 清洗仍保留（兜注册后 frontmatter 被改坏的活读场景）。

    问题分级：只有错误级问题拒注册；WARN 级（开放注册
    降级/废除键过渡告警）只输出告警日志，不阻断注册。
    """
    entry = _load_entry(slug)
    if entry is None:
        return None
    errors, warnings = split_issue_warnings(
        frontmatter.validate_manifest(entry.manifest))
    for w in warnings:
        logger.warning(f"[SkillRuntime] Skill「{entry.name}」frontmatter 告警：{w}")
    if errors:
        # 拒注册同时摘除陈旧条目（refresh/重注册路径：frontmatter 改坏后
        # 旧注册态不得继续可用）
        _registry.pop(slug, None)
        logger.error(
            f"[SkillRuntime] Skill「{entry.name}」frontmatter schema 校验失败，"
            f"拒绝注册（fail-hard，修复 data/skills/{slug}.md 头部声明 "
            f"后经 refresh_skill 重试）：{'；'.join(errors)}"
        )
        return None
    _registry[slug] = entry
    tools = entry.available_tools
    logger.info(
        f"[SkillRuntime] 已注册 Skill「{entry.name}」"
        f"（{len(entry.sections)} 个章节，能力声明: {tools or '无'}）"
    )
    global _synced
    _synced = True
    return entry


def unregister_skill(slug: str) -> None:
    """删除 Skill 时注销其注册表条目。"""
    entry = _registry.pop(slug, None)
    if entry is not None:
        logger.info(f"[SkillRuntime] 已注销 Skill「{entry.name}」的注册条目")
    global _synced
    _synced = True


def refresh_skill(slug: str) -> Optional[SkillEntry]:
    """编辑/重新上传 Skill 后重新解析注册。"""
    unregister_skill(slug)
    return register_skill(slug)


def sync_all(force: bool = False) -> int:
    """启动/首次使用时全量注册 data/skills 下的 Skill（幂等，可重复调用）。

    插件包约定双形态：单文件 <slug>.md 与目录包
    <slug>/<slug>.md（包内其余文件为资源）同等扫描。
    直接扫描 SKILL_DOCS_DIR，不经过 list_skill_docs/ensure_default_skill_docs，
    避免与文档系统互相递归。
    """
    global _synced
    if _synced and not force:
        return len(_registry)
    from pathlib import Path

    directory = Path(ports.skill_docs_port().SKILL_DOCS_DIR)
    if not directory.exists():
        _synced = True
        return 0
    count = 0
    # 每个 Skill 都是独立的注册单元。一个遗留的非法/损坏 slug 不能
    # 截断整个注册批次，否则后面的有效 Skill 会静默消失，运行时
    # 只能错误地回落到模型流程。
    slugs: List[str] = sorted(f.stem for f in directory.glob("*.md") if f.stem)
    # 目录包：隐藏目录（.history 等）不参与注册
    slugs += sorted(
        p.name for p in directory.iterdir()
        if p.is_dir() and not p.name.startswith(".")
        and (p / f"{p.name}.md").exists()
    )
    seen_canon: Dict[str, str] = {}
    for slug in slugs:
        # canonical 身份碰撞拒注册：alias 必须显式
        # 登记；归一碰撞 = 配置错误，不得双注册同身份 Skill。
        canon = _norm_name(slug)
        if canon in seen_canon:
            logger.error(
                f"[SkillRuntime] alias 碰撞，拒绝注册 {slug!r}"
                f"（同身份已注册: {seen_canon[canon]!r}）")
            continue
        try:
            # fail-hard 拒注册的 Skill 不计入、不占 canonical 身份
            #（schema 违规 = 未注册，身份留给修复后的合法文件）
            if _load_entry(slug) is not None and register_skill(slug) is not None:
                seen_canon[canon] = slug
                count += 1
        except Exception as e:
            logger.warning(
                f"[SkillRuntime] 跳过无效 Skill {slug!r}: {e}"
            )
    _synced = True
    return count


def _ensure_synced() -> None:
    """懒同步：注册表为空时（如进程刚启动）从磁盘全量注册。"""
    if not _synced or not _registry:
        sync_all()


def reset_registry() -> None:
    """清空注册表（测试隔离用）。"""
    global _synced
    _registry.clear()
    _synced = False


def get_entry(slug: str) -> Optional[SkillEntry]:
    # 点查优先：fail-hard 拒注册的 slug 不能被懒同步 sync_all 全盘扫描
    # 重新捞回注册（拒注册是明确裁决，不是「还没扫到」）；
    # 仅在注册表从未初始化时才触发懒同步。
    if not _synced:
        sync_all()
    return _registry.get(slug)


def list_entries() -> List[SkillEntry]:
    if not _synced:
        sync_all()
    return list(_registry.values())


def _norm_name(s: str) -> str:
    """名称归一化（canonical 身份）：小写 + 去空格/连字符/
    下划线/扩展名——「AI短剧一站式生成」与「AI-短剧一站式生成」同身份。"""
    return (
        (s or "").strip().casefold()
        .replace(" ", "").replace("-", "").replace("_", "")
        .replace(".md", "").replace(".txt", "")
    )


def resolve_entry(wanted: str) -> Optional[SkillEntry]:
    """按 Skill 名称/别名模糊定位注册条目（精确 → 归一化相等 → 双向包含）。

    包含匹配收紧为**唯一命中才返回**——近似名 Skill 并存时
    （如「古风甜宠短剧」vs「古风短剧」）多命中记 warning 并返回 None，
    宁可要求选准也不静默错配。
    """
    _ensure_synced()
    wanted = (wanted or "").strip()
    if not wanted:
        return None
    wn = _norm_name(wanted)
    entries = list(_registry.values())
    for e in entries:
        if wanted == e.name or wanted == e.slug:
            return e
    for e in entries:
        if _norm_name(e.name) == wn or _norm_name(e.slug) == wn:
            return e
    if len(wn) >= 2:
        hits: List[SkillEntry] = []
        for e in entries:
            for n in (e.name, e.slug):
                nn = _norm_name(n)
                if nn and len(nn) >= 2 and (wn in nn or nn in wn):
                    hits.append(e)
                    break
        if len(hits) == 1:
            return hits[0]
        if len(hits) > 1:
            logger.warning(
                f"[SkillRuntime] resolve_entry({wanted!r}) 模糊匹配多命中"
                f"（{[e.name for e in hits]}），拒绝错配返回 None，请精确选择 Skill"
            )
    return None


def tool_sections(skill_name: str, tool: str) -> str:
    """返回某能力声明对应的 Skill 章节全文；Skill 未注册/无对应章节返回空串。"""
    entry = resolve_entry(skill_name)
    if entry is None:
        return ""
    return entry.section_for(tool)


def resolve_skill_resource(wanted: str, resource: str) -> Tuple[Optional[Path], str]:
    """目录包资源按需加载解析（P2-4，fail-closed 单一实现）。

    只放行资源清单（目录包 references/ 实际文件列表）内的资源；
    声明外资源（清单外路径/绝对路径/.. 穿越/单文件形态）一律拒绝。
    返回 (资源绝对路径, "")；失败返回 (None, 错误说明)。

    口径演进：三级资源加载采用「资源清单即声明」（references/ 目录），
    替代计划书早期 assets|scripts 目录字面约定，能力等价且更收敛。"""
    entry = resolve_entry(wanted)
    if entry is None:
        return None, f"未找到 Skill「{wanted}」"
    root = entry.package_root
    if root is None:
        return None, (
            f"Skill「{entry.name}」为单文件形态，无附属资源；"
            "仅目录包（<slug>/<slug>.md）支持 resource 参数按需读取 references/ 资源")
    rel = str(resource or "").strip().replace("\\", "/")
    parts = [p for p in rel.split("/") if p and p != "."]
    if not rel or not parts or ".." in parts:
        return None, (
            f"资源路径 {resource!r} 非法（只允许包内 references/ 相对路径）")
    manifest = entry.resource_manifest
    rel_norm = "/".join(parts)
    if rel_norm not in set(manifest):
        listed = "、".join(manifest[:10]) or "无"
        return None, (
            f"资源 {resource!r} 不在 Skill「{entry.name}」资源清单内"
            f"（fail-closed：声明外资源一律拒绝）。可用资源：{listed}")
    target = root / rel_norm
    # 双保险：解析后仍必须落在包根内（防符号链接/联接指向包外）
    try:
        if not target.resolve().is_relative_to(root.resolve()):
            return None, (
                f"资源 {resource!r} 解析后逃逸包根（fail-closed：拒绝）")
    except OSError as e:
        return None, f"资源 {resource!r} 解析失败（拒绝）：{e}"
    return target, ""


def tool_available(skill_name: str, tool: str) -> bool:
    """该 Skill 是否声明了对应管线能力（章节探针）。"""
    return bool(tool_sections(skill_name, tool))


def skill_manifest_of(skill_name: str) -> Optional[Dict[str, dict]]:
    """当前 Skill 的 manifest 声明；未注册/未声明返回 None（最小闸语义）。"""
    entry = resolve_entry(skill_name)
    if entry is None:
        return None
    return entry.manifest


def skill_flow_enabled(skill_name: str, key: str) -> bool:
    """manifest 的 flow 开关是否启用（spec_wizard/spec_gate）。

    未声明 manifest 或未声明该键时返回 False：引擎对业务流程一无所知，
    平台级流程闸/向导只对显式声明的 Skill 生效。
    """
    manifest = skill_manifest_of(skill_name)
    if not manifest:
        return False
    return bool((manifest.get("flow") or {}).get(key, False))


def spec_wizard_active(skill_name: str) -> bool:
    """规格向导启用判定（frontmatter 唯一源）。

    frontmatter flow.spec_wizard 显式声明；未声明 = 不启用（引擎零预设）。"""
    manifest = skill_manifest_of(skill_name)
    return bool(((manifest or {}).get("flow") or {}).get("spec_wizard"))


def script_required_active(skill_name: str) -> bool:
    """剧本原料闸启用判定（frontmatter 唯一源）。

    frontmatter flow.script_required 显式声明；未声明 = 不启用。"""
    manifest = skill_manifest_of(skill_name)
    return bool(((manifest or {}).get("flow") or {}).get("script_required"))


# ---------- v3 声明读取 API（requires_inputs/kind/language 消费） ----------
# 与 spec_wizard_active/script_required_active 同模块属性访问模式（调用方经
# registry.<fn> 引用，测试 patch 目标稳定）；未声明 = 零预设（空表/空串/空 dict），
# 非法声明项 fail-closed 丢弃（注册期告警在 validate_manifest，消费侧不二次报错）。


def skill_requires_inputs(skill_name: str) -> List[Dict[str, Any]]:
    """manifest requires_inputs 声明（v3）：规范化后的原料需求清单。

    每项 {type, required, hint, features}；required 缺省 true；白名单外
    type/非法项丢弃；features = 声明轴标记清单（如 voice_reference，
    任务#8 ④，缺省空表）。未声明返回空表（回落旧 script_required
    判定，两路语义不叠加）。"""
    manifest = skill_manifest_of(skill_name)
    raw = (manifest or {}).get("requires_inputs")
    if not isinstance(raw, list):
        return []
    out: List[Dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        t = item.get("type")
        if not isinstance(t, str) or t not in REQUIRES_INPUT_TYPES:
            continue
        req = item.get("required")
        hint = item.get("hint")
        feats_raw = item.get("features")
        if not isinstance(feats_raw, list):
            feats_raw = []
        feats = [
            str(x).strip() for x in feats_raw
            if isinstance(x, str) and x.strip()
        ]
        out.append({
            "type": t,
            "required": True if req is None else bool(req),
            "hint": str(hint or "").strip(),
            "features": feats,
        })
    return out


def skill_declares_feature(skill_name: str, feature: str) -> bool:
    """Skill 的 requires_inputs 是否声明某声明轴标记（features 维度）。

    任务#8 ④：闸机软提醒跟随声明（如 voice_reference 音色参考轴），
    未声明返回 False（零预设，消费端自行决定是否回落状态探测）。"""
    if not skill_name or not feature:
        return False
    return any(
        feature in (item.get("features") or [])
        for item in skill_requires_inputs(skill_name)
    )


def skill_kind(skill_name: str) -> str:
    """manifest kind 声明（v3：pipeline|style）；未声明/非已知值返回空串。

    展示/消费口径；注入策略解析用 skill_injection_kind（
    未知 kind 开放注册降级，不返回空串而返回默认策略）。"""
    manifest = skill_manifest_of(skill_name)
    v = (manifest or {}).get("kind")
    return str(v) if v in KIND_VALUES else ""


# 默认注入策略（未声明 kind / 未知 kind 开放注册降级同口径）
DEFAULT_INJECTION_KIND = "pipeline"


def skill_injection_kind(skill_name: str) -> str:
    """注入策略维度解析（kind 只管注入策略这一个维度）。

    已知 kind（pipeline/style）直接返回；声明了未知 kind
    降级为默认（pipeline）策略并输出告警（开放注册，不拒服务）；
    未声明 kind 回落默认策略（零预设）。"""
    manifest = skill_manifest_of(skill_name)
    v = (manifest or {}).get("kind")
    if v is None:
        return DEFAULT_INJECTION_KIND
    if isinstance(v, str) and v in KIND_VALUES:
        return v
    logger.warning(
        f"[SkillRuntime] Skill「{skill_name}」声明未知 kind {v!r}，"
        f"按开放注册降级为默认（{DEFAULT_INJECTION_KIND}）注入策略"
    )
    return DEFAULT_INJECTION_KIND


def skill_language(skill_name: str) -> Dict[str, str]:
    """manifest language 声明（v3：{prompt, output}，取值 zh|en|auto）。

    只保留白名单内取值；未声明返回空 dict（语言闸维持现状）。"""
    manifest = skill_manifest_of(skill_name)
    raw = (manifest or {}).get("language")
    if not isinstance(raw, dict):
        return {}
    out: Dict[str, str] = {}
    for key in ("prompt", "output"):
        v = raw.get(key)
        if v in LANGUAGE_VALUES:
            out[key] = str(v)
    return out


def skill_prompt_en_categories(skill_name: str) -> List[str]:
    """manifest language.prompt_en_categories 声明（任务#8 ①）：
    产物类别级语言闸豁免清单（keyElement|shot|audio 子集）。

    只保留白名单内取值、去重保序；未声明返回空表（语言闸维持
    平台中文地板，豁免不泛化）。"""
    manifest = skill_manifest_of(skill_name)
    raw = (manifest or {}).get("language")
    if not isinstance(raw, dict):
        return []
    cats = raw.get("prompt_en_categories")
    if not isinstance(cats, list):
        return []
    out: List[str] = []
    for c in cats:
        if c in LANGUAGE_EN_CATEGORY_VALUES and c not in out:
            out.append(str(c))
    return out


def fallback_skill_from_state(raw_state: Optional[Dict[str, Any]]) -> str:
    """项目最近使用的 Skill 兜底：请求未携带 Skill 名时，
    回退 usedSkills 末位，保证后续轮次（继续/拆分分镜）仍绑定同一执行器。

    这是「当前 Skill 归属」的单一实现：chat_service / planner / agent_loop
    统一走这里，禁止各自再写一份 usedSkills 兜底（单一事实源）。
    """
    if not isinstance(raw_state, dict):
        return ""
    used = raw_state.get("usedSkills") or []
    return str(used[-1] or "") if used else ""


def match_skill_name_from_text(text: str) -> str:
    """消息文本里出现已注册 Skill 名时自动绑定（用户直接发 Skill 名/文档按钮引用，
    但请求未带 skill_slug；确定性匹配，不依赖模型自觉）。

    按名称/标识匹配：命中多个时取最后一个（用户最新提到的 Skill 更可能是当前意图）。
    """
    body = str(text or "")
    if not body:
        return ""
    matched = ""
    for entry in list_entries():
        name = str(entry.name or "")
        slug = str(entry.slug or "")
        if name and name in body:
            matched = name
        elif slug and slug in body:
            matched = str(entry.name or slug)
    return matched


# ---------- pause 声明解析下沉 ----------
# guard 需顶层消费，为避免 skill_runtime→web 反向依赖下沉本包；
# web/skill_docs 保留 re-export（兼容既有导入路径）。
_PAUSE_RULES_BLOCK_RE = re.compile(
    r"```(?:json|js)?\s*pause_rules\s*\n(.*?)```", re.S | re.I
)


def parse_pause_rules(content: str) -> Optional[Dict[str, Any]]:
    """解析可选的 pause_rules 声明块；未声明/格式非法返回 None。

    白名单键类型校验：stage_pause(bool)。显式声明优先于
    「何时暂停/强制暂停点」关键词检测（换表述不再静默失效）。
    """
    m = _PAUSE_RULES_BLOCK_RE.search(content or "")
    if not m:
        return None
    try:
        data = json.loads(m.group(1))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    out: Dict[str, Any] = {}
    if isinstance(data.get("stage_pause"), (bool, int)):
        out["stage_pause"] = bool(data["stage_pause"])
    return out
