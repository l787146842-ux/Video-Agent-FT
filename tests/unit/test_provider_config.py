"""provider_config：.env 写入消毒、key 读写、mock 判定、画布配置合并（全部重定向到临时目录）"""
import json
import pytest

import src.video_agent.core.provider_config as pc
from src.video_agent.config import settings


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


# ---------- 画布配置合并测试 ----------

@pytest.fixture
def canvas_env(tmp_path, monkeypatch):
    """重定向画布相关配置路径到临时目录（frozen dataclass 用 object.__setattr__）"""
    object.__setattr__(settings, "canvas_providers_url", "http://127.0.0.1:19999/api/providers")
    object.__setattr__(settings, "canvas_providers_file", str(tmp_path / "canvas_providers.json"))
    object.__setattr__(settings, "canvas_env_file", str(tmp_path / "canvas.env"))
    object.__setattr__(settings, "canvas_health_cache_seconds", 0)
    # 重置缓存
    monkeypatch.setattr(pc, "_canvas_ids_cache", None)
    monkeypatch.setattr(pc, "_canvas_ids_cache_time", 0.0)
    yield tmp_path
    # 恢复默认值
    object.__setattr__(settings, "canvas_providers_url", "http://127.0.0.1:3000/api/providers")
    object.__setattr__(settings, "canvas_providers_file", r"E:\07 天问\熊布\data\api_providers.json")
    object.__setattr__(settings, "canvas_env_file", r"E:\07 天问\熊布\API\.env")
    object.__setattr__(settings, "canvas_health_cache_seconds", 30)


def test_load_canvas_providers_file_not_exist(canvas_env):
    """画布配置文件不存在时返回空列表"""
    result = pc.load_canvas_providers()
    assert result == []


def test_load_canvas_providers_from_file(canvas_env):
    """画布配置文件存在时正常读取"""
    canvas_file = canvas_env / "canvas_providers.json"
    canvas_file.write_text(json.dumps([
        {"id": "modelscope", "name": "ModelScope", "enabled": True},
        {"id": "volcengine", "name": "火山引擎", "enabled": True},
    ]), encoding="utf-8")
    result = pc.load_canvas_providers()
    assert len(result) == 2
    assert result[0]["id"] == "modelscope"


def test_merged_providers_dedup_local_priority(canvas_env, tmp_path, monkeypatch):
    """合并逻辑：同 id 画布优先（连接设置）+ 模型并集，本地独有保留"""
    # 本地配置
    local_file = tmp_path / "api_providers.json"
    local_file.write_text(json.dumps([
        {"id": "modelscope", "name": "MS-Local", "enabled": True,
         "image_models": ["img-local"], "video_models": ["vid-local"], "chat_models": []},
        {"id": "custom-api", "name": "MyCustom", "enabled": True},
    ]), encoding="utf-8")
    monkeypatch.setattr(pc, "PROVIDERS_FILE", local_file)

    # 画布配置
    canvas_file = canvas_env / "canvas_providers.json"
    canvas_file.write_text(json.dumps([
        {"id": "modelscope", "name": "MS-Canvas", "enabled": True,
         "image_models": ["img-canvas"], "video_models": [], "chat_models": ["chat-canvas"]},
        {"id": "volcengine", "name": "火山引擎", "enabled": True},
    ]), encoding="utf-8")

    merged = pc.load_merged_providers()
    ids = [p["id"] for p in merged]

    # modelscope 只出现一次（画布优先）
    assert ids.count("modelscope") == 1
    ms = next(p for p in merged if p["id"] == "modelscope")
    assert ms["name"] == "MS-Canvas"  # 画布优先（连接设置）
    # 模型列表取并集
    assert "img-canvas" in ms["image_models"]
    assert "img-local" in ms["image_models"]
    assert "vid-local" in ms["video_models"]  # 本地独有模型保留
    assert "chat-canvas" in ms["chat_models"]

    # custom-api 保留（Agent 独有）
    assert "custom-api" in ids

    # volcengine 从画布追加
    assert "volcengine" in ids
    vc = next(p for p in merged if p["id"] == "volcengine")
    assert vc.get("_source") == "canvas"


def test_get_canvas_provider_ids(canvas_env):
    """缓存的画布 provider id 集合正确"""
    canvas_file = canvas_env / "canvas_providers.json"
    canvas_file.write_text(json.dumps([
        {"id": "modelscope", "name": "MS", "enabled": True},
        {"id": "runninghub", "name": "RH", "enabled": True},
    ]), encoding="utf-8")

    ids = pc.get_canvas_provider_ids()
    assert "modelscope" in ids
    assert "runninghub" in ids
    assert "custom-api" not in ids


def test_get_api_key_canvas_fallback(canvas_env, tmp_path, monkeypatch):
    """三级 fallback：本地无 key 时从画布 .env 读取"""
    # 画布 .env 有 key
    canvas_env_file = canvas_env / "canvas.env"
    canvas_env_file.write_text("MODELSCOPE_API_KEY=sk-from-canvas\n", encoding="utf-8")

    # 画布 provider 列表含 modelscope
    canvas_file = canvas_env / "canvas_providers.json"
    canvas_file.write_text(json.dumps([
        {"id": "modelscope", "name": "MS", "enabled": True},
    ]), encoding="utf-8")

    # 确保本地无此 key
    monkeypatch.delenv("MODELSCOPE_API_KEY", raising=False)

    key = pc.get_api_key("modelscope")
    assert key == "sk-from-canvas"
