"""
S3 存储适配器骨架 — 预留接口，尚未实现。

将来需要接入 AWS S3 / 兼容 S3 协议的云存储时，
安装 boto3 并实现以下方法即可。
"""
from .base import BaseStorageAdapter


class S3StorageAdapter(BaseStorageAdapter):
    """AWS S3 存储适配器（骨架，尚未实现）"""

    def __init__(self, bucket: str, region: str = "", access_key: str = "", secret_key: str = "",
                 url_prefix: str = ""):
        self._bucket = bucket
        self._region = region
        self._access_key = access_key
        self._secret_key = secret_key
        self._url_prefix = url_prefix or f"https://{bucket}.s3.amazonaws.com"

    def save(self, data: bytes, filename: str, content_type: str = "") -> str:
        raise NotImplementedError("S3 存储尚未实现，请使用 local 存储后端或等待后续版本")

    def read(self, filename: str) -> bytes:
        raise NotImplementedError("S3 存储尚未实现，请使用 local 存储后端或等待后续版本")

    def delete(self, filename: str) -> bool:
        raise NotImplementedError("S3 存储尚未实现，请使用 local 存储后端或等待后续版本")

    def exists(self, filename: str) -> bool:
        raise NotImplementedError("S3 存储尚未实现，请使用 local 存储后端或等待后续版本")

    def get_url(self, filename: str) -> str:
        raise NotImplementedError("S3 存储尚未实现，请使用 local 存储后端或等待后续版本")
