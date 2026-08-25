"""生成路由共享设施：任务管理、SSE 通知、请求模型、轮询。

被 generate_image.py / generate_video.py / generate.py 共用，本身不注册路由。
"""
import asyncio
import time
from typing import Any, Dict, List

from pydantic import BaseModel

from loguru import logger

from src.video_agent.adapters.factory import AdapterFactory
from src.video_agent.config import settings

# 任务管理：委托给 GenerationTaskManager 单例
from src.video_agent.web.task_manager import (
    get_task_manager,
    writeback_if_complete as _writeback_if_complete,
)

_tm = get_task_manager()

# 向后兼容别名（供 actions.py 等模块导入）
_tasks = _tm.tasks


def _notify_sse(event_data: Dict[str, Any]) -> None:
    """向所有 SSE 订阅者推送任务完成事件"""
    _tm.notify(event_data)


def _track_task(coro) -> None:
    """创建并追踪后台任务"""
    _tm.track(coro)


def _log_task_exception(task: asyncio.Task) -> None:
    """兼容别名"""
    pass


# 任务保留时长（秒）：超过后在下一次写入时清理，防止内存无限增长
_TASK_TTL_SECONDS = settings.task_ttl_seconds
_TASK_MAX = settings.task_max

# mock 视频用可播放的示例视频，而不是死链
MOCK_VIDEO_URL = "https://interactive-examples.mdn.mozilla.net/media/cc0-videos/flower.mp4"


def _new_task(task_id: str, **fields: Any) -> Dict[str, Any]:
    return _tm.create_task(task_id, **fields)


class ImageGenRequest(BaseModel):
    prompt: str
    provider_id: str = ""
    model: str = ""
    size: str = "1280x720"
    aspect_ratio: str = "16:9"
    # 分辨率档位（1K/2K/4K）：CLI 类供应商无 size 参数，靠提示词感知
    resolution: str = ""
    reference_images: List[Dict[str, str]] = []
    # 关联到哪个 draft（完成后服务端自动回写）
    draft_id: str = ""
    draft_type: str = "keyElement"


class VideoGenRequest(BaseModel):
    prompt: str
    provider_id: str = ""
    model: str = ""
    duration: int = 5
    resolution: str = "1080p"
    aspect_ratio: str = "16:9"
    images: List[Dict[str, str]] = []
    # 视频参考素材（C3：Seedance 2.5 支持 ≤10 段视频参考，每项 {url, role?}）
    videos: List[Dict[str, str]] = []
    # 音色参考音频列表（Seedance 2.0 MultiModalToVideo 参考项，每项 {url, name?}）
    audios: List[Dict[str, str]] = []
    enhance_prompt: bool = False
    multimodal: bool = False
    draft_id: str = ""
    draft_type: str = "shot"


class BatchImageGenRequest(BaseModel):
    target: str = "all_shots"  # "all_keyElements" / "all_shots" / 逗号分隔的 draft_id
    provider_id: str = ""
    model: str = ""
    size: str = "1280x720"
    aspect_ratio: str = "16:9"


class GenLogRequest(BaseModel):
    media_type: str  # image | video | audio
    status: str      # started | succeeded | failed
    provider: str = ""
    model: str = ""
    prompt: str = ""
    draft_id: str = ""
    error: str = ""
    result_url: str = ""
    elapsed: float = 0.0
    requested_size: str = ""
    source: str = "manual"


async def poll_task(task_id: str) -> Dict[str, Any]:
    """通用任务状态轮询（图片/视频端点共用）"""
    task = _tasks.get(task_id)
    if not task:
        return {"status": "not_found"}

    if task["status"] in ("succeeded", "completed", "failed"):
        return {**task, "elapsed": task.get("elapsed") or round(time.time() - task.get("created_at", time.time()), 1)}

    adapter_name = task.get("adapter_name", "")
    if adapter_name:
        try:
            adapter = AdapterFactory.get_adapter(task["adapter_type"], adapter_name)
            result = await adapter.fetch_result(task_id)
            if result.status == "completed":
                task["status"] = "succeeded"
                # result 可能是 VideoGenerationResponse 或 ImageGenerationResponse，
                # 两者字段不重叠，getattr 是跨类型的合理探测（非冗余防御）
                if getattr(result, "video_url", None):
                    # mock 视频适配器返回的是演示占位地址，替换为可播放的示例视频
                    task["video_url"] = MOCK_VIDEO_URL if task.get("mock") else result.video_url
                if getattr(result, "image_urls", None):
                    urls = result.image_urls
                    if task.get("mock"):
                        # mock 图片适配器的 mock-storage.local 是死链，换成可显示的占位图
                        urls = [f"https://picsum.photos/seed/{task_id}/1280/720"]
                    task["result"] = {"images": urls}
                _writeback_if_complete(task_id)
            elif result.status == "failed":
                task["status"] = "failed"
                task["error"] = result.error_msg
        except Exception as e:
            logger.warning(f"[Generate] Poll error for {task_id}: {e}")

    return {**task, "elapsed": task.get("elapsed") or round(time.time() - task.get("created_at", time.time()), 1)}
