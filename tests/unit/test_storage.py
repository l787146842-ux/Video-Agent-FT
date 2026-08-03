"""单元测试：Storage 存储抽象层

覆盖：
- LocalStorageAdapter CRUD（save/read/delete/exists/get_url）
- 工厂函数 get_storage() 默认返回 LocalStorageAdapter
- S3StorageAdapter 骨架抛 NotImplementedError
- persist_data_uri 通过 Storage 接口落盘
"""
import base64

import pytest

from src.video_agent.storage import get_storage, reset_storage
from src.video_agent.storage.base import BaseStorageAdapter
from src.video_agent.storage.local import LocalStorageAdapter
from src.video_agent.storage.s3 import S3StorageAdapter


@pytest.fixture(autouse=True)
def clean_storage():
    """每个测试前后重置存储单例"""
    reset_storage()
    yield
    reset_storage()


@pytest.fixture
def local_adapter(tmp_path):
    return LocalStorageAdapter(tmp_path)


class TestLocalStorageAdapter:
    def test_save_creates_file(self, local_adapter, tmp_path):
        url = local_adapter.save(b"hello", "test.png", "image/png")
        assert url == "/workspace/assets/test.png"
        assert (tmp_path / "test.png").exists()
        assert (tmp_path / "test.png").read_bytes() == b"hello"

    def test_read_existing_file(self, local_adapter, tmp_path):
        (tmp_path / "data.bin").write_bytes(b"\x00\x01\x02")
        result = local_adapter.read("data.bin")
        assert result == b"\x00\x01\x02"

    def test_read_missing_file_raises(self, local_adapter):
        with pytest.raises(FileNotFoundError):
            local_adapter.read("nonexistent.png")

    def test_delete_existing_file(self, local_adapter, tmp_path):
        (tmp_path / "del.txt").write_bytes(b"bye")
        assert local_adapter.delete("del.txt") is True
        assert not (tmp_path / "del.txt").exists()

    def test_delete_missing_file_returns_false(self, local_adapter):
        assert local_adapter.delete("ghost.txt") is False

    def test_exists(self, local_adapter, tmp_path):
        assert local_adapter.exists("nope.png") is False
        (tmp_path / "yep.png").write_bytes(b"")
        assert local_adapter.exists("yep.png") is True

    def test_get_url(self, local_adapter):
        assert local_adapter.get_url("img.jpg") == "/workspace/assets/img.jpg"

    def test_custom_url_prefix(self, tmp_path):
        adapter = LocalStorageAdapter(tmp_path, url_prefix="https://cdn.example.com/assets")
        url = adapter.save(b"x", "a.png")
        assert url == "https://cdn.example.com/assets/a.png"


class TestS3StorageAdapter:
    def test_all_methods_raise_not_implemented(self):
        s3 = S3StorageAdapter(bucket="test-bucket", region="us-east-1")
        with pytest.raises(NotImplementedError, match="S3 存储尚未实现"):
            s3.save(b"data", "file.png")
        with pytest.raises(NotImplementedError):
            s3.read("file.png")
        with pytest.raises(NotImplementedError):
            s3.delete("file.png")
        with pytest.raises(NotImplementedError):
            s3.exists("file.png")
        with pytest.raises(NotImplementedError):
            s3.get_url("file.png")


class TestGetStorageFactory:
    def test_default_returns_local(self):
        storage = get_storage()
        assert isinstance(storage, LocalStorageAdapter)

    def test_singleton(self):
        s1 = get_storage()
        s2 = get_storage()
        assert s1 is s2

    def test_reset_creates_new_instance(self):
        s1 = get_storage()
        reset_storage()
        s2 = get_storage()
        assert s1 is not s2


class TestPersistDataUriIntegration:
    def test_persist_data_uri_uses_storage(self, tmp_path, monkeypatch):
        """persist_data_uri 应通过 Storage 接口落盘"""
        import src.video_agent.storage as storage_mod
        from src.video_agent.storage.local import LocalStorageAdapter

        # 用临时目录替换默认存储
        reset_storage()
        monkeypatch.setattr(storage_mod, "_storage_instance", LocalStorageAdapter(tmp_path))

        from src.video_agent.adapters.openai_compat import persist_data_uri

        # 1x1 红色 PNG
        png_b64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg=="
        data_uri = f"data:image/png;base64,{png_b64}"

        url = persist_data_uri(data_uri)
        assert url.startswith("/workspace/assets/gen-")
        assert url.endswith(".png")

        # 验证文件确实写入了临时目录
        filename = url.split("/")[-1]
        assert (tmp_path / filename).exists()
