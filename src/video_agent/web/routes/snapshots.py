"""B11：对话分支 / 工作流快照。

- 快照 = 当前对话消息 + 状态快照 + trace 引用的不可变副本
  （workspace/snapshots/<project>/<snap_id>.json）；
- 分支 = 从快照派生新对话（消息装载进新对话，原对话与当前状态不动——
  非破坏性；状态回滚属危险操作，另行走版本账本）；
- 快照列表可预览/删除。
"""
import json
import time
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException
from loguru import logger
from pydantic import BaseModel

from src.video_agent.state.manager import StateManager
from src.video_agent.utils import gen_id
from src.video_agent.utils.fileio import atomic_write_text
from src.video_agent.utils.paths import WORKSPACE_DIR

router = APIRouter()


def _snap_dir(project_id: str):
    d = WORKSPACE_DIR / "snapshots" / (project_id or "_")
    d.mkdir(parents=True, exist_ok=True)
    return d


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
async def create_snapshot():
    """把当前活跃对话打为不可变快照（消息 + 状态 + trace 引用）。"""
    svc = StateManager.get_instance()
    async with svc.lock:
        payload = svc.list_conversations()
    active = next(
        (c for c in payload.get("conversations") or [] if c.get("id") == payload.get("active_conversation_id")),
        None,
    )
    if active is None:
        raise HTTPException(status_code=400, detail="没有可快照的对话")
    snap_id = gen_id("snap")
    record = {
        "snap_id": snap_id,
        "project_id": svc.active_project_id or "",
        "title": str(active.get("title") or "工作流快照"),
        "messages": active.get("messages") or [],
        "state": svc.get_full_snapshot(),
        "created_at": time.time(),
    }
    f = _snap_dir(record["project_id"]) / f"{snap_id}.json"
    atomic_write_text(f, json.dumps(record, ensure_ascii=False))
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
