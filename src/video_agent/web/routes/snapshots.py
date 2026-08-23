"""B11：对话分支 / 工作流快照。

- 快照 = 当前对话消息 + 状态快照 + trace 引用的不可变副本
  （workspace/snapshots/<project>/<snap_id>.json）；
- 分支 = 从快照派生新对话（消息装载进新对话，原对话与当前状态不动——
  非破坏性；状态回滚属危险操作，另行走版本账本）；
- 快照列表可预览/删除。
"""
import json
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from loguru import logger
from pydantic import BaseModel

from src.video_agent.config import settings
from src.video_agent.state.manager import StateManager
from src.video_agent.utils import gen_id
from src.video_agent.utils.fileio import atomic_write_text
from src.video_agent.utils.paths import WORKSPACE_DIR
from src.video_agent.web.error_payload import classify_legacy_code

router = APIRouter()


def _snap_dir(project_id: str):
    d = WORKSPACE_DIR / "snapshots" / (project_id or "_")
    d.mkdir(parents=True, exist_ok=True)
    return d


def _prune_snapshots(project_id: str) -> int:
    """每项目快照数量上限（默认 20，SNAPSHOT_MAX_PER_PROJECT 可配）。

    超限淘汰最旧（按 created_at 升序）：快照数据结构无手动标记/置顶字段，
    最简且语义清晰的策略即「最新优先保留」；淘汰在创建成功后执行，
    新快照永不被当次淘汰。返回删除数量。
    """
    cap = max(1, int(settings.snapshot_max_per_project))
    entries = []
    for f in _snap_dir(project_id).glob("*.json"):
        try:
            created = float(json.loads(f.read_text(encoding="utf-8")).get("created_at") or 0.0)
        except Exception:
            created = 0.0  # 损坏/缺字段视为最旧，优先淘汰
        entries.append((created, f))
    removed = 0
    for _, f in sorted(entries, key=lambda e: e[0]):
        if len(entries) - removed <= cap:
            break
        try:
            f.unlink()
            removed += 1
            logger.info(f"[Snapshot] 超出上限（{cap}），已淘汰最旧快照 {f.stem}")
        except OSError as e:
            logger.warning(f"[Snapshot] 淘汰快照失败 {f.name}: {e}")
    return removed


def _read_snapshot(project_id: str, snap_id: str) -> Dict[str, Any]:
    f = _snap_dir(project_id) / f"{snap_id}.json"
    if not f.exists():
        raise HTTPException(status_code=404, detail="快照不存在")
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"快照读取失败: {e}")


class BranchRequest(BaseModel):
    title: str = ""


class SnapshotRequest(BaseModel):
    # 分叉点截断（任务 #16）：提供时快照仅含 messages[:up_to_index+1]（含该条）；
    # 不提供时全量快照（既有调用零行为变化）
    up_to_index: Optional[int] = None


@router.get("/conversations/snapshots")
async def list_snapshots():
    """列出当前项目全部快照（元信息，不含全文）。"""
    svc = StateManager.get_instance()
    pid = svc.active_project_id or ""
    out: List[Dict[str, Any]] = []
    for f in sorted(_snap_dir(pid).glob("*.json"), reverse=True):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            out.append({
                "snap_id": data.get("snap_id"),
                "title": data.get("title"),
                "message_count": len(data.get("messages") or []),
                "created_at": data.get("created_at"),
            })
        except Exception:
            continue
    return {"snapshots": out}


@router.post("/conversations/snapshot")
async def create_snapshot(body: SnapshotRequest = SnapshotRequest()):
    """把当前活跃对话打为不可变快照（消息 + 状态 + trace 引用）。

    up_to_index（可选，分叉点）：仅截取至该索引（含）；越界/为负返回 400
    结构化错误。派生分支接口不变：分支装载快照内的全部消息。
    """
    svc = StateManager.get_instance()
    async with svc.lock:
        payload = svc.list_conversations()
    active = next(
        (c for c in payload.get("conversations") or [] if c.get("id") == payload.get("active_conversation_id")),
        None,
    )
    if active is None:
        raise HTTPException(status_code=400, detail="没有可快照的对话")
    messages = list(active.get("messages") or [])
    if body.up_to_index is not None:
        if body.up_to_index < 0 or body.up_to_index >= len(messages):
            msg = f"up_to_index 越界：{body.up_to_index}（当前对话共 {len(messages)} 条消息）"
            return JSONResponse(
                status_code=400,
                content=classify_legacy_code("SNAPSHOT_INDEX_OUT_OF_RANGE", msg).http_body(
                    "SNAPSHOT_INDEX_OUT_OF_RANGE"),
            )
        messages = messages[: body.up_to_index + 1]
    snap_id = gen_id("snap")
    record = {
        "snap_id": snap_id,
        "project_id": svc.active_project_id or "",
        "title": str(active.get("title") or "工作流快照"),
        "messages": messages,
        "state": svc.get_full_snapshot(),
        "created_at": time.time(),
    }
    f = _snap_dir(record["project_id"]) / f"{snap_id}.json"
    atomic_write_text(f, json.dumps(record, ensure_ascii=False))
    _prune_snapshots(record["project_id"])
    logger.info(f"[Snapshot] 已创建快照 {snap_id}（{len(record['messages'])} 条消息）")
    return {"snap_id": snap_id, "title": record["title"]}


@router.get("/conversations/snapshots/{snap_id}")
async def get_snapshot(snap_id: str):
    """查看快照详情（消息 + 状态）。"""
    svc = StateManager.get_instance()
    return _read_snapshot(svc.active_project_id or "", snap_id)


@router.post("/conversations/snapshots/{snap_id}/branch")
async def branch_snapshot(snap_id: str, body: BranchRequest):
    """从快照派生新对话（分支）：消息装载进新对话并设为活跃；当前状态不动。"""
    svc = StateManager.get_instance()
    snap = _read_snapshot(svc.active_project_id or "", snap_id)
    async with svc.lock:
        payload = svc.create_conversation(body.title or f"{snap.get('title', '分支')} · 分支")
        conv_id = payload.get("active_conversation_id") or ""
        convs = svc.state_dict.setdefault("conversations", [])
        for c in convs:
            if c.get("id") == conv_id:
                c["messages"] = list(snap.get("messages") or [])
                c["title"] = body.title or f"{snap.get('title', '分支')} · 分支"
                c.setdefault("_meta", {})["branched_from"] = snap_id
                break
        svc.save()
    logger.info(f"[Snapshot] 从 {snap_id} 派生分支对话 {conv_id}")
    return svc.list_conversations()


@router.delete("/conversations/snapshots/{snap_id}")
async def delete_snapshot(snap_id: str):
    """删除快照（不影响任何对话）。"""
    svc = StateManager.get_instance()
    f = _snap_dir(svc.active_project_id or "") / f"{snap_id}.json"
    if not f.exists():
        raise HTTPException(status_code=404, detail="快照不存在")
    f.unlink()
    return {"ok": True}
