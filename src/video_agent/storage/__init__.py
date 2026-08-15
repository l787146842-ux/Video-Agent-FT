"""
存储模块 — 统一文件存储接口。

用法：
    from src.video_agent.storage import get_storage

    storage = get_storage()
    url = storage.save(raw_bytes, "gen-xxx.png", "image/png")

B6/F42：S3 骨架已删除（STORAGE_BACKEND=s3 是幻影开关，零生产调用方）；
当前唯一后端为 LocalStorageAdapter。新增后端时按 adapters 同法注册并接线。
"""
from typing import Optional

from .base import BaseStorageAdapter
from .local import LocalStorageAdapter

__all__ = ["BaseStorageAdapter", "LocalStorageAdapter", "get_storage"]

# 模块级单例缓存
_storage_instance: Optional[BaseStorageAdapter] = None


def get_storage() -> BaseStorageAdapter:
    """获取全局存储适配器实例（单例）——local 后端，文件写入 workspace/assets/。"""
    global _storage_instance
    if _storage_instance is not None:
        return _storage_instance

    from src.video_agent.config import settings
    from src.video_agent.utils.paths import ASSETS_DIR

    if settings.storage_backend != "local":
        from loguru import logger

        logger.warning(
            f"[Storage] 未知后端 {settings.storage_backend!r}，回落 local"
            "（S3 骨架已删除，见 B6/F42；新增后端需在 adapters/storage 注册并接线）"
        )
    _storage_instance = LocalStorageAdapter(ASSETS_DIR)
    return _storage_instance


def reset_storage() -> None:
    """重置单例（测试用）"""
    global _storage_instance
    _storage_instance = None
