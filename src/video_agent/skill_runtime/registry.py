"""Skill 上传即注册：文档章节 → 注册表条目。

Skill 目录包（单一形态 data/skills/<slug>/SKILL.md，Agent Skills
开放标准）仍是唯一数据源与下拉框数据源；平台声明随文档头部 YAML
frontmatter 合一。本注册表保存每个 Skill
解析后的章节与能力声明清单（不对应已注册
工具，仅作阶段裁剪/闸机的客观探针）。
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import re

from loguru import logger

from src.video_agent.config import settings  # 叶子依赖：停用开关活读（门户）
from src.video_agent.core import ports
from src.video_agent.skill_runtime import frontmatter
from src.video_agent.skill_runtime.manifest_schema import (
    split_issue_warnings,
)

# 管线能力词汇表：「章节声明 → 阶段能力」标记，仅供
# stage_probes 阶段裁剪、prompt_gates 音频闸、skill_docs/scan_skills
# Skill lint 作客观探针；平台不注册同名工具。
# Skill 正文散文已全部清洗为真实工具名；本表为能力词唯一事实源，
# prompts/planner/protocol.md「Skill 文档能力词对照」段须同批同步
#（漂移由 tests/unit/test_capability_word_alignment.py 拦截）。
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
    "image_generate": "生图",
    "generate_video": "视频生成",
    # 分析写入工具（A1 批）：能力词 script_analyze 的真身落点
    "script_analysis_report": "剧本分析",
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
    def available_tools(self) -> List[str]:
        """该 Skill 的管线能力声明清单（对应章节非空才成立）。
    
        名单是阶段裁剪/音频闸/lint 的客观探针（非已注册工具）。
        （C1b 裁决 2026-08-31：custom_sections/skill_section_run 通道退役。）
        """
        tools = [t for t in PIPELINE_CAPABILITY_TOOLS if self.section_for(t)]
        return tools
    
    def section_for(self, tool: str) -> str:
        stages = CAPABILITY_TOOL_STAGES.get(tool) or ()
        parts = [self.sections.get(s, "") for s in stages]
        return "\n\n".join(p for p in parts if p and p.strip()).strip()

    @property
    def package_root(self) -> Optional[Path]:
        """目录包根（data/skills/<slug>/）；主文档不在场返回 None。

        单一包形态（<slug>/SKILL.md）下与 frontmatter.resolve_doc_path
        同源：主文档存在即包根 = 其父目录。"""
        doc = frontmatter.resolve_doc_path(self.slug)
        if doc is None or doc.parent.name != self.slug:
            return None
        return doc.parent

    @property
    def declared_resources(self) -> Dict[str, Dict[str, Any]]:
        """frontmatter resources 资源清单声明（批6 版本锁，活读）：
        {包内相对路径: {sha256, size, mime}}；未声明/非法形状返回空 dict
        （形状问题归 manifest_schema WARN，消费侧 fail-closed 零预设）。"""
        raw = (self.manifest or {}).get("resources")
        if not isinstance(raw, dict):
            return {}
        return {
            k: v for k, v in raw.items()
            if isinstance(k, str) and k.strip() and isinstance(v, dict)
        }

    @property
    def resource_manifest(self) -> List[str]:
        """目录包资源清单（P2-4 按需加载白名单，fail-closed）：
        references/ 下文本类资源的包内相对路径清单（排序）；
        无 references/ 目录 = 空清单（零资源合法）。

        清单即声明：read_skill（resource=…）只放行清单内资源，
        清单外一律拒绝；二进制资源不开放经文本工具读取；
        无 references/ 目录 = 空清单（零资源合法）；
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

# 媒体资源后缀（批4：二进制资源禁入文本通道）：图/音/视频后缀只解析为
# 元数据描述符（名/大小/类型）供引用消费，不按文本读入上下文。
# 不进文本资源清单（resource_manifest 口径不变，fail-closed 不变）。
RESOURCE_MEDIA_SUFFIXES = {
    ".png": "image", ".jpg": "image", ".jpeg": "image", ".gif": "image",
    ".webp": "image", ".bmp": "image",
    ".mp3": "audio", ".wav": "audio", ".m4a": "audio", ".flac": "audio",
    ".aac": "audio", ".ogg": "audio",
    ".mp4": "video", ".mov": "video", ".avi": "video", ".mkv": "video",
    ".webm": "video",
}

# 素材资源子目录约定（批6：对齐 Flova 素材捆绑）：目录包 assets/ 放图/文档/
# 视频/音频素材，按引用消费（描述符通道，二进制不进文本/上下文）；
# references/ 保留给文本参考（resource_manifest 口径不变）。
ASSET_DIR_NAME = "assets"

# 文档类素材后缀（仅 assets/ 通道）：与媒体资源同走描述符按引用消费，
# 不按文本读；白名单外后缀仍 fail-closed 拒绝。
ASSET_DOC_SUFFIXES = {
    ".pdf": "document", ".doc": "document", ".docx": "document",
    ".pptx": "document", ".xlsx": "document",
}
ASSET_DESCRIPTOR_SUFFIXES = {**RESOURCE_MEDIA_SUFFIXES, **ASSET_DOC_SUFFIXES}


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
    坏声明不能带病上线，修好 data/skills/<slug>/SKILL.md
    头部 frontmatter 才能注册；单个坏 Skill 拒注册不截断 sync_all 批次。
    消费端 fail-closed 清洗仍保留（兜注册后 frontmatter 被改坏的活读场景）。
    版本锁已整体退役（Q10 裁决 2026-09-01：连记账一起删——拒绝用户改自己
    的技能不合理；sha256 核验/记账代码删除）；resources 声明仍透传描述符，
    本地版本备份归 web/skill_docs 的 .history/ 机制（保留）。
    
    问题分级：只有错误级问题拒注册；WARN 级（开放注册
    降级/废除键过渡告警）只输出告警日志，不阻断注册。
    name/description 为注册期必填（Agent Skills 开放标准：渐进披露
    第一层目录摘要的权威声明），缺失即拒注册。
    """
    entry = _load_entry(slug)
    if entry is None:
        return None
    errors, warnings = split_issue_warnings(
        frontmatter.validate_manifest(entry.manifest))
    for w in warnings:
        logger.warning(f"[SkillRuntime] Skill「{entry.name}」frontmatter 告警：{w}")
    manifest = entry.manifest or {}
    for key in ("name", "description"):
        v = manifest.get(key)
        if not isinstance(v, str) or not v.strip():
            errors.append(
                f"frontmatter 缺必填键 {key}（Agent Skills 开放标准："
                "name/description 为渐进披露第一层目录摘要的权威声明）")
    # 版本锁已整体退役（Q10 裁决 2026-09-01）：sha256 不符/悬空声明不拒注册，
    # 核验记账代码同批删除；declared_resources 仅作描述符透传。
    if errors:
        # 拒注册同时摘除陈旧条目（refresh/重注册路径：frontmatter 改坏后
        # 旧注册态不得继续可用）
        _registry.pop(slug, None)
        logger.error(
            f"[SkillRuntime] Skill「{entry.name}」frontmatter schema 校验失败，"
            f"拒绝注册（fail-hard，修复 data/skills/{slug}/SKILL.md 头部声明 "
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

    单一包形态（Agent Skills 开放标准）：只扫 <slug>/SKILL.md 目录包。
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
    # 目录包：<slug>/SKILL.md；隐藏目录（.history 等）不参与注册。
    slugs: List[str] = sorted(
        p.name for p in directory.iterdir()
        if p.is_dir() and not p.name.startswith(".")
        and (p / frontmatter.SKILL_DOC_NAME).exists()
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


# ---------- 可加载性门户（M2，2026-08-30 用户裁决：停用=真停用） ----------
# 全部消费面（目录段/兜底/文本匹配/注入支路/read_skill/风格层…）只调这三个函数，
# 禁止各消费点复述开关过滤（P1 单一事实源）。判定顺序：先注册维、再开关维；
# 开关活读 settings.skills_disabled（热切换即时生效，不缓存）。


def disabled_slugs() -> frozenset:
    """被停用 slug 集合（每次调用活读；空集 = 全启用）。"""
    return frozenset(settings.skills_disabled or [])


def loadable_entries() -> List[SkillEntry]:
    """已注册 ∧ 未停用的条目，按 slug 显式排序（防 refresh 重插导致目录顺序漂移）。"""
    _ensure_synced()
    dis = disabled_slugs()
    return [_registry[s] for s in sorted(_registry) if s not in dis]


def resolve_loadable_entry(wanted: str) -> Optional[SkillEntry]:
    """resolve_entry 命中后查开关：停用/未注册返回 None。"""
    entry = resolve_entry(wanted)
    if entry is None or entry.slug in disabled_slugs():
        return None
    return entry


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

    只放行资源清单（目录包 references/ 实际文件列表）内的文本资源；
    声明外资源（清单外路径/绝对路径/.. 穿越）一律拒绝。
    返回 (资源绝对路径, "")；失败返回 (None, 错误说明)。

    口径演进：三级资源加载采用「资源清单即声明」（references/ 目录），
    替代计划书早期 scripts 目录字面约定，能力等价且更收敛；批6 起
    assets/ 素材子目录同走描述符通道放行。

    媒体/素材资源（批4 二进制禁入文本通道，批6 放行 assets/）：
    references/ 下图/音/视频后缀与 assets/ 下登记后缀（媒体+文档）的实际文件可解析，
    但仅供调用方转成元数据描述符（名/大小/类型）按引用消费，不按文本读；
    同样受包内路径/符号链接/包根逃逸守卫（与文本资源同口径只紧不松）。"""
    entry = resolve_loadable_entry(wanted)
    if entry is None:
        if resolve_entry(wanted) is not None:
            return None, f"Skill「{wanted}」已停用，不可加载（停用=真停用）"
        return None, f"未找到 Skill「{wanted}」"
    root = entry.package_root
    if root is None:
        return None, (
            f"Skill「{entry.name}」主文档（<slug>/SKILL.md）不在场，"
            "无法定位目录包资源")
    rel = str(resource or "").strip().replace("\\", "/")
    parts = [p for p in rel.split("/") if p and p != "."]
    if not rel or not parts or ".." in parts:
        return None, (
            f"资源路径 {resource!r} 非法（只允许包内 references/ 或 "
            f"{ASSET_DIR_NAME}/ 相对路径）")
    manifest = entry.resource_manifest
    rel_norm = "/".join(parts)
    target = root / rel_norm
    if rel_norm not in set(manifest):
        # 描述符例外通道：仅限 references/ 下图/音/视频后缀或 assets/ 下登记后缀
        #（批4 媒体通道，批6 扩展素材目录）的实际文件可解析为描述符，
        # 不按文本读；其余仍 fail-closed 拒绝
        suffix = target.suffix.lower()
        is_media = (
            target.is_file()
            and not target.is_symlink()
            and (
                (parts[0] == RESOURCE_DIR_NAME
                 and suffix in RESOURCE_MEDIA_SUFFIXES)
                or (parts[0] == ASSET_DIR_NAME
                    and suffix in ASSET_DESCRIPTOR_SUFFIXES)
            )
        )
        if not is_media:
            listed = "、".join(manifest[:10]) or "无"
            return None, (
                f"资源 {resource!r} 不在 Skill「{entry.name}」资源清单内"
                f"（fail-closed：声明外资源一律拒绝）。可用资源：{listed}")
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


def fallback_skill_from_state(raw_state: Optional[Dict[str, Any]]) -> str:
    """项目当前 Skill 归属兜底（可加载性门户收口，M2 停用=真停用）。

    候选序列 = activeSkill → usedSkills 倒序，取首个命中门户者；全盲返回空。
    不改项目态（不清 activeSkill/usedSkills，重新启用后自动恢复）；
    显式自由对话（批 C：activeSkill 已登记且 slug 为空）即终止不再滑落。
    这是「当前 Skill 归属」的单一实现：chat_service / planner / agent_loop
    统一走这里，禁止各自再写一份兜底（单一事实源）。
    """
    if not isinstance(raw_state, dict):
        return ""
    active = raw_state.get("activeSkill")
    if isinstance(active, dict):
        slug = str(active.get("slug") or "").strip()
        if not slug:
            return ""  # 显式自由对话（批 C）：不回落 usedSkills
        if resolve_loadable_entry(slug) is not None:
            return slug
    for item in reversed(list(raw_state.get("usedSkills") or [])):
        cand = str(item or "").strip()
        if cand and resolve_loadable_entry(cand) is not None:
            return cand
    return ""


def match_skill_name_from_text(text: str) -> str:
    """消息文本里出现可加载（已注册 ∧ 未停用）Skill 名时自动绑定（用户直接发
    Skill 名/文档按钮引用，但请求未带 skill_slug；确定性匹配，不依赖模型自觉）。
    停用项不参与自动挑选（M2 停用=真停用，门户收口）。

    按名称/标识匹配：命中多个时取最后一个（用户最新提到的 Skill 更可能是当前意图）。
    """
    body = str(text or "")
    if not body:
        return ""
    matched = ""
    for entry in loadable_entries():
        name = str(entry.name or "")
        slug = str(entry.slug or "")
        if name and name in body:
            matched = name
        elif slug and slug in body:
            matched = str(entry.name or slug)
    return matched


