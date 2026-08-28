"""system prompt 组装。

承载：协议/Skill 目录/选中草稿/选中 Skill 轻量状态块的组装。
段落顺序：稳定内容在前，选中 Skill 轻量块放在最末尾（近生成端，遵循度最高）。
任务#12 批次B：Skill 正文一律不注入（全文直注/分级注入/组合注入全部退役），
系统只注入 L1 元数据目录与轻量状态提示，正文由模型调 read_skill 按需读取。
逐轮变化的状态上下文（状态 JSON/工具边界说明/故事板客观进度）不占
system 段，经 build_state_tail_message 以 history 尾部消息（user 通道）
每步注入——system 段（含 Skill 块）成为跨步稳定前缀（供应商 KV-cache 友好）。

planner.py 保留 _build_system_prompt 等同名委托，既有调用/测试路径不变。
"""
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Tuple

from loguru import logger

from src.video_agent.config import settings
# prompt_gates 保留顶层导入：gates_inputs 必须在其后导入（gates_script↔prompt_gates
# 尾块 re-export 对首入方向敏感；原料判定家族）；段内条件判定已收归
# planner 单一事实源，本文件不再直接消费它
from src.video_agent.core import prompt_gates  # noqa: F401
# gates_inputs 必须在 prompt_gates 之后导入（见上方注释）
from src.video_agent.core import gates_inputs
from src.video_agent.core import live_metrics
from src.video_agent.skill_runtime import guard as skill_guard
# v3 声明读取经模块属性访问（测试 patch registry.<fn> 即生效）
from src.video_agent.skill_runtime import registry as skill_registry
from src.video_agent.state.models import CAT_AUDIO_ITEMS, CAT_KEY_ELEMENTS, CAT_SHOTS
# MCP 两段式注入段 1：外部工具目录文本块（名称+摘要，
# schema 不进 FC tools；完整 schema 由 enable 后按需注入）
from src.video_agent.tools.mcp import catalog as mcp_catalog
from src.video_agent.utils.prompts import load_prompt, render_prompt

if TYPE_CHECKING:
    from src.video_agent.core.planner import PlannerContext

# 遥测：system prompt 组装总长预警阈值（字符）——超过即 warning，
# 提醒清理草稿（token 治理的组装层可观测性）
_SYSTEM_PROMPT_WARN_CHARS = 60000

# v3 元数据头展示标签（kind 目录口径 + 暂停 trigger 文案）
_KIND_LABELS = {
    "pipeline": "流程型（固定流水线）",
    "style": "风格型（美学指导）",
}
# Skill 正文注入家族（全文直注/分级注入/组合注入/平台边界包壳/
# kind 差异化声明）已随任务#12 批次B 整体退役：正文一律经
# read_skill 按需读取，系统只注入 L1 目录与轻量状态提示。
# reference kind 低权重注入分支已随任务#8 ② 下架清偿（KIND_VALUES 不再含
# reference，声明入口关闭、降级 pipeline；死分支已删）。


_PAUSE_TRIGGER_LABELS = {
    "spec_finalized": "规格定稿后",
    "storyboard_structure_ready": "故事板结构就绪（分组/草稿搭建完成）后",
    "first_generation_call": "首次调用生成类工具前",
}


class PromptBuilder:
    """system prompt 组装器：依赖通过 callable 注入，不与 Planner 循环引用"""

    def __init__(
        self,
        get_skill_docs: Callable[[], Any],
        get_project_id: Callable[[], str],
        get_raw_state: Optional[Callable[[], Dict[str, Any]]] = None,
    ) -> None:
        self._get_skill_docs = get_skill_docs
        self._get_project_id = get_project_id
        # 当前工作台 raw state（分阶段聚焦注入探测用；缺省不启用聚焦）
        self._get_raw_state = get_raw_state
        # 每次组装前预计算的原始长度载体（段 builder 与遥测共用，
        # 避免 state_builder 重复调用）
        self._state_json = ""
        self._selected_block = ""

    def build_system_prompt(self, context: "PlannerContext") -> str:
        """构建 system prompt：从 prompts/ 加载 + 注入状态上下文。

        段落注册制：各段经 PROMPT_SECTIONS 登记（唯一 name +
        order + builder），按 order 排序逐段构建，空串跳过；条件段的有无
        由各段 builder 内部决定。段序与历史顺序 1:1（前缀缓存优化：稳定
        内容在前，选中 Skill 轻量块放在最末尾近生成端）。
        状态上下文（状态 JSON/工具边界说明/故事板进度）已移出 system 段，
        见 build_state_tail_message（history 尾部消息注入，不在此登记）。

        同源裁剪解释：stage_note 段只消费 planner 经
        context 携带的裁剪解释（单一事实源），本处不再自行判定；
        独立使用（不经 planner）时 note 缺省为空即回退为不注入。

        协议段唯一 = planner/system_fc.md（Tool 优先瘦身协议，共有段经
        {{include}} 从 shared/ 拼装）。
        """
        # 预计算共享原始数据：遥测/超限预警需要原始长度（非包壳后段长）。
        # state 已移出 system 段（经 history 尾部消息注入），此处仅为
        # 遥测口径保留长度采集；选中 Skill 轻量块仍在 system 最末段
        if context.use_studio_context:
            if context.state_builder is not None:
                state_json = context.state_builder()
            else:
                state_json = context.state_json
        else:
            state_json = ""
        selected_block = ""
        if context.skill_name:
            selected_block = self.build_selected_skill_block(context.skill_name)
        self._state_json = state_json
        self._selected_block = selected_block

        # 按注册表 order 排序逐段构建，空串跳过（段序与历史拼装顺序 1:1）
        parts: List[Tuple[str, str]] = []
        for spec in PROMPT_SECTIONS:
            seg = spec.builder(self, context)
            if seg:
                parts.append((spec.name, seg))

        text = "\n\n".join(seg for _, seg in parts)
        # 组装明细入 live 注册表（context-usage 调试端点可读各段字符数）；
        # 遥测段名映射由 PROMPT_SECTIONS 自动生成（消除硬编码映射）；
        # prompt_sections.jsonl 字段格式锁死不变（check_prompt_budget.py 消费，零破坏）
        try:
            sec_lens: Dict[str, int] = {}
            for name, seg in parts:
                sec_lens[name] = sec_lens.get(name, 0) + len(seg)
            sections: Dict[str, int] = {key: 0 for key in _telemetry_section_keys()}
            for name, n in sec_lens.items():
                key = _SECTION_TELEMETRY_ALIAS.get(name)
                if key is not None:
                    sections[key] = sections.get(key, 0) + n
            # state 已移出 system 段（history 尾部消息），遥测仍记原始长度，
            # 观测口径不变；Skill 段为轻量状态块（含《Skill 流程纪律》全文），取原始长度
            sections["state"] = len(state_json) if context.use_studio_context else 0
            sections["skill"] = len(selected_block)
            sections["total"] = len(text)
            live_metrics.record_sections(self._get_project_id(), sections)
        except Exception as _e:
            logger.debug("[prompt_builder] 忽略异常: {}", _e)
        # 遥测：组装超限预警（各段字符数入账，便于定位臃胀来源）
        if len(text) > _SYSTEM_PROMPT_WARN_CHARS:
            logger.warning(
                f"[PromptBuilder] system prompt 组装超阈值：总长 {len(text)} 字符 > "
                f"{_SYSTEM_PROMPT_WARN_CHARS}（选中Skill块={len(selected_block)}，"
                f"状态JSON≈{len(state_json) if context.use_studio_context else 0}）；"
                "建议清理草稿或依赖降级保险丝"
            )
        return text

    def build_state_tail_message(
        self,
        context: "PlannerContext",
        state_builder_override: Optional[Callable[[], str]] = None,
    ) -> str:
        """状态上下文 history 尾部消息（user 通道，作为 history 最后一条注入）。

        状态 JSON/工具边界说明/故事板客观进度不占 system 段：每步以尾部
        消息注入，让 LLM 在每个轮次都看到先前轮次执行后的最新状态（近生成
        端，遵循度最高）；system 段（含 Skill 块）由此成为跨步稳定前缀。
        内部次序与原 system 段相对顺序一致（状态 JSON → 边界说明 → 故事板进度）。
        返回空串 = 本轮不注入。

        state_builder_override：预算保险丝降级重建时替换状态构建器（只留
        组标题/计数的降级状态），语义同 context.degraded_state_builder。
        """
        if not context.use_studio_context:
            return ""
        builder = state_builder_override or context.state_builder
        if builder is not None:
            state_json = builder()
        else:
            state_json = context.state_json
        parts: List[str] = []
        if state_json:
            parts.append("当前工作台状态 JSON 如下（每轮自动刷新）：\n\n" + state_json)
        # 同源裁剪解释：条件判定单一事实源归 planner._compute_excluded_tools，
        # 裁剪生效时经 context.stage_note 携带；未生效缺省为空即不注入。
        # 随状态同通道迁移：静默裁剪消除语义不变，只是不再击穿 system 前缀。
        if context.stage_note:
            parts.append(context.stage_note)
        if context.skill_name:
            note = self.build_storyboard_progress_note()
            if note:
                parts.append(note)
        return "\n\n".join(parts)

    def build_storyboard_progress_note(self) -> str:
        """故事板客观进度描述（纯数据）——只报三类有无，
        暂停点以当前 Skill 流程基线为准（正文经 read_skill 按需读取），
        平台不给排序意见；
        顺带同批暂停建议（建议非强制，省往返）。
        文案外置 prompts/shared/storyboard_progress.md。"""
        if self._get_raw_state is None:
            return ""
        try:
            raw = self._get_raw_state()
        except Exception:
            return ""
        ke = bool(raw.get(CAT_KEY_ELEMENTS))
        sh = bool(raw.get(CAT_SHOTS))
        au = bool(raw.get(CAT_AUDIO_ITEMS))
        if not (ke or sh or au):
            return ""
        mark = lambda b: "✓" if b else "✗"
        return render_prompt(
            "shared/storyboard_progress.md",
            ke_mark=mark(ke), sh_mark=mark(sh), au_mark=mark(au))

    def stage_allows_global_settings(self) -> bool:
        """全局设置注入的阶段门控——规格规划阶段（无任何分组）
        时长上限/渠道/分辨率都没有消费方，不注入；故事板阶段起才注入。
        无法探测阶段时保守注入（不失约束）。"""
        if self._get_raw_state is None:
            return True
        try:
            return self.detect_stage() != "planning"
        except Exception:
            return True

    def build_global_settings_note(self) -> str:
        """全局生成设置注入块：分镜最大时长 + 默认出图/出视频渠道 + 聊天出图开关。
        文案外置 prompts/shared/global_settings.md，
        代码只留动态行组装。"""
        image_line = ""
        if settings.default_image_provider_id:
            model = f" / 模型 {settings.default_image_model}" if settings.default_image_model else ""
            image_line = (
                f"默认出图渠道：供应商 {settings.default_image_provider_id}{model}，"
                f"图片分辨率 {settings.default_image_resolution}（草稿自身未配置时按其填写参数）")
        video_line = ""
        if settings.default_video_provider_id:
            model = f" / 模型 {settings.default_video_model}" if settings.default_video_model else ""
            video_line = (
                f"默认出视频渠道：供应商 {settings.default_video_provider_id}{model}，"
                f"视频分辨率 {settings.default_video_resolution}（草稿自身未配置时按其填写参数）")
        return render_prompt(
            "shared/global_settings.md",
            max_shot_duration=settings.max_shot_duration,
            image_line=image_line,
            video_line=video_line,
            chat_image_off=not settings.chat_image_enabled,
        )

    def build_iron_rules_block(self) -> str:
        """当前项目「执行铁律.md」全文注入块（项目级契约唯一表述源）。

        无铁律文档（未开工的新项目）或读取失败时返回空串，不阻断对话。
        """
        try:
            from src.video_agent.core.spec_rules import find_iron_rules_doc

            iron = find_iron_rules_doc(self._get_raw_state() or {})
            content = str((iron or {}).get("content") or "").strip()
        except Exception:
            return ""
        if not content:
            return ""
        # 头部文案外置 prompts/shared/iron_rules_header.md
        header = load_prompt("shared/iron_rules_header.md").strip()
        return header + "\n" + content

    def build_skill_catalog(self, context: "PlannerContext") -> str:
        """构建 Skill 目录（渐进式披露的「目录」）：全部文档 Skill 的名称+摘要常驻，
        全文不注入，模型判断相关性后调 read_skill 按需加载。
        代码内置 Skill（编剧/分镜师/制片）已彻底移除，不进目录。"""
        list_skill_docs = self._get_skill_docs().list_skill_docs

        lines: List[str] = []
        try:
            for d in list_skill_docs():
                name = d.get("name") or d.get("slug") or ""
                desc = (d.get("description") or "").strip() or "未提供摘要"
                lines.append(f"- {name}：{desc}")
        except Exception:  # 文档目录读取失败不阻断对话（降级遥测可见）
            live_metrics.record_degradation("prompt_builder.catalog")
        if not lines:
            return ""
        # 渐进式披露单源收敛：总纲唯一源 = shared/important_rules.md
        # （随协议段常驻），此处只留针对 Skill 目录的指针式短述
        header = (
            "== Skill 目录（渐进式披露，总纲见《重要规则》：上下文只常驻各 Skill 的"
            "名称与摘要，全文一律经 read_skill 按需加载，不要凭目录摘要自行推测流程细节）==\n"
            + "\n".join(lines)
        )
        if context.skill_name:
            header += (
                f"\n用户当前在前端选中了「{context.skill_name}」，其正文同样不注入，"
                "执行该 Skill 前先用 read_skill 读取全文；其他 Skill 需要时也要先 read_skill。"
            )
        # 组合激活（任务 #11）：风格层叠加时目录段同步告知（正文不注入，只在目录可见）
        if self._get_raw_state is not None:
            try:
                raw = self._get_raw_state() or {}
                style_names: List[str] = []
                for s in skill_registry.style_skills_from_state(raw):
                    entry = skill_registry.resolve_entry(s)
                    style_names.append(entry.name if entry is not None else s)
                if style_names:
                    header += (
                        "\n另有风格层叠加生效："
                        + "、".join(style_names)
                        + "（正文同样不注入，执行产出前先 read_skill 读取各风格层）。"
                    )
            except Exception:
                pass
        return header

    def build_selected_skill_block(self, skill_name: str) -> str:
        """选中 Skill 的轻量状态块（任务#12 批次B：正文零注入）。
    
        只含：选中 Skill 名称 + read_skill 按需加载指引 + 元数据头
        （版本/来源/类型/暂停点/原料就绪状态）+《Skill 流程纪律》全文；
        Skill 正文由模型执行前调 read_skill 按需读取。段序不变（段注册表
        order 100 最末，保前缀缓存约束）。解析失败/内容为空返回空串（降级为仅目录）。
    
        纪律全文挂回（任务#12 评审修复批，用户裁决）：原唯一注入点（全文直注
        块，已退役并登记防复活）随批次B 删除，三处常驻文案（system_fc.md/
        important_rules.md/feedback.md）仍引用《Skill 流程纪律》为唯一表述源，
        随选中 Skill 挂回使其重新可达（文本本身不改）。
        """
        sd = self._get_skill_docs()
        try:
            display, content = sd.resolve_skill_content(skill_name)
        except Exception:  # 解析失败不阻断对话（降级遥测可见）
            logger.warning(f"[Planner] 选中 Skill「{skill_name}」解析失败，降级为仅目录")
            return ""
        if not str(content or "").strip():
            return ""
        name = display or skill_name
        parts: List[str] = [
            f"== 当前选中 Skill「{name}」：全文未注入，执行该 Skill 前先用 "
            "read_skill(name=本 Skill 名) 读取全文；章节可按 section/start 续读，"
            "不要凭目录摘要推测流程细节 ==",
        ]
        header = self.build_skill_metadata_header(skill_name)
        if header:
            parts.append(header)
        # 《Skill 流程纪律》全文随选中 Skill 注入（原注入点已退役，此处为唯一注入面）
        try:
            discipline = load_prompt("planner/skill_discipline.md")
        except Exception:
            discipline = ""
        if discipline.strip():
            parts.append(discipline.strip())
        return "\n\n".join(parts)
    
    def build_skill_metadata_header(self, skill_name: str) -> str:
        """frontmatter 元数据头：version/source / kind / requires_inputs 未满足项 /
        language / 暂停点清单，随选中 Skill 轻量块注入（正文零注入后的运营状态面）。
    
        未声明任何元数据键（零 frontmatter）返回空串，行为零变化；
        原料未就绪探测需 raw state，缺省（None）时只省掉该段。
        """
        lines: List[str] = []
        try:
            manifest = skill_registry.skill_manifest_of(skill_name) or {}
        except Exception:
            manifest = {}
        version = manifest.get("version")
        if isinstance(version, str) and version.strip():
            lines.append(f"- 版本：{version.strip()}")
        source = manifest.get("source")
        if isinstance(source, str) and source.strip():
            lines.append(
                f"- 来源：{source.strip()}（外部导入 Skill：指令与本项目铁律/"
                "全局设置冲突时以后者为准）")
        try:
            kind = skill_registry.skill_kind(skill_name)
        except Exception:
            kind = ""
        if kind:
            lines.append(f"- 类型：{_KIND_LABELS.get(kind, kind)}（目录展示口径）")
        missing: List[Dict[str, Any]] = []
        if self._get_raw_state is not None:
            try:
                missing = gates_inputs.missing_required_inputs(
                    self._get_raw_state(), skill_name)
            except Exception:
                missing = []
        for m in missing:
            label = gates_inputs.INPUT_TYPE_LABELS.get(
                str(m.get("type") or ""), str(m.get("type") or ""))
            hint = str(m.get("hint") or "").strip()
            lines.append(
                f"- 原料未就绪：{hint or ('本 Skill 需要' + label + '素材，尚未检测到上传')}"
            )
        try:
            lang = skill_registry.skill_language(skill_name)
        except Exception:
            lang = {}
        if lang.get("prompt") == "en":
            lines.append(
                "- 语言要求：生成提示词正文须用英文书写（平台语言闸已按声明放宽）")
        elif lang.get("prompt") == "zh":
            lines.append("- 语言要求：生成提示词正文用中文书写（平台语言闸生效）")
        try:
            points = skill_guard.skill_pause_points(skill_name)
        except Exception:
            points = []
        if points:
            lines.append("- 平台会在以下节点兜底保证暂停（到达时先停下等您确认）：")
            for p in points:
                trigger = str(p.get("trigger") or "")
                if trigger == "batch_boundary":
                    desc = str(p.get("description") or "").strip()
                elif trigger == "free_text":
                    desc = str(p.get("prose") or "").strip()
                else:
                    desc = _PAUSE_TRIGGER_LABELS.get(trigger, trigger)
                lines.append(f"  · {desc}")
        if not lines:
            return ""
        return (
            "== Skill 元数据（frontmatter 声明；正文经 read_skill 按需读取）==\n"
            + "\n".join(lines)
        )

    # ---------- 分阶段探测 ----------

    def detect_stage(self) -> str:
        """根据工作台状态推断当前制作阶段（每轮构建 system prompt 时实时计算）：
        无分组→规格规划；有分组无草稿→故事板结构；草稿缺提示词→提示词草案；
        全部就绪→素材生成。状态不可读时返回空串（不启用聚焦）。"""
        if self._get_raw_state is None:
            return ""
        try:
            raw = self._get_raw_state()
        except Exception:
            return ""
        groups = (
            list(raw.get(CAT_KEY_ELEMENTS) or [])
            + list(raw.get(CAT_SHOTS) or [])
            + list(raw.get(CAT_AUDIO_ITEMS) or [])
        )
        if not groups:
            return "planning"
        drafts = [d for g in groups for d in (g.get("drafts") or []) if isinstance(d, dict)]
        if not drafts:
            return "storyboard"
        if any(not str(d.get("prompt") or "").strip() for d in drafts):
            return "prompt_draft"
        return "generation"


# ---------- 段落注册表（提示词注册制） ----------
#
# 段序与历史过程式拼装顺序 1:1 登记（保前缀缓存约束：稳定段在前、
# 选中 Skill 最末近生成端）；重名/重序在模块加载期即 raise。
# 条件段的有无由各 builder 内部决定，返回空串即被组装循环跳过。
# 状态上下文（状态 JSON/边界说明/故事板进度）不在本表登记：已移出
# system 段，经 build_state_tail_message 以 history 尾部消息注入。

@dataclass(frozen=True)
class PromptSectionSpec:
    """system prompt 段落登记项：唯一 name + order（小者在前）+ builder。

    builder 签名：(pb: PromptBuilder, context: PlannerContext) -> str；
    返回空串 = 本轮不注入该段。
    """
    name: str
    order: int
    builder: Callable[["PromptBuilder", "PlannerContext"], str]


def _sec_protocol(pb: "PromptBuilder", context: "PlannerContext") -> str:
    """协议段（稳定前缀第一段）：从 prompts/ 目录加载（Rule4），
    max_steps 模板化注入（消协议模板与 config 双写漂移）。"""
    if not context.use_studio_context:
        return ""
    # 协议单轨：动作通道唯一 = FC 工具。
    return render_prompt("planner/system_fc.md", max_steps=settings.max_steps) or ""


def _sec_session_summary(pb: "PromptBuilder", context: "PlannerContext") -> str:
    """会话摘要专用段：位于全局设置段之后（P2-2 段序手术：compaction 激活
    不再击穿稳定前缀；状态上下文已移出 system 段，不再参与段序锚定）。
    压缩摘要置于 system 段而非伪装成 history 首条 user 消息；
    是否注入按 interaction.session_summary.active 每轮判定（由
    chat_consume._maybe_compact_history 每请求签发：压缩生效置 True，
    未触发/失败回落同步清除），文本取 session_summary 缓存
    （内容指纹失效机制不变）。摘要自指措辞与新注入位置自洽：
    以第三人称交接陈述呈现，工作台状态 JSON 仍是最新事实源。"""
    if pb._get_raw_state is None:
        return ""
    try:
        cached = ((pb._get_raw_state() or {}).get("interaction") or {}).get("session_summary") or {}
    except Exception:
        return ""
    text = str(cached.get("text") or "").strip()
    if not (cached.get("active") and text):
        return ""
    return (
        "== 会话摘要（较早对话已被系统压缩；下文工作台状态 JSON 仍是最新事实源）==\n"
        "以下是本会话较早对话的交接摘要（细节可按摘要中的产物引用回溯定位）：\n"
        + text
    )


def _sec_catalog(pb: "PromptBuilder", context: "PlannerContext") -> str:
    """Skill 目录（渐进式披露：名称+摘要常驻，全文按需 read_skill）。"""
    return pb.build_skill_catalog(context)


def _sec_mcp_catalog(pb: "PromptBuilder", context: "PlannerContext") -> str:
    """MCP 外部工具目录（两段式注入段 1）：仅名称+摘要常驻，
    完整 schema 等 mcp_tool_catalog enable 后次回合进 FC tools。"""
    try:
        return mcp_catalog.catalog_block(
            pb._get_raw_state() if pb._get_raw_state else None) or ""
    except Exception:
        return ""


def _sec_iron_rules(pb: "PromptBuilder", context: "PlannerContext") -> str:
    """铁律全文注入（宪法）：项目级生产契约的唯一表述源——
    铁律文档在每轮对话开始时由系统 ensure，存在即注入，不与 Skill 激活绑定
    （协议模板不重复业务规则，铁律不能缺位）。"""
    if pb._get_raw_state is None:
        return ""
    return pb.build_iron_rules_block()


def _sec_selected_draft(pb: "PromptBuilder", context: "PlannerContext") -> str:
    """前端当前选中的草稿指针（类型标注）：位于会话摘要段之后、选中 Skill 段
    之前（P2-2 段序手术：UI 点击切换不再击穿前缀稳定段；状态上下文已移出
    system 段，不再参与段序锚定）。"""
    if not (context.use_studio_context and context.selected_draft_id):
        return ""
    return (
        f"\n用户当前选中的草稿：draft_id={context.selected_draft_id}"
        f"（类型 {context.selected_type or '未知'}）。"
    )


def _sec_global_settings(pb: "PromptBuilder", context: "PlannerContext") -> str:
    """全局生成设置（前端「全局设置」页用户配置，热生效）：
    分镜时长上限 + 默认生成渠道，Agent 拆镜/生成必须遵守；
    阶段门控——规格规划阶段无消费方，不注入（context rot 治理）。"""
    if not context.use_studio_context:
        return ""
    # 会话级压缩 session_compact 是创作设定的唯一软性保护，
    # 见 planner/session_compact.md；
    # 生成渠道清单注入机制已整体清除——渠道唯一事实源为
    # 顶部「全局设置」（provider_config/provider_prefs），规格文档不再承载渠道
    if not pb.stage_allows_global_settings():
        return ""
    return pb.build_global_settings_note()


def _sec_selected_skill(pb: "PromptBuilder", context: "PlannerContext") -> str:
    """选中 Skill 轻量状态块放在最后（近生成端）：长 system prompt 中部的指令
    遵循度会衰减，而产出规范（提示词写法/分组规则）恰恰是最需要被严格
    执行的部分。状态上下文已移出 system 段（history 尾部消息注入），
    Skill 块不再有大段状态 JSON 前置淹没问题。"""
    return pb._selected_block


def _validate_prompt_sections(
    specs: Tuple[PromptSectionSpec, ...],
) -> Tuple[PromptSectionSpec, ...]:
    """模块加载期校验：重名/重序即 raise；按 order 升序返回。"""
    names: set = set()
    orders: Dict[int, str] = {}
    for s in specs:
        if s.name in names:
            raise ValueError(f"PROMPT_SECTIONS 段名重复: {s.name}")
        if s.order in orders:
            raise ValueError(
                f"PROMPT_SECTIONS 段序重复: order={s.order} "
                f"({orders[s.order]} 与 {s.name})")
        names.add(s.name)
        orders[s.order] = s.name
    return tuple(sorted(specs, key=lambda s: s.order))


PROMPT_SECTIONS: Tuple[PromptSectionSpec, ...] = _validate_prompt_sections((
    PromptSectionSpec("protocol", 10, _sec_protocol),
    PromptSectionSpec("catalog", 20, _sec_catalog),
    PromptSectionSpec("mcp_catalog", 30, _sec_mcp_catalog),
    PromptSectionSpec("iron_rules", 40, _sec_iron_rules),
    PromptSectionSpec("global_settings", 60, _sec_global_settings),
    # P2-2 段序手术：摘要段后移至全局设置之后——
    # compaction 激活不再击穿协议/目录等稳定前缀（KV-cache 友好）
    PromptSectionSpec("session_summary", 65, _sec_session_summary),
    # P2-2 段序手术：选中草稿指针后移——
    # UI 点击切换草稿不再击穿 global_settings 及以前的稳定前缀。
    # 状态上下文（原 order 70/80/90 的 state_json/stage_note/
    # storyboard_progress）已移出 system 段：经 build_state_tail_message
    # 以 history 尾部消息（user 通道）每步注入，system 成跨步稳定前缀。
    # selected_draft 每请求才可能变（UI 点击），跨步稳定，留在 system。
    PromptSectionSpec("selected_draft", 75, _sec_selected_draft),
    PromptSectionSpec("selected_skill", 100, _sec_selected_skill),
))

# 遥测字段别名（注册表段名 → prompt_sections.jsonl 字段）：None = 不入
# jsonl（字段格式锁死，消费方 check_prompt_budget.py 零改动）；
# state_json/selected_skill 的遥测值取原始长度（非段长），在组装处显式赋值
_SECTION_TELEMETRY_ALIAS: Dict[str, Optional[str]] = {
    "protocol": "protocol",
    # 会话摘要段不进 jsonl 分项（字段格式锁死，消费方零改动；
    # 其增长只体现在 total 口径）
    "session_summary": None,
    "catalog": "catalog",
    "mcp_catalog": "mcp_catalog",
    "iron_rules": "iron_rules",
    "selected_draft": None,
    "global_settings": None,
    "selected_skill": None,
}
# 批次E：渠道机制退役后的恒 0 兼容字段 channels 已清偿
# （唯一消费方 check_prompt_budget.py 不读该字段）。


def _telemetry_section_keys() -> List[str]:
    """遥测字段清单：由段注册表自动生成（序 = 注册表 order），
    别名表决定段名→jsonl 字段。"""
    keys: List[str] = []
    for spec in PROMPT_SECTIONS:
        key = _SECTION_TELEMETRY_ALIAS.get(spec.name)
        if key is not None and key not in keys:
            keys.append(key)
    return keys
