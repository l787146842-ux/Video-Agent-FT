"""provider_config：.env 写入消毒、key 读写、可用供应商判定、画布配置合并（全部重定向到临时目录）"""
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


def test_provider_key_env_sanitized():
    assert pc.provider_key_env("modelscope") == "MODELSCOPE_API_KEY"
    name = pc.provider_key_env("weird id!!")
    assert name.startswith("API_PROVIDER_") and name.endswith("_KEY")
    assert " " not in name and "!" not in name


def test_load_providers_fallback_when_missing():
    providers = pc.load_api_providers()
    assert any(p["id"] == "modelscope" for p in providers)


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


# ---------- 审查修复批：mock 演示通道退役后存量条目不再对外暴露 ----------

def test_get_available_providers_filters_mock_entries(monkeypatch):
    """存量用户配置里的 protocol=mock 条目不进下拉框（批次F 退役兼容）"""
    import src.video_agent.web.providers as wp
    monkeypatch.setattr(wp, "load_merged_providers", lambda: [
        {"id": "mock-demo", "name": "Mock 演示", "enabled": True, "protocol": "mock"},
        {"id": "openai", "name": "OpenAI", "enabled": True,
         "chat_models": ["gpt-4o"]},
        {"id": "disabled-one", "name": "已停用", "enabled": False},
    ])
    result = wp.get_available_providers()
    ids = [p["id"] for p in result]
    assert "mock-demo" not in ids  # mock 条目不对外暴露
    assert "openai" in ids         # 真实启用条目照常返回
    assert "disabled-one" not in ids


_MOCK_MERGED = [
    {"id": "mock-demo", "name": "Mock 演示", "enabled": True, "protocol": "mock",
     "chat_models": ["mock-chat"], "image_models": ["mock-img"]},
    {"id": "real", "name": "真实厂", "enabled": True,
     "chat_models": ["real-chat"], "image_models": ["real-img"]},
]


def test_mock_filter_single_chokepoint_all_consumers(monkeypatch):
    """收口钉死：mock 过滤唯一经 exclude_retired_mock_providers，
    首可用生图兜底与聊天默认解析统一消费同一过滤口径"""
    monkeypatch.setattr(pc, "load_merged_providers", lambda: list(_MOCK_MERGED))
    # 首可用生图兜底：mock 条目即使排在前头也不得命中
    pid, model = pc.first_available_image_provider()
    assert (pid, model) == ("real", "real-img")
    # 聊天默认解析（截断重答路由）：mock 条目不进候选
    from src.video_agent.web.routes import chat as chat_routes
    monkeypatch.setattr(
        chat_routes.provider_config, "load_merged_providers",
        lambda: list(_MOCK_MERGED))
    assert chat_routes._resolve_chat_target() == ("real", "real-chat")


def test_mock_filter_excludes_only_protocol_mock():
    """过滤口径只认 protocol=mock；无 protocol 字段/其他协议不受影响"""
    kept = pc.exclude_retired_mock_providers([
        {"id": "a"},
        {"id": "b", "protocol": "openai"},
        {"id": "c", "protocol": "mock"},
        {"id": "d", "protocol": ""},
    ])
    assert [p["id"] for p in kept] == ["a", "b", "d"]
