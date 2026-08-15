"""system prompt 组装（从 planner.py 拆出，批次5 文件瘦身）。

承载：协议/Skill 目录/选中草稿/记忆检索/状态 JSON/选中 Skill 全文（含分阶段聚焦块）的组装。
段落顺序：稳定内容在前，状态 JSON 殿后；选中 Skill 全文放在最末尾（近生成端，
遵循度最高，避免被大段状态 JSON 淹没）。

planner.py 保留 _build_system_prompt 等同名委托，既有调用/测试路径不变。
"""
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional

from loguru import logger

from src.video_agent.config import settings
from src.video_agent.core import prompt_gates
from src.video_agent.memory import MemoryManager
from src.video_agent.utils.prompts import load_prompt

if TYPE_CHECKING:
    from src.video_agent.core.planner import PlannerContext

# 814F7 遥测：system prompt 组装总长预警阈值（字符）——超过即 warning，
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

    def build_system_prompt(self, context: "PlannerContext", fc_mode: bool = False) -> str:
        """构建 system prompt：从 prompts/ 加载 + 注入状态上下文。

        段落顺序为前缀缓存（P1）优化：稳定内容在前，状态 JSON 殿后；
        选中 Skill 全文放在最末尾（近生成端，遵循度最高，避免被大段状态 JSON 淹没）。

        fc_mode（814R1 恢复双协议瘦身）：True 时协议段用 planner/system_fc.md
        （Tool 优先瘦身协议，共有段经 {{include}} 从 shared/ 拼装），
        False 时用 planner/system.md 完整协议（含 studio-actions 动作清单）。
        """
        parts: List[str] = []

        if context.use_studio_context:
            # Rule4: 从 prompts/ 目录加载（稳定前缀第一段）
            protocol = load_prompt("planner/system_fc.md" if fc_mode else "planner/system.md")
            if protocol:
                parts.append(protocol)
            # B1 修正：动作定义唯一源 = text_actions.md。
            # 注入条件以 adapter 真实能力（fc_mode=False）为准——任何不支持
            # Function Calling 的通道都需要文本协议，不依赖 chat_service 的
            # 通道猜测（text_protocol 字段保留为兼容标记，不再作注入开关）。
            if not fc_mode:
                text_protocol = load_prompt("planner/text_actions.md")
                if text_protocol:
                    parts.append(text_protocol)

        # 渐进式披露：不再注入全部 Skill 全文，
        # 改为注入 Skill 目录（名称+摘要），全文由模型按需调 read_skill 加载
        catalog = self.build_skill_catalog(context)
        if catalog:
            parts.append(catalog)

        # 铁律全文注入（宪法 D2）：项目级生产契约的唯一表述源——
        # 铁律文档在每轮对话开始时由系统 ensure，存在即注入，不与 Skill 激活绑定
        # （system.md 不再重复业务规则，铁律不能缺位）
        if self._get_raw_state is not None:
            iron_block = self.build_iron_rules_block()
            if iron_block:
                parts.append(iron_block)

        # 选中 Skill 全文块的硬保障说明：实际拼接移到状态 JSON 之后（靠末尾近生成端，
        # 遵循度更高；避免被大段状态 JSON「淹没在中间」）
        selected_block = ""
        if context.skill_name:
            selected_block = self.build_selected_skill_block(context.skill_name)

        if context.use_studio_context:
            if context.selected_draft_id:
                parts.append(
                    f"\n用户当前选中的草稿：draft_id={context.selected_draft_id}"
                    f"（类型 {context.selected_type or '未知'}）。studio-actions 里的 \"current\" 指向它。"
                )

            # 全局生成设置（前端「全局设置」页用户配置，热生效）：
            # 分镜时长上限 + 默认生成渠道，Agent 拆镜/生成必须遵守
            note = self.build_global_settings_note()
            if note:
                parts.append(note)

            # 混合记忆检索注入（语义 + 关键词 + 时间衰减），按项目隔离；
            # 命中明细写入 context.memory_hits（4.7：随 done payload 下发前端可视化）
            if settings.memory_enabled:
                query = self.last_user_text(context)
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
                        parts.append(memory_ctx)

            # 本项目已配置的生成渠道（仅当 Skill 在 manifest 声明 channels_block：
            # 规格向导「制作渠道」维度的候选来源，S1：不预设所有 Skill 都要收集渠道）
            channels = self.build_generation_channels_block(context.skill_name)
            if channels:
                parts.append(channels)

            # 状态上下文殿后（每轮变化最大）：优先用惰性构建器按轮刷新，
            # 让 LLM 在每一轮都看到上一轮执行后的最新状态（P0 修复）
            if context.state_builder is not None:
                state_json = context.state_builder()
            else:
                state_json = context.state_json
            if state_json:
                parts.append("当前工作台状态 JSON 如下（每轮自动刷新）：\n\n" + state_json)

            # 混合形态工具边界的可见性说明（裁剪生效时告诉模型哪些工具未开放、
            # 应先完成什么，防止幻觉调用；放在状态 JSON 之后，不破坏稳定前缀缓存）；
            # 仅对声明 spec_stage_trim 的 Skill 生效（S1：与 planner 裁剪条件对齐）
            if context.skill_name and self._get_raw_state is not None \
                    and prompt_gates.gate_mode() == "strict":
                try:
                    from src.video_agent.skill_runtime.registry import skill_flow_enabled

                    stage_note = ""
                    if skill_flow_enabled(context.skill_name, "spec_stage_trim"):
                        _, stage_note = prompt_gates.stage_tool_restrictions(self._get_raw_state())
                except Exception:
                    stage_note = ""
                if stage_note:
                    parts.append(stage_note)

        # 选中 Skill 全文放在最后（近生成端）：长 system prompt 中部的指令遵循度
        # 会衰减，而产出规范（提示词写法/分组规则）恰恰是最需要被严格执行的部分
        if selected_block:
            parts.append(selected_block)

        text = "\n\n".join(parts)
        # B6/F36：组装明细入 live 注册表（context-usage 调试端点可读各段字符数）
        try:
            from src.video_agent.core import live_metrics

            live_metrics.record_sections(
                self._get_project_id(),
                {
                    "protocol": len(protocol) if context.use_studio_context else 0,
                    "catalog": len(catalog),
                    "iron_rules": len(parts[2]) if len(parts) > 2 and "执行铁律" in parts[2] else 0,
                    "memory": sum(len(p) for p in parts if "历史记忆" in p),
                    "channels": sum(len(p) for p in parts if "已配置的生成渠道" in p),
                    "state": len(state_json) if context.use_studio_context else 0,
                    "skill": len(selected_block),
                    "total": len(text),
                },
            )
        except Exception:
            pass
        # 814F7 遥测：组装超限预警（各段字符数入账，便于定位臃胀来源）
        if len(text) > _SYSTEM_PROMPT_WARN_CHARS:
            logger.warning(
                f"[PromptBuilder] system prompt 组装超阈值：总长 {len(text)} 字符 > "
                f"{_SYSTEM_PROMPT_WARN_CHARS}（选中Skill块={len(selected_block)}，"
                f"状态JSON≈{len(state_json) if context.use_studio_context else 0}）；"
                "建议清理草稿/缩短 Skill 全文或依赖降级保险丝"
            )
        return text

    def build_global_settings_note(self) -> str:
        """全局生成设置注入块：分镜最大时长 + 默认出图/出视频渠道 + 聊天出图开关。"""
        lines = [
            f"- 分镜最大时长：{settings.max_shot_duration} 秒"
            "（自己拆分镜时单个分镜时长不超该值——超限会被系统校正；duration 字段与提示词内总时长描述与其一致）"
        ]
        if settings.default_image_provider_id:
            model = f" / 模型 {settings.default_image_model}" if settings.default_image_model else ""
            lines.append(
                f"- 默认出图渠道：供应商 {settings.default_image_provider_id}{model}，"
                f"图片分辨率 {settings.default_image_resolution}（草稿自身未配置时按其填写参数）"
            )
        if settings.default_video_provider_id:
            model = f" / 模型 {settings.default_video_model}" if settings.default_video_model else ""
            lines.append(
                f"- 默认出视频渠道：供应商 {settings.default_video_provider_id}{model}，"
                f"视频分辨率 {settings.default_video_resolution}（草稿自身未配置时按其填写参数）"
            )
        if not settings.chat_image_enabled:
            lines.append("- 聊天框出图当前关闭：不要主动触发 generate_image / image_generate")
        return "== 全局生成设置（用户在「全局设置」页配置，必须遵守）==\n" + "\n".join(lines)

    def build_iron_rules_block(self) -> str:
        """当前项目「执行铁律.md」全文注入块（宪法 D2：项目级契约唯一表述源）。

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
        return (
            "== 当前项目《执行铁律》全文（项目级生产契约，必须完整遵守；"
            "优先级：用户最新指令 > 本文档 + 制片规格 > Skill/系统默认）==\n" + content
        )

    def build_generation_channels_block(self, skill_name: str = "") -> str:
        """本项目已配置的出图/出视频渠道清单（规格向导候选来源）。

        仅当 Skill 在 manifest 声明 channels_block 时注入（S1：渠道收集是
        特定 Skill 的规格交互维度，不是平台默认行为）。
        仅列出启用且对应模型列表非空的供应商（mock 除外）；聊天模型不在此列。
        """
        if skill_name:
            try:
                from src.video_agent.skill_runtime.registry import skill_flow_enabled

                if not skill_flow_enabled(skill_name, "channels_block"):
                    return ""
            except Exception:
                return ""
        else:
            return ""
        try:
            from src.video_agent.web.provider_config import load_merged_providers
            providers = load_merged_providers()
        except Exception:
            return ""
        image_lines: List[str] = []
        video_lines: List[str] = []
        for p in providers:
            if not p.get("enabled", True):
                continue
            if (p.get("protocol") or "") == "mock":
                continue
            name = str(p.get("name") or "").strip()
            pid = str(p.get("id") or "").strip()
            if not name or not pid:
                continue
            imgs = [m for m in (p.get("image_models") or []) if m]
            vids = [m for m in (p.get("video_models") or []) if m]
            if imgs:
                image_lines.append(f"- {name}（内部 id: {pid}）：{'、'.join(imgs)}")
            if vids:
                video_lines.append(f"- {name}（内部 id: {pid}）：{'、'.join(vids)}")
        if not image_lines and not video_lines:
            return ""
        parts: List[str] = [
            "== 本项目已配置的生成渠道（规格向导「制作渠道」维度候选来源；系统会校验：未列出的厂商/模型无法使用）=="
        ]
        if image_lines:
            parts.append("【出图（image）】\n" + "\n".join(image_lines))
        if video_lines:
            parts.append("【出视频（video）】\n" + "\n".join(video_lines))
        parts.append(
            "规格文档中必须写明生成渠道（空格分隔、不要用逗号）："
            "「图像生成：<厂商显示名> <模型名>」「视频生成：<厂商显示名> <模型名>」；"
            "系统会据此自动绑定出图/出视频渠道。"
        )
        return "\n\n".join(parts)

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
        except Exception:  # 文档目录读取失败不阻断对话
            pass
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
        """选中 Skill 的注入块（814F3：settings.skill_runtime 开关落地）。

        - auto（默认）：有章节→执行器清单+流程基线；无章节→全文兜底直注；
        - executors：只走执行器形态，无章节时不注入全文（返回空串）；
        - legacy：强制全文直注 + 阶段聚焦（非 FC 通道/无执行器 Skill 的保底形态）。
        无章节全文兜底：非 FC 通道调不了 read_skill，888 事故保障不降级。
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
        流程规范（888 项目事故保障）；外来工具名映射对照表同步追加。
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
        mapping_note = sd.build_foreign_tool_note(content)
        mapping_block = f"\n\n{mapping_note}" if mapping_note else ""
        discipline = load_prompt("planner/skill_discipline.md") or ""
        base = (
            f"== 当前选中 Skill「{display or skill_name}」全文（本 Skill 无注册执行器章节，"
            f"全文直接注入，必须严格遵守其中的流程与规范）==\n"
            "【执行基准声明】本次任务的产出规范（分组/命名/字段结构/提示词写法与顺序等）"
            "一律以本 Skill 为准；Skill 内如提供多种可选写法，选最贴合本次需求的一种并全程保持一致。\n\n"
            f"{content}{mapping_block}\n\n"
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
        # P0-2：流程基线 = 当前 Skill 的 <planner> 章节（切换 Skill 即切换流程）
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
        if flow:
            lines += [
                "",
                "== 当前 Skill 的流程基线（<planner>，必须按此顺序与阶段边界执行）==",
                flow,
            ]
            # 流程章节常引用外来工具名（flova 原生命名如 text_editor/media_generator）：
            # 映射对照随基线一并注入，避免同一 system prompt 内两套工具名打架（S1）
            try:
                foreign_note = self._get_skill_docs().build_foreign_tool_note(flow)
            except Exception:
                foreign_note = ""
            if foreign_note:
                lines += ["", foreign_note]
        lines += [
            "",
            "【执行方式】每个拆解/编写步骤必须真的执行了其中一种（调对应执行器，或直接输出 "
            "studio-actions）后才可声称完成；"
            "未调用任何执行器、也未输出任何 studio-actions 时，系统会判定本步未完成"
            "（声称「已拆解/已完成/已写入故事板」与状态对账不符）；"
            "执行器失败时请重试或停下说明，虚报结果会被状态对账识破。",
            "【阶段边界与确认】各执行器的产出由系统按 Skill 章节校验（结构阶段只建分组、"
            "提示词阶段只写提示词）；阶段暂停点以本 Skill『何时暂停』为准，需暂停时用 "
            "workflow_pause/request_confirmation 邀请确认，用户要求连续执行时照做并在回复末尾附警告。",
            "【通用能力】无专属执行器的章节用 skill_section_run（section=章节标识）执行；"
            "推进顺序先调 skill_pipeline_plan 拿下一可执行批次（同批可并行），不要跳步。"
            "只调用上面列出的执行器与系统既有工具（document_write / read_uploaded_doc / image_generate / generate_video / workflow_pause 等）；"
            "不要调用本清单之外的 Skill 工具名，也不要对当前 Skill 调用 read_skill（执行器内部已注入对应章节）。",
        ]
        return "\n".join(lines)

    # ---------- 分阶段聚焦注入（legacy 全文兜底路径专用） ----------

    _STAGE_LABELS = {
        "planning": "规格规划",
        "storyboard": "故事板结构",
        "prompt_draft": "提示词草案",
        "generation": "素材生成",
        "assembly": "组装导出",
    }
    _FOCUS_MAX_CHARS = 12000

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
            list(raw.get("keyElements") or [])
            + list(raw.get("shots") or [])
            + list(raw.get("audioItems") or [])
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
        """当前阶段聚焦块：把 Skill 中与当前制作阶段对应的章节在 system prompt
        末尾再强调一遍。外来 Skill（如 flova）的各节在原生平台是分别注入对应
        子工具的；legacy 路径只能靠「全文 + 阶段聚焦重复」逼近同等遵循度。
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
        if len(focus) > self._FOCUS_MAX_CHARS:
            focus = focus[:self._FOCUS_MAX_CHARS] + "\n……（阶段章节超长，已截断）"
        label = self._STAGE_LABELS.get(stage, stage)
        return (
            f"\n\n== 【当前阶段重点 · {label}】工作台状态显示任务正处于该阶段，"
            "本阶段的全部产出（字段/结构/提示词写法与顺序）必须逐条遵守以下章节，"
            "它摘自本 Skill 对应段落，与上文全文同等效力、不受其他段落稀释 ==\n" + focus
        )

    @staticmethod
    def last_user_text(context: "PlannerContext") -> str:
        """从历史中取最近一条用户消息作为记忆检索 query"""
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
