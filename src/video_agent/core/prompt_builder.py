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

# 制作阶段 → 中文标签（聚焦注入块的标题用）
_STAGE_LABELS = {
    "planning": "规格规划",
    "storyboard": "故事板结构",
    "prompt_draft": "提示词草案",
    "generation": "素材生成",
    "assembly": "组装导出",
}
# 聚焦注入章节的体积保险丝（超长章节只截前段，避免 system 臃肿）
_FOCUS_MAX_CHARS = 12000


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

        段落顺序为前缀缓存（P1）优化：稳定内容（协议/Skill 目录/选中 Skill/
        草稿说明/记忆）在前，逐轮变化的工作台状态 JSON 殿后，
        使多步循环内各轮的前缀逐字节稳定，命中供应商 prompt 前缀缓存。
        """
        parts: List[str] = []

        if context.use_studio_context:
            # Rule4: 从 prompts/ 目录加载（稳定前缀第一段）
            protocol = load_prompt("planner/system.md")
            if protocol:
                parts.append(protocol)

        # 渐进式披露：不再注入全部 Skill 全文，
        # 改为注入 Skill 目录（名称+摘要），全文由模型按需调 read_skill 加载
        catalog = self.build_skill_catalog(context)
        if catalog:
            parts.append(catalog)

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

            # 混合记忆检索注入（语义 + 关键词 + 时间衰减），按项目隔离
            if settings.memory_enabled:
                query = self.last_user_text(context)
                if query:
                    project_id = self._get_project_id()
                    memory_ctx = MemoryManager.get_instance().build_context(query, project_id=project_id)
                    if memory_ctx:
                        parts.append(memory_ctx)

            # 状态上下文殿后（每轮变化最大）：优先用惰性构建器按轮刷新，
            # 让 LLM 在每一轮都看到上一轮执行后的最新状态（P0 修复）
            if context.state_builder is not None:
                state_json = context.state_builder()
            else:
                state_json = context.state_json
            if state_json:
                parts.append("当前工作台状态 JSON 如下（每轮自动刷新）：\n\n" + state_json)

            # 混合形态工具边界的可见性说明（裁剪生效时告诉模型哪些工具未开放、
            # 应先完成什么，防止幻觉调用；放在状态 JSON 之后，不破坏稳定前缀缓存）
            if context.skill_name and self._get_raw_state is not None \
                    and prompt_gates.gate_mode() == "strict":
                try:
                    _, stage_note = prompt_gates.stage_tool_restrictions(self._get_raw_state())
                except Exception:
                    stage_note = ""
                if stage_note:
                    parts.append(stage_note)

        # 选中 Skill 全文放在最后（近生成端）：长 system prompt 中部的指令遵循度
        # 会衰减，而产出规范（提示词写法/分组规则）恰恰是最需要被严格执行的部分
        if selected_block:
            parts.append(selected_block)

        return "\n\n".join(parts)

    def build_global_settings_note(self) -> str:
        """全局生成设置注入块：分镜最大时长 + 默认出图/出视频渠道 + 聊天出图开关。"""
        lines = [
            f"- 分镜最大时长：{settings.max_shot_duration} 秒"
            "（自己拆分镜时单个分镜时长不得超过该值，duration 字段与提示词内总时长描述与其一致）"
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
            "执行任务前必须先调用 read_skill（name=Skill 名称）加载对应 Skill 的完整流程，"
            "不要凭目录摘要自行推测流程细节）==\n" + "\n".join(lines)
        )
        if context.skill_name:
            header += (
                f"\n用户当前在前端选中了「{context.skill_name}」，其全文已另行注入下方"
                f"（无需再对它调 read_skill）；其他 Skill 需要时仍要先 read_skill。"
            )
        return header

    def build_selected_skill_block(self, skill_name: str) -> str:
        """选中 Skill 的全文注入块（硬保障，不依赖模型自觉调 read_skill）"""
        sd = self._get_skill_docs()
        build_foreign_tool_note = sd.build_foreign_tool_note
        resolve_skill_content = sd.resolve_skill_content
        try:
            display, content = resolve_skill_content(skill_name)
        except Exception:  # 解析失败不阻断对话
            logger.warning(f"[Planner] 选中 Skill「{skill_name}」解析失败，降级为仅目录")
            return ""
        content = (content or "").strip()
        if not content:
            return ""
        if len(content) > settings.max_doc_chars:
            content = content[:settings.max_doc_chars] + "\n……（Skill 全文超长，已截断）"
        # 外来工作流直译的 Skill 常引用本系统不存在的工具名，
        # 检测到已知外来词汇时自动追加对照表，把映射从模型猜测变成显式指令
        mapping_note = build_foreign_tool_note(content)
        mapping_block = f"\n\n{mapping_note}" if mapping_note else ""
        base = (
            f"== 当前选中 Skill「{display or skill_name}」全文（已直接注入，必须严格遵守"
            f"其中的流程与规范；不要再对它调用 read_skill）==\n"
            "【执行基准声明】本次任务的产出规范（分组/命名/字段结构/提示词写法与顺序等）"
            "一律以本 Skill 为准；Skill 内如提供多种可选写法，选最贴合本次需求的一种并全程保持一致。\n\n"
            f"{content}{mapping_block}\n\n"
            "【Skill 流程纪律 — 最高优先级】\n"
            "1. Skill 阶段必须逐段执行，严禁把多阶段（规格/结构/草案/生成）合并一口气做完"
            "（各边界系统会硬拦截跨阶段写入与生成）；首次拆分故事板只创建 keyElement 分组"
            "并暂停等用户确认元素拆分，用户确认后再创建分镜/音频分组。\n"
            "2. Skill 里每一个「确认/暂停/审阅」点，都必须用 request_confirmation（文本模式）或 "
            "workflow_pause（Tool 模式）真正停下等待用户；只在正文里写「请确认」而不发暂停信号是无效的。"
            "每个步骤完成后的暂停都必须携带引导选项（options，2 个左右：确认推进/调整），"
            "让用户一键选择下一步，而不是只留一句文字等用户手打回复。\n"
            "3. 要求分批次确认的（如先元素图草案、确认后再镜头视频草案），必须真的分批："
            "本批完成→暂停等确认，下一批等用户确认后的新消息再做。\n"
            "4. 本轮若已到达某个暂停点：立即发出暂停信号并结束本轮，不要顺手把下一阶段也做完。\n"
            "5. 交付自检：每写完一批草稿提示词，逐条对照本 Skill 的「提示词写法」章节检查结构/顺序/要素"
            "是否齐备，发现不符先改正再交付。\n"
            "6. 规格收集交互（一次性分组收集）：写入规格文档前，必须用一次 request_confirmation/"
            "workflow_pause 把所有维度候选项一并发出——每个 option 带 group 字段标注维度标题"
            "（如 group=时长/画幅/视觉风格/声音与语言），每个维度 2-4 个带说明的候选项；"
            "前端会渲染为分页向导卡片（逐页选择、末页发送），用户选完一次性发回全部选择。"
            "严禁把各维度拆成多轮逐一询问（每轮推理太慢），更严禁不经询问自行拍板。"
            "全部收齐后才写入规格文档；"
            "Final_Video_Spec.md 正文必须是精简清单：视频标题、视频类型、目标受众与播放场景、"
            "输出语言、总时长、画幅比例、叙事驱动、视觉风格、声音风格、制作偏好，"
            "每项一行、一句话，严禁写成长篇章节或展开论述。\n"
            "7. 元素图像就绪闸门：关键元素提示词被确认后，必须暂停并引导用户选择「生成元素概念图」或"
            "「上传已有元素素材」；只有确认元素图像已就绪（草稿卡已有图片：生成或上传绑定均可）之后，"
            "才开始编制分镜提示词；元素图像空缺时严禁先写分镜提示词，后续镜头要参考元素图像。\n"
            "8. 提示词产出形态：分镜视频提示词用中文叙事式多节拍写法（如「镜头一：中景，……切至镜头二：……」），"
            "节拍内部按 摄像机→主体→空间→音频 顺序展开；严禁写成「Camera:/Subject:/Space:/Audio:」式英文标签分栏。"
            "分镜中引用的关键元素用 @Element_标题 写入（系统生成时会自动把对应元素概念图作为参考图注入）；"
            "关键元素提示词按 Skill 的 key_element 结构用中文叙事描写（主体身份/特征细节/氛围基调），禁止模板套话。\n"
            "9. 引导选项文案必须与用户确认后的实际下一步动作一致，严禁超前承诺："
            "关键元素拆分确认后的下一步是「为关键元素编写生图提示词草案」，不是「生成概念图」"
            "（概念图要在元素提示词被确认之后才生成）；同理，提示词草案确认后的下一步才是触发生成。"
            "选项 label 直接写明即将执行的动作，避免用户选择后看到的实际操作与选项不符。"
        )
        # 当前阶段聚焦块追加在最末尾（离生成端最近，遵循度最高）
        return base + self.build_stage_focus_block(content)

    # ---------- 分阶段聚焦注入 ----------

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
        子工具的；本系统单一编排模型只能靠「全文 + 阶段聚焦重复」逼近同等遵循度。
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
        if len(focus) > _FOCUS_MAX_CHARS:
            focus = focus[:_FOCUS_MAX_CHARS] + "\n……（阶段章节超长，已截断）"
        label = _STAGE_LABELS.get(stage, stage)
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
