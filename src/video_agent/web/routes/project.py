"""
/api/project — 项目状态端点
负责前端与 StudioStateService 之间的状态读写、多项目管理。
"""
import time
import random
from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Any, Dict, List, Optional

from src.video_agent.state.manager import StateManager
from src.video_agent.state.models import CAT_KEY_ELEMENTS, CAT_SHOTS, CAT_AUDIO_ITEMS

router = APIRouter()


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


@router.get("/project/list")
async def list_projects():
    """返回所有项目列表 + 当前活跃 ID"""
    svc = StateManager.get_instance()
    return svc.list_projects()


@router.get("/project/state")
@router.get("/state")              # 设计方案路径别名
async def get_project_state():
    """前端初始化加载 / Agent 刷新状态"""
    svc = StateManager.get_instance()
    return svc.get_full_snapshot()


@router.post("/project/new")
async def create_new_project(body: NewProjectRequest):
    """新建项目：保存当前 → 创建新项目 → 返回新状态"""
    svc = StateManager.get_instance()
    project_id = svc.create_project(body.name.strip() or "未命名项目")
    return {"ok": True, "project_id": project_id, "state": svc.get_full_snapshot()}


@router.post("/project/switch")
async def switch_project(body: SwitchProjectRequest):
    """切换项目：保存当前 → 加载目标 → 返回目标状态"""
    svc = StateManager.get_instance()
    ok = svc.switch_project(body.project_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"项目 '{body.project_id}' 不存在")
    return {"ok": True, "project_id": body.project_id, "state": svc.get_full_snapshot()}


@router.post("/project/delete")
async def delete_project(body: DeleteProjectRequest):
    """删除指定项目"""
    svc = StateManager.get_instance()
    ok = svc.delete_project(body.project_id)
    if not ok:
        raise HTTPException(status_code=400, detail="无法删除（至少保留一个项目）")
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

    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    docs = svc.state_dict.setdefault("documents", [])
    for d in docs:
        if d.get("name") == name:
            d["content"] = body.content
            d["updated_at"] = now
            break
    else:
        docs.append({
            "id": f"doc-{int(time.time())}-{random.randint(100, 999)}",
            "name": name,
            "content": body.content,
            "created_at": now,
            "updated_at": now,
        })
    svc.save()
    return {"ok": True, "documents": docs}


@router.put("/project/state")
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

    svc.save()
    return {"ok": True}
