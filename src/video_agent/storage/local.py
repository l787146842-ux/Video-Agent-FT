"""
本地文件存储适配器 — 将文件写入 workspace/assets/ 目录。

这是默认存储后端：
- 文件落盘到 ASSETS_DIR
- 返回 /workspace/assets/{filename} 格式的相对 URL
"""
from pathlib import Path

from loguru import logger

from .base import BaseStorageAdapter


class LocalStorageAdapter(BaseStorageAdapter):
    """本地文件系统存储"""

    def __init__(self, assets_dir: Path, url_prefix: str = "/workspace/assets"):
        self._assets_dir = assets_dir
        self._url_prefix = url_prefix

    def save(self, data: bytes, filename: str, content_type: str = "") -> str:
        """写入文件到本地目录，返回相对 URL"""
        self._assets_dir.mkdir(parents=True, exist_ok=True)
        filepath = self._assets_dir / filename
        filepath.write_bytes(data)
        logger.info(f"[Storage] 文件已落盘: {filename} ({len(data)} bytes)")
        return f"{self._url_prefix}/{filename}"

    def read(self, filename: str) -> bytes:
        """读取本地文件"""
        filepath = self._assets_dir / filename
        if not filepath.exists():
            raise FileNotFoundError(f"文件不存在: {filename}")
        return filepath.read_bytes()

    def delete(self, filename: str) -> bool:
        """删除本地文件"""
        filepath = self._assets_dir / filename
        if filepath.exists():
            filepath.unlink()
            logger.info(f"[Storage] 文件已删除: {filename}")
            return True
        return False

    def exists(self, filename: str) -> bool:
        """检查文件是否存在"""
        return (self._assets_dir / filename).exists()

    def get_url(self, filename: str) -> str:
        """返回文件的 URL 路径"""
        return f"{self._url_prefix}/{filename}"

