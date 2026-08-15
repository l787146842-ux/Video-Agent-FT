"""B9：视频批量生成队列 API（提交/查询/断点续跑/取消）。"""
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()


class VideoBatchCreate(BaseModel):
    provider_id: str = ""
    model: str = ""
    resolution: str = ""
    duration: int = 0
    shot_group_ids: Optional[List[str]] = None


@router.post("/generate/video-batch")
async def create_video_batch(body: VideoBatchCreate):
    """按故事板分镜清单创建批量视频生成任务，立即返回 batch_id（后台逐镜提交）。"""
    from src.video_agent.state.manager import StateManager
    from src.video_agent.web.video_batch import get_video_batch_manager

    project_id = StateManager.get_instance().active_project_id or ""
    try:
        return get_video_batch_manager().create(
            project_id, body.provider_id, body.model,
            resolution=body.resolution, duration=body.duration,
            shot_group_ids=body.shot_group_ids,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/generate/video-batch")
async def list_video_batches(project_id: str = ""):
    """列出批量任务（最新在前）。"""
    from src.video_agent.web.video_batch import get_video_batch_manager

    return {"batches": get_video_batch_manager().list(project_id)}


@router.get("/generate/video-batch/{batch_id}")
async def get_video_batch(batch_id: str):
    """查询单个批次（逐镜状态/错误）。"""
    from src.video_agent.web.video_batch import get_video_batch_manager

    try:
        return get_video_batch_manager().get(batch_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"批次 '{batch_id}' 不存在")


@router.post("/generate/video-batch/{batch_id}/resume")
async def resume_video_batch(batch_id: str):
    """断点续跑：只重试 failed/pending 镜，已成功镜跳过（任务级 + 步骤级）。"""
    from src.video_agent.web.video_batch import get_video_batch_manager

    try:
        return get_video_batch_manager().resume(batch_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"批次 '{batch_id}' 不存在")


@router.post("/generate/video-batch/{batch_id}/cancel")
async def cancel_video_batch(batch_id: str):
    """取消批次（已提交的生成任务由生成管线各自完成，不再提交新镜）。"""
    from src.video_agent.web.video_batch import get_video_batch_manager

    ok = get_video_batch_manager().cancel(batch_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"批次 '{batch_id}' 不存在")
    return {"ok": True}
