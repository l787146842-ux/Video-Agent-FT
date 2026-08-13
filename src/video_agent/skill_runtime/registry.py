"""Skill 上传即注册：文档章节 → 注册表条目。

Skill 文档（data/skills/*.md）仍是唯一数据源与下拉框数据源；
本注册表保存每个 Skill 解析后的章节与可用执行器清单，
执行器调用时据此只注入自己对应的章节。
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from loguru import logger

# 本项目新增的 Skill 执行器工具（复用现有工具不在此列：
# document_write / read_uploaded_doc / image_generate / generate_video / workflow_pause）

# 故事板结构拆解执行器家族（原 storyboard_designer 拆分为三部分，按阶段逐个调用）
STORYBOARD_STRUCTURE_TOOLS = (
    "storyboard_key_elements",
    "storyboard_shots",
    "storyboard_audio",
)

SKILL_EXECUTOR_TOOLS = (
    "script_analyze",
    *STORYBOARD_STRUCTURE_TOOLS,
    "write_media_prompt",
    "audio_generate",
    "video_assembler",
)

# 执行器 → 需要的 Skill 章节（stage 键，与 skill_docs.split_skill_sections 对齐）
TOOL_STAGES: Dict[str, tuple] = {
    "script_analyze": ("planning",),
    "storyboard_key_elements": ("storyboard_ke",),
    "storyboard_shots": ("storyboard_shot",),
    "storyboard_audio": ("storyboard_audio",),
    "write_media_prompt": ("prompt_draft",),
    "audio_generate": ("generation",),
    "video_assembler": ("assembly",),
}


@dataclass
class SkillEntry:
    """一个 Skill 文档解析后的注册表条目。"""

    slug: str
    name: str
    content: str
    # stage → 章节原文（split_skill_sections 产出）
    sections: Dict[str, str] = field(default_factory=dict)
    # skill_manifest 声明块解析结果（{"gates":..., "flow":..., "pause":...}）；
    # None = 未声明，平台行为回落最小闸（S1：引擎不预设任何业务流程）
    manifest: Optional[Dict[str, dict]] = None

    @property
    def available_tools(self) -> List[str]:
        """该 Skill 实际可用的执行器（对应章节非空才注册）。"""
        return [t for t in SKILL_EXECUTOR_TOOLS if self.section_for(t)]

    def section_for(self, tool: str) -> str:
        stages = TOOL_STAGES.get(tool) or ()
        parts = [self.sections.get(s, "") for s in stages]
        return "\n\n".join(p for p in parts if p and p.strip()).strip()


_registry: Dict[str, SkillEntry] = {}
_synced: bool = False


def _load_entry(slug: str) -> Optional[SkillEntry]:
    """从磁盘读取一个 Skill 文档并解析章节；不存在返回 None。"""
    from src.video_agent.web.skill_docs import (
        get_skill_doc,
        parse_skill_manifest,
        split_skill_sections,
    )

    doc = get_skill_doc(slug)
    if not doc:
        return None
    content = doc.get("content") or ""
    return SkillEntry(
        slug=slug,
        name=doc.get("name") or slug,
        content=content,
        sections=split_skill_sections(content),
        manifest=parse_skill_manifest(content),
    )


def register_skill(slug: str) -> Optional[SkillEntry]:
    """解析并注册一个 Skill；文档不存在或无法解析时返回 None。"""
    entry = _load_entry(slug)
    if entry is None:
        return None
    _registry[slug] = entry
    tools = entry.available_tools
    logger.info(
        f"[SkillRuntime] 已注册 Skill「{entry.name}」"
        f"（{len(entry.sections)} 个章节，执行器: {tools or '无'}）"
    )
    global _synced
    _synced = True
    return entry


def unregister_skill(slug: str) -> None:
    """删除 Skill 时注销其执行器注册表条目（复用现有工具不受影响）。"""
    entry = _registry.pop(slug, None)
    if entry is not None:
        logger.info(f"[SkillRuntime] 已注销 Skill「{entry.name}」的执行器注册")
    global _synced
    _synced = True


def refresh_skill(slug: str) -> Optional[SkillEntry]:
    """编辑/重新上传 Skill 后重新解析注册。"""
    unregister_skill(slug)
    return register_skill(slug)


def sync_all(force: bool = False) -> int:
    """启动/首次使用时全量注册 data/skills/*.md（幂等，可重复调用）。

    直接扫描 SKILL_DOCS_DIR，不经过 list_skill_docs/ensure_default_skill_docs，
    避免与文档系统互相递归。
    """
    global _synced
    if _synced and not force:
        return len(_registry)
    from pathlib import Path

    from src.video_agent.web import skill_docs as sd

    directory = Path(sd.SKILL_DOCS_DIR)
    if not directory.exists():
        _synced = True
        return 0
    count = 0
    try:
        for f in sorted(directory.glob("*.md")):
            slug = f.stem
            if slug and _load_entry(slug) is not None:
                register_skill(slug)
                count += 1
    except Exception as e:  # 注册失败不阻断主流程
        logger.warning(f"[SkillRuntime] 全量注册失败: {e}")
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
    _ensure_synced()
    return _registry.get(slug)


def list_entries() -> List[SkillEntry]:
    _ensure_synced()
    return list(_registry.values())


def _norm_name(s: str) -> str:
    """名称归一化（与 skill_docs 模糊匹配一致）。"""
    return (s or "").strip().casefold().replace(" ", "").replace(".md", "").replace(".txt", "")


def resolve_entry(wanted: str) -> Optional[SkillEntry]:
    """按 Skill 名称/别名模糊定位注册条目（精确 → 归一化相等 → 双向包含）。"""
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
        for e in entries:
            for n in (e.name, e.slug):
                nn = _norm_name(n)
                if nn and len(nn) >= 2 and (wn in nn or nn in wn):
                    return e
    return None


def tool_sections(skill_name: str, tool: str) -> str:
    """返回某执行器应注入的 Skill 章节全文；Skill 未注册/无对应章节返回空串。"""
    entry = resolve_entry(skill_name)
    if entry is None:
        return ""
    return entry.section_for(tool)


def tool_available(skill_name: str, tool: str) -> bool:
    """该 Skill 是否注册了对应执行器。"""
    return bool(tool_sections(skill_name, tool))


def skill_manifest_of(skill_name: str) -> Optional[Dict[str, dict]]:
    """当前 Skill 的 manifest 声明；未注册/未声明返回 None（最小闸语义）。"""
    entry = resolve_entry(skill_name)
    if entry is None:
        return None
    return entry.manifest


def skill_flow_enabled(skill_name: str, key: str) -> bool:
    """manifest 的 flow 开关是否启用（spec_wizard/spec_stage_trim/channels_block）。

    未声明 manifest 或未声明该键时返回 False：引擎对业务流程一无所知，
    平台级流程闸/向导/裁剪只对显式声明的 Skill 生效（S1 清偿）。
    """
    manifest = skill_manifest_of(skill_name)
    if not manifest:
        return False
    return bool((manifest.get("flow") or {}).get(key, False))


def spec_wizard_active(skill_name: str) -> bool:
    """规格向导启用判定（2222 二轮：客观流程特征检测，替代纯声明制）。

    Skill 正文提及规格文档名（流程含规格编写环节）→ 默认启用；
    manifest 显式 `"spec_wizard": false` → 逃生门关闭；显式 true 保持启用。
    修复「有规格流程但未声明 spec_wizard 的 Skill 向导不弹」（2222 二轮）；
    判定依据是 Skill 客观文本而非平台预设，不违反 S1。
    """
    entry = resolve_entry(skill_name)
    if entry is None:
        return False
    declared = ((entry.manifest or {}).get("flow") or {}).get("spec_wizard")
    if declared is True:
        return True
    if declared is False:
        return False
    from src.video_agent.core.prompt_gates import text_mentions_spec_doc

    return text_mentions_spec_doc(entry.content)


def fallback_skill_from_state(raw_state: Optional[Dict[str, Any]]) -> str:
    """项目最近使用的 Skill 兜底（7777 事故）：请求未携带 Skill 名时，
    回退 usedSkills 末位，保证后续轮次（继续/拆分分镜）仍绑定同一执行器。

    这是「当前 Skill 归属」的单一实现：chat_service / planner / agent_loop
    统一走这里，禁止各自再写一份 usedSkills 兜底（P1 单一事实源）。
    """
    if not isinstance(raw_state, dict):
        return ""
    used = raw_state.get("usedSkills") or []
    return str(used[-1] or "") if used else ""


def register_doc_hooks() -> None:
    """挂到 skill_docs 保存/删除路径的刷新函数（由 skill_docs 调用）。"""
    # 占位：实际钩子在 skill_docs.save_skill_doc / delete_skill_doc 中调用 refresh_skill / unregister_skill
    return None
