"""system prompt 组装（从 planner.py 拆出， 文件瘦身）。

承载：协议/Skill 目录/选中草稿/记忆检索/状态 JSON/选中 Skill 全文（含分阶段聚焦块）的组装。
段落顺序：稳定内容在前，状态 JSON 殿后；选中 Skill 全文放在最末尾（近生成端，
遵循度最高，避免被大段状态 JSON 淹没）。

planner.py 保留 _build_system_prompt 等同名委托，既有调用/测试路径不变。
"""
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Tuple

from loguru import logger

from src.video_agent.config import settings
from src.video_agent.core import prompt_gates
# gates_inputs 必须在 prompt_gates 之后导入（gates_script↔prompt_gates 尾块
# re-export 对首入方向敏感；任务#35 B2 原料判定家族）
from src.video_agent.core import gates_inputs
# （审核）：顶层化（registry 顶层不依赖 core，无环；live_metrics 同包）
from src.video_agent.core import live_metrics
from src.video_agent.skill_runtime import guard as skill_guard
# v3 声明读取经模块属性访问（任务#35 B2：测试 patch registry.<fn> 即生效）
from src.video_agent.skill_runtime import registry as skill_registry
from src.video_agent.skill_runtime.registry import skill_flow_enabled
from src.video_agent.memory import MemoryManager
from src.video_agent.state.models import CAT_AUDIO_ITEMS, CAT_KEY_ELEMENTS, CAT_SHOTS
# MCP 两段式注入段 1（任务#37 B4）：外部工具目录文本块（名称+摘要，
# schema 不进 FC tools；完整 schema 由 enable 后按需注入）
from src.video_agent.tools.mcp import catalog as mcp_catalog
from src.video_agent.utils.prompts import load_prompt, render_prompt

if TYPE_CHECKING:
    from src.video_agent.core.planner import PlannerContext

# 遥测：system prompt 组装总长预警阈值（字符）——超过即 warning，
# 提醒清理草稿/缩短 Skill 全文（token 治理的组装层可观测性）
_SYSTEM_PROMPT_WARN_CHARS = 60000

# 通用主路径分级注入阈值（任务#36 B5）：全文超过该字符数时不再直注全文，
# 改为「planner 章节全文 + 章节目录（标题+字符区间）」，其余章节经
# read_skill（section/start）按需续读；≤ 阈值全文直注。
# 与 read_skill 短路判定（fc_tool_runner._skill_full_text_injected）同口径。
GENERIC_FULL_INJECT_LIMIT = 20000

# v3 元数据头展示标签（任务#35 B2/B3：kind 目录口径 + 暂停 trigger 文案）
_KIND_LABELS = {
    "pipeline": "流程型（固定流水线）",
    "style": "风格型（美学指导）",
    "reference": "参考型（知识素材）",
}
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

    def build_system_prompt(self, context: "PlannerContext") -> str:
        """构建 system prompt：从 prompts/ 加载 + 注入状态上下文。

        段落顺序为前缀缓存优化：稳定内容在前，状态 JSON 殿后；
        选中 Skill 全文放在最末尾（近生成端，遵循度最高，避免被大段状态 JSON 淹没）。

        协议段唯一 = planner/system_fc.md（Tool 优先瘦身协议，共有段经
        {{include}} 从 shared/ 拼装）；文本协议 system.md 已退役删除
        （P2e 单轨收敛，ADR-0001），原 fc_mode 双分支随之移除。
        """
        parts: List[Tuple[str, str]] = []

        if context.use_studio_context:
            # Rule4: 从 prompts/ 目录加载（稳定前缀第一段）；
            # max_steps 模板化注入（消协议模板与 config 双写漂移）
            protocol = render_prompt(
                "planner/system_fc.md",
                max_steps=settings.max_steps,
            )
            if protocol:
                parts.append(("protocol", protocol))
            # 协议单轨（ADR-0001）：文本协议 system.md 已随 P2e 退役删除，
            # 动作通道唯一 = FC 工具（mock 通道除外，其输出为演示用固定文本）。

        # 渐进式披露：不再注入全部 Skill 全文，
        # 改为注入 Skill 目录（名称+摘要），全文由模型按需调 read_skill 加载
        catalog = self.build_skill_catalog(context)
        if catalog:
            parts.append(("catalog", catalog))

        # MCP 外部工具目录（两段式注入段 1）：仅名称+摘要常驻，
        # 完整 schema 等 mcp_tool_catalog enable 后次回合进 FC tools
        try:
            mcp_block = mcp_catalog.catalog_block(self._get_raw_state()
                                                  if self._get_raw_state else None)
        except Exception:
            mcp_block = ""
        if mcp_block:
            parts.append(("mcp_catalog", mcp_block))

        # 铁律全文注入（宪法）：项目级生产契约的唯一表述源——
        # 铁律文档在每轮对话开始时由系统 ensure，存在即注入，不与 Skill 激活绑定
        # （协议模板不重复业务规则，铁律不能缺位）
        if self._get_raw_state is not None:
            iron_block = self.build_iron_rules_block()
            if iron_block:
                parts.append(("iron_rules", iron_block))

        # 选中 Skill 全文块的硬保障说明：实际拼接移到状态 JSON 之后（靠末尾近生成端，
        # 遵循度更高；避免被大段状态 JSON「淹没在中间」）
        selected_block = ""
        if context.skill_name:
            selected_block = self.build_selected_skill_block(context.skill_name)

        if context.use_studio_context:
            if context.selected_draft_id:
                parts.append((
                    "selected_draft",
                    f"\n用户当前选中的草稿：draft_id={context.selected_draft_id}"
                    f"（类型 {context.selected_type or '未知'}）。",
                ))

            # 全局生成设置（前端「全局设置」页用户配置，热生效）：
            # 分镜时长上限 + 默认生成渠道，Agent 拆镜/生成必须遵守；
            # 阶段门控——规格规划阶段无消费方，不注入（context rot 治理）
            if self.stage_allows_global_settings():
                note = self.build_global_settings_note()
                if note:
                    parts.append(("global_settings", note))

            # 混合记忆检索注入（语义 + 关键词 + 时间衰减），按项目隔离；
            # 命中明细写入 context.memory_hits（4.7：随 done payload 下发前端可视化）
            if settings.memory_enabled:
                query = self.memory_recall_query(context)
                if query:
                    project_id = self._get_project_id()
                    mm = MemoryManager.get_instance()
                    if hasattr(mm, "build_context_with_hits"):
                        memory_ctx, hits = mm.build_context_with_hits(query, project_id=project_id)
                        try:
                            context.memory_hits = hits
                        except Exception as e:
                            logger.debug(f"[Planner] memory_hits 写入跳过: {e}")
                    else:
                        memory_ctx = mm.build_context(query, project_id=project_id)
                    if memory_ctx:
                        parts.append(("memory", memory_ctx))

            # 生成渠道清单注入机制已整体清除——渠道唯一事实源为
            # 顶部「全局设置」（provider_config/provider_prefs），规格文档不再承载渠道

            # 状态上下文殿后（每轮变化最大）：优先用惰性构建器按轮刷新，
            # 让 LLM 在每一轮都看到上一轮执行后的最新状态（修复）
            if context.state_builder is not None:
                state_json = context.state_builder()
            else:
                state_json = context.state_json
            if state_json:
                parts.append(("state_json", "当前工作台状态 JSON 如下（每轮自动刷新）：\n\n" + state_json))

            # 混合形态工具边界的可见性说明（裁剪生效时告诉模型哪些工具未开放、
            # 应先完成什么，防止幻觉调用；放在状态 JSON 之后，不破坏稳定前缀缓存）；
            # 仅对声明 spec_stage_trim 的 Skill 生效（与 planner 裁剪条件对齐）
            if context.skill_name and self._get_raw_state is not None \
                    and prompt_gates.gate_mode() == "strict":
                try:
                    stage_note = ""
                    if skill_flow_enabled(context.skill_name, "spec_stage_trim"):
                        _, stage_note = prompt_gates.stage_tool_restrictions(self._get_raw_state())
                except Exception:
                    stage_note = ""
                if stage_note:
                    parts.append(("stage_note", stage_note))

            # 故事板客观进度描述（只报状态，暂停点归 Skill）
            if context.skill_name:
                progress_note = self.build_storyboard_progress_note()
                if progress_note:
                    parts.append(("storyboard_progress", progress_note))

        # 选中 Skill 全文放在最后（近生成端）：长 system prompt 中部的指令遵循度
        # 会衰减，而产出规范（提示词写法/分组规则）恰恰是最需要被严格执行的部分
        if selected_block:
            parts.append(("selected_skill", selected_block))

        text = "\n\n".join(seg for _, seg in parts)
        # 组装明细入 live 注册表（context-usage 调试端点可读各段字符数）；
        # 具名段组装后遥测直接读段名（消位置索引猜测，段序变动不失真）
        try:
            sec_lens: Dict[str, int] = {}
            for name, seg in parts:
                sec_lens[name] = sec_lens.get(name, 0) + len(seg)
            live_metrics.record_sections(
                self._get_project_id(),
                {
                    "protocol": sec_lens.get("protocol", 0) if context.use_studio_context else 0,
                    "catalog": sec_lens.get("catalog", 0),
                    "mcp_catalog": sec_lens.get("mcp_catalog", 0),
                    "iron_rules": sec_lens.get("iron_rules", 0),
                    "memory": sec_lens.get("memory", 0),
                    "channels": sec_lens.get("channels", 0),
                    "state": len(state_json) if context.use_studio_context else 0,
                    "skill": len(selected_block),
                    "total": len(text),
                },
            )
        except Exception as _e:
            logger.debug("[prompt_builder] 忽略异常: {}", _e)
        # 遥测：组装超限预警（各段字符数入账，便于定位臃胀来源）
        if len(text) > _SYSTEM_PROMPT_WARN_CHARS:
            logger.warning(
                f"[PromptBuilder] system prompt 组装超阈值：总长 {len(text)} 字符 > "
                f"{_SYSTEM_PROMPT_WARN_CHARS}（选中Skill块={len(selected_block)}，"
                f"状态JSON≈{len(state_json) if context.use_studio_context else 0}）；"
                "建议清理草稿/缩短 Skill 全文或依赖降级保险丝"
            )
        return text

    def build_storyboard_progress_note(self) -> str:
        """故事板客观进度描述（纯数据）——只报三类有无，
        暂停点指向已注入的 Skill 流程基线，平台不给排序意见；
        顺带同批暂停建议（建议非强制，省往返）。
        文案外置 prompts/shared/storyboard_progress.md（批3 指令收敛，Rule6）。"""
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
        """ ：全局设置注入的阶段门控——规格规划阶段（无任何分组）
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
        文案外置 prompts/shared/global_settings.md（批3 指令收敛，Rule6），
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
        """当前项目「执行铁律.md」全文注入块（宪法 ：项目级契约唯一表述源）。

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
        # 头部文案外置 prompts/shared/iron_rules_header.md（批3 指令收敛，Rule6）
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
        except Exception:  # 文档目录读取失败不阻断对话（降级遥测可见，批5）
            live_metrics.record_degradation("prompt_builder.catalog")
        if not lines:
            return ""
        header = (
            "== Skill 目录（渐进式披露：上下文只有各 Skill 的名称与摘要。"
            "未选中的 Skill 执行任务前先调用 read_skill（name=Skill 名称）加载其完整流程，"
            "不要凭目录摘要自行推测流程细节）==\n" + "\n".join(lines)
        )
        if context.skill_name:
            header += (
                f"\n用户当前在前端选中了「{context.skill_name}」，其完整流程已注入下方（超长时"
                "按分级注入规则给章节目录，按需 read_skill 续读）；"
                "其他 Skill 需要时仍要先 read_skill。"
            )
        return header

    def build_selected_skill_block(self, skill_name: str) -> str:
        """选中 Skill 的注入块（任务#36 B5：通用主路径切换）。

        settings.skill_runtime（SKILL_RUNTIME_MODE）降级为 deprecated 全局回退闸：
        - auto（默认）：通用主路径 build_generic_skill_block——元数据头 +
          全文分级注入（≤20000 直注；超长给 planner 章节全文 + 章节目录）；
        - executors：执行器形态已一步退役（用户裁决不设观察期），按通用主路径
          执行并记弃用告警；
        - legacy：强制旧全文直注行为，保留作事故回退。
        """
        mode = str(getattr(settings, "skill_runtime", "auto") or "auto").strip().lower()
        if mode == "legacy":
            block = self._build_unsectioned_skill_block(skill_name)
        else:
            if mode == "executors":
                logger.warning(
                    "[Planner] skill_runtime=executors 已弃用（执行器一步退役，任务#36 B5），"
                    "按通用主路径执行；请移除 SKILL_RUNTIME_MODE/SKILL_RUNTIME 环境变量"
                )
            block = self.build_generic_skill_block(skill_name)
        # v3 元数据头（任务#35 B2/B3）：拼在 Skill 块正文之前；未声明任何
        # v3 键时返回空串（未迁移 v2 manifest 零增量）；选中块本身仍在
        # system prompt 最末段（近生成端），不破坏稳定段在前的前缀缓存排序
        header = self.build_skill_metadata_header(skill_name)
        if header and block:
            return header + "\n\n" + block
        return block

    def build_skill_metadata_header(self, skill_name: str) -> str:
        """sidecar v3 元数据头：kind / requires_inputs 未满足项 / language /
        暂停点清单，注入在选中 Skill 块全文之前。

        未声明任何 v3 键（未迁移 v2 manifest）返回空串，行为零变化；
        原料未就绪探测需 raw state，缺省（None）时只省掉该段。
        """
        lines: List[str] = []
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
            "== Skill 元数据（sidecar 声明，执行下方 Skill 内容前先读）==\n"
            + "\n".join(lines)
        )

    def _build_unsectioned_skill_block(self, skill_name: str) -> str:
        """无可识别章节的 Skill：全文直注兜底。

        非 FC 通道（如 agy CLI）调不了 read_skill，若只给目录，模型等于看不到
        流程规范（888 项目保障）；外来工具名映射对照表同步追加。
        """
        sd = self._get_skill_docs()
        try:
            display, content = sd.resolve_skill_content(skill_name)
        except Exception:  # 解析失败不阻断对话
            logger.warning(f"[Planner] 选中 Skill「{skill_name}」解析失败，降级为仅目录")
            return ""
        content = (content or "").strip()
        if not content:
            return ""
        if len(content) > settings.max_doc_chars:
            content = content[:settings.max_doc_chars] + "\n……（Skill 全文超长，已截断）"
        # 外来工具名映射注记已随 删除（导入期转换归专用 Skill 系统）
        discipline = load_prompt("planner/skill_discipline.md") or ""
        base = (
            f"== 当前选中 Skill「{display or skill_name}」全文（本 Skill 无注册执行器章节，"
            f"全文直接注入，必须严格遵守其中的流程与规范）==\n"
            "【执行基准声明】本次任务的产出规范（分组/命名/字段结构/提示词写法与顺序等）"
            "一律以本 Skill 为准；Skill 内如提供多种可选写法，选最贴合本次需求的一种并全程保持一致。\n\n"
            f"{content}\n\n"
            f"{discipline}"
        )
        # 当前阶段聚焦块追加在最末尾（离生成端最近，遵循度最高）
        return base + self.build_stage_focus_block(content)

    def build_generic_skill_block(self, skill_name: str) -> str:
        """通用主路径注入块（任务#36 B5）：全文直注或分级注入。

        - ≤ GENERIC_FULL_INJECT_LIMIT：全文直注（超 max_doc_chars 硬截断）；
        - 超长：planner 章节全文 + 章节目录（标题+字符区间）+ 续读指令，
          其余章节由模型执行对应环节前调 read_skill（section/start）续读。
        执行器形态已一步退役，本块为选中 Skill 的唯一注入形态（legacy 除外）。
        """
        sd = self._get_skill_docs()
        try:
            display, content = sd.resolve_skill_content(skill_name)
        except Exception:  # 解析失败不阻断对话
            logger.warning(f"[Planner] 选中 Skill「{skill_name}」解析失败，降级为仅目录")
            return ""
        content = (content or "").strip()
        if not content:
            return ""
        discipline = load_prompt("planner/skill_discipline.md") or ""
        if len(content) <= GENERIC_FULL_INJECT_LIMIT:
            # 全文直注（与旧兜底同口径：max_doc_chars 硬截断防撑爆上下文）
            body = content
            if len(body) > settings.max_doc_chars:
                body = body[:settings.max_doc_chars] + "\n……（Skill 全文超长，已截断）"
            base = (
                f"== 当前选中 Skill「{display or skill_name}」全文（必须严格遵守其中的"
                "流程与规范）==\n"
                "【执行基准声明】本次任务的产出规范（分组/命名/字段结构/提示词写法与顺序等）"
                "一律以本 Skill 为准；Skill 内如提供多种可选写法，选最贴合本次需求的一种"
                "并全程保持一致。\n\n"
                f"{body}\n\n"
                f"{discipline}"
            )
            return base + self._build_generic_flow_steps(skill_name)
        return self._build_tiered_skill_block(
            sd, skill_name, display or skill_name, content, discipline)

    def _build_tiered_skill_block(
        self, sd: Any, skill_name: str, display: str, content: str, discipline: str,
    ) -> str:
        """分级注入块（全文 > GENERIC_FULL_INJECT_LIMIT）：planner 章节全文 +
        章节目录（标题+字符区间）+ 续读指令。章节区间与 read_skill 续读同口径
        （skill_docs.list_skill_sections）。planner 章节缺失时回落全文首段截断。"""
        try:
            sections = sd.split_skill_sections(content) or {}
        except Exception:
            sections = {}
        planner = (sections.get("planning") or "").strip()
        try:
            toc = sd.list_skill_sections(content) or []
        except Exception:
            toc = []
        lines: List[str] = [
            f"== 当前选中 Skill「{display}」（全文 {len(content)} 字，超过分级注入阈值"
            f" {GENERIC_FULL_INJECT_LIMIT}，按分级规则注入）==",
            "【执行基准声明】本次任务的产出规范（分组/命名/字段结构/提示词写法与顺序等）"
            "一律以本 Skill 为准；Skill 内如提供多种可选写法，选最贴合本次需求的一种"
            "并全程保持一致。",
        ]
        if planner:
            lines += [
                "",
                "== 流程规划章节（全文注入，必须按此顺序与阶段边界执行）==",
                planner,
            ]
        else:
            # 无 planner 章节：回落全文首段截断，保底不丢流程入口
            head = content[:GENERIC_FULL_INJECT_LIMIT]
            lines += [
                "",
                "== Skill 正文首段（未识别到流程规划章节，先注入前 "
                f"{GENERIC_FULL_INJECT_LIMIT} 字）==",
                head,
            ]
        if toc:
            lines += [
                "",
                "== 章节目录（标题与字符区间；执行对应环节前先调用 "
                "read_skill（name=本 Skill，section=章节标题，或 start=区间起点）续读该章节"
                "全文，不要凭目录猜测章节内容）==",
            ]
            lines += [f"- {t['title']}（第 {t['start']}~{t['end']} 字）" for t in toc]
        lines += [
            "",
            "执行纪律（与全文同等效力）：",
            discipline.strip() if discipline else "- 严格按流程顺序推进，不跳阶段。",
        ]
        return "\n".join(lines) + self._build_generic_flow_steps(skill_name)

    def _build_generic_flow_steps(self, skill_name: str) -> str:
        """sidecar 流程清单段（机械顺序清单，与 stage_precondition 闸同源「法条」；
        ADR-0004：模型永远唯一行动主体，runtime 只做账本与裁判不发起行动，
        本清单供阶段前置闸在工具调用点否决越阶（顺序保障 = 刹车不是方向盘））。
        原执行器运行时块的同源注入段，随通用主路径保留。"""
        try:
            from src.video_agent.skill_runtime.registry import skill_manifest_of

            _steps = (((skill_manifest_of(skill_name) or {}).get("flow") or {}).get("steps")) or {}
            if not _steps:
                return ""
            _ordered = [
                f"{k}. {v}" for k, v in sorted(
                    _steps.items(), key=lambda kv: int(kv[0]))
            ]
        except Exception:
            # 流程清单装配失败不阻断对话（降级遥测可见，批5）
            live_metrics.record_degradation("prompt_builder.flow_steps")
            return ""
        return (
            "\n\n== 流程清单（sidecar 声明；跨阶段调用会被阶段前置闸拒收）==\n"
            + "\n".join(_ordered)
        )

    # ---------- 分阶段聚焦注入（legacy 全文兜底路径专用） ----------

    _STAGE_LABELS = {
        "planning": "规格规划",
        "storyboard": "故事板结构",
        "prompt_draft": "提示词草案",
        "generation": "素材生成",
        "assembly": "组装导出",
    }
    # 注：_FOCUS_MAX_CHARS（聚焦摘录截断上限）随 P3-17 单注入收敛删除——
    # 聚焦块不再重复章节正文，截断需求随之消失（全文截断仍由 max_doc_chars 管）

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

    def build_stage_focus_block(self, content: str) -> str:
        """当前阶段聚焦指针块（P3-17：「全文 + 阶段聚焦重复注入」合并为单注入）。

        旧实现把当前阶段对应章节的内容在全文之后再摘录重注一遍（同章节注两遍，
        纯 token 浪费）；现实现保留「末尾近生成端强调」的意图，但只注入指针
        （指向全文中对应章节），章节正文在组装结果中仅出现一次。
        无法识别阶段或章节时返回空串（行为不变）。"""
        stage = self.detect_stage()
        if not stage:
            return ""
        split_sections = getattr(self._get_skill_docs(), "split_skill_sections", None)
        if split_sections is None:
            return ""
        try:
            sections = split_sections(content) or {}
        except Exception:
            return ""
        focus = (sections.get(stage) or "").strip()
        if not focus:
            return ""
        label = self._STAGE_LABELS.get(stage, stage)
        return (
            f"\n\n== 【当前阶段重点 · {label}】工作台状态显示任务正处于该阶段，"
            "本阶段的全部产出（字段/结构/提示词写法与顺序）必须逐条遵守上文 Skill 全文中"
            "与本阶段对应的章节——该章节已随全文注入且仅此一份，此处不再摘录重复，"
            "与全文同等效力、不受其他段落稀释 ==\n"
        )

    @staticmethod
    def last_user_text(context: "PlannerContext") -> str:
        """从历史中取最近一条用户消息作为记忆检索 query 基底"""
        for msg in reversed(context.history or []):
            if msg.get("role") == "user":
                content = msg.get("content", "")
                if isinstance(content, str):
                    return content
                if isinstance(content, list):
                    return " ".join(
                        str(p.get("text", "")) for p in content
                        if isinstance(p, dict) and p.get("type") == "text"
                    )
        return ""

    def memory_recall_query(self, context: "PlannerContext") -> str:
        """记忆召回 query 扩展：用户消息 + 当前阶段标签 + 激活 Skill 名拼接。

        单靠最近一条用户消息常缺主题词（「继续」「改一下」类短消息
        几乎检索不到任何记忆）；阶段标签与 Skill 名把检索维度拉回
        当前制作上下文。阶段不可探测时只省掉该段，不影响主 query。"""
        base = self.last_user_text(context)
        parts: List[str] = [base] if base else []
        try:
            label = self._STAGE_LABELS.get(self.detect_stage(), "")
            if label:
                parts.append(label)
        except Exception:
            pass
        skill = str(getattr(context, "skill_name", "") or "").strip()
        if skill:
            parts.append(skill)
        return " ".join(parts)
