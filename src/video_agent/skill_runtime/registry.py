"""Skill 上传即注册：文档章节 → 注册表条目。

Skill 文档（data/skills/*.md 或目录包 data/skills/<slug>/<slug>.md）
仍是唯一数据源与下拉框数据源；平台声明随文档头部 YAML frontmatter
合一（任务#5，外置 JSON sidecar 已退役）。本注册表保存每个 Skill
解析后的章节与能力声明清单（任务#36 B5 执行器退役后不再对应已注册
工具，仅作阶段裁剪/闸机的客观探针）。
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import json
import re

from loguru import logger

from src.video_agent.core import ports
from src.video_agent.skill_runtime import frontmatter
from src.video_agent.skill_runtime.manifest_schema import (
    KIND_VALUES,
    LANGUAGE_VALUES,
    REQUIRES_INPUT_TYPES,
)

# 管线能力词汇表（任务#36 B5：执行器已一步退役，原 SKILL_EXECUTOR_TOOLS/
# STORYBOARD_STRUCTURE_TOOLS 降级为「章节声明 → 阶段能力」标记，仅供
# pipeline_orchestrator 阶段裁剪、prompt_gates 音频闸、skill_docs/scan_skills
# Skill lint 作客观探针；平台不再注册同名工具）。
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
# （原 TOOL_STAGES 同数据，随执行器退役改名）
CAPABILITY_TOOL_STAGES: Dict[str, tuple] = {
    "script_analyze": ("planning",),
    "storyboard_key_elements": ("storyboard_ke",),
    "storyboard_shots": ("storyboard_shot",),
    "storyboard_audio": ("storyboard_audio",),
    "write_media_prompt": ("prompt_draft",),
    "audio_generate": ("generation",),
    "video_assembler": ("assembly",),
}

# P3-15 自定义章节通道：frontmatter 顶层声明 custom_sections（章节标识→通道名），
# 非管线类 Skill 不必套固定 7 章节模板也能声明自定义章节（执行器形态已退役，
# 现仅作章节声明探针；不参与固定章节词汇表与漂移门禁口径）。
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

        任务#36 B5 执行器退役后：名单不再是已注册工具，而是阶段裁剪/
        音频闸/lint 的客观探针（同名工具已删除）。
        P3-15：声明 custom_sections 且任一标识可解析出非空章节时，
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


_registry: Dict[str, SkillEntry] = {}
_synced: bool = False


def _load_entry(slug: str) -> Optional[SkillEntry]:
    """从磁盘读取一个 Skill 文档并解析章节；不存在返回 None。"""
    sd = ports.skill_docs_port()

    doc = sd.get_skill_doc(slug)
    if not doc:
        return None
    # 声明唯一源 = 文档头部 frontmatter（任务#5 合一）；manifest 经
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

    C4 fail-hard（任务#22）：frontmatter schema 校验失败拒绝注册，替代旧
    「只告警不阻断」——坏声明不能带病上线，修好 data/skills/<slug>.md
    头部 frontmatter 才能注册；单个坏 Skill 拒注册不截断 sync_all 批次。
    消费端 fail-closed 清洗仍保留（兜注册后 frontmatter 被改坏的活读场景）。
    """
    entry = _load_entry(slug)
    if entry is None:
        return None
    issues = frontmatter.validate_manifest(entry.manifest)
    if issues:
        # 拒注册同时摘除陈旧条目（refresh/重注册路径：frontmatter 改坏后
        # 旧注册态不得继续可用）
        _registry.pop(slug, None)
        logger.error(
            f"[SkillRuntime] Skill「{entry.name}」frontmatter schema 校验失败，"
            f"拒绝注册（fail-hard，修复 data/skills/{slug}.md 头部声明 "
            f"后经 refresh_skill 重试）：{'；'.join(issues)}"
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

    插件包约定双形态（任务#5）：单文件 <slug>.md 与目录包
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
        # v2 收尾：canonical 身份碰撞拒注册（计划§6：alias 必须显式
        # 登记；归一碰撞 = 配置错误，不得双注册同身份 Skill）。
        canon = _norm_name(slug)
        if canon in seen_canon:
            logger.error(
                f"[SkillRuntime] alias 碰撞，拒绝注册 {slug!r}"
                f"（同身份已注册: {seen_canon[canon]!r}）")
            continue
        try:
            # fail-hard 拒注册的 Skill 不计入、不占 canonical 身份
            #（C4：schema 违规 = 未注册，身份留给修复后的合法文件）
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
    """名称归一化（canonical 身份，Rule2 v6）：小写 + 去空格/连字符/
    下划线/扩展名——「AI短剧一站式生成」与「AI-短剧一站式生成」同身份。"""
    return (
        (s or "").strip().casefold()
        .replace(" ", "").replace("-", "").replace("_", "")
        .replace(".md", "").replace(".txt", "")
    )


def resolve_entry(wanted: str) -> Optional[SkillEntry]:
    """按 Skill 名称/别名模糊定位注册条目（精确 → 归一化相等 → 双向包含）。

 ：包含匹配收紧为**唯一命中才返回**——近似名 Skill 并存时
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
    """manifest 的 flow 开关是否启用（spec_wizard/spec_stage_trim/spec_gate）。

    未声明 manifest 或未声明该键时返回 False：引擎对业务流程一无所知，
    平台级流程闸/向导/裁剪只对显式声明的 Skill 生效（。
    """
    manifest = skill_manifest_of(skill_name)
    if not manifest:
        return False
    return bool((manifest.get("flow") or {}).get(key, False))


def spec_wizard_active(skill_name: str) -> bool:
    """规格向导启用判定（frontmatter 唯一源，文本启发式退役）。

    frontmatter flow.spec_wizard 显式声明；未声明 = 不启用（引擎零预设）。
    存量 Skill 的现值已由迁移脚本冻结进 frontmatter。"""
    manifest = skill_manifest_of(skill_name)
    return bool(((manifest or {}).get("flow") or {}).get("spec_wizard"))


def script_required_active(skill_name: str) -> bool:
    """剧本原料闸启用判定（frontmatter 唯一源，文本启发式退役）。

    frontmatter flow.script_required 显式声明；未声明 = 不启用。
    存量 Skill 的现值已由迁移脚本冻结进 frontmatter。"""
    manifest = skill_manifest_of(skill_name)
    return bool(((manifest or {}).get("flow") or {}).get("script_required"))


# ---------- v3 声明读取 API（任务#35 B2：requires_inputs/kind/language 消费） ----------
# 与 spec_wizard_active/script_required_active 同模块属性访问模式（调用方经
# registry.<fn> 引用，测试 patch 目标稳定）；未声明 = 零预设（空表/空串/空 dict），
# 非法声明项 fail-closed 丢弃（注册期告警在 validate_manifest，消费侧不二次报错）。


def skill_requires_inputs(skill_name: str) -> List[Dict[str, Any]]:
    """manifest requires_inputs 声明（v3）：规范化后的原料需求清单。

    每项 {type, required, hint}；required 缺省 true；白名单外 type/非法项丢弃。
    未声明返回空表（回落旧 script_required 判定，两路语义不叠加）。"""
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
        out.append({
            "type": t,
            "required": True if req is None else bool(req),
            "hint": str(hint or "").strip(),
        })
    return out


def skill_kind(skill_name: str) -> str:
    """manifest kind 声明（v3：pipeline|style|reference）；未声明/非法返回空串。"""
    manifest = skill_manifest_of(skill_name)
    v = (manifest or {}).get("kind")
    return str(v) if v in KIND_VALUES else ""


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


# ---------- （审核）：pause 声明解析下沉 ----------
# 原属 web/skill_docs；guard 需顶层消费，为避免 skill_runtime→web 反向依赖下沉本包；
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
