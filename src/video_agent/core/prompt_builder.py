"""system prompt 组装。

承载：协议/Skill 目录/选中草稿/选中 Skill 预算注入块的组装。
段落顺序：稳定内容在前，选中 Skill 块放在最末尾（近生成端，遵循度最高）。
Skill 是指令性制作手册（决策史见 git tag adr-archive-20260901）：选中 Skill 正文经渐进披露预算化注入（头部按章节边界切齐，
其余经 read_skill 续读）；官方 Skill 干净注入，仅外部来源附来源标记。压制性包壳已退役（业界不给
skill 内容贴符咒，安全靠机械装置：动作单轨/确认闸/platform 安全底线不可关，宪法 §2.1）。
逐轮变化的状态上下文（状态 JSON/工具边界说明/故事板客观进度）不占
system 段，经 build_state_tail_message 以 history 尾部消息（user 通道）
每步注入——system 段（含 Skill 块）成为跨步稳定前缀（供应商 KV-cache 友好）。

planner.py 保留 _build_system_prompt 等同名委托，既有调用/测试路径不变。
"""
import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Tuple

from loguru import logger

from src.video_agent.config import settings
# prompt_gates 保留顶层导入（段内条件判定已收归 planner 单一事实源，
# 本文件不再直接消费它）；gates_inputs 原料判定家族已随 C1b 裁决退役删除。
from src.video_agent.core import prompt_gates  # noqa: F401
from src.video_agent.core import subagent as subagent_mod
from src.video_agent.utils import live_metrics
from src.video_agent.core.token_budget import estimate_tokens
# v3 声明读取经模块属性访问（测试 patch registry.<fn> 即生效）
from src.video_agent.skill_runtime import registry as skill_registry
from src.video_agent.state.models import CAT_AUDIO_ITEMS, CAT_KEY_ELEMENTS, CAT_SHOTS
# MCP 两段式注入段 1：外部工具目录文本块（名称+摘要，
# schema 不进 FC tools；完整 schema 由 enable 后按需注入）
from src.video_agent.tools.mcp import catalog as mcp_catalog
from src.video_agent.utils.prompts import (
    load_prompt, load_prompt_section, render_prompt, render_prompt_section,
)

if TYPE_CHECKING:
    from src.video_agent.core.planner import PlannerContext

# 遥测：system prompt 组装总长预警阈值（字符）——超过即 warning，
# 提醒清理草稿（token 治理的组装层可观测性）
_SYSTEM_PROMPT_WARN_CHARS = 60000

# Skill 清单单条摘要预算（字符；2026-09-12 用户裁决 500，对齐 dsh
# catalogDescriptionMaxLength）。frontmatter description 仍以Skill 作者
# 原文为唯一事实源（list_skills/工作台展示原文），仅目录段展示层截断
_CATALOG_DESC_MAX_CHARS = 500

# 状态降级引导语外置（P3 状态即数据）：状态 JSON 只留 degraded/compacted
# 客观标志位，引导语按标志位从 shared/degradation.md 加载，随状态尾部
# 消息独立成段注入（不进 system 段，保 KV-cache 前缀）
_DEGRADATION_FILE = "shared/degradation.md"
_DEGRADATION_FLAG_SECTIONS = (
    ("degraded", "STATE_DEGRADED"),
    ("compacted", "STATE_COMPACTED"),
)

# B1：Skill 正文 <planner> 段提取（默认注入唯一正文段）
_PLANNER_TAG_RE = re.compile(r"<planner>\s*(.*?)\s*</planner>", re.S | re.I)


# 2026-09-23 批13（用户裁决）：`_read_todos_from_raw` 与 `build_todo_note`
# 已**整段删除**（清单尾部注入退役）。原「读会话 todo 清单并回注」链路
# 与 dsh 原版相反——原版注释明写清单事件是 UI/replay 状态而非第二条模型
# 消息（`dsh-tool-todo` lib/index.js:6-8），本平台多造了这条注入；
# 且主代理侧与 Skill `<planner>` 段构成同一事实源两份（P1）。
# 主代理已改为无 todo_write（CHILD_ONLY_TOOLS），注入随之无消费方。

# v3 元数据头展示标签（kind/language）已随用户裁决 2026-08-31 退役
# （外部标杆对齐：frontmatter 只留 name/description/source 等最小键）。
# Skill 正文注入家族（全文直注/分级注入/组合注入/平台边界包壳/
# kind 差异化声明）已整体退役；自此选中 Skill
# 正文改经渐进披露预算化注入；（B1 裁决 2026-08-31：预算式头部注入退役，
# 默认注入收窄为 <planner> 段全文 + 章节目录，其余经 read_skill 按需取读）；
# 压制性包壳同期退役（官方干净注入，外部仅来源标记）。
# reference kind 低权重注入分支已随任务#8 ② 下架清偿（KIND_VALUES 不再含
# reference，声明入口关闭、降级 pipeline；死分支已删）。
# （C1b 裁决 2026-08-31：pause_points 机械暂停退役——元数据头不再注入
# 暂停点清单，暂停由模型读 planner 散文自主经 workflow_pause 执行。）


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

        同源裁剪解释（stage_note）已随批 B 工具全量常驻退役（2026-09-09）：
        阶段边界注释不再存在；选中草稿指针亦移入尾部（批 B3）。

        协议段唯一 = planner/protocol.md（Tool 优先瘦身协议，共有段已内联）。
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
        # 遥测字段格式锁死不变（只内存注册；Q12 裁决 2026-09-01 停 jsonl 落盘，原消费方已退役）
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
        """状态注入正文构建（单一事实源；二期 G3：每步尾部消息 → 轮首
        source=state 事件一次落流，planner._build_and_log_state_event 消费）。

        内部次序：状态 JSON → 降级引导段（按 degraded/compacted 标志位）→
        执行偏好/模式 note → 故事板进度 → 选中草稿指针。
        返回空串 = 本轮不注入（非 studio 上下文）。

        state_builder_override：测试/特殊编排替换状态构建器。"""
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
            # 降级/压缩引导段：按状态 JSON 客观标志位独立成段紧随其后
            deg_note = self._build_degradation_note(state_json)
            if deg_note:
                parts.append(deg_note)
        # 同源裁剪解释（stage_note）已随批 B 工具全量常驻退役（2026-09-09）：
        # 阶段边界注释不再存在。（2026-09-18 批 B 曾加 A' 章节注入，已随
        # 2026-09-19 主代理纯编排批退役——故事板设计委派子代理后主代理
        # 不再亲做故事板，每步章节注入失去消费方。）
        # 批 10 · 执行偏好注入（外部标杆同款）：轮始按档位签发
        # （planner._load_execution_pref_note），每步随尾部消息可见；
        # 行为层引导，闸机（tool_risk/gen_confirm + 同意账本）兜底硬保证。
        if getattr(context, "execution_pref_note", ""):
            parts.append(context.execution_pref_note)
        # 执行模式注入（2026-09-06 对齐批）：轮始按档位签发
        # （planner._load_execution_mode_note）；ai_decide 默认档 = 空串不注入；
        # key_steps_confirm/pause_all 的停由轮末阶段闸机械保证，此处只承担
        # 引导呈现语义（auto_full 压制自发暂停，不改变生成确认闸）。
        if getattr(context, "execution_mode_note", ""):
            parts.append(context.execution_mode_note)
        if context.skill_name:
            note = self.build_storyboard_progress_note()
            if note:
                parts.append(note)
        # 2026-09-23 批13：模型自记进度清单的尾部注入已退役（见上方模块注释；
        # 主代理已无 todo_write，注入无消费方，且与 Skill <planner> 构成双事实源）。
        # 选中草稿指针（批 B3 自 system order 75 移入尾部）：UI 选中态属
        # 每请求可变事实（P3 状态归位）；移入尾部后 system 静态核心跨请求
        # 字节稳定（UI 点击不再击穿 selected_skill 段前缀）
        if context.selected_draft_id:
            parts.append(render_prompt_section(
                "shared/selected_draft.md", "POINTER",
                draft_id=context.selected_draft_id,
                draft_type=context.selected_type or "未知"))
        # R11 裁剪可见性：轮内被裁工具非空时渲染 UNAVAILABLE 段，模型可见
        # 哪些工具本轮不可用及替代路由（消除“思考打架”）；
        # K6 批：CHILD_ONLY_TOOLS（子代理专属打卡工具）不渲染——主代理
        # 不感知打卡工具存在（仅执行期裁剪，不进可见性说明）。
        #
        # 2026-09-21 批A/A2（事故 5555/追加-1）：**子级整段不渲染**。
        # 本段文案面向主代理单场景写死——替代路由恒为「经委派（run_subagent）
        # 执行对应阶段」；而子级的 `turn_excluded` 里**正好含 run_subagent**
        # （SUBAGENT_TOOL_DENY 首条=结构防递归，子级 deny 集整体并入裁剪集，
        # 见 planner._compute_excluded_tools）。于是子级收到的是循环指令：
        # 「run_subagent 本轮不可用，替代路由：经委派（run_subagent）执行」。
        # 且子级工具面**启动时已固定**（DELEGATION_CONTEXT 明说不可扩权），
        # 逐条列被裁项对子级无行动价值——其唯一正确表述（「不在本次委派
        # 授权面」）已由 DELEGATION_CONTEXT 承担，再渲染属复述（P1）。
        # 主代理侧行为**逐字不变**（下方分支只对 depth≥1 生效）。
        _turn_excl = getattr(context, "turn_excluded", None)
        if _turn_excl and not getattr(context, "subagent_depth", 0):
            _render_excl = frozenset(_turn_excl) - subagent_mod.CHILD_ONLY_TOOLS
            if _render_excl:
                _excl_names = ", ".join(sorted(_render_excl))
                _excl_route = "经委派（run_subagent）执行对应阶段"
                parts.append(render_prompt(
                    "shared/turn_excluded.md",
                    names=_excl_names, route=_excl_route))
        # （步数行已随二期 G3 退役删除：每步必变 = 强制每步前缀失效的
        # 元凶之一；STEP_FEEDBACK 已带「第 N 轮」，信息不丢）
        return "\n\n".join(parts)

    @staticmethod
    def _build_degradation_note(state_json: str) -> str:
        """状态降级引导段（P3 载体改造）：解析状态 JSON 的 degraded/compacted
        客观标志位，命中时从 shared/degradation.md 加载对应分节作独立引导段。

        引导语不嵌状态数据体（原 note 字段已废除）；分节缺失时仅
        logger.warning、不注入（标志位仍在数据体，不内联逐字兜底，M-2 同口径）。
        非 JSON/解析失败（测试桩等）静默跳过。
        """
        try:
            parsed = json.loads(state_json)
        except Exception:
            return ""
        if not isinstance(parsed, dict):
            return ""
        for flag, section in _DEGRADATION_FLAG_SECTIONS:
            if not parsed.get(flag):
                continue
            text = load_prompt_section(_DEGRADATION_FILE, section)
            if not text:
                logger.warning(
                    f"[prompt_builder] prompts/{_DEGRADATION_FILE}::{section} "
                    "分节缺失，降级引导段不注入")
            return text
        return ""

    def build_storyboard_progress_note(self) -> str:
        """故事板客观进度描述（纯数据）——只报三类已建组数（批补丁：
        ✓/✗ 会被模型解读成「已完整」引发纠结，计数是零判定的纯事实），
        暂停点以当前 Skill 流程基线（『何时暂停』/关键暂停点）为准，
        平台不给排序意见；
        顺带同批暂停建议（建议非强制，省往返）。
        文案外置 prompts/shared/storyboard_progress.md。"""
        if self._get_raw_state is None:
            return ""
        try:
            raw = self._get_raw_state()
        except Exception:
            return ""
        # 三类全空不注入（尾部消息「零增量」契约；空数组状态 JSON 已自明）
        if not (raw.get(CAT_KEY_ELEMENTS) or raw.get(CAT_SHOTS)
                or raw.get(CAT_AUDIO_ITEMS)):
            return ""
        return render_prompt(
            "shared/storyboard_progress.md",
            ke_count=len(raw.get(CAT_KEY_ELEMENTS) or []),
            sh_count=len(raw.get(CAT_SHOTS) or []),
            au_count=len(raw.get(CAT_AUDIO_ITEMS) or []))

    def stage_allows_global_settings(self) -> bool:
        """（已退役保留壳）全局设置阶段门控——批 B3 改无条件注入后无消费方；
        detect_stage 仍被阶段感知状态构建等使用，本壳仅防外部引用断裂。
        壳到期制登记：短期保留，确认无引用后可删。"""
        if self._get_raw_state is None:
            return True
        try:
            return self.detect_stage() != "planning"
        except Exception:
            return True

    def build_global_settings_note(self, duration_only: bool = False) -> str:
        """全局生成设置注入块：分镜最大时长 + 默认出图/出视频渠道 + 聊天出图开关。
        文案外置 prompts/shared/global_settings.md，
        代码只留动态行组装。

        注入条件（记于此而非 in-file 注释头：本文件经 render_prompt 整文件加载，
        行内 `#` 注释会进装配、破坏等价，故按 storyboard_progress 同款例外处理）：
        由 stage_allows_global_settings() 阶段门控——规格规划阶段（无任何分组）
        时长/渠道/分辨率均无消费方故不注入，故事板阶段起注入；且需 use_studio_context。

        duration_only=True（故事板/提示词阶段的子代理）：只出「分镜最大时长」行，
        跳过出图/出视频渠道、分辨率、聊天出图开关——这些对拆镜/写提示词无消费方。"""
        image_line = ""
        video_line = ""
        if not duration_only:
            if settings.default_image_provider_id:
                model = f" / 模型 {settings.default_image_model}" if settings.default_image_model else ""
                image_line = (
                    f"默认出图渠道：供应商 {settings.default_image_provider_id}{model}，"
                    f"图片分辨率 {settings.default_image_resolution}（草稿自身未配置时按其填写参数）")
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
            chat_image_off=(not settings.chat_image_enabled) and not duration_only,
        )

    def build_iron_rules_block(self) -> str:
        """当前项目「执行铁律.md」全文注入块（项目级契约唯一表述源）。

        无铁律文档（未开工的新项目）或读取失败时返回空串，不阻断对话。

        注入条件（记于此而非 in-file 注释头：头部文案 iron_rules_header.md 经
        load_prompt 整文件加载后 .strip() 拼接，行内 `#` 注释会进装配、破坏等价，
        故按 storyboard_progress 同款例外处理）：项目存在《执行铁律》文档时作系统
        提示头部注入（每轮对话开始由系统 ensure，存在即注入，不与 Skill 激活绑定）。
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
        """构建 Skill 目录（渐进式披露的「目录」）：启用文档 Skill 的名称+摘要常驻，
        选中 Skill 的 <planner> 段全文与章节目录由 build_selected_skill_block 注入，
        其余章节经 read_skill 按需加载。
        批5（对齐外部标杆 卡片开关）：开关过滤（settings.skills_disabled 里的 slug 不进目录）
        + 条目预算（settings.skill_catalog_max_entries，超预算按项目 usedSkills 最近使用序
        截断，尾部附「另有 N 个已启用 Skill 未列出」指针行）。
        M3 批2（2026-08-30 裁决：注册表=加载唯一门户）：数据源从磁盘 list_skill_docs 切为
        registry.loadable_entries（发现→注册→加载；被拒注册包不进目录），description 取
        frontmatter manifest（与注册同权威源）；recency 排序/预算截断/降级遥测语义不变。
        文案外置 prompts/shared/skill_inject.md；代码内置 Skill（编剧/分镜师/制片）已彻底移除，不进目录。"""
        entries: List[Any] = []
        try:
            entries = list(skill_registry.loadable_entries())
        except Exception:  # 注册表读取失败不阻断对话（降级遥测可见）
            live_metrics.record_degradation("prompt_builder.catalog")
        # 条目预算（批5）：超预算按最近使用序截断——项目 usedSkills 登记过的 slug
        # 按使用序从近到远在前，其余保持原序（稳定排序；无使用记录时目录顺序不变）
        recency: Dict[str, int] = {}
        if self._get_raw_state is not None:
            try:
                used = (self._get_raw_state() or {}).get("usedSkills") or []
                recency = {str(s or ""): i for i, s in enumerate(used)}
            except Exception:
                recency = {}
        entries.sort(key=lambda e: -recency.get(e.slug, -1))
        max_entries = int(settings.skill_catalog_max_entries or 0)
        omitted = 0
        if max_entries > 0 and len(entries) > max_entries:
            omitted = len(entries) - max_entries
            entries = entries[:max_entries]

        lines: List[str] = []
        for e in entries:
            name = e.name or e.slug or ""
            desc = str((e.manifest or {}).get("description") or "").strip() or "未提供摘要"
            # 单条摘要预算（2026-09-12 用户裁决 500 字符，对齐 dsh
            # catalogDescriptionMaxLength）：frontmatter description 长度
            # 由 Skill 作者决定，展示层截断兜底，不回写 skill 文件（冻结）
            if len(desc) > _CATALOG_DESC_MAX_CHARS:
                desc = desc[:_CATALOG_DESC_MAX_CHARS] + "…"
            lines.append(f"- {name}：{desc}")
        if not lines:
            return ""
        # 渐进式披露单源收敛：总纲唯一源 = protocol.md《重要规则》段
        # （随协议段常驻），目录段文案外置 shared/skill_inject.md 分节
        header = (
            load_prompt_section("shared/skill_inject.md", "HEADER")
            + "\n" + "\n".join(lines)
        )
        if omitted:
            header += "\n" + render_prompt_section(
                "shared/skill_inject.md", "OMITTED", count=omitted)
        if context.skill_name:
            header += "\n" + render_prompt_section(
                "shared/skill_inject.md", "SELECTED",
                skill_name=context.skill_name)
        return header

    def build_selected_skill_block(self, skill_name: str) -> str:
        """选中 Skill 按需加载注入块（指令性注入合法化后的现行口径）。

        默认注入收窄：<planner> 流程段全文 + 章节目录；其余章节正文经
        read_skill(name, section="章节名") 按需取读（纪律提醒见《Skill 流程纪律》
        第 11 条）。预算式正文头部注入已退役（零判断方案不回退）。
        块内组成：选中提示行 + 元数据头 + 《Skill 流程纪律》全文 +
        <planner> 段全文 + 章节目录。
        段序不变（段注册表 order 100 最末，保前缀缓存约束）。
        解析失败/内容为空返回空串（降级为仅目录）。
        """
        sd = self._get_skill_docs()
        try:
            display, content = sd.resolve_skill_content(skill_name)
        except Exception:  # 解析失败不阻断对话（降级遥测可见）
            logger.warning(f"[Planner] 选中 Skill「{skill_name}」解析失败，降级为仅目录")
            return ""
        content = str(content or "").strip()
        if not content:
            return ""
        name = display or skill_name
        parts: List[str] = [render_prompt_section(
            "shared/skill_inject.md", "SELECTED_NOTE", name=name)]
        header = self.build_skill_metadata_header(skill_name)
        if header:
            parts.append(header)
        # 《Skill 流程纪律》全文随选中 Skill 注入（原注入点已退役，此处为唯一注入面）
        try:
            discipline = load_prompt_section("planner/skill_runtime.md", "DISCIPLINE")
        except Exception:
            discipline = ""
        if discipline and discipline.strip():
            parts.append(discipline.strip())
        planner_text = self._planner_section_text(content, sd)
        if planner_text:
            parts.append(f"<planner>\n{planner_text}\n</planner>")
        toc = self._toc_lines(content, sd)
        if toc:
            parts.append(render_prompt_section(
                "shared/skill_inject.md", "TOC_NOTE", name=name) + "\n" + "\n".join(toc))
        return "\n\n".join(parts)

    def _planner_section_text(self, content: str, sd: Any) -> str:
        """<planner> 流程段全文（B1 默认注入唯一正文段）。

        tag 形态优先；标题式回落「流程规划」章节切片；均无命中返空串。"""
        m = _PLANNER_TAG_RE.search(content)
        if m:
            return m.group(1).strip()
        try:
            toc = sd.list_skill_sections(content) or []
        except Exception:
            toc = []
        for s in toc:
            title = str(s.get("title") or "")
            if title in ("流程规划", "planner"):
                return content[int(s.get("start") or 0):int(s.get("end") or 0)].strip()
        return ""

    def _toc_lines(self, content: str, sd: Any) -> List[str]:
        """章节目录行（- 章节名 (字数)）；解析失败返空表。"""
        try:
            toc = sd.list_skill_sections(content) or []
        except Exception:
            return []
        lines: List[str] = []
        for s in toc:
            title = str(s.get("title") or "").strip()
            if not title:
                continue
            seg_len = max(0, int(s.get("end") or 0) - int(s.get("start") or 0))
            lines.append(f"- {title}（{seg_len} 字）")
        return lines

    def build_skill_metadata_header(self, skill_name: str) -> str:
        """frontmatter 元数据头：version/source / kind / language，
        随选中 Skill 注入块附加（运营状态面）。
    
        未声明任何元数据键（零 frontmatter）返回空串，行为零变化。
        （C1b 裁决 2026-08-31：requires_inputs 原料声明轴退役，
        未满足项段删除。）
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
        # 指令性制作手册口径：压制性包壳退役——仅外部/社区来源附中性来源标记
        # （供用户知情，无约束性措辞）；平台来源（platform/未声明）干净注入。
        if (
            isinstance(source, str)
            and source.strip()
            and source.strip().lower() != "platform"
        ):
            lines.append("- " + render_prompt_section(
                "shared/skill_inject.md", "META_LINE", source=source.strip()))
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
    """协议段（稳定前缀第一段）：整文件加载 prompts/planner/protocol.md（Rule 6）。
    步数预算不再模板化写死进协议（原 max_steps 死参数已删）；
    客观步数改经状态尾部消息注入（turn_budget，见 build_state_tail_message）。

    2026-09-21 批A/A1（事故 5555/Q8+追加-2）：**子级不注入本段**。
    本协议是**主代理编排协议**（自称「制片调度…把各专业阶段委派给对应执行
    环节」），对子级大部分语义为反（子级不能委派）；且其内两处指针
    （「停轮与批次时机见《Skill 流程纪律》第 6 条」「防虚报…唯一细则见第 3 条」）
    在子级**物理悬空**——`skill_runtime.md::DISCIPLINE` 只随 `_selected_block`
    注入，而子级 `skill_name=""`（`planner._launch_subagent`），永远拿不到。
    即：子级拿到的是「详见第 6 章」而第 6 章不在书里。
    子级的自足声明唯一源 = `prompts/planner/subagent.md::DELEGATION_CONTEXT`
    （随任务下发，含分批纪律——见 A3），本段不再对子级重复。
    """
    if not context.use_studio_context:
        return ""
    # 2026-09-21 批A/A1：子级（depth≥1）不注入主代理协议（指针悬空 + 语义反）
    if getattr(context, "subagent_depth", 0):
        return ""
    # 协议单轨：动作通道唯一 = FC 工具。
    return load_prompt("planner/protocol.md") or ""


def _sec_session_summary(pb: "PromptBuilder", context: "PlannerContext") -> str:
    """会话摘要专用段：位于全局设置段之后（P2-2 段序手术：compaction 激活
    不再击穿稳定前缀；状态上下文已移出 system 段，不再参与段序锚定）。
    压缩摘要置于 system 段而非伪装成 history 首条 user 消息；
    是否注入按 interaction.session_summary.active 每轮判定（由
    history_compact._maybe_compact_history 每请求签发：压缩生效置 True，
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
    # 批4/P0-3b：硬编码文案外置 prompts/shared/session_summary.md
    return render_prompt_section("shared/session_summary.md", "HEADER", text=text)


def _sec_catalog(pb: "PromptBuilder", context: "PlannerContext") -> str:
    """Skill 目录（渐进式披露：名称+摘要常驻，全文按需 read_skill）。
    scope 任务（微调真子对话）不注入：子对话只看对应目标元素，
    目录清单属非目标面（对齐外部标杆，连指针清单也不给）。"""
    if getattr(context, "subagent_depth", 0):
        return ""
    if getattr(context, "adjust_scope", None):
        return ""
    return pb.build_skill_catalog(context)


def _sec_mcp_catalog(pb: "PromptBuilder", context: "PlannerContext") -> str:
    """MCP 外部工具目录（两段式注入段 1）：仅名称+摘要常驻，
    完整 schema 等 mcp_tool_catalog enable 后次回合进 FC tools。"""
    if getattr(context, "subagent_depth", 0):
        return ""
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


# _sec_selected_draft 已随批 B3 移出 system 段（选中草稿指针改经
# build_state_tail_message 注入，P3 状态归位）——builder 与注册表项同批退役。


def _sec_adjust_discipline(pb: "PromptBuilder", context: "PlannerContext") -> str:
    """微调任务纪律段（微调真子对话，批 S2）：仅 scope 任务注入。
    文案外置 prompts/planner/adjust.md（宪法 Rule 6），
    内容恒定不嵌目标编号（保前缀缓存；目标信息由状态裁剪面携带）。"""
    if not getattr(context, "adjust_scope", None):
        return ""
    try:
        return (load_prompt("planner/adjust.md") or "").strip()
    except Exception:
        return ""  # 文案读取失败不阻断对话（纪律降级遥测可见）


def _sec_global_settings(pb: "PromptBuilder", context: "PlannerContext") -> str:
    """全局生成设置（前端「全局设置」页用户配置，热生效）：
    分镜时长上限 + 默认生成渠道，Agent 拆镜/生成必须遵守。
    批 B3 改无条件注入：阶段门控（planning 不注入）会在首组建组后于
    system 中段凭空出现整段，击穿前缀缓存——本段内容极小且极少变化，
    常驻的字节稳定性收益大于 context rot 代价。"""
    if getattr(context, "subagent_depth", 0):
        # 子代理仅故事板/提示词阶段注入「仅分镜最大时长」行（拆镜/写提示词需知时长上限），
        # 其余子代理阶段维持不注入（无消费方，且省稳定前缀字节）
        if getattr(context, "subagent_stage", "") in (
                "storyboard_design", "write_media_prompt"):
            return pb.build_global_settings_note(duration_only=True)
        return ""
    if not context.use_studio_context:
        return ""
    # 会话级压缩 compaction 是创作设定的唯一软性保护，
    # 压缩指令唯一家 = feedback.md::COMPACTION_INSTRUCTION（session_log.compact_pass）；
    # 生成渠道清单注入机制已整体清除——渠道唯一事实源为
    # 顶部「全局设置」（provider_config/provider_prefs），规格文档不再承载渠道
    return pb.build_global_settings_note()


def _sec_selected_skill(pb: "PromptBuilder", context: "PlannerContext") -> str:
    """选中 Skill 轻量状态块放在最后（近生成端）：长 system prompt 中部的指令
    遵循度会衰减，而产出规范（提示词写法/分组规则）恰恰是最需要被严格
    执行的部分。状态上下文已移出 system 段（history 尾部消息注入），
    Skill 块不再有大段状态 JSON 前置淹没问题。"""
    return pb._selected_block


def _sec_subagent(pb: "PromptBuilder", context: "PlannerContext") -> str:
    """子代理委派策略段（A2/A3，对齐 dsh `tool:subagent`）。

    条件注入（空串即跳过，保「prompt 说的 = 工具集真有的」）：仅当
    开关开、顶级轮（非子级白名单模式、subagent_depth=0）时 run_subagent
    对模型可见，才注入委派策略；子级看不到委派工具→不注入（防递归语义）。
    内容恒定（不嵌目标/不随轮变）→ 属稳定前缀，对 KV-cache 友好。
    委派策略与业务无关（通用段），新增子代理场景（如画布）无需改本段。"""
    if not getattr(settings, "subagent_enabled", False):
        return ""
    if getattr(context, "subagent_deny", None) or getattr(context, "subagent_depth", 0):
        return ""
    return subagent_mod.subagent_policy()


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
    # P2-2 段序手术 + 批 B3：选中草稿指针已移出 system（经状态尾部消息注入），
    # order 75 槽位退役——system 静态核心跨请求字节稳定。
    # 状态上下文（原 order 70/80/90 的 state_json/stage_note/
    # storyboard_progress）已移出 system 段：经 build_state_tail_message
    # 以 history 尾部消息（user 通道）每步注入，system 成跨步稳定前缀。
    # 微调任务纪律段（批 S2）：仅 scope 任务注入，内容恒定（跨步稳定前缀）
    PromptSectionSpec("adjust_discipline", 80, _sec_adjust_discipline),
    # 子代理委派策略段（批③A）：仅顶级轮且开关开时注入，内容恒定（稳定前缀）
    PromptSectionSpec("subagent", 90, _sec_subagent),
    PromptSectionSpec("selected_skill", 100, _sec_selected_skill),
))

# 遥测字段别名（注册表段名 → 遥测字段）：None = 不入册（字段格式锁死；
# Q12 裁决 2026-09-01 停 jsonl 落盘后只供内存注册表，原消费方已退役）；
# state_json/selected_skill 的遥测值取原始长度（非段长），在组装处显式赋值
_SECTION_TELEMETRY_ALIAS: Dict[str, Optional[str]] = {
    "protocol": "protocol",
    # 会话摘要段不进遥测分项（字段格式锁死，消费方零改动；
    # 其增长只体现在 total 口径）
    "session_summary": None,
    "catalog": "catalog",
    "mcp_catalog": "mcp_catalog",
    "iron_rules": "iron_rules",
    "selected_draft": None,
    "global_settings": None,
    "selected_skill": None,
    # 微调纪律段只计 total（字段格式锁死，不新增遥测分项）
    "adjust_discipline": None,
    # 子代理委派段只计 total（字段格式锁死，不新增遥测分项）
    "subagent": None,
}
# 批次E：渠道机制退役后的恒 0 兼容字段 channels 已清偿
# （原唯一消费方 check_prompt_budget.py 已随 C1a 裁决退役）。


def _telemetry_section_keys() -> List[str]:
    """遥测字段清单：由段注册表自动生成（序 = 注册表 order），
    别名表决定段名→遥测字段。"""
    keys: List[str] = []
    for spec in PROMPT_SECTIONS:
        key = _SECTION_TELEMETRY_ALIAS.get(spec.name)
        if key is not None and key not in keys:
            keys.append(key)
    return keys
