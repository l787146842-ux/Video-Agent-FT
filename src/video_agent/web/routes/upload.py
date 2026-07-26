"""
/api/ai/upload — 文件上传端点
接收前端上传的素材文件，保存到 workspace/assets/ 并返回可访问 URL。

安全约束：
- 扩展名白名单（图片/视频/音频/文档），拒绝 .html/.exe 等可被回显或执行的类型
- 单文件 200MB 上限（流式写入，边写边检查）
"""
import time
import random
from pathlib import Path

from fastapi import APIRouter, UploadFile, File, HTTPException

router = APIRouter()

# 上传目录（相对于项目根）
UPLOAD_DIR = Path(__file__).resolve().parent.parent.parent.parent.parent / "workspace" / "assets"

MAX_FILE_SIZE = 200 * 1024 * 1024  # 200MB
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
    """前端 handleChatFileUpload() 调用"""
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
                            detail=f"文件 '{f.filename}' 超过 200MB 上限",
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
            "kind": kind if kind != "doc" else "image",  # 前端资产分类沿用旧行为
            "url": f"/workspace/assets/{safe_name}",
        })

    return {"files": results}
