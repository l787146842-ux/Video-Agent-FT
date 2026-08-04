"""
文档 & 生成 Tool — write_document / read_uploaded_doc / image_generate / workflow_pause
"""
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Type

from pydantic import BaseModel, Field
from loguru import logger

from src.video_agent.config import settings
from src.video_agent.tools.base import BaseTool, ToolResult
from src.video_agent.state.models import CAT_KEY_ELEMENTS, CAT_SHOTS, CAT_AUDIO_ITEMS, ALL_CATEGORIES_TUPLE
from src.video_agent.state.manager import StateManager
from src.video_agent.exceptions import GenerationError
from src.video_agent.web.generation import generate_image_via_provider
from src.video_agent.utils import gen_id
from src.video_agent.workflows.interactive import get_interactive_engine


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
    provider_id: str = Field("", description="生图供应商 ID")
    model: str = Field("", description="生图模型名")


class WorkflowPauseInput(BaseModel):
    message: str = Field("", description="向用户说明已完成什么、接下来要做什么")


class WorkflowStepInput(BaseModel):
    pass


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

        async with svc.lock:
            docs = svc.state_dict.setdefault("documents", [])

            for d in docs:
                if d.get("name") == params.name:
                    d["content"] = params.content
                    d["updated_at"] = now
                    svc.save()
                    return ToolResult(success=True, data={"name": params.name, "action": "updated"})

            docs.append({
                "id": gen_id("doc"),
                "name": params.name,
                "content": params.content,
                "created_at": now,
                "updated_at": now,
            })
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
        svc = StateManager.get_instance()
        state = svc.state_dict

        # 收集目标 drafts（只读，无需加锁）
        targets: List[Dict] = []
        if params.target in ("all_keyElements", "all_keyelements"):
            for g in state.get(CAT_KEY_ELEMENTS, []):
                for d in g.get("drafts", []):
                    if (d.get("prompt") or "").strip():
                        targets.append(d)
        elif params.target in ("all_shots", "all_shot"):
            for g in state.get(CAT_SHOTS, []):
                for d in g.get("drafts", []):
                    if (d.get("prompt") or "").strip():
                        targets.append(d)
        else:
            for cat in ALL_CATEGORIES_TUPLE:
                for g in state.get(cat, []):
                    for d in g.get("drafts", []):
                        if d.get("id") == params.target and (d.get("prompt") or "").strip():
                            targets.append(d)

        if not targets:
            return ToolResult(success=False, error="未找到有提示词的草稿")

        # 生图是耗时 IO，在锁外执行
        ok, failed = 0, []
        results: List[tuple] = []  # (draft, url)
        for draft in targets:
            try:
                url = await generate_image_via_provider(
                    params.provider_id, params.model, draft["prompt"],
                    size=draft.get("size", "1280x720"),
                    aspect_ratio=draft.get("aspectRatio", "16:9"),
                )
                results.append((draft, url))
                ok += 1
            except (GenerationError, Exception) as e:
                failed.append(str(e))

        # 加锁写入结果并持久化
        async with svc.lock:
            for draft, url in results:
                draft["imgUrl"] = url
                draft["tag"] = "已生成"
            svc.save()

        if ok == 0:
            return ToolResult(success=False, error="全部生成失败: " + "；".join(failed[:2]))
        return ToolResult(success=True, data={"generated": ok, "failed": len(failed)})


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


class WorkflowStepTool(BaseTool):
    name = "workflow_step"
    description = (
        "推进工作流到下一阶段（三段式：规划→提示词草案→生成）。"
        "执行当前阶段的 Skill，完成后暂停等待用户确认。"
        "当用户要求“开始制作”“推进”“执行工作流”时调用。"
    )

    def get_input_schema(self) -> Type[BaseModel]:
        return WorkflowStepInput

    async def aexecute(self, params: WorkflowStepInput) -> ToolResult:
        engine = get_interactive_engine()
        result = await engine.step()
        status = result.get("status", "unknown")
        if status == "waiting":
            return ToolResult(success=False, error=result.get("detail", "等待用户确认中"))
        if status == "blocked":
            return ToolResult(success=False, error=result.get("detail", "工作流被阻塞"))
        return ToolResult(success=True, data=result)


# ---------- 注册 ----------

def register_document_tools():
    """注册文档 & 生成 & 工作流 Tool"""
    from src.video_agent.tools.manager import ToolManager
    ToolManager.register(DocumentWriteTool())
    ToolManager.register(ReadUploadedDocTool())
    ToolManager.register(ReadSkillTool())
    ToolManager.register(ReadProjectDocTool())
    ToolManager.register(ImageGenerateTool())
    ToolManager.register(WorkflowPauseTool())
    ToolManager.register(WorkflowStepTool())
    logger.info("[Tools] 7 document/generation/workflow tools registered")
