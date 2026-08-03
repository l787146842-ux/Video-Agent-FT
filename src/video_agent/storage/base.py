"""
存储适配器抽象基类 — 统一文件存储接口。

所有存储后端（本地、S3、OSS 等）均实现此接口，
业务代码通过 get_storage() 获取实例，不直接依赖具体实现。
"""
from abc import ABC, abstractmethod


class BaseStorageAdapter(ABC):
    """文件存储统一接口"""

    @abstractmethod
    def save(self, data: bytes, filename: str, content_type: str = "") -> str:
        """存储文件，返回可访问的 URL 路径

        Args:
            data: 文件二进制内容
            filename: 文件名（含扩展名）
            content_type: MIME 类型（如 image/png）

        Returns:
            文件的外部可访问 URL 路径
        """
        ...

    @abstractmethod
    def read(self, filename: str) -> bytes:
        """读取文件内容

        Args:
            filename: 文件名

        Returns:
            文件二进制内容

        Raises:
            FileNotFoundError: 文件不存在
        """
        ...

    @abstractmethod
    def delete(self, filename: str) -> bool:
        """删除文件

        Args:
            filename: 文件名

        Returns:
            是否成功删除（文件不存在返回 False）
        """
        ...

    @abstractmethod
    def exists(self, filename: str) -> bool:
        """检查文件是否存在"""
        ...

    @abstractmethod
    def get_url(self, filename: str) -> str:
        """返回文件的外部可访问 URL（不检查文件是否存在）"""
        ...
