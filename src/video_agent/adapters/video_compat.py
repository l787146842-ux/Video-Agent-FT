"""
OpenAI 兼容视频生成适配器（ModelScope / 华为 MaaS 等异步任务 API）。

API 格式：
    提交: POST {base_url}/video/generations
          Body: {model, input: {prompt, img_url?}, parameters: {size?, duration?, fps?}}
          返回: {task_id, status} 或 {output: {task_id, task_status}}

    轮询: GET {base_url}/tasks/{task_id}
          返回: {status/task_status, video_url/output}

遵循 Rule4：外部调用走 Adapter。
"""
import time
from typing import Any, Dict, Optional

import httpx
from loguru import logger

from src.video_agent.config import settings
from src.video_agent.exceptions import AdapterError
from .base import BaseVideoAdapter, VideoGenerationResponse


class OpenAICompatVideoAdapter(BaseVideoAdapter):
    """
    通用 OpenAI 兼容视频生成适配器。

    支持 ModelScope（api-inference.modelscope.cn）和其他兼容
    POST /video/generations + GET /tasks/{task_id} 格式的供应商。
    """

    def __init__(self, base_url: str, api_key: str = "", model: str = ""):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self._client: Optional[httpx.AsyncClient] = None

    def _headers(self) -> Dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    def _get_client(self, timeout: int = 60) -> httpx.AsyncClient:
        """Lazy 创建/复用 httpx 客户端"""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(timeout, connect=10.0),
                headers=self._headers(),
            )
        return self._client

    async def close(self) -> None:
        """释放 HTTP 连接池资源"""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def generate(self, image_url: str = "", prompt: str = "", **kwargs) -> VideoGenerationResponse:
        """
        提交视频生成任务。

        参数：
            image_url: 首帧图片 URL（图生视频模式，可选）
            prompt: 视频动态描述提示词
            kwargs: duration(int), resolution(str), aspect_ratio(str), model(str)
        """
        model = kwargs.get("model") or self.model
        if not model:
            raise AdapterError("视频生成失败：未指定视频模型", error_code="VIDEO_NO_MODEL")

        duration = kwargs.get("duration", 5)
        resolution = kwargs.get("resolution", "720p")
        aspect_ratio = kwargs.get("aspect_ratio", "16:9")

        # 构建分辨率尺寸
        size = self._resolve_size(resolution, aspect_ratio)

        # 构建请求体（ModelScope / 华为 MaaS 兼容格式）
        input_data: Dict[str, Any] = {"prompt": prompt}
        if image_url:
            input_data["img_url"] = image_url

        payload = {
            "model": model,
            "input": input_data,
            "parameters": {
                "size": size,
                "duration": duration,
            },
        }

        try:
            client = self._get_client(60)
            resp = await client.post("/videos/generations", json=payload)

            if resp.status_code in (200, 201, 202):
                data = resp.json()
                task_id = self._extract_task_id(data)
                if task_id:
                    logger.info(f"[VideoAdapter] 任务已提交: {task_id} (model={model})")
                    return VideoGenerationResponse(task_id=task_id, status="processing")
                # 某些 API 同步返回结果
                video_url = self._extract_video_url(data)
                if video_url:
                    return VideoGenerationResponse(
                        task_id=f"vid-{int(time.time())}", status="completed", video_url=video_url
                    )
                raise AdapterError(
                    f"视频 API 返回 200 但无法解析 task_id: {str(data)[:200]}",
                    error_code="VIDEO_PARSE_ERROR",
                )
            else:
                error_text = resp.text[:300]
                raise AdapterError(
                    f"视频生成提交失败 [HTTP {resp.status_code}]: {error_text}",
                    status_code=resp.status_code,
                    error_code="VIDEO_SUBMIT_FAILED",
                )
        except httpx.ConnectError as e:
            raise AdapterError(
                f"视频生成失败：无法连接 API 服务 ({self.base_url})",
                error_code="VIDEO_CONNECT_ERROR",
            ) from e
        except httpx.TimeoutException as e:
            raise AdapterError(
                "视频生成提交超时（60s），请稍后重试",
                error_code="VIDEO_TIMEOUT",
            ) from e
        except AdapterError:
            raise
        except httpx.HTTPError as e:
            raise AdapterError(f"视频生成请求异常: {e}", error_code="VIDEO_HTTP_ERROR") from e

    async def fetch_result(self, task_id: str) -> VideoGenerationResponse:
        """
        轮询任务状态。

        尝试三种路径：
        1. GET /tasks/{task_id}（ModelScope 标准）
        2. GET /video/generations/{task_id}（备选）
        3. GET /contents/generations/tasks/{task_id}（Seedance / 火山引擎 Ark）
        """
        client = self._get_client(30)

        # 路径 1: /tasks/{task_id}
        try:
            resp = await client.get(f"/tasks/{task_id}")
            if resp.status_code == 200:
                return self._parse_task_response(resp.json(), task_id)
        except httpx.HTTPError:
            pass

        # 路径 2: /video/generations/{task_id}
        try:
            resp = await client.get(f"/video/generations/{task_id}")
            if resp.status_code == 200:
                return self._parse_task_response(resp.json(), task_id)
        except httpx.HTTPError:
            pass

        # 路径 3: /contents/generations/tasks/{task_id}（Seedance）
        try:
            resp = await client.get(f"/contents/generations/tasks/{task_id}")
            if resp.status_code == 200:
                return self._parse_task_response(resp.json(), task_id)
        except httpx.HTTPError:
            pass

        # 三种路径都失败
        return VideoGenerationResponse(
            task_id=task_id, status="processing", error_msg="轮询中（暂无结果）"
        )

    # ---------- 内部解析 ----------

    def _parse_task_response(self, data: Dict[str, Any], task_id: str) -> VideoGenerationResponse:
        """解析轮询响应（兼容多种格式）"""
        # 格式 A: {status: "completed", video_url: "..."}
        # 格式 B: {output: {task_status: "Succeeded", video_url: "..."}}
        # 格式 C: {task_status: "completed", output: {video_url: "..."}}

        output = data.get("output", data)
        status_raw = (
            data.get("status")
            or data.get("task_status")
            or output.get("task_status")
            or output.get("status")
            or ""
        ).lower()

        # 状态映射
        if status_raw in ("completed", "succeeded", "success", "finished"):
            video_url = self._extract_video_url(data)
            if video_url:
                return VideoGenerationResponse(task_id=task_id, status="completed", video_url=video_url)
            return VideoGenerationResponse(
                task_id=task_id, status="processing", error_msg="已完成但未找到视频 URL"
            )
        elif status_raw in ("failed", "error", "cancelled"):
            error_msg = (
                data.get("error")
                or data.get("error_msg")
                or output.get("error_message")
                or output.get("message")
                or "视频生成失败"
            )
            return VideoGenerationResponse(task_id=task_id, status="failed", error_msg=str(error_msg))
        else:
            # pending / processing / running / queued
            return VideoGenerationResponse(task_id=task_id, status="processing")

    @staticmethod
    def _extract_task_id(data: Dict[str, Any]) -> str:
        """从提交响应中提取 task_id"""
        return (
            data.get("task_id")
            or data.get("id")
            or (data.get("output", {}) or {}).get("task_id")
            or ""
        )

    @staticmethod
    def _extract_video_url(data: Dict[str, Any]) -> str:
        """从响应中提取视频 URL（兼容多种嵌套格式）"""
        # 直接字段
        url = data.get("video_url") or data.get("url") or ""
        if url:
            return url
        # output 嵌套
        output = data.get("output", {}) or {}
        url = output.get("video_url") or output.get("url") or ""
        if url:
            return url
        # results 数组
        results = output.get("results") or data.get("results") or []
        if results and isinstance(results, list):
            first = results[0] if results else {}
            if isinstance(first, dict):
                return first.get("url") or first.get("video_url") or ""
            if isinstance(first, str):
                return first
        # video_url 数组
        videos = data.get("videos") or output.get("videos") or []
        if videos and isinstance(videos, list):
            return videos[0] if isinstance(videos[0], str) else ""
        return ""

    @staticmethod
    def _resolve_size(resolution: str, aspect_ratio: str) -> str:
        """将分辨率 + 宽高比转换为像素尺寸"""
        # 如果已经是 WxH 格式
        if "x" in resolution and resolution[0].isdigit():
            return resolution

        # 根据宽高比和分辨率计算
        ratio_map = {
            "16:9": (16, 9),
            "9:16": (9, 16),
            "1:1": (1, 1),
            "4:3": (4, 3),
            "3:4": (3, 4),
        }
        w_ratio, h_ratio = ratio_map.get(aspect_ratio, (16, 9))

        res_map = {
            "480p": 480,
            "720p": 720,
            "1080p": 1080,
        }
        base = res_map.get(resolution, 720)

        # 以短边为基准
        if w_ratio >= h_ratio:
            h = base
            w = int(base * w_ratio / h_ratio)
        else:
            w = base
            h = int(base * h_ratio / w_ratio)

        # 对齐到 8 的倍数（多数模型要求）
        w = (w // 8) * 8
        h = (h // 8) * 8
        return f"{w}x{h}"
