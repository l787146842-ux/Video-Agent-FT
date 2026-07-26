"""provider_config：.env 写入消毒、key 读写、mock 判定（全部重定向到临时目录）"""
import pytest

import src.video_agent.web.provider_config as pc


@pytest.fixture(autouse=True)
def isolate_files(tmp_path, monkeypatch):
    """把 .env 与 providers 文件重定向到临时目录，绝不碰真实 API/.env"""
    monkeypatch.setattr(pc, "ENV_FILE", tmp_path / ".env")
    monkeypatch.setattr(pc, "PROVIDERS_FILE", tmp_path / "api_providers.json")
    # 清理可能被测试写入的进程环境变量
    monkeypatch.delenv("TEST_KEY", raising=False)
    monkeypatch.delenv("API_PROVIDER_FOO_KEY", raising=False)
    yield


def test_update_and_read_env_key(tmp_path):
    pc.update_env_key("TEST_KEY", "abc123")
    assert pc.read_env_keys()["TEST_KEY"] == "abc123"
    # 更新已有 key 不产生重复行
    pc.update_env_key("TEST_KEY", "xyz789")
    content = (tmp_path / ".env").read_text(encoding="utf-8")
    assert content.count("TEST_KEY=") == 1
    assert pc.read_env_keys()["TEST_KEY"] == "xyz789"


def test_env_value_newline_injection_blocked(tmp_path):
    # 恶意 value 试图注入第二个键值对
    pc.update_env_key("TEST_KEY", "value\nINJECTED_KEY=evil")
    keys = pc.read_env_keys()
    assert "INJECTED_KEY" not in keys
    assert "evil" not in keys.get("TEST_KEY", "") or "\n" not in keys["TEST_KEY"]


def test_illegal_env_name_rejected():
    with pytest.raises(ValueError):
        pc.update_env_key("bad name; rm -rf", "x")
    with pytest.raises(ValueError):
        pc.clear_env_key("BAD=NAME")


def test_clear_env_key(tmp_path):
    pc.update_env_key("TEST_KEY", "abc")
    pc.clear_env_key("TEST_KEY")
    assert "TEST_KEY" not in pc.read_env_keys()


def test_get_key_preview_masks(monkeypatch):
    pc.update_env_key("TEST_KEY", "sk-longsecret1234")
    has, preview = pc.get_key_preview("TEST_KEY")
    assert has is True
    assert "longsecret" not in preview
    assert preview.endswith("1234")


def test_is_mock_provider():
    assert pc.is_mock_provider("", "") is True
    assert pc.is_mock_provider("mock", "anything") is True
    assert pc.is_mock_provider("real-provider", "mock-image") is True
    # 未知 provider 但模型非 mock：不是 mock（会在后续解析端点时报配置错误）
    assert pc.is_mock_provider("real-provider", "gpt-5.5") is False


def test_provider_key_env_sanitized():
    assert pc.provider_key_env("modelscope") == "MODELSCOPE_API_KEY"
    name = pc.provider_key_env("weird id!!")
    assert name.startswith("API_PROVIDER_") and name.endswith("_KEY")
    assert " " not in name and "!" not in name


def test_load_providers_fallback_when_missing():
    providers = pc.load_api_providers()
    assert any(p["id"] == "mock" for p in providers)
