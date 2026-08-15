"""
OpenAI 兼容视频生成适配器（ModelScope / 华为 MaaS / 火山 Ark 等异步任务 API）。

API 格式：
    ① 经典格式（单首帧）：POST {base_url}/videos/generations
          Body: {model, input: {prompt, img_url?}, parameters: {size?, duration?, fps?}}
    ② Seedance 2.0 MultiModalToVideo 媒体列表格式（多参考图 + 音频参考）：
          POST {base_url}/contents/generations/tasks
          Body: {model, content: [{type: text|image_url|audio_url, ...}],
                 resolution, ratio, duration, watermark, seed}
          传入 media_refs（[{url, kind, role}]）时自动切换到本格式。
    ③ MMG 满血2.0 类中转站（video_request_mode="openai"，base_url 需含 /v1）：
          POST {base_url}/videos
          Body: {model, prompt, duration(5/8/10/12/15), aspect_ratio(仅9:16),
                 resolution(720p), reference_urls?[HTTPS直链数组]}
          请求头: Idempotency-Key（提交前生成的唯一幂等键）

    轮询: GET {base_url}/tasks/{task_id}（MMG: GET /videos/{id}，
          completed 后经 GET /videos/{id}/content 下载成片）
          返回: {status/task_status, video_url/output}

遵循 Rule4：外部调用走 Adapter。
"""
import base64
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import httpx
from loguru import logger

from src.video_agent.config import settings
from src.video_agent.exceptions import AdapterError
from src.video_agent.utils.paths import ASSETS_DIR
from .base import BaseVideoAdapter, VideoGenerationResponse


# MMG 满血2.0 类中转站（video_request_mode="openai"）的合法时长（官方文档限定）
_MMG_ALLOWED_DURATIONS = (5, 8, 10, 12, 15)
# MMG 文档：Data URL/Base64 参考素材解码后合计最大 20 MiB
_MMG_MAX_BASE64_BYTES = 20 * 1024 * 1024
# 本地素材 URL 前缀：远端供应商无法访问本机地址，不可作为参考素材直传
_LOCAL_URL_PREFIXES = ("/workspace/", "http://localhost", "http://127.0.0.1")
_MMG_MIME_BY_SUFFIX = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".webp": "image/webp", ".gif": "image/gif", ".mp4": "video/mp4",
    ".mp3": "audio/mpeg", ".wav": "audio/wav", ".m4a": "audio/mp4",
}


# Seedance 媒体列表格式中图片参考的合法 role；不认识的 role 归一到 reference_image
_IMAGE_ROLES = {
    "first_frame": "first_frame",
    "last_frame": "last_frame",
    "reference": "reference_image",
    "reference_image": "reference_image",
    "subject": "subject_reference",
    "subject_reference": "subject_reference",
}


class OpenAICompatVideoAdapter(BaseVideoAdapter):
    """
    通用 OpenAI 兼容视频生成适配器。

    支持 ModelScope（api-inference.modelscope.cn）和其他兼容
    POST /videos/generations + GET /tasks/{task_id} 格式的供应商；
    传入 media_refs 时切换为 Seedance 2.0 MultiModalToVideo 的媒体列表格式
    （POST /contents/generations/tasks，支持多参考图 + 音色参考音频）。
    """

    def __init__(
        self,
        base_url: str,
        api_key: str = "",
        model: str = "",
        video_request_mode: str = "classic",
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        # classic: ModelScope/Seedance 媒体列表格式；openai: OpenAI /video/generations 扁平格式
        self.video_request_mode = (video_request_mode or "classic").lower()
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
            kwargs: duration(int), resolution(str), aspect_ratio(str), model(str),
                    media_refs(list[dict])：多模态参考素材列表，每项
                    {"url": str, "kind": "image"|"audio", "role": first_frame|
                    last_frame|reference|reference_audio}；非空时走 Seedance 2.0
                    MultiModalToVideo 媒体列表格式（多参考图 + 音色参考音频）。
        """
        model = kwargs.get("model") or self.model
        if not model:
            raise AdapterError("视频生成失败：未指定视频模型", error_code="VIDEO_NO_MODEL")

        duration = kwargs.get("duration", 5)
        resolution = kwargs.get("resolution", "720p")
        aspect_ratio = kwargs.get("aspect_ratio", "16:9")

        media_refs = self._normalize_media_refs(kwargs.get("media_refs"), image_url)

        if self.video_request_mode == "openai":
            # MMG 满血2.0 类中转站：POST /videos 扁平格式（见官方接入文档）
            # duration 仅允许 5/8/10/12/15，取最近合法值
            dur = int(duration or 5)
            if dur not in _MMG_ALLOWED_DURATIONS:
                snapped = min(_MMG_ALLOWED_DURATIONS, key=lambda d: abs(d - dur))
                logger.warning(
                    f"[VideoAdapter] duration={dur} 不在合法集合，自动调整为 {snapped}"
                )
                dur = snapped
            # MMG 仅支持 9:16，其他比例强制归一并告警
            ratio = aspect_ratio or "9:16"
            if ratio != "9:16":
                logger.warning(f"[VideoAdapter] MMG 仅支持 9:16，{ratio} 已强制转换")
                ratio = "9:16"
            payload: Dict[str, Any] = {
                "model": model,
                "prompt": prompt or "",
                "duration": dur,
                "aspect_ratio": ratio,
                "resolution": resolution if resolution and "x" not in resolution else "720p",
            }
            # 参考素材：统一转 Data URL 放 references（避免临时外链过期被 MMG 拒绝）；
            # 超过 Base64 总上限 20MiB 的远程素材按文档回退为 reference_urls 直链
            ref_urls: list = []
            ref_data: list = []
            data_budget = _MMG_MAX_BASE64_BYTES
            for r in media_refs:
                url = r["url"]
                if url.startswith("data:"):
                    du = url
                elif url.startswith(_LOCAL_URL_PREFIXES):
                    du = await self._local_to_data_uri(url)
                    if not du:
                        logger.warning(f"[VideoAdapter] 本地参考素材读取失败，已跳过: {url}")
                        continue
                elif url.startswith("https://"):
                    # 提交前先由本服务下载内联，失败直接报可读错误而非把死链透传
                    du = await self._remote_to_data_uri(url)
                else:
                    logger.warning(f"[VideoAdapter] 不支持的参考素材 URL，已跳过: {url}")
                    continue
                size = self._data_uri_decoded_size(du)
                if size > data_budget:
                    if url.startswith("https://") and not url.startswith(_LOCAL_URL_PREFIXES):
                        ref_urls.append(url)
                        continue
                    raise AdapterError(
                        f"参考素材 {url[:100]} 解码后 {size // 1024}KB 超过 MMG Base64 总上限 20MiB",
                        error_code="VIDEO_REF_TOO_LARGE",
                    )
                ref_data.append(du)
                data_budget -= size
            if ref_data:
                payload["references"] = ref_data[:12]
            if ref_urls:
                payload["reference_urls"] = ref_urls[:12]
            endpoint = "/videos"
            use_media_format = False
        else:
            # 仅首帧（无额外参考图/音频）时保持经典格式（兼容性更广）；
            # 存在多参考图或音色参考音频时切换 Seedance 媒体列表格式
            use_media_format = len(media_refs) > 1 or any(
                r["kind"] == "audio" for r in media_refs
            )
        if self.video_request_mode != "openai":
            if use_media_format:
                # Seedance 2.0 MultiModalToVideo：媒体列表格式
                payload = {
                    "model": model,
                    "content": self._build_media_content(prompt, media_refs),
                    "resolution": resolution,
                    "ratio": aspect_ratio,
                    "duration": duration,
                    "watermark": False,
                    "seed": -1,
                }
                endpoint = "/contents/generations/tasks"
            else:
                # 构建分辨率尺寸
                size = self._resolve_size(resolution, aspect_ratio)

                # 经典格式首帧兑底：仅传 media_refs 单张首帧时也能回退到 img_url
                legacy_first_frame = image_url or next(
                    (r["url"] for r in media_refs if r["kind"] == "image"), ""
                )

                # 构建请求体（ModelScope / 华为 MaaS 兼容格式）
                input_data: Dict[str, Any] = {"prompt": prompt}
                if legacy_first_frame:
                    input_data["img_url"] = legacy_first_frame

                payload = {
                    "model": model,
                    "input": input_data,
                    "parameters": {
                        "size": size,
                        "duration": duration,
                    },
                }
                endpoint = "/videos/generations"

        try:
            client = self._get_client(60)
            headers = (
                {"Idempotency-Key": f"video_{uuid.uuid4()}"}
                if self.video_request_mode == "openai" else {}
            )
            resp = await client.post(endpoint, json=payload, headers=headers)

            if resp.status_code in (200, 201, 202):
                data = self._safe_json(resp)
                task_id = self._extract_task_id(data)
                if task_id:
                    logger.info(
                        f"[VideoAdapter] 任务已提交: {task_id} (model={model}, "
                        f"format={'multimodal' if use_media_format else 'legacy'}, "
                        f"media_refs={len(media_refs)})"
                    )
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

    def _safe_json(self, resp: httpx.Response) -> Dict[str, Any]:
        """解析响应 JSON；非 JSON 响应（如网关返回 HTML/空 body）时抛出带现场信息的错误"""
        try:
            return resp.json()
        except ValueError as e:
            raise AdapterError(
                f"视频 API 返回非 JSON 响应 (HTTP {resp.status_code}, "
                f"content-type={resp.headers.get('content-type', '?')})，"
                f"请确认供应商 base_url 是否支持该视频接口: {resp.text[:120]!r}",
                status_code=resp.status_code,
                error_code="VIDEO_PARSE_ERROR",
            ) from e

    async def fetch_result(self, task_id: str) -> VideoGenerationResponse:
        """
        轮询任务状态。

        openai 模式（MMG 类）：GET /videos/{id}，completed 后经 /videos/{id}/content
        下载成片存入 workspace/assets（官方文档要求忽略状态响应中的 video_url 字段）。
        classic 模式尝试三种路径：
        1. GET /tasks/{task_id}（ModelScope 标准）
        2. GET /video/generations/{task_id}（备选）
        3. GET /contents/generations/tasks/{task_id}（Seedance / 火山引擎 Ark）
        """
        client = self._get_client(30)

        if self.video_request_mode == "openai":
            try:
                resp = await client.get(f"/videos/{task_id}")
                if resp.status_code == 200:
                    result = self._parse_task_response(self._safe_json(resp), task_id)
                    if result.status == "completed":
                        # 官方文档：忽略状态响应中的 video_url 兼容字段，
                        # 成片一律经 /content 下载到本地素材目录（带 502/503 重试）
                        if (result.video_url or "").startswith("/workspace/assets/"):
                            return result
                        local_url = await self._download_mmg_content(client, task_id)
                        if local_url:
                            result.video_url = local_url
                            return result
                        # 成片暂未就绪，继续轮询
                        return VideoGenerationResponse(
                            task_id=task_id, status="processing",
                            error_msg="成片准备中，稍后重试下载",
                        )
                    return result
            except httpx.HTTPError as _e:
                logger.debug("[video_compat] 忽略异常: {}", _e)
            return VideoGenerationResponse(
                task_id=task_id, status="processing", error_msg="轮询中（暂无结果）"
            )

        # 路径 1: /tasks/{task_id}
        try:
            resp = await client.get(f"/tasks/{task_id}")
            if resp.status_code == 200:
                return self._parse_task_response(resp.json(), task_id)
        except httpx.HTTPError as _e:
            logger.debug("[video_compat] 忽略异常: {}", _e)

        # 路径 2: /video/generations/{task_id}
        try:
            resp = await client.get(f"/video/generations/{task_id}")
            if resp.status_code == 200:
                return self._parse_task_response(resp.json(), task_id)
        except httpx.HTTPError as _e:
            logger.debug("[video_compat] 忽略异常: {}", _e)

        # 路径 3: /contents/generations/tasks/{task_id}（Seedance）
        try:
            resp = await client.get(f"/contents/generations/tasks/{task_id}")
            if resp.status_code == 200:
                return self._parse_task_response(resp.json(), task_id)
        except httpx.HTTPError as _e:
            logger.debug("[video_compat] 忽略异常: {}", _e)

        # 三种路径都失败
        return VideoGenerationResponse(
            task_id=task_id, status="processing", error_msg="轮询中（暂无结果）"
        )

    async def _download_mmg_content(self, client: httpx.AsyncClient, task_id: str) -> str:
        """下载 MMG 成片到 workspace/assets，返回本地访问 URL；未就绪返回空串。

        官方文档：completed 后文件可能延迟就绪，/content 可能暂时 502/503，
        重试同一地址即可，不重建任务。
        """
        import asyncio
        for attempt in range(3):
            try:
                dl = await client.get(f"/videos/{task_id}/content", timeout=300)
            except httpx.HTTPError:
                return ""
            if dl.status_code in (502, 503):
                await asyncio.sleep(10)
                continue
            if dl.status_code != 200 or len(dl.content) <= 1024:
                return ""
            ASSETS_DIR.mkdir(parents=True, exist_ok=True)
            fname = f"video_{task_id}_{int(time.time())}.mp4"
            (ASSETS_DIR / fname).write_bytes(dl.content)
            logger.info(f"[VideoAdapter] MMG 成片已下载: {fname} ({len(dl.content) // 1024}KB)")
            return f"/workspace/assets/{fname}"
        return ""

    async def _local_to_data_uri(self, url: str) -> str:
        """本地素材 URL（/workspace/assets/...）转 Data URL（Base64 内联发送）"""
        import base64
        from pathlib import Path
        from urllib.parse import urlparse
        path = urlparse(url).path if "://" in url else url
        if not path.startswith("/workspace/assets/"):
            return ""
        fname = Path(path).name  # 仅取 basename，防目录穿越
        full = ASSETS_DIR / fname
        try:
            full = full.resolve()
            full.relative_to(ASSETS_DIR.resolve())
            if not full.exists():
                return ""
            raw = full.read_bytes()
            if len(raw) > 20 * 1024 * 1024:
                logger.warning(f"[VideoAdapter] 本地素材超过 20MB，跳过 Base64 内联: {fname}")
                return ""
            ext_mime = {
                ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                ".webp": "image/webp", ".gif": "image/gif", ".mp4": "video/mp4",
                ".mp3": "audio/mpeg", ".wav": "audio/wav", ".m4a": "audio/mp4",
            }
            mime = ext_mime.get(full.suffix.lower(), "application/octet-stream")
            return f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"
        except (ValueError, OSError) as e:
            logger.warning(f"[VideoAdapter] 本地素材转 Data URL 失败: {e}")
            return ""

    async def _remote_to_data_uri(self, url: str) -> str:
        """下载远程参考素材为 data URI；失败时抛出带 URL/状态码的明确错误。

        远端供应商（MMG）抓取临时外链时常因链接过期/防盗链返回 400，
        提交前由本服务先下载内联，失败直接给出可读错误而非把死链透传。
        """
        try:
            resp = await self._get_client(30).get(url)
        except Exception as e:  # noqa: BLE001
            raise AdapterError(
                f"参考素材无法下载: {url} ({e})，请确认该 HTTPS 直链无需登录、可直接下载",
                error_code="VIDEO_REF_FETCH_FAILED",
            ) from e
        if resp.status_code != 200 or not resp.content:
            raise AdapterError(
                f"参考素材无法下载: {url} (HTTP {resp.status_code})，"
                "该链接可能已过期或需要登录/防盗链，请重新生成或更换可公网访问的直链",
                status_code=resp.status_code,
                error_code="VIDEO_REF_FETCH_FAILED",
            ) from None
        ctype = resp.headers.get("content-type", "").split(";")[0].strip()
        if not ctype.startswith(("image/", "audio/", "video/")):
            ctype = _MMG_MIME_BY_SUFFIX.get(
                Path(urlparse(url).path).suffix.lower(), "application/octet-stream"
            )
        b64 = base64.b64encode(resp.content).decode("ascii")
        return f"data:{ctype};base64,{b64}"

    @staticmethod
    def _data_uri_decoded_size(data_uri: str) -> int:
        """估算 data URI 解码后的字节数（base64 长度 - padding）"""
        if "," not in data_uri:
            return 0
        b64 = data_uri.split(",", 1)[1]
        return max(0, len(b64) * 3 // 4 - b64.count("="))

    # ---------- 媒体列表格式（Seedance 2.0 MultiModalToVideo） ----------

    @staticmethod
    def _normalize_media_refs(media_refs: Any, image_url: str) -> list:
        """归一化参考素材列表：去重、补 kind/role 默认值。

        image_url（经典首帧参数）不在列表中时自动作为 first_frame 前置，
        保证旧调用方升级后行为不回退。无有效素材时返回空列表（走经典格式）。
        """
        norm: list = []
        seen: set = set()
        for ref in media_refs or []:
            if not isinstance(ref, dict):
                continue
            url = str(ref.get("url") or "").strip()
            if not url or url in seen:
                continue
            seen.add(url)
            kind = str(ref.get("kind") or "").strip().lower()
            if kind not in ("image", "audio", "video"):
                kind = "audio" if any(
                    url.lower().split("?")[0].endswith(ext)
                    for ext in (".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg")
                ) else (
                    "video" if any(
                        url.lower().split("?")[0].endswith(ext)
                        for ext in (".mp4", ".mov", ".webm", ".mkv")
                    ) else "image"
                )
            if kind == "audio":
                role = "reference_audio"
            elif kind == "video" or str(ref.get("role") or "").lower() == "reference_video":
                role = "reference_video"
            else:
                role = _IMAGE_ROLES.get(str(ref.get("role") or "reference").lower(), "reference_image")
            norm.append({"url": url, "kind": kind, "role": role})
        # 经典首帧参数兼容：未在列表中出现则作为 first_frame 前置
        if image_url and image_url not in seen:
            norm.insert(0, {"url": image_url, "kind": "image", "role": "first_frame"})
        return norm

    @staticmethod
    def _build_media_content(prompt: str, media_refs: list) -> list:
        """构建 content 数组：文本提示词 + 图片/音频参考项（带 role 标注）"""
        content: list = [{"type": "text", "text": prompt or ""}]
        for ref in media_refs:
            if ref["kind"] == "audio":
                content.append({
                    "type": "audio_url",
                    "audio_url": {"url": ref["url"]},
                    "role": ref["role"],
                })
            elif ref["kind"] == "video":
                content.append({
                    "type": "video_url",
                    "video_url": {"url": ref["url"]},
                    "role": ref["role"],
                })
            else:
                content.append({
                    "type": "image_url",
                    "image_url": {"url": ref["url"]},
                    "role": ref["role"],
                })
        return content

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
            error_raw = (
                data.get("error")
                or data.get("error_msg")
                or output.get("error_message")
                or output.get("message")
                or "视频生成失败"
            )
            if isinstance(error_raw, dict):
                # MMG 格式: {code, message}
                error_raw = error_raw.get("message") or error_raw.get("code") or "视频生成失败"
            return VideoGenerationResponse(task_id=task_id, status="failed", error_msg=str(error_raw))
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
