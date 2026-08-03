"""
存储模块 — 统一文件存储接口。

用法：
    from src.video_agent.storage import get_storage

    storage = get_storage()
    url = storage.save(raw_bytes, "gen-xxx.png", "image/png")
"""
import os
from typing import Optional

from .base import BaseStorageAdapter
from .local import LocalStorageAdapter
from .s3 import S3StorageAdapter

__all__ = ["BaseStorageAdapter", "LocalStorageAdapter", "S3StorageAdapter", "get_storage"]

# 模块级单例缓存
_storage_instance: Optional[BaseStorageAdapter] = None


def get_storage() -> BaseStorageAdapter:
    """获取全局存储适配器实例（单例）。

    根据 settings.storage_backend 配置选择后端：
    - "local"（默认）：LocalStorageAdapter，文件写入 workspace/assets/
    - "s3"：S3StorageAdapter（骨架，尚未实现）
    """
    global _storage_instance
    if _storage_instance is not None:
        return _storage_instance

    from src.video_agent.config import settings
    from src.video_agent.utils.paths import ASSETS_DIR

    backend = settings.storage_backend
    if backend == "s3":
        _storage_instance = S3StorageAdapter(
            bucket=os.getenv("S3_BUCKET", ""),
            region=os.getenv("S3_REGION", ""),
            access_key=os.getenv("S3_ACCESS_KEY", ""),
            secret_key=os.getenv("S3_SECRET_KEY", ""),
            url_prefix=os.getenv("S3_URL_PREFIX", ""),
        )
    else:
        _storage_instance = LocalStorageAdapter(ASSETS_DIR)

    return _storage_instance


def reset_storage() -> None:
    """重置单例（测试用）"""
    global _storage_instance
    _storage_instance = None
