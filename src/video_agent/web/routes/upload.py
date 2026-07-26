"""
/api/ai/upload — 文件上传端点
接收前端上传的素材文件，保存到 workspace/assets/ 并返回可访问 URL。
"""
import shutil
import time
import random
from pathlib import Path

from fastapi import APIRouter, UploadFile, File, HTTPException

router = APIRouter()

# 上传目录（相对于项目根）
UPLOAD_DIR = Path(__file__).resolve().parent.parent.parent.parent.parent / "workspace" / "assets"


@router.post("/ai/upload")
async def upload_files(files: list[UploadFile] = File(...)):
    """前端 handleChatFileUpload() 调用"""
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    results = []
    for f in files:
        ext = Path(f.filename or "file").suffix or ".bin"
        safe_name = f"{int(time.time())}-{random.randint(1000,9999)}{ext}"
        dest = UPLOAD_DIR / safe_name
        try:
            with open(dest, "wb") as buf:
                shutil.copyfileobj(f.file, buf)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"保存文件失败: {e}")

        # 判断素材类型
        kind = "image"
        if ext.lower() in (".mp4", ".avi", ".mov", ".webm"):
            kind = "video"
        elif ext.lower() in (".mp3", ".wav", ".ogg", ".flac"):
            kind = "audio"

        results.append({
            "name": f.filename or safe_name,
            "kind": kind,
            "url": f"/workspace/assets/{safe_name}",
        })

    return {"files": results}
