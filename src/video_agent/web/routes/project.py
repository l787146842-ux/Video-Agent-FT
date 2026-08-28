"""
/api/project — 项目状态端点
负责前端与 StudioStateService 之间的状态读写、多项目管理。
"""
from datetime import datetime, timezone

from fastapi import APIRouter
from pydantic import BaseModel
from typing import Any, Dict, List, Optional

from src.video_agent.exceptions import StateConflictError, VideoAgentError
from src.video_agent.state.manager import StateManager
from src.video_agent.state.models import CAT_KEY_ELEMENTS, CAT_SHOTS, CAT_AUDIO_ITEMS
from src.video_agent.utils import gen_id
from src.video_agent.web.error_payload import LEGACY_NOT_FOUND, LEGACY_VALIDATION_ERROR

router = APIRouter()


# ---------- Response Models ----------

class ProjectItem(BaseModel):
    """项目索引条目（与前端 Project 同形；索引多余键静默过滤）"""
    id: str
    name: str
    created_at: str = ""
    updated_at: str = ""


class ProjectListResponse(BaseModel):
    projects: List[ProjectItem] = []
    active_project_id: str = ""


class ProjectStateResponse(BaseModel):
    """get_full_snapshot 返回的完整状态（字段动态，用宽松模型）"""
    model_config = {"extra": "allow"}


class OkResponse(BaseModel):
    ok: bool = True
    board_version: Optional[int] = None


class OkWithStateResponse(BaseModel):
    ok: bool = True
    state: Optional[Dict[str, Any]] = None
    project_id: str = ""


class UndoStatusResponse(BaseModel):
    # 无默认值：端点恒回传两字段，契约层必填（前端生成物免可选判空）
    can_undo: bool
    can_redo: bool


class ProjectStateUpdate(BaseModel):
    # 前端发起保存时的项目 ID：与后端活跃项目不一致说明是跨项目的过期写入
    # （如防抖 PUT 在途期间用户切换了项目），必须拒绝，否则旧项目数据会污染新项目
    project_id: Optional[str] = None
    base_version: Optional[int] = None
    # 五列表收窄为参数化 Dict 形态：落盘链路为裸 json.dumps（元素须保持 dict），
    # 且前端元素字段远多于 models.py 对应模型（无 extra=allow 会静默丢字段），
    # 故不模型化元素；全量建模见 docs/未清偿债务清单.md D-06
    keyElements: Optional[List[Dict[str, Any]]] = None
    shots: Optional[List[Dict[str, Any]]] = None
    audioItems: Optional[List[Dict[str, Any]]] = None
    assets: Optional[List[Dict[str, Any]]] = None
    chatMessages: Optional[List[Dict[str, Any]]] = None


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
    async with svc.lock:
        project_id = svc.create_project(body.name.strip() or "未命名项目")
        snapshot = svc.get_full_snapshot()
    return {"ok": True, "project_id": project_id, "state": snapshot}


@router.post("/project/switch", response_model=OkWithStateResponse)
async def switch_project(body: SwitchProjectRequest):
    """切换项目：保存当前 → 加载目标 → 返回目标状态"""
    svc = StateManager.get_instance()
    async with svc.lock:
        ok = svc.switch_project(body.project_id)
        if not ok:
            raise VideoAgentError(
                f"项目 '{body.project_id}' 不存在",
                status_code=404,
                error_code=LEGACY_NOT_FOUND,
            )
        snapshot = svc.get_full_snapshot()
    return {"ok": True, "project_id": body.project_id, "state": snapshot}


@router.post("/project/delete", response_model=OkWithStateResponse)
async def delete_project(body: DeleteProjectRequest):
    """删除指定项目"""
    svc = StateManager.get_instance()
    async with svc.lock:
        ok = svc.delete_project(body.project_id)
        if not ok:
            raise VideoAgentError(
                "无法删除（至少保留一个项目）",
                status_code=400,
                error_code=LEGACY_VALIDATION_ERROR,
            )
        snapshot = svc.get_full_snapshot()
    return {"ok": True, "state": snapshot}


class DocumentSave(BaseModel):
    name: str
    content: str


@router.put("/project/document")
async def save_project_document(body: DocumentSave):
    """文档面板手动编辑保存（upsert 到 state.documents）"""
    name = body.name.strip()
    if not name:
        raise VideoAgentError(
            "文档名不能为空", status_code=400, error_code=LEGACY_VALIDATION_ERROR
        )
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
        raise VideoAgentError(
            "文档名不能为空", status_code=400, error_code=LEGACY_VALIDATION_ERROR
        )
    svc = StateManager.get_instance()
    docs = svc.state_dict.setdefault("documents", [])
    svc.state_dict["documents"] = [d for d in docs if d.get("name") != name]
    await svc.save_async()
    return {"ok": True, "documents": svc.state_dict["documents"]}


@router.put("/project/state", response_model=OkResponse)
async def put_project_state(body: ProjectStateUpdate):
    """前端整体保存状态"""
    svc = StateManager.get_instance()
    async with svc.lock:
        # 乐观锁：陈旧 PUT 必须被拒，前端采纳响应版本跟进
        if body.base_version is not None and body.base_version != svc.board_version:
            raise StateConflictError("版本冲突：状态已被其他窗口更新，请刷新后重试")
        # 过期写入防护：请求在途期间项目已切换，拒绝落盘（前端收到 409 静默丢弃）
        if body.project_id and body.project_id != svc.active_project_id:
            raise StateConflictError(
                f"项目已切换（期望 '{svc.active_project_id}'，收到 '{body.project_id}'），丢弃本次过期保存"
            )
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
    return {"ok": True, "board_version": svc.board_version}


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
