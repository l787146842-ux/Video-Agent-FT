"""
/api/project — 项目状态端点
负责前端与 StudioStateService 之间的状态读写、多项目管理。
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel
from typing import Any, Dict, List, Optional

from src.video_agent.exceptions import StateConflictError, VideoAgentError
from src.video_agent.state import board_merge, conversation_ops
from src.video_agent.state.board_merge import CAT_ASSETS
from src.video_agent.state.manager import StateManager
from src.video_agent.state.models import (
    CAT_KEY_ELEMENTS, CAT_SHOTS, CAT_AUDIO_ITEMS,
    KeyElementGroup, ShotGroup, AudioGroup, FrontendAsset, ChatMessage,
)
from src.video_agent.utils import gen_id
from src.video_agent.utils.live_metrics import record_degradation
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
    # 五列表以宽松 Dict 收料 + 路由层逐元素软校验（评审返修）：
    # 整板强类型化（List[KeyElementGroup] 等）会让单个退化元素（老落盘数据缺
    # id/text 等必填字段）拖垮整次保存 → 整板 422、前端全量保存直接失败。改为
    # List[Dict] 收料，落盘前经 _coerce_elements 逐元素 model_validate：合法元素
    # 照常回转（by_alias + exclude_unset，往返零丢字段、不注入默认值），非法元素
    # 丢弃并记 record_degradation("project_state.element_rejected") 计数（可观测非静默）。
    keyElements: Optional[List[Dict[str, Any]]] = None
    shots: Optional[List[Dict[str, Any]]] = None
    audioItems: Optional[List[Dict[str, Any]]] = None
    assets: Optional[List[Dict[str, Any]]] = None
    chatMessages: Optional[List[Dict[str, Any]]] = None


def _coerce_elements(
    items: Optional[List[Dict[str, Any]]],
    model_cls: type,
) -> Optional[List[Dict[str, Any]]]:
    """逐元素软校验 + 回转落盘 dict（整板 PUT 不因单个退化元素整板 422）。

    - 逐元素 model_cls.model_validate：合法元素照常回转，非法元素（缺 id/text 等
      必填字段的老落盘数据）丢弃 + record_degradation 计数（可观测，不静默）；
    - by_alias=True：输出前端 camelCase 键（与提交形态一致）；
    - mode="json"：产出 JSON 兼容纯量，供下游裸 json.dumps 落盘链路直接消费；
    - exclude_unset=True：只回传实际提交字段（保留 extra="allow" 透传的未建模
      额外字段，又不注入模型默认值污染落盘形态/回传快照）。
    None 原样返回（未提交的列表不参与落盘，保持部分保存语义）。
    """
    if items is None:
        return None
    out: List[Dict[str, Any]] = []
    for el in items:
        try:
            m = model_cls.model_validate(el)
        except Exception:
            record_degradation("project_state.element_rejected")
            continue
        out.append(m.model_dump(by_alias=True, mode="json", exclude_unset=True))
    return out


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


def _state_etag(snapshot: Dict[str, Any]) -> str:
    """状态 ETag：project_id + board_version 双因子派生的弱校验子（W/）。

    单靠 board_version 非单射——每项目独立账本、新建/分叉项目都从 0 起算，
    跨项目相同 bv 会让浏览器 304 命中另一项目的缓存体（串台）。加 project_id
    前缀使 (project_id, bv) → ETag 单射；弱校验子语义不变（仅实质状态变更失效，
    投影/序列化差异不触发）。
    """
    pid = str(snapshot.get("project_id", "") or "")
    bv = snapshot.get("board_version", 0)
    return f'W/"{pid}-{bv}"'


def _opaque_tag(etag: str) -> str:
    """剥弱校验子前缀 W/ 取 opaque-tag（RFC9110 弱比较只比 opaque-tag）。"""
    e = (etag or "").strip()
    if e[:2].lower() == "w/":
        e = e[2:].strip()
    return e


def _parse_if_none_match(value: str) -> List[str]:
    """解析 If-None-Match 头为候选 token 列表（RFC9110）。

    逗号分隔多候选，但引号内的逗号不作分隔（opaque-tag 可含逗号）；
    保留原始 token（含可能的 W/ 前缀与引号），交由弱比较处理。
    """
    out: List[str] = []
    buf: List[str] = []
    in_quotes = False
    for ch in value:
        if ch == '"':
            in_quotes = not in_quotes
            buf.append(ch)
        elif ch == "," and not in_quotes:
            out.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
    tail = "".join(buf).strip()
    if tail:
        out.append(tail)
    return [c for c in out if c]


def _etag_matches(if_none_match: str, etag: str) -> bool:
    """If-None-Match 命中判定（RFC9110 弱比较）：
    - `*`（含候选列表内的 `*`）匹配任意现有表示；
    - 逐个候选剥 W/ 前缀比 opaque-tag（弱校验子语义：允许非实质差异）。
    """
    inm = (if_none_match or "").strip()
    if not inm:
        return False
    target = _opaque_tag(etag)
    for cand in _parse_if_none_match(inm):
        if cand == "*":
            return True
        if _opaque_tag(cand) == target:
            return True
    return False


@router.get("/project/state", response_model=ProjectStateResponse)
@router.get("/state", response_model=ProjectStateResponse)              # 设计方案路径别名
async def get_project_state(request: Request, response: Response):
    """前端初始化加载 / Agent 刷新状态。

    支持 ETag/If-None-Match 条件请求：状态未变（board_version 不变）回 304
    免传全量快照，降低轮询/重复拉取开销。
    """
    svc = StateManager.get_instance()
    snapshot = svc.get_full_snapshot()
    etag = _state_etag(snapshot)
    response.headers["ETag"] = etag
    # 私有缓存 + no-cache：状态含项目内容不得被共享缓存（代理/CDN）留存；
    # no-cache 强制每次带 ETag 回源校验（未变才 304），杜绝跨项目/跨用户回吐缓存体
    response.headers["Cache-Control"] = "private, no-cache"
    if _etag_matches(request.headers.get("if-none-match", ""), etag):
        # 304 无体：直接返回 Response 绕过 response_model 序列化（同带缓存头）
        return Response(status_code=304, headers={
            "ETag": etag, "Cache-Control": "private, no-cache",
        })
    return snapshot


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


def _media_fingerprint(state) -> List[str]:
    """批 2 · 插播报：项目媒体状态指纹（草稿媒体 URL + 素材绑定）。

    整板落库前后对比，变化即记 media_synced 流事件（「素材变更已同步」卡
    的唯一触发依据；纯标题/排序改动不算媒体变更，不播报）。
    """
    items: List[str] = []
    for cat in (CAT_KEY_ELEMENTS, CAT_SHOTS, CAT_AUDIO_ITEMS):
        for g in (state.get(cat) or []):
            if not isinstance(g, dict):
                continue
            for d in (g.get("drafts") or []):
                if not isinstance(d, dict):
                    continue
                urls = (str(d.get("imgUrl") or ""), str(d.get("videoUrl") or ""),
                        str(d.get("audioUrl") or ""))
                if not any(urls):
                    continue  # 无媒体的空卡不构成媒体状态
                items.append("|".join((cat, str(d.get("id") or ""), *urls)))
    for a in (state.get(CAT_ASSETS) or []):
        if isinstance(a, dict) and (a.get("url") or a.get("isBound")):
            items.append("|".join((
                "asset", str(a.get("id") or ""), str(a.get("url") or ""),
                str(a.get("isBound") or ""),
            )))
    return sorted(items)


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
        _media_before = _media_fingerprint(state)

        # 元素逐元素软校验→dict 回转（入口单点）：下游级联 diff / board_merge / 落盘
        # 均消费纯 dict，与建模前形态一致（exclude_unset 保证与提交同形）。
        key_elements = _coerce_elements(body.keyElements, KeyElementGroup)
        shots = _coerce_elements(body.shots, ShotGroup)
        audio_items = _coerce_elements(body.audioItems, AudioGroup)
        assets = _coerce_elements(body.assets, FrontendAsset)
        chat_messages = _coerce_elements(body.chatMessages, ChatMessage)

        # 对象删除级联（二期子对话批 1）：落盘前对提交列表做新旧草稿 id diff，
        # 硬删命中的 scope 隐藏线程（先掐绑定在途任务）；线程随撤销快照原子恢复。
        _old_ids, _new_ids = set(), set()
        for _cat, _incoming in (
            (CAT_KEY_ELEMENTS, key_elements),
            (CAT_SHOTS, shots),
            (CAT_AUDIO_ITEMS, audio_items),
        ):
            if _incoming is None:
                continue
            _old_ids |= conversation_ops.board_draft_ids(state.get(_cat) or [])
            _new_ids |= conversation_ops.board_draft_ids(_incoming)
        # 素材池来源草稿计入存活集（评审修补批）：「移入未归类素材池」是
        # 可还原的非破坏移动，其来源草稿线程不得被误当删除级联硬删；
        # assets 未提交（None）时沿用服务端现状口径。
        if assets is not None:
            _new_ids |= conversation_ops.asset_pool_draft_ids(assets)
        else:
            _new_ids |= conversation_ops.asset_pool_draft_ids(state.get(CAT_ASSETS) or [])
        if _old_ids - _new_ids:
            conversation_ops.cleanup_scoped_threads_for_removed(
                svc, _old_ids - _new_ids, save=False,
                stop_tasks=stop_tasks_bound_to_conversations)

        if key_elements is not None:
            state[CAT_KEY_ELEMENTS] = key_elements
        if shots is not None:
            state[CAT_SHOTS] = shots
        if audio_items is not None:
            state[CAT_AUDIO_ITEMS] = audio_items
        if assets is not None:
            state["assets"] = assets
        if chat_messages is not None:
            state["chatMessages"] = chat_messages

        # 批 2 · 插播报：媒体状态真实变化才记一次性同步事件（下一轮对话
        # 轮始播报「素材变更已同步」；纯标题/排序保存不播报）
        if _media_fingerprint(state) != _media_before:
            svc.record_flow_event("media_synced", "项目素材媒体已更新")

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
        _media_before = _media_fingerprint(state)
        # 元素逐元素软校验→dict 回转（同整板 PUT 口径）：board_merge 按纯 dict 粒度三向合并；
        # 空列表提交（清板）与 None（未提交）语义不同，故用 is not None 判别、不以真值回落。
        key_elements = _coerce_elements(body.keyElements, KeyElementGroup)
        shots = _coerce_elements(body.shots, ShotGroup)
        audio_items = _coerce_elements(body.audioItems, AudioGroup)
        assets = _coerce_elements(body.assets, FrontendAsset)
        mine = {
            CAT_KEY_ELEMENTS: key_elements if key_elements is not None else list(state.get(CAT_KEY_ELEMENTS) or []),
            CAT_SHOTS: shots if shots is not None else list(state.get(CAT_SHOTS) or []),
            CAT_AUDIO_ITEMS: audio_items if audio_items is not None else list(state.get(CAT_AUDIO_ITEMS) or []),
            CAT_ASSETS: assets if assets is not None else list(state.get(CAT_ASSETS) or []),
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
            # 对象删除级联（同整板 PUT 口径）：落盘分支新旧草稿 id diff 清线程；
            # 素材池来源草稿计入存活集（评审修补批，同整板 PUT）
            _old_ids, _new_ids = set(), set()
            for _cat in (CAT_KEY_ELEMENTS, CAT_SHOTS, CAT_AUDIO_ITEMS):
                _old_ids |= conversation_ops.board_draft_ids(state.get(_cat) or [])
                _new_ids |= conversation_ops.board_draft_ids(merged.get(_cat) or [])
            _new_ids |= conversation_ops.asset_pool_draft_ids(merged.get(CAT_ASSETS) or [])
            if _old_ids - _new_ids:
                conversation_ops.cleanup_scoped_threads_for_removed(
                    svc, _old_ids - _new_ids, save=False,
                    stop_tasks=stop_tasks_bound_to_conversations)
            state[CAT_KEY_ELEMENTS] = merged[CAT_KEY_ELEMENTS]
            state[CAT_SHOTS] = merged[CAT_SHOTS]
            state[CAT_AUDIO_ITEMS] = merged[CAT_AUDIO_ITEMS]
            state[CAT_ASSETS] = merged[CAT_ASSETS]
            # 批 2 · 插播报：同整板 PUT 口径（媒体真实变化才记一次性同步事件）
            if _media_fingerprint(state) != _media_before:
                svc.record_flow_event("media_synced", "项目素材媒体已更新")
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
