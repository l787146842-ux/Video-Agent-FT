"""
/api/project — 项目状态端点
负责前端与 StudioStateService 之间的状态读写、多项目管理。
"""
from datetime import datetime, timezone

from fastapi import APIRouter
from pydantic import BaseModel
from typing import Any, Dict, List, Optional

from src.video_agent.exceptions import StateConflictError, VideoAgentError
from src.video_agent.state import board_merge, conversation_ops
from src.video_agent.state.board_merge import CAT_ASSETS
from src.video_agent.state.manager import StateManager
from src.video_agent.state.models import CAT_KEY_ELEMENTS, CAT_SHOTS, CAT_AUDIO_ITEMS
from src.video_agent.utils import gen_id
from src.video_agent.web.error_payload import LEGACY_NOT_FOUND, LEGACY_VALIDATION_ERROR
from src.video_agent.web.agent_task_manager import stop_tasks_bound_to_conversations
from src.video_agent.web.task_manager import get_task_manager

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

        # 对象删除级联（二期子对话批 1）：落盘前对提交列表做新旧草稿 id diff，
        # 硬删命中的 scope 隐藏线程（先掐绑定在途任务）；线程随撤销快照原子恢复。
        _old_ids, _new_ids = set(), set()
        for _cat, _incoming in (
            (CAT_KEY_ELEMENTS, body.keyElements),
            (CAT_SHOTS, body.shots),
            (CAT_AUDIO_ITEMS, body.audioItems),
        ):
            if _incoming is None:
                continue
            _old_ids |= conversation_ops.board_draft_ids(state.get(_cat) or [])
            _new_ids |= conversation_ops.board_draft_ids(_incoming)
        if _old_ids - _new_ids:
            conversation_ops.cleanup_scoped_threads_for_removed(
                svc, _old_ids - _new_ids, save=False,
                stop_tasks=stop_tasks_bound_to_conversations)

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


class BoardMergeResponse(BaseModel):
    """G1 三向合并响应：无冲突直接落盘（applied）；有冲突回冲突清单 +
    默认保留用户版的合并结果，前端经冲突面板定夺后整板回提。"""
    ok: bool = True
    applied: bool = False
    base_available: bool = False
    board_version: Optional[int] = None
    merged: Optional[Dict[str, Any]] = None
    conflicts: List[Dict[str, Any]] = []


@router.post("/project/state/merge", response_model=BoardMergeResponse)
async def merge_project_state(body: ProjectStateUpdate):
    """G1 并行局部修改：陈旧整板提交不再整板拒收，改按元素粒度三向合并。

    base=客户端所见版号快照（内存历史缓冲）/ mine=本次提交 /
    theirs=服务端当前；单方改动直接采纳，双方同改同一处进冲突清单。
    基线不可得（重启后/超出缓冲）回落旧 409 语义由前端处理。
    """
    svc = StateManager.get_instance()
    async with svc.lock:
        # 过期写入防护：同整板 PUT 口径（跨项目陈旧写直接拒）
        if body.project_id and body.project_id != svc.active_project_id:
            raise StateConflictError(
                f"项目已切换（期望 '{svc.active_project_id}'，收到 '{body.project_id}'），丢弃本次过期保存"
            )
        state = svc.state_dict
        mine = {
            CAT_KEY_ELEMENTS: body.keyElements if body.keyElements is not None else list(state.get(CAT_KEY_ELEMENTS) or []),
            CAT_SHOTS: body.shots if body.shots is not None else list(state.get(CAT_SHOTS) or []),
            CAT_AUDIO_ITEMS: body.audioItems if body.audioItems is not None else list(state.get(CAT_AUDIO_ITEMS) or []),
            CAT_ASSETS: body.assets if body.assets is not None else list(state.get(CAT_ASSETS) or []),
        }
        base = board_merge.base_board(svc.active_project_id, body.base_version)
        if base is None:
            return BoardMergeResponse(
                ok=False, applied=False, base_available=False,
                board_version=svc.board_version)
        theirs = {
            CAT_KEY_ELEMENTS: list(state.get(CAT_KEY_ELEMENTS) or []),
            CAT_SHOTS: list(state.get(CAT_SHOTS) or []),
            CAT_AUDIO_ITEMS: list(state.get(CAT_AUDIO_ITEMS) or []),
            CAT_ASSETS: list(state.get(CAT_ASSETS) or []),
        }
        merged, conflicts = board_merge.merge_board(base, mine, theirs)
        if not conflicts:
            # 对象删除级联（同整板 PUT 口径）：落盘分支新旧草稿 id diff 清线程
            _old_ids, _new_ids = set(), set()
            for _cat in (CAT_KEY_ELEMENTS, CAT_SHOTS, CAT_AUDIO_ITEMS):
                _old_ids |= conversation_ops.board_draft_ids(state.get(_cat) or [])
                _new_ids |= conversation_ops.board_draft_ids(merged.get(_cat) or [])
            if _old_ids - _new_ids:
                conversation_ops.cleanup_scoped_threads_for_removed(
                    svc, _old_ids - _new_ids, save=False,
                    stop_tasks=stop_tasks_bound_to_conversations)
            state[CAT_KEY_ELEMENTS] = merged[CAT_KEY_ELEMENTS]
            state[CAT_SHOTS] = merged[CAT_SHOTS]
            state[CAT_AUDIO_ITEMS] = merged[CAT_AUDIO_ITEMS]
            state[CAT_ASSETS] = merged[CAT_ASSETS]
            await svc.save_async()
            return BoardMergeResponse(
                ok=True, applied=True, base_available=True,
                board_version=svc.board_version, merged=merged)
        return BoardMergeResponse(
            ok=True, applied=False, base_available=True,
            board_version=svc.board_version, merged=merged, conflicts=conflicts)


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


# ---------- E1 回档三件套（消息级快照指针化 + 版本列表 + 分叉） ----------

class SnapshotItem(BaseModel):
    id: str
    ts: str = ""
    label: str = ""


class SnapshotListResponse(BaseModel):
    snapshots: List[SnapshotItem] = []


class SnapshotActionRequest(BaseModel):
    snapshot_id: str
    name: str = ""  # 仅 fork 用：新项目名称（缺省自动命名）


# 生成任务终态白名单：非终态 = 在飞，回档禁行（E1 生成中禁回退）
_TASK_DONE_STATUSES = (
    "succeeded", "completed", "failed", "cancelled", "canceled",
    "stopped", "error",
)


def _forbid_restore_while_generating() -> None:
    """E1 生成中禁回退：存在非终态生成任务时 409 拒收。"""
    tasks = get_task_manager().list_tasks(limit=200)
    inflight = [
        t for t in tasks
        if str(t.get("status") or "").lower() not in _TASK_DONE_STATUSES
    ]
    if inflight:
        raise VideoAgentError(
            "生成任务进行中禁止回档，请等待生成完成或先停止任务",
            status_code=409,
            error_code="GENERATION_IN_PROGRESS",
        )


@router.get("/project/snapshots", response_model=SnapshotListResponse)
async def list_snapshots_api():
    """E1：故事板面板版本列表（快照指针清单，不含本体）。"""
    return {"snapshots": StateManager.get_instance().list_snapshots()}


@router.post("/project/restore")
async def restore_snapshot_api(body: SnapshotActionRequest):
    """E1：回档到快照时刻（二次确认由前端弹窗把关；
    恢复前自动压 undo 栈，回档本身可 Redo 复核）。"""
    svc = StateManager.get_instance()
    _forbid_restore_while_generating()
    snap = svc.get_snapshot(body.snapshot_id)
    if snap is None:
        raise VideoAgentError(
            f"快照 {body.snapshot_id} 不存在", status_code=404,
            error_code=LEGACY_NOT_FOUND)
    svc.restore_snapshot(snap)
    return {"ok": True, "state": svc.get_full_snapshot()}


@router.post("/project/fork")
async def fork_snapshot_api(body: SnapshotActionRequest):
    """E1：从快照时刻新开项目（分叉；原项目不动）。"""
    svc = StateManager.get_instance()
    _forbid_restore_while_generating()
    pid = svc.fork_from_snapshot(body.snapshot_id, body.name)
    if pid is None:
        raise VideoAgentError(
            f"快照 {body.snapshot_id} 不存在", status_code=404,
            error_code=LEGACY_NOT_FOUND)
    return {"ok": True, "project_id": pid, "projects": svc.list_projects()}
