"""
文档 & 生成 Tool — write_document / image_generate / workflow_pause
"""
import time
import random
from datetime import datetime
from typing import Any, Dict, List, Optional, Type

from pydantic import BaseModel, Field
from loguru import logger

from src.video_agent.tools.base import BaseTool, ToolResult
from src.video_agent.state.models import CAT_KEY_ELEMENTS, CAT_SHOTS, CAT_AUDIO_ITEMS, ALL_CATEGORIES_TUPLE


# ---------- Input Schemas ----------

class WriteDocumentInput(BaseModel):
    name: str = Field(..., description="文档名称（如 Final_Video_Spec.md）")
    content: str = Field(..., description="文档 Markdown 全文")


class GenerateImageInput(BaseModel):
    target: str = Field("all_keyElements", description="目标: all_keyElements | all_shots | 具体 draft_id")
    provider_id: str = Field("", description="生图供应商 ID")
    model: str = Field("", description="生图模型名")


class WorkflowPauseInput(BaseModel):
    message: str = Field("", description="向用户说明已完成什么、接下来要做什么")


class WorkflowStepInput(BaseModel):
    pass


# ---------- Tool 实现 ----------

class DocumentWriteTool(BaseTool):
    name = "document_write"
    description = "写入/更新项目文档工件（如制作规格、脚本大纲）。已存在同名文档则覆盖。"

    def get_input_schema(self) -> Type[BaseModel]:
        return WriteDocumentInput

    async def aexecute(self, params: WriteDocumentInput) -> ToolResult:
        from src.video_agent.state.manager import StateManager

        svc = StateManager.get_instance()
        docs = svc.state_dict.setdefault("documents", [])
        now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

        for d in docs:
            if d.get("name") == params.name:
                d["content"] = params.content
                d["updated_at"] = now
                svc.save()
                return ToolResult(success=True, data={"name": params.name, "action": "updated"})

        docs.append({
            "id": f"doc-{int(time.time())}-{random.randint(100, 999)}",
            "name": params.name,
            "content": params.content,
            "created_at": now,
            "updated_at": now,
        })
        svc.save()
        return ToolResult(success=True, data={"name": params.name, "action": "created"})


class ImageGenerateTool(BaseTool):
    name = "image_generate"
    description = (
        "触发图片生成（危险操作）。仅当用户明确要求'生成/出图/执行'时才可调用。"
        "系统会自动将 sceneRefs 引用的关键元素概念图作为参考图注入。"
    )

    def get_input_schema(self) -> Type[BaseModel]:
        return GenerateImageInput

    async def aexecute(self, params: GenerateImageInput) -> ToolResult:
        from src.video_agent.state.manager import StateManager
        from src.video_agent.web.generation import generate_image_via_provider
        from src.video_agent.exceptions import GenerationError

        svc = StateManager.get_instance()
        state = svc.state_dict

        # 收集目标 drafts
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

        ok, failed = 0, []
        for draft in targets:
            try:
                url = await generate_image_via_provider(
                    params.provider_id, params.model, draft["prompt"],
                    size=draft.get("size", "1280x720"),
                    aspect_ratio=draft.get("aspectRatio", "16:9"),
                )
                draft["imgUrl"] = url
                draft["tag"] = "已生成"
                ok += 1
            except (GenerationError, Exception) as e:
                failed.append(str(e))

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
        from src.video_agent.state.manager import StateManager
        svc = StateManager.get_instance()
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
        from src.video_agent.web.routes.workflow import get_interactive_engine
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
    ToolManager.register(ImageGenerateTool())
    ToolManager.register(WorkflowPauseTool())
    ToolManager.register(WorkflowStepTool())
    logger.info("[Tools] 4 document/generation/workflow tools registered")
