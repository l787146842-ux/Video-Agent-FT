# Video Agent v1 — Adapter 接口规范

> Adapter 是系统的最底层驱动。它负责将内部标准化的请求，转换为各个云端模型（如 Kling、Runway）或本地服务（如 ComfyUI）的具体 API 调用。所有的外部 API 调用逻辑必须且只能封装在 Adapter 中。

---

## 一、Adapter 定位与设计原则

```text
Tool ──▶ Adapter Interface (BaseAdapter) ──▶ 具体 Adapter (Kling/ComfyUI) ──▶ 外部 API
```

**核心法则（Rule 4：所有外部服务调用必须实现 Adapter）**
1. **统一模型接口**：为相同类型的 AI 服务（如视频生成、图片生成）定义极其一致的接口。不论底层是 Kling 还是 Runway，对上层 Tool 来说调用方法一致。
2. **凭据集中管理**：API Keys、Tokens、Base URLs 等配置信息由 Adapter 统一读取环境变量或配置中心，Tool 层不允许接触凭据。
3. **隔离底层差异**：统一处理各个平台的特殊重试逻辑、并发限制、特有错误码、鉴权方式及特定的轮询/回调机制。
4. **异步优先**：鉴于 AI 接口耗时较长，Adapter 必须全面支持异步 (async/await) 并提供统一的任务状态查询标准接口。

---

## 二、基础 Adapter 接口定义

在系统中，针对不同类型的生成任务应该定义各自领域的抽象接口。

### 2.1 视频生成 Adapter (BaseVideoAdapter)

```python
from abc import ABC, abstractmethod
from pydantic import BaseModel
from typing import Optional

class VideoGenerationResponse(BaseModel):
    task_id: str
    status: str  # 'pending', 'processing', 'completed', 'failed'
    video_url: Optional[str] = None
    error_msg: Optional[str] = None

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
```

### 2.2 图片生成 Adapter (BaseImageAdapter)

```python
from abc import ABC, abstractmethod
from pydantic import BaseModel
from typing import Optional, List

class ImageGenerationResponse(BaseModel):
    task_id: str
    status: str
    image_urls: List[str] = []
    error_msg: Optional[str] = None

class BaseImageAdapter(ABC):
    
    @abstractmethod
    async def generate_image(self, prompt: str, reference_image: str = None, **kwargs) -> ImageGenerationResponse:
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
```

---

## 三、具体 Adapter 实现示例 (Kling 视频生成 API)

```python
import aiohttp
import os
import asyncio

class KlingVideoAdapter(BaseVideoAdapter):
    def __init__(self):
        self.api_key = os.getenv("KLING_API_KEY")
        self.base_url = "https://api.klingapi.com/v1"
        
    async def generate(self, image_url: str, prompt: str, **kwargs) -> VideoGenerationResponse:
        # 具体 Kling API 的请求封装
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        payload = {
            "image": image_url,
            "prompt": prompt,
            "duration": kwargs.get("duration", 5)
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{self.base_url}/video/generate", json=payload, headers=headers) as response:
                if response.status != 200:
                    text = await response.text()
                    return VideoGenerationResponse(task_id="", status="failed", error_msg=text)
                    
                data = await response.json()
                return VideoGenerationResponse(task_id=data["task_id"], status="pending")

    async def fetch_result(self, task_id: str) -> VideoGenerationResponse:
        headers = {"Authorization": f"Bearer {self.api_key}"}
        
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{self.base_url}/task/{task_id}", headers=headers) as response:
                data = await response.json()
                if data["status"] == "SUCCESS":
                    return VideoGenerationResponse(
                        task_id=task_id, 
                        status="completed", 
                        video_url=data["result_url"]
                    )
                elif data["status"] in ["FAILED", "ERROR"]:
                    return VideoGenerationResponse(
                        task_id=task_id, 
                        status="failed", 
                        error_msg=data.get("error_detail", "Unknown Error")
                    )
                else:
                    return VideoGenerationResponse(task_id=task_id, status="processing")
```

---

## 四、Adapter 工厂与服务定位

上层模块（Tool或系统其他服务）决不能直接 import 具体的 `KlingVideoAdapter`，必须通过简单的工厂模式获取实例，确保随时可以热切换供应商。

```python
class AdapterFactory:
    _adapters = {}

    @classmethod
    def register(cls, adapter_type: str, provider: str, adapter_cls):
        if adapter_type not in cls._adapters:
            cls._adapters[adapter_type] = {}
        cls._adapters[adapter_type][provider] = adapter_cls()

    @classmethod
    def get_adapter(cls, adapter_type: str, provider: str = "default"):
        return cls._adapters.get(adapter_type, {}).get(provider)

# 服务启动时注册
AdapterFactory.register("video_generation", "kling", KlingVideoAdapter)
AdapterFactory.register("video_generation", "runway", RunwayVideoAdapter)
AdapterFactory.register("image_generation", "comfyui", ComfyUIAdapter)

# Tool调用时
video_adapter = AdapterFactory.get_adapter("video_generation", provider="kling")
```

---

## 五、状态轮询与异步等待封装

由于大量的 AI 媒体生成是长耗时操作（几十秒至几十分钟不等），所有依赖拉取结果（Polling）的 Adapter 应当配合标准的轮询辅助方法使用。

```python
async def wait_until_complete(adapter: BaseVideoAdapter, task_id: str, timeout: int = 1200, poll_interval: int = 5):
    """
    通用长任务轮询辅助函数
    """
    import time
    start_time = time.time()
    
    while time.time() - start_time < timeout:
        result = await adapter.fetch_result(task_id)
        if result.status == "completed":
            return result
        if result.status == "failed":
            raise Exception(f"Generation task failed: {result.error_msg}")
            
        await asyncio.sleep(poll_interval)
        
    return {"status": "failed", "error": "生成超时"}(f"Task {task_id} timeout after {timeout} seconds")
```
