"""
/api/ai/upload — 文件上传端点
接收前端上传的素材文件，保存到 workspace/assets/ 并返回可访问 URL。

/api/image-proxy — 图片代理端点
后端代理下载跨域图片，供前端格式转换使用（绕过浏览器 CORS 限制）。

安全约束：
- 扩展名白名单（图片/视频/音频/文档），拒绝 .html/.exe 等可被回显或执行的类型
- 单文件大小上限读自 config（settings.max_upload_size_mb，默认 50MB，流式写入边写边检查）
"""
import time
import random
from pathlib import Path

import httpx
from fastapi import APIRouter, UploadFile, File, HTTPException, Query
from fastapi.responses import Response

from src.video_agent.config import settings
from src.video_agent.utils.paths import ASSETS_DIR

router = APIRouter()

# 上传目录（统一从 paths.py 导入）
UPLOAD_DIR = ASSETS_DIR

# 单文件大小上限（唯一事实源：config.py，可用 MAX_UPLOAD_SIZE_MB 环境变量覆盖）
MAX_FILE_SIZE = settings.max_upload_size_mb * 1024 * 1024
_CHUNK = 1024 * 1024

ALLOWED_EXTS = {
    # 图片
    ".png": "image", ".jpg": "image", ".jpeg": "image", ".webp": "image", ".gif": "image",
    # 视频
    ".mp4": "video", ".avi": "video", ".mov": "video", ".webm": "video",
    # 音频
    ".mp3": "audio", ".wav": "audio", ".ogg": "audio", ".flac": "audio",
    # 文档（供剧本拆解）
    ".txt": "doc", ".md": "doc", ".pdf": "doc", ".docx": "doc",
}


@router.post("/ai/upload")
async def upload_files(files: list[UploadFile] = File(...)):
    """前端 handleChatFileUpload 调用"""
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    results = []
    for f in files:
        ext = Path(f.filename or "file").suffix.lower()
        kind = ALLOWED_EXTS.get(ext)
        if not kind:
            raise HTTPException(
                status_code=400,
                detail=f"不支持的文件类型 '{ext or '(无扩展名)'}'，"
                       f"允许：{', '.join(sorted(ALLOWED_EXTS))}",
            )

        safe_name = f"{int(time.time())}-{random.randint(1000, 9999)}{ext}"
        dest = UPLOAD_DIR / safe_name
        written = 0
        try:
            with open(dest, "wb") as buf:
                while True:
                    chunk = await f.read(_CHUNK)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > MAX_FILE_SIZE:
                        raise HTTPException(
                            status_code=413,
                            detail=f"文件 '{f.filename}' 超过 {settings.max_upload_size_mb}MB 上限",
                        )
                    buf.write(chunk)
        except HTTPException:
            dest.unlink(missing_ok=True)
            raise
        except Exception as e:
            dest.unlink(missing_ok=True)
            raise HTTPException(status_code=500, detail=f"保存文件失败: {e}")

        results.append({
            "name": f.filename or safe_name,
            "kind": kind,  # image / video / audio / doc
            "url": f"/workspace/assets/{safe_name}",
        })

    return {"files": results}


@router.get("/image-proxy")
async def image_proxy(url: str = Query(..., description="图片 URL")):
    """后端代理下载图片，返回原始字节（供前端 Canvas 格式转换用，绕过 CORS）。

    ：协议白名单 + 内网/回环校验（url_safety.validate_external_url 单一事实源，
    防 SSRF/DNS rebinding）。"""
    from src.video_agent.web.url_safety import validate_external_url

    try:
        validate_external_url(url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="仅支持 http/https URL")
    try:
        async with httpx.AsyncClient(timeout=30, trust_env=False, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"图片下载失败: {e}")
    content_type = resp.headers.get("content-type", "application/octet-stream")
    return Response(
        content=resp.content,
        media_type=content_type,
        headers={"Cache-Control": "public, max-age=3600"},
    )
