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
# （审核）：顶层化（registry 顶层不依赖 core，无环；live_metrics 同包）
from src.video_agent.core import live_metrics
from src.video_agent.skill_runtime.registry import skill_flow_enabled
from src.video_agent.memory import MemoryManager
from src.video_agent.state.models import CAT_AUDIO_ITEMS, CAT_KEY_ELEMENTS, CAT_SHOTS
from src.video_agent.utils.prompts import load_prompt, render_prompt

if TYPE_CHECKING:
    from src.video_agent.core.planner import PlannerContext

# 遥测：system prompt 组装总长预警阈值（字符）——超过即 warning，
# 提醒清理草稿/缩短 Skill 全文（token 治理的组装层可观测性）
_SYSTEM_PROMPT_WARN_CHARS = 60000


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
                    f"（类型 {context.selected_type or '未知'}）。studio-actions 里的 \"current\" 指向它。",
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
                f"\n用户当前在前端选中了「{context.skill_name}」，其已注册执行器清单另行注入下方；"
                "调用执行器时系统自动注入对应章节（全文不注入）。如确需全文可调用 read_skill；"
                "其他 Skill 需要时仍要先 read_skill。"
            )
        return header

    def build_selected_skill_block(self, skill_name: str) -> str:
        """选中 Skill 的注入块（settings.skill_runtime 开关落地）。

        - auto（默认）：有章节→执行器清单+流程基线；无章节→全文兜底直注；
        - executors：只走执行器形态，无章节时不注入全文（返回空串）；
        - legacy：强制全文直注 + 阶段聚焦指针（非 FC 通道/无执行器 Skill 的保底形态；
          聚焦为指针式强调，章节内容随全文仅注入一次，P3-17 单注入收敛）。
        无章节全文兜底：非 FC 通道调不了 read_skill，888 保障不降级。
        """
        mode = str(getattr(settings, "skill_runtime", "auto") or "auto").strip().lower()
        if mode == "legacy":
            return self._build_unsectioned_skill_block(skill_name)
        runtime_block = self.build_executor_runtime_block(skill_name)
        if runtime_block:
            return runtime_block
        if mode == "executors":
            logger.info(f"[Planner] Skill「{skill_name}」无可执行章节（executors 模式不注入全文）")
            return ""
        return self._build_unsectioned_skill_block(skill_name)

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

    def build_executor_runtime_block(self, skill_name: str) -> str:
        """executors 模式：注册执行器清单（不再注入全文，章节在执行器内注入）。"""
        try:
            from src.video_agent.skill_runtime.registry import resolve_entry

            entry = resolve_entry(skill_name)
        except Exception:
            entry = None
        if entry is None:
            return ""
        tools = entry.available_tools
        if not tools:
            return ""
        # 2：流程基线 = 当前 Skill 的 <planner> 章节（切换 Skill 即切换流程）
        flow = ""
        try:
            from src.video_agent.skill_runtime.guard import skill_planner_flow

            flow = skill_planner_flow(skill_name)
        except Exception:
            flow = ""
        lines = [
            f"== 当前选中 Skill「{entry.name}」已注册独立执行器（上传即注册）==",
            "本 Skill 全文不在此处注入；执行器已注册，系统会按对应章节自动校验你的产出：",
        ]
        lines += [f"- {t}" for t in tools]
        # P3-15 自定义章节通道接线（非 legacy 全文直注段）：显式下发
        # custom_sections 声明的章节标识（skill_section_run 的 section 参数
        # 取值），模型不必从散文里猜标识；未声明时零增量。
        _custom = getattr(entry, "custom_sections", None) or {}
        if _custom:
            lines += [
                "",
                "== 自定义章节（sidecar 声明；用 skill_section_run 执行，"
                "section 参数取下列标识）==",
            ]
            lines += [f"- {k}" for k in _custom]
        if flow:
            lines += [
                "",
                "== 当前 Skill 的流程基线（<planner>，必须按此顺序与阶段边界执行）==",
                flow,
            ]
            # 外来工具名映射注记已随 删除（导入期转换归专用 Skill 系统）
        # 批 12：sidecar 流程清单（机械顺序清单，与 stage_precondition 闸同源「法条」；
        # Rule2 v6：确定性阶段由 runtime 直跑，模型循环只做节点内创作，越阶由闸否决）
        try:
            from src.video_agent.skill_runtime.registry import skill_manifest_of

            _steps = (((skill_manifest_of(skill_name) or {}).get("flow") or {}).get("steps")) or {}
            if _steps:
                _ordered = [
                    f"{k}. {v}" for k, v in sorted(
                        _steps.items(), key=lambda kv: int(kv[0]))
                ]
                lines += [
                    "",
                    "== 流程清单（sidecar 声明；跨阶段调用会被阶段前置闸拒收）==",
                    *_ordered,
                    # 批3 暂停纪律单家：暂停确认的邀请表述归 skill_discipline.md，
                    # 此处不再复述（P1 规则单家）
                ]
        except Exception:
            # 流程清单装配失败不阻断对话（降级遥测可见，批5）
            live_metrics.record_degradation("prompt_builder.flow_steps")
        # 执行方式/阶段边界/通用能力 prose 外置 prompts/planner/executor_runtime.md
        # （批3 指令收敛，Rule6；暂停纪律表述以 skill_discipline.md 为单家）
        _runtime_prose = load_prompt("planner/executor_runtime.md").strip()
        if _runtime_prose:
            lines += ["", _runtime_prose]
        return "\n".join(lines)

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
