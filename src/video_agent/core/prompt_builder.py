"""system prompt 组装（从 planner.py 拆出，批次5 文件瘦身）。

承载：协议/Skill 目录/选中 Skill 全文/选中草稿/记忆检索/状态 JSON 的组装，
段落顺序为前缀缓存优化（稳定内容在前，状态 JSON 殿后）。

planner.py 保留 _build_system_prompt 等同名委托，既有调用/测试路径不变。
"""
from typing import TYPE_CHECKING, Any, Callable, Dict, List

from loguru import logger

from src.video_agent.config import settings
from src.video_agent.memory import MemoryManager
from src.video_agent.utils.prompts import load_prompt

if TYPE_CHECKING:
    from src.video_agent.core.planner import PlannerContext


class PromptBuilder:
    """system prompt 组装器：依赖通过 callable 注入，不与 Planner 循环引用"""

    def __init__(self, get_skill_docs: Callable[[], Any], get_project_id: Callable[[], str]) -> None:
        self._get_skill_docs = get_skill_docs
        self._get_project_id = get_project_id

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

        # 硬保障：用户在前端选中的 Skill 强制全文注入。
        # 原因：模型不一定主动调 read_skill，非 FC 通道（如 gemini-cli）根本调不了；
        # 选中项是用户明确指定的任务依据，丢了它产出质量直接劣化。
        # 未选中的 Skill 仍保持目录 + 按需加载，token 治理不回退。
        if context.skill_name:
            selected_block = self.build_selected_skill_block(context.skill_name)
            if selected_block:
                parts.append(selected_block)

        if context.use_studio_context:
            if context.selected_draft_id:
                parts.append(
                    f"\n用户当前选中的草稿：draft_id={context.selected_draft_id}"
                    f"（类型 {context.selected_type or '未知'}）。studio-actions 里的 \"current\" 指向它。"
                )

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
        return (
            f"== 当前选中 Skill「{display or skill_name}」全文（已直接注入，必须严格遵守"
            f"其中的流程与规范；不要再对它调用 read_skill）==\n{content}{mapping_block}\n\n"
            "【Skill 流程纪律 — 最高优先级】\n"
            "1. 本 Skill 规定的阶段划分与暂停点必须逐段执行：严禁把多个阶段（规格文档、故事板结构、"
            "提示词草案、生成）合并到同一轮回复里一口气做完。\n"
            "2. Skill 里每一个「确认/暂停/审阅」点，都必须用 request_confirmation（文本模式）或 "
            "workflow_pause（Tool 模式）真正停下等待用户；只在正文里写「请确认」而不发暂停信号是无效的。\n"
            "3. 要求分批次确认的（如先元素图草案、确认后再镜头视频草案），必须真的分批："
            "本批完成→暂停等确认，下一批等用户确认后的新消息再做。\n"
            "4. 本轮若已到达某个暂停点：立即发出暂停信号并结束本轮，不要顺手把下一阶段也做完。"
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
