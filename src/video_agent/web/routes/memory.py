"""
/api/memory — 记忆管理端点（4.7：记忆对用户可见可管理，不再是黑盒注入）

- GET  /api/memory?project_id=xxx   清单（置顶优先，其余新→旧；project_id 可选过滤）
- POST /api/memory/{id}/pin         置顶/取消置顶（M4）
- DELETE /api/memory/{id}           删除单条
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.video_agent.memory import MemoryManager

router = APIRouter()


@router.get("/memory")
async def list_memory(project_id: str = ""):
    """记忆清单（管理面板用）；backend 标识当前向量后端（chromadb/json）"""
    mm = MemoryManager.get_instance()
    records = mm.list_records(project_id=project_id)
    return {
        "backend": mm.backend_name,
        "records": [
            {
                "id": r.id,
                "kind": r.kind,
                "content": r.content,
                "source": r.source,
                "project_id": r.project_id,
                "created_at": r.created_at,
                "keywords": r.keywords,
                "pinned": r.pinned,
            }
            for r in records
        ],
    }


class PinBody(BaseModel):
    pinned: bool = True


@router.post("/memory/{record_id}/pin")
async def pin_memory(record_id: str, body: PinBody):
    """置顶/取消置顶；置顶记忆永远排在清单最前，且豁免将来的自动清理"""
    mm = MemoryManager.get_instance()
    if not mm.pin_record(record_id, body.pinned):
        raise HTTPException(status_code=404, detail=f"记忆 '{record_id}' 不存在")
    return {"ok": True}


@router.delete("/memory/{record_id}")
async def delete_memory(record_id: str):
    """删除单条记忆；不存在返回 404"""
    mm = MemoryManager.get_instance()
    if not mm.delete_record(record_id):
        raise HTTPException(status_code=404, detail=f"记忆 '{record_id}' 不存在")
    return {"ok": True}
