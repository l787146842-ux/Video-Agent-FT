from abc import ABC, abstractmethod
from pydantic import BaseModel
from typing import Optional, List

class VideoGenerationResponse(BaseModel):
    task_id: str
    status: str  # 'pending', 'processing', 'completed', 'failed'
    video_url: Optional[str] = None
    error_msg: Optional[str] = None
    raw_response: Optional[dict] = None

class BaseVideoAdapter(ABC):
    
    @abstractmethod
    async def generate(self, image_url: str, prompt: str, **kwargs) -> VideoGenerationResponse:
        """
        提交生成任务
        """
        pass

    @abstractmethod
    async def fetch_result(self, task_id: str) -> VideoGenerationResponse:
        """
        查询任务结果
        """
        pass

class ImageGenerationResponse(BaseModel):
    task_id: str
    status: str
    image_urls: List[str] = []
    error_msg: Optional[str] = None
    raw_response: Optional[dict] = None

class BaseImageAdapter(ABC):
    
    @abstractmethod
    async def generate_image(self, prompt: str, reference_image: Optional[str] = None, **kwargs) -> ImageGenerationResponse:
        """
        提交图生图/文生图任务
        """
        pass
        
    @abstractmethod
    async def fetch_result(self, task_id: str) -> ImageGenerationResponse:
        """
        查询图片生成结果
        """
        pass
