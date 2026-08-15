"""
文档 & 生成 Tool — write_document / read_uploaded_doc / image_generate / workflow_pause
"""
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Type

from pydantic import BaseModel, Field
from loguru import logger

from src.video_agent.config import settings
from src.video_agent.core import prompt_gates
from src.video_agent.core.spec_rules import IRON_RULES_HEADING, ensure_iron_rules_doc
from src.video_agent.tools.base import BaseTool, ToolResult
from src.video_agent.state.models import CAT_KEY_ELEMENTS, CAT_SHOTS, CAT_AUDIO_ITEMS, ALL_CATEGORIES_TUPLE
from src.video_agent.state.manager import StateManager
from src.video_agent.exceptions import GenerationError
from src.video_agent.web.provider_config import (
    first_available_image_provider,
    resolve_provider_ref,
    spec_media_preference,
)
from src.video_agent.utils import gen_id


# ---------- Input Schemas ----------

class WriteDocumentInput(BaseModel):
    name: str = Field(..., description="文档名称（如 Final_Video_Spec.md）")
    content: str = Field(..., description="文档 Markdown 全文")


class ReadUploadedDocInput(BaseModel):
    name: str = Field("", description="文档名称（与清单中的名称一致，优先）")
    doc_id: str = Field("", description="文档 ID（可选，name 为空时用）")
    start: int = Field(0, ge=0, description="读取起始位置（字符偏移）；正文超长时工具会返回下一段的 start 值，传入即可续读")


class ReadSkillInput(BaseModel):
    name: str = Field(..., description="Skill 名称（与 Skill 目录中的名称一致）")


class ReadProjectDocInput(BaseModel):
    name: str = Field(..., description="规格文档名称（如 Final_Video_Spec.md）")
    start: int = Field(0, ge=0, description="读取起始位置（字符偏移）；正文超长时工具会返回下一段的 start 值，传入即可续读")


class GenerateImageInput(BaseModel):
    target: str = Field("all_keyElements", description="目标: all_keyElements | all_shots | 具体 draft_id")
    provider_id: str = Field("", description="生图供应商 ID（可留空，系统自动回退草稿自带供应商或配置中首个可用生图供应商）")
    model: str = Field("", description="生图模型名（可留空，自动用供应商默认模型）")


class WorkflowPauseInput(BaseModel):
    message: str = Field("", description="向用户说明已完成什么、接下来要做什么")
    options: List[Dict[str, str]] = Field(
        default_factory=list,
        description="引导选项（前端渲染为选择卡片，用户选择后作为回复发送），暂停时原则上必须提供："
        "每项 {label: 选项名, description: 一句话说明, group: 所属问题/维度标题（可选）}。"
        "label 必须如实描述用户确认后立即执行的下一步动作（如关键元素拆分确认后是「编写关键元素提示词」，"
        "不是「生成概念图」），严禁超前承诺。"
        "多个维度一次性收集时（如成片规格：时长/画幅/风格/声音），每项带上 group 字段，"
        "前端会渲染为分页向导卡片，用户逐页选完后一次性发送全部选择，避免逐题多轮往返",
    )


# ---------- Tool 实现 ----------

def _norm_name(s: str) -> str:
    """名称归一化：去空格/后缀/大小写，用于模糊匹配"""
    s = (s or "").strip().casefold()
    for ext in (".md", ".txt"):
        if s.endswith(ext):
            s = s[: -len(ext)]
    return s.replace(" ", "")


def _fuzzy_pick(items: List[Dict[str, Any]], wanted: str, keys: List[str]) -> Optional[Dict[str, Any]]:
    """从清单里按名称模糊定位一条记录：精确 → 归一化相等 → 双向包含。

    模型传的名称常与清单略有出入（带/不带后缀、别名），
    匹配失败会导致 read_* 读不到内容，渐进式披露直接失效，故尽量宽松。
    """
    wanted_norm = _norm_name(wanted)
    if not wanted_norm:
        return None

    def names(item: Dict[str, Any]) -> List[str]:
        return [str(item.get(k) or "") for k in keys]

    # 1. 精确匹配
    for item in items:
        if wanted in names(item):
            return item
    # 2. 归一化后相等（剧本 ≈ 剧本.md）
    for item in items:
        if any(_norm_name(n) == wanted_norm for n in names(item) if n):
            return item
    # 3. 双向包含（短名找长名 / 长名找短名），防止单字误匹配
    if len(wanted_norm) >= 2:
        for item in items:
            for n in names(item):
                nn = _norm_name(n)
                if nn and len(nn) >= 2 and (wanted_norm in nn or nn in wanted_norm):
                    return item
    return None

class DocumentWriteTool(BaseTool):
    name = "document_write"
    description = "写入/更新项目文档工件（如制作规格、脚本大纲）。已存在同名文档则覆盖。"

    def get_input_schema(self) -> Type[BaseModel]:
        return WriteDocumentInput

    async def aexecute(self, params: WriteDocumentInput) -> ToolResult:
        svc = StateManager.get_instance()
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        content = str(params.content or "")
        is_spec = prompt_gates.is_spec_doc_name(params.name)
        # 铁律文档保护（888 事故）：铁律由系统维护 + 用户在文档面板手改，
        # 模型只读不得整篇重写（会盖掉用户编辑）
        if IRON_RULES_HEADING in str(params.name or ""):
            return ToolResult(
                success=False,
                error=("《执行铁律.md》由系统维护、用户在文档面板手动编辑，模型不得整篇重写"
                       "（会盖掉用户的修改）。如需调整流程开关，按用户指令由系统幂等合并对应声明行即可。"),
            )
        # 规格向导拒收模型手写规格（方案乙 4444）：规格由系统按向导选定拼装
        if is_spec:
            from src.video_agent.skill_runtime.registry import spec_wizard_active

            _used = svc.state_dict.get("usedSkills") or []
            if spec_wizard_active(str(_used[-1] or "") if _used else ""):
                if prompt_gates.has_spec_document(svc.state_dict):
                    return ToolResult(
                        success=False,
                        error=("规格已按您的选择生成，无需重复写入；"
                               "要调整请在文档面板修改或重发选择。"),
                    )
                # 814G3：规格尚未交互时文案不得说「已生成」（模型/用户都未交互过）
                return ToolResult(
                    success=False,
                    error=("规格文档尚未生成：系统将按用户在向导中的选择统一拼装，"
                           "模型不得手写；请暂停等待规格交互完成后再继续。"),
                )

        async with svc.lock:
            docs = svc.state_dict.setdefault("documents", [])

            for d in docs:
                if d.get("name") == params.name:
                    d["content"] = content
                    d["updated_at"] = now
                    if is_spec:
                        ensure_iron_rules_doc(svc.state_dict)
                    svc.save()
                    return ToolResult(success=True, data={"name": params.name, "action": "updated"})

            docs.append({
                "id": gen_id("doc"),
                "name": params.name,
                "content": content,
                "created_at": now,
                "updated_at": now,
            })
            if is_spec:
                ensure_iron_rules_doc(svc.state_dict)
            svc.save()
        return ToolResult(success=True, data={"name": params.name, "action": "created"})


class ReadUploadedDocTool(BaseTool):
    name = "read_uploaded_doc"
    description = (
        "按需读取用户上传的素材文档（故事/剧本等）全文。"
        "上传文档正文不会自动注入上下文，清单里只有名称/字数/预览，"
        "需要全文时必须调用本工具，不得声称看不到文档。"
    )

    def get_input_schema(self) -> Type[BaseModel]:
        return ReadUploadedDocInput

    async def aexecute(self, params: ReadUploadedDocInput) -> ToolResult:
        svc = StateManager.get_instance()
        docs = svc.state_dict.get("uploadedDocs") or []
        target = None
        if params.name:
            target = _fuzzy_pick(docs, params.name, ["name"])
        if target is None and params.doc_id:
            target = next((d for d in docs if d.get("id") == params.doc_id), None)
        if target is None:
            available = "、".join(d.get("name", "") for d in docs[:10]) or "无"
            return ToolResult(success=False, error=f"未找到该文档。已存档文档：{available}")
        content = target.get("content", "") or ""
        max_chars = settings.max_doc_chars
        start = max(0, params.start)
        if start >= len(content) and content:
            return ToolResult(success=False, error=f"文档已读完（共 {len(content)} 字，无后续内容）")
        body = content[start:start + max_chars]
        end = start + len(body)
        # 分段续读：返回区间与下一段 start 值，超长文档不再丢尾部
        note = "" if end >= len(content) else (
            f"\n……（正文共 {len(content)} 字，本次返回第 {start}~{end} 字；"
            f"传 start={end} 继续读取剩余 {len(content) - end} 字）"
        )
        return ToolResult(success=True, data={
            "name": target.get("name", ""),
            "content": body + note,
            "char_count": target.get("char_count", len(content)),
        })


def _truncate_content(content: str) -> str:
    """按需读取的正文统一上限截断，防止单次工具返回撑爆上下文（兼容旧调用）"""
    max_chars = settings.max_doc_chars
    if len(content) > max_chars:
        return content[:max_chars] + f"\n……（正文超长，已截断为前 {max_chars} 字）"
    return content


def _slice_content(content: str, start: int) -> tuple:
    """分段读取：返回 (切片正文, 续读提示)。超出上限时提示下一段 start 值，
    超长文档不再丢尾部（取代旧的一刀切截断）"""
    max_chars = settings.max_doc_chars
    start = max(0, start)
    body = content[start:start + max_chars]
    end = start + len(body)
    note = "" if end >= len(content) else (
        f"\n……（正文共 {len(content)} 字，本次返回第 {start}~{end} 字；"
        f"传 start={end} 继续读取剩余 {len(content) - end} 字）"
    )
    return body, note


class ReadSkillTool(BaseTool):
    name = "read_skill"
    description = (
        "按需加载指定 Skill 的完整流程文档。上下文里只有 Skill 目录（名称+摘要），"
        "执行任务前必须先调用本工具读取对应 Skill 全文，不要凭目录摘要自行推测流程。"
    )

    def get_input_schema(self) -> Type[BaseModel]:
        return ReadSkillInput

    async def aexecute(self, params: ReadSkillInput) -> ToolResult:
        from src.video_agent.web.skill_docs import (
            build_foreign_tool_note,
            list_skill_docs,
            resolve_skill_content,
        )

        wanted = (params.name or "").strip()
        # 与 Planner 选中项注入共用同一套解析（仅文档 Skill，模糊匹配）
        matched, content = resolve_skill_content(wanted)
        if not content:
            available: List[str] = []
            try:
                available += [d.get("name", "") for d in list_skill_docs()]
            except Exception:
                pass
            return ToolResult(
                success=False,
                error=f"未找到 Skill「{wanted}」。可用 Skill：{'、'.join(available) or '无'}",
            )
        body = _truncate_content(content)
        # 外来工作流 Skill 的工具名映射对照表（与选中项硬注入行为一致）
        note = build_foreign_tool_note(content)
        if note:
            body = body + "\n\n" + note
        return ToolResult(success=True, data={"name": matched, "content": body})


class ReadProjectDocTool(BaseTool):
    name = "read_project_doc"
    description = (
        "按需读取项目规格文档（write_document 产出，如 Final_Video_Spec.md）全文。"
        "工作台状态 JSON 的 documents 节只有清单（名称/摘要），"
        "开工前必须先读规格文档并遵守其中约束。"
    )

    def get_input_schema(self) -> Type[BaseModel]:
        return ReadProjectDocInput

    async def aexecute(self, params: ReadProjectDocInput) -> ToolResult:
        svc = StateManager.get_instance()
        docs = svc.state_dict.get("documents") or []
        wanted = (params.name or "").strip()
        target = _fuzzy_pick(docs, wanted, ["name"])
        if target is None:
            available = "、".join(d.get("name", "") for d in docs[:10]) or "无"
            return ToolResult(success=False, error=f"未找到文档「{wanted}」。已有文档：{available}")
        full = target.get("content", "") or ""
        start = max(0, params.start)
        if start >= len(full) and full:
            return ToolResult(success=False, error=f"文档已读完（共 {len(full)} 字，无后续内容）")
        body, note = _slice_content(full, start)
        return ToolResult(success=True, data={
            "name": target.get("name", ""),
            "content": body + note,
            "updated_at": target.get("updated_at", ""),
        })


class ImageGenerateTool(BaseTool):
    name = "image_generate"
    description = (
        "触发图片生成（危险操作）。仅当用户明确要求'生成/出图/执行'时才可调用。"
        "系统会自动将 sceneRefs 引用的关键元素概念图作为参考图注入。"
    )

    def get_input_schema(self) -> Type[BaseModel]:
        return GenerateImageInput

    async def aexecute(self, params: GenerateImageInput) -> ToolResult:
        from src.video_agent.config import settings
        from src.video_agent.state import storyboard_ops as ops
        from src.video_agent.web.generation import submit_image_task, wait_image_task

        # 聊天框出图开关：关 = Agent 在对话中不主动触发生图
        if not settings.chat_image_enabled:
            return ToolResult(success=False, error=(
                "聊天框出图已在全局设置中关闭，如需生图请先在顶栏「全局设置」开启「聊天框出图」。"
            ))

        svc = StateManager.get_instance()
        state = svc.state_dict

        # 收集目标 (group, draft, draft_type) 三元组（只读，无需加锁）
        targets: List[tuple] = []
        if params.target in ("all_keyElements", "all_keyelements"):
            for g in state.get(CAT_KEY_ELEMENTS, []):
                for d in g.get("drafts", []):
                    if (d.get("prompt") or "").strip():
                        targets.append((g, d, "keyElement"))
        elif params.target in ("all_shots", "all_shot"):
            for g in state.get(CAT_SHOTS, []):
                for d in g.get("drafts", []):
                    if (d.get("prompt") or "").strip():
                        targets.append((g, d, "shot"))
        else:
            for cat in ALL_CATEGORIES_TUPLE:
                for g in state.get(cat, []):
                    for d in g.get("drafts", []):
                        if d.get("id") == params.target and (d.get("prompt") or "").strip():
                            targets.append((g, d, "shot" if cat == CAT_SHOTS else "keyElement"))

        if not targets:
            return ToolResult(success=False, error="未找到有提示词的草稿")

        # 供应商回退链（8888 事故修复；B7 唯一权威源=全局设置）：LLM 参数 → 全局设置 → 草稿自带 providerId
        # → 配置中首个可用生图供应商；LLM 常传空 provider，不回退会报「供应商 '' 未配置」
        provider_id = resolve_provider_ref(str(params.provider_id or "").strip())
        model = str(params.model or "").strip()
        if not provider_id:
            spec_pid, spec_model = spec_media_preference(state)
            if spec_pid:
                provider_id = spec_pid
                model = model or spec_model
                logger.info(f"[image_generate] provider 未指定，按全局设置回退: {spec_pid}/{model}")
        if not provider_id:
            for _g, d, _t in targets:
                pid = resolve_provider_ref(str(d.get("providerId") or "").strip())
                if pid:
                    provider_id = pid
                    logger.info(f"[image_generate] provider 未指定，回退草稿自带供应商: {pid}")
                    break
        if not provider_id:
            if settings.default_image_provider_id:
                provider_id = settings.default_image_provider_id
                model = model or settings.default_image_model
                logger.info(f"[image_generate] provider 未指定，回退全局设置默认出图渠道: {provider_id}/{model}")
        if not provider_id:
            from src.video_agent.web.provider_config import first_available_image_provider_async

            provider_id, fb_model = await first_available_image_provider_async()
            if provider_id:
                model = model or fb_model
                logger.info(f"[image_generate] provider 未指定，回退配置首个可用生图供应商: {provider_id}/{model}")
        if not provider_id:
            return ToolResult(success=False, error=(
                "当前工作区未配置任何可用的生图供应商，请先在 API 配置页添加供应商与 API Key。"
            ))

        # 规格制作参数（7777 二轮）：图片分辨率由规格文档优先，
        # 其次草稿自带，最后全局默认（回退链与供应商链口径一致）
        from src.video_agent.web.provider_config import spec_production_params

        spec_image_res = str(spec_production_params(state).get("image_resolution") or "")

        # 统一任务管线提交：提交即记录生成日志 + SSE 点亮前端卡片读秒，
        # 与手动/批量生图行为一致；全部提交后再逐个等结果（任务是并发的）
        submitted: List[tuple] = []  # (draft, task_id)
        for group, draft, dtype in targets:
            refs = ops.resolve_scene_refs(state, group) if group else []
            eff_resolution = (
                spec_image_res or str(draft.get("imageResolution") or "")
                or settings.default_image_resolution or "1K"
            )
            draft["imageResolution"] = eff_resolution  # 参数栏同步可见
            task_id = submit_image_task(
                state, draft, provider_id, model, refs,
                aspect_ratio=(draft.get("aspectRatio") or "16:9"),
                resolution=eff_resolution,
                on_failure_save=svc.save_debounced,
                draft_type=dtype,
            )
            submitted.append((draft, task_id))
        svc.save()  # 持久化「生成中」标签与草稿参数回写
        
        # 实际使用的供应商/模型回写草稿（imgUrl/tag 已由任务管线 writeback 处理）
        async with svc.lock:
            for draft, _ in submitted:
                if provider_id:
                    draft["providerId"] = provider_id
                if model:
                    draft["model"] = model
            svc.save()

        # 提交即返回（W12/P2）：结果由前端 SSE + 轮询跟踪，
        # 避免 N×600s 工具轮阻塞 agent 循环
        return ToolResult(success=True, data={
            "submitted": len(submitted),
            "task_ids": [tid for _, tid in submitted],
            "detail": f"已提交 {len(submitted)} 个生图任务，结果将通过 SSE/轮询通知",
        })


class WorkflowPauseTool(BaseTool):
    name = "workflow_pause"
    description = "暂停工作流并请求用户确认。用于拆解完成后请用户过目再继续的场景。"

    def get_input_schema(self) -> Type[BaseModel]:
        return WorkflowPauseInput

    async def aexecute(self, params: WorkflowPauseInput) -> ToolResult:
        svc = StateManager.get_instance()
        async with svc.lock:
            interaction = svc.state_dict.setdefault("interaction", {})
            interaction["awaiting_confirmation"] = True
            interaction["confirmation_message"] = params.message or "请确认以上内容，确认后我将继续。"
            svc.save()
        return ToolResult(success=True, data={"paused": True, "message": params.message})


# ---------- 注册 ----------

def register_document_tools():
    """注册文档 & 生成 & 暂停 Tool（workflow_step 随 workflows 引擎下线，814F3）"""
    from src.video_agent.tools.manager import ToolManager
    ToolManager.register(DocumentWriteTool())
    ToolManager.register(ReadUploadedDocTool())
    ToolManager.register(ReadSkillTool())
    ToolManager.register(ReadProjectDocTool())
    ToolManager.register(ImageGenerateTool())
    ToolManager.register(WorkflowPauseTool())
    logger.info("[Tools] 7 document/generation/workflow tools registered")
