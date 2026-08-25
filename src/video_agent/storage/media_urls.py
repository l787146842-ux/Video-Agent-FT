"""媒体 URL → 可注入形式解析。

职责：把待注入 LLM 的媒体 URL 统一转为可被供应商直读的形式——
- /workspace/ 本地文件 → 读盘转 base64 data URI（越界/不存在/超限返回空）
- http(s) 远程链接 → 服务端代下载转 data URI（失败返回空）
- 其他（已是 data: URI 等）→ 原样透传

分层依据：媒体 URL 的本地读取/内联本质是存储读取域，故落 storage 包
公开 API。web/multimodal_builder 保留薄 re-export 壳
（web 消费方与既有测试 patch 目标不变）。
"""
import asyncio
import base64
import mimetypes
from pathlib import Path
from urllib.parse import urlparse

from loguru import logger

from src.video_agent.adapters.fetch_adapter import get_media_fetch_adapter
from src.video_agent.config import settings
from src.video_agent.utils.paths import WORKSPACE_DIR

# 单张图片注入 LLM 的大小上限（base64 编码后体积膨胀约 4/3）
MAX_IMAGE_BYTES = 10 * 1024 * 1024
# 远程图片服务端代下载的超时（秒）
REMOTE_FETCH_TIMEOUT = 20.0


def downscale_image(raw: bytes, suffix: str) -> tuple:
    """注入前把图片缩放到长边 ≤ settings.llm_image_max_edge。

    Vision 模型内部会重采样，内联原图纯属浪费 token（单张可达数千）。
    返回 (bytes, mime)；缩放失败/未装 Pillow/未超限时返回 (raw, "") 表示沿用原图。
    """
    max_edge = settings.llm_image_max_edge
    if max_edge <= 0:
        return raw, ""
    try:
        import io

        from PIL import Image
    except ImportError:
        return raw, ""
    try:
        img = Image.open(io.BytesIO(raw))
        w, h = img.size
        if max(w, h) <= max_edge:
            return raw, ""
        scale = max_edge / max(w, h)
        img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)
        # PNG（含透明通道）保持 PNG，其余统一 JPEG q85
        keep_png = suffix == ".png" or img.mode in ("RGBA", "LA", "P")
        buf = io.BytesIO()
        if keep_png:
            img.save(buf, format="PNG", optimize=True)
            return buf.getvalue(), "image/png"
        if img.mode != "RGB":
            img = img.convert("RGB")
        img.save(buf, format="JPEG", quality=85)
        out = buf.getvalue()
        logger.info(f"[MediaUrls] 图片已缩放 {w}x{h} → {img.size[0]}x{img.size[1]} "
                    f"({len(raw) // 1024}KB → {len(out) // 1024}KB)")
        return out, "image/jpeg"
    except Exception as e:
        logger.warning(f"[MediaUrls] 图片缩放失败，沿用原图: {e}")
        return raw, ""


def read_image_data_uri(img_url: str) -> str:
    """读取 /workspace/ 本地图片并转为 base64 data URI（同步，供 to_thread 调用）。

    云端 LLM 无法访问 127.0.0.1，本地图片必须内联为 data URI 才能被供应商读取。
    路径越界 / 文件不存在 / 超过大小上限时返回空串（跳过该图片）。
    注入前按 llm_image_max_edge 缩放（vision token 优化）。
    """
    rel = img_url[len("/workspace/"):]
    path = (WORKSPACE_DIR / rel).resolve()
    try:
        path.relative_to(WORKSPACE_DIR.resolve())
    except ValueError:
        logger.warning(f"[MediaUrls] 图片路径越界，已跳过: {img_url}")
        return ""
    if not path.is_file():
        logger.warning(f"[MediaUrls] 图片不存在，已跳过: {img_url}")
        return ""
    if path.stat().st_size > MAX_IMAGE_BYTES:
        logger.warning(f"[MediaUrls] 图片超过 10MB，已跳过: {img_url}")
        return ""
    raw, mime_override = downscale_image(path.read_bytes(), path.suffix.lower())
    mime = mime_override or mimetypes.guess_type(path.name)[0] or "image/png"
    b64 = base64.b64encode(raw).decode("ascii")
    return f"data:{mime};base64,{b64}"


async def fetch_remote_image_data_uri(url: str) -> str:
    """服务端代下载远程图片 → base64 data URI。

    云端 LLM 网关经常无法抓取外部临时托管链接（时效过期/防盗链/内网），
    把 URL 原样透传会导致整个请求被供应商 400 拒绝；统一改为服务端先
    下载内联。失败（404/超时/超限/非图片）返回空串，调用方降级为文本清单。
    """
    if not url.lower().startswith(("http://", "https://")):
        return ""
    try:
        result = await get_media_fetch_adapter().download(
            url, timeout=REMOTE_FETCH_TIMEOUT, follow_redirects=True, context="multimodal"
        )
    except Exception as e:
        logger.warning(f"[MediaUrls] 远程图片拉取失败，跳过注入: {url} ({e})")
        return ""
    if result.status_code != 200:
        logger.warning(f"[MediaUrls] 远程图片拉取失败 HTTP {result.status_code}，跳过注入: {url}")
        return ""
    raw = result.content
    if len(raw) > MAX_IMAGE_BYTES:
        logger.warning(f"[MediaUrls] 远程图片超过 10MB，跳过注入: {url}")
        return ""
    suffix = Path(urlparse(url).path).suffix.lower() or ".png"
    raw, mime_override = downscale_image(raw, suffix)
    ct = (result.content_type or "").split(";")[0].strip()
    mime = mime_override or (ct if ct.startswith("image/") else "") or mimetypes.guess_type(url)[0] or "image/png"
    b64 = base64.b64encode(raw).decode("ascii")
    return f"data:{mime};base64,{b64}"


async def resolve_injectable_url(url: str) -> str:
    """把待注入 LLM 的媒体 URL 统一转为可被供应商直读的形式：

    - /workspace/ 本地文件 → 读盘转 data URI（越界/不存在返回空）
    - http(s) 远程链接 → 服务端代下载转 data URI（失败返回空）
    - 其他（已是 data: URI 等）→ 原样透传
    返回空串表示该图片本次无法注入，调用方应跳过（素材清单仍会列出）。
    """
    if url.startswith("/workspace/"):
        return await asyncio.to_thread(read_image_data_uri, url)
    if url.lower().startswith(("http://", "https://")):
        return await fetch_remote_image_data_uri(url)
    return url
