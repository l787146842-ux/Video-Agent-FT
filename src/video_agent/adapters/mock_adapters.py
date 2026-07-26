import asyncio
import uuid
import time
from typing import Optional

from .base import (
    BaseVideoAdapter,
    BaseImageAdapter,
    VideoGenerationResponse,
    ImageGenerationResponse
)

class MockVideoAdapter(BaseVideoAdapter):
    def __init__(self, delay_seconds: int = 2, pre_configured_status: str = "completed"):
        self.delay_seconds = delay_seconds
        self.pre_configured_status = pre_configured_status
        # In-memory "database" dict mapping task_id to status and start_time
        self._tasks = {}

    async def generate(self, image_url: str, prompt: str, **kwargs) -> VideoGenerationResponse:
        task_id = f"mock_vid_{uuid.uuid4().hex[:8]}"
        self._tasks[task_id] = {
            "start_time": time.time(),
            "target_status": self.pre_configured_status
        }
        return VideoGenerationResponse(task_id=task_id, status="pending")

    async def fetch_result(self, task_id: str) -> VideoGenerationResponse:
        if task_id not in self._tasks:
            return VideoGenerationResponse(
                task_id=task_id, status="failed", error_msg="Task ID not found in Mock"
            )
            
        task_info = self._tasks[task_id]
        elapsed = time.time() - task_info["start_time"]
        
        if elapsed < self.delay_seconds:
            return VideoGenerationResponse(task_id=task_id, status="processing")
            
        target_status = task_info["target_status"]
        if target_status == "completed":
            return VideoGenerationResponse(
                task_id=task_id, 
                status="completed", 
                video_url=f"http://mock-storage.local/video/{task_id}.mp4"
            )
        else:
            return VideoGenerationResponse(
                task_id=task_id, 
                status="failed", 
                error_msg="Simulated Mock Failure"
            )


class MockImageAdapter(BaseImageAdapter):
    def __init__(self, delay_seconds: int = 1, pre_configured_status: str = "completed"):
        self.delay_seconds = delay_seconds
        self.pre_configured_status = pre_configured_status
        self._tasks = {}

    async def generate_image(self, prompt: str, reference_image: Optional[str] = None, **kwargs) -> ImageGenerationResponse:
        task_id = f"mock_img_{uuid.uuid4().hex[:8]}"
        self._tasks[task_id] = {
            "start_time": time.time(),
            "target_status": self.pre_configured_status
        }
        return ImageGenerationResponse(task_id=task_id, status="pending")

    async def fetch_result(self, task_id: str) -> ImageGenerationResponse:
        if task_id not in self._tasks:
            return ImageGenerationResponse(
                task_id=task_id, status="failed", error_msg="Task ID not found in Mock"
            )
            
        task_info = self._tasks[task_id]
        elapsed = time.time() - task_info["start_time"]
        
        if elapsed < self.delay_seconds:
            return ImageGenerationResponse(task_id=task_id, status="processing")
            
        target_status = task_info["target_status"]
        if target_status == "completed":
            return ImageGenerationResponse(
                task_id=task_id, 
                status="completed", 
                image_urls=[f"http://mock-storage.local/image/{task_id}.png"]
            )
        else:
            return ImageGenerationResponse(
                task_id=task_id, 
                status="failed", 
                error_msg="Simulated Mock Failure"
            )
