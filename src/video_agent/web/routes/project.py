"""
/api/project — 项目状态端点
负责前端与 StudioStateService 之间的状态读写、多项目管理。
"""
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Any, Dict, List, Optional

from src.video_agent.state.manager import StateManager
from src.video_agent.state.models import CAT_KEY_ELEMENTS, CAT_SHOTS, CAT_AUDIO_ITEMS
from src.video_agent.utils import gen_id
from src.video_agent.workflows.interactive import reset_interactive_engine

router = APIRouter()


# ---------- Response Models ----------

class ProjectListResponse(BaseModel):
    projects: List[Dict[str, Any]] = []
    active_project_id: str = ""


class ProjectStateResponse(BaseModel):
    """get_full_snapshot() 返回的完整状态（字段动态，用宽松模型）"""
    model_config = {"extra": "allow"}


class OkResponse(BaseModel):
    ok: bool = True


class OkWithStateResponse(BaseModel):
    ok: bool = True
    state: Optional[Dict[str, Any]] = None
    project_id: str = ""


class UndoStatusResponse(BaseModel):
    can_undo: bool = False
    can_redo: bool = False


class ProjectStateUpdate(BaseModel):
    keyElements: Optional[list] = None
    shots: Optional[list] = None
    audioItems: Optional[list] = None
    assets: Optional[list] = None
    chatMessages: Optional[list] = None


class NewProjectRequest(BaseModel):
    name: str = "未命名项目"


class SwitchProjectRequest(BaseModel):
    project_id: str


class DeleteProjectRequest(BaseModel):
    project_id: str


@router.get("/project/list", response_model=ProjectListResponse)
async def list_projects():
    """返回所有项目列表 + 当前活跃 ID"""
    svc = StateManager.get_instance()
    return svc.list_projects()


@router.get("/project/state", response_model=ProjectStateResponse)
@router.get("/state", response_model=ProjectStateResponse)              # 设计方案路径别名
async def get_project_state():
    """前端初始化加载 / Agent 刷新状态"""
    svc = StateManager.get_instance()
    return svc.get_full_snapshot()


@router.post("/project/new", response_model=OkWithStateResponse)
async def create_new_project(body: NewProjectRequest):
    """新建项目：保存当前 → 创建新项目 → 返回新状态"""
    svc = StateManager.get_instance()
    project_id = svc.create_project(body.name.strip() or "未命名项目")
    reset_interactive_engine()
    return {"ok": True, "project_id": project_id, "state": svc.get_full_snapshot()}


@router.post("/project/switch", response_model=OkWithStateResponse)
async def switch_project(body: SwitchProjectRequest):
    """切换项目：保存当前 → 加载目标 → 返回目标状态"""
    svc = StateManager.get_instance()
    ok = svc.switch_project(body.project_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"项目 '{body.project_id}' 不存在")
    reset_interactive_engine()
    return {"ok": True, "project_id": body.project_id, "state": svc.get_full_snapshot()}


@router.post("/project/delete", response_model=OkWithStateResponse)
async def delete_project(body: DeleteProjectRequest):
    """删除指定项目"""
    svc = StateManager.get_instance()
    ok = svc.delete_project(body.project_id)
    if not ok:
        raise HTTPException(status_code=400, detail="无法删除（至少保留一个项目）")
    reset_interactive_engine()
    return {"ok": True, "state": svc.get_full_snapshot()}


class DocumentSave(BaseModel):
    name: str
    content: str


@router.put("/project/document")
async def save_project_document(body: DocumentSave):
    """文档面板手动编辑保存（upsert 到 state.documents）"""
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="文档名不能为空")
    svc = StateManager.get_instance()

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    docs = svc.state_dict.setdefault("documents", [])
    for d in docs:
        if d.get("name") == name:
            d["content"] = body.content
            d["updated_at"] = now
            break
    else:
        docs.append({
            "id": gen_id("doc"),
            "name": name,
            "content": body.content,
            "created_at": now,
            "updated_at": now,
        })
    await svc.save_async()
    return {"ok": True, "documents": docs}


class DocumentDelete(BaseModel):
    name: str


@router.post("/project/document/delete")
async def delete_project_document(body: DocumentDelete):
    """删除指定名称的项目文档"""
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="文档名不能为空")
    svc = StateManager.get_instance()
    docs = svc.state_dict.setdefault("documents", [])
    svc.state_dict["documents"] = [d for d in docs if d.get("name") != name]
    await svc.save_async()
    return {"ok": True, "documents": svc.state_dict["documents"]}


@router.put("/project/state", response_model=OkResponse)
async def put_project_state(body: ProjectStateUpdate):
    """前端整体保存状态"""
    svc = StateManager.get_instance()
    state = svc.state_dict

    if body.keyElements is not None:
        state[CAT_KEY_ELEMENTS] = body.keyElements
    if body.shots is not None:
        state[CAT_SHOTS] = body.shots
    if body.audioItems is not None:
        state[CAT_AUDIO_ITEMS] = body.audioItems
    if body.assets is not None:
        state["assets"] = body.assets
    if body.chatMessages is not None:
        state["chatMessages"] = body.chatMessages

    await svc.save_async()
    return {"ok": True}


# ---------- Undo/Redo ----------


@router.post("/project/undo")
async def undo_action():
    """撤销上一步操作"""
    svc = StateManager.get_instance()
    ok = svc.undo()
    if not ok:
        return {"ok": False, "message": "没有可撤销的操作"}
    return {"ok": True, "state": svc.get_full_snapshot()}


@router.post("/project/redo")
async def redo_action():
    """重做上一步撤销的操作"""
    svc = StateManager.get_instance()
    ok = svc.redo()
    if not ok:
        return {"ok": False, "message": "没有可重做的操作"}
    return {"ok": True, "state": svc.get_full_snapshot()}


@router.get("/project/undo-status", response_model=UndoStatusResponse)
async def undo_status():
    """查询当前 undo/redo 可用状态"""
    svc = StateManager.get_instance()
    return {"can_undo": svc.can_undo, "can_redo": svc.can_redo}


@router.post("/project/undo-checkpoint")
async def undo_checkpoint():
    """破坏性操作（删除草稿/分组、批量覆盖）前压入撤销快照。

    前端整体 PUT /project/state 不自动压栈（防抖保存会洪水般填满 undo 栈），
    改为由前端在执行破坏性操作前显式调用本端点，保证一次 undo 即可恢复。
    """
    svc = StateManager.get_instance()
    svc.push_undo()
    return {"ok": True, "can_undo": svc.can_undo, "can_redo": svc.can_redo}
