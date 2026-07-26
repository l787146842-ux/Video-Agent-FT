from .base import (
    BaseVideoAdapter,
    BaseImageAdapter,
    VideoGenerationResponse,
    ImageGenerationResponse
)
from .factory import AdapterFactory, wait_until_complete
from .mock_adapters import MockVideoAdapter, MockImageAdapter

# Bootstrapping Mocks into the factory for development usage by default
AdapterFactory.register("video_generation", "mock", MockVideoAdapter())
AdapterFactory.register("image_generation", "mock", MockImageAdapter())

__all__ = [
    "BaseVideoAdapter",
    "BaseImageAdapter",
    "VideoGenerationResponse",
    "ImageGenerationResponse",
    "AdapterFactory",
    "wait_until_complete",
    "MockVideoAdapter",
    "MockImageAdapter"
]
