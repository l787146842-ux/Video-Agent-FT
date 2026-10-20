"""事故 1010 回归：供应商配置/API Key 变更后**即时生效**，不需要重启进程。

现场：用户在 API 设置页配置好 workbuddy（custom-api-7）的 Key，「验证地址」
显示连接正常，但聊天一直 401 `invalid_api_key`，必须重启后端才能用。

根因：`AdapterFactory` 按 `provider:model` 缓存适配器实例（含 `api_key`）。
保存 Key 的 `PUT /api/providers` 只写 `API/.env`，**不碰缓存**；缓存键不含凭证，
故下次取用命中旧实例——该实例建于 Key 保存之前、`api_key` 为空字符串，
请求因此不带 `Authorization`。而「验证地址」走 `probe_adapter` 的一次性探测，
每回都用当前 Key，所以永远显示正常（验证通过 ≠ 配置已生效）。

两层修复（本文件分别钉死）：
1. 取用路径按**本次解析出的端点/凭证**校验缓存实例（`_endpoint_matches`）——
   不只信配置指纹，实例自身凭证与当前值不符即判陈旧重建；
2. 配置指纹（`config_fingerprint`）覆盖「改 Base URL / 改模型列表 / 直接编辑
   文件」等**不经过 resolve 对比**的变更路径，逐供应商增量校准。
"""
import json

import pytest

import src.video_agent.utils.provider_config_loader as pcl
from src.video_agent.adapters.factory import AdapterFactory


@pytest.fixture(autouse=True)
def isolate(monkeypatch, tmp_path):
    """配置与 Key 全部重定向到临时目录；适配器注册表逐测试清空。"""
    monkeypatch.setattr(pcl, "ENV_FILE", tmp_path / ".env")
    monkeypatch.setattr(pcl, "PROVIDERS_FILE", tmp_path / "api_providers.json")
    monkeypatch.delenv("API_PROVIDER_CUSTOM_API_7_KEY", raising=False)
    AdapterFactory.reset()
    yield
    AdapterFactory.reset()


def _write_providers(tmp_path, base_url="http://127.0.0.1:7863/v1",
                     chat_models=("cn:deepseek-v4.1-flash",), **extra):
    payload = [{
        "id": "custom-api-7", "name": "workbuddy", "protocol": "openai",
        "base_url": base_url, "enabled": True, "chat_models": list(chat_models),
        "image_models": [], "video_models": [],
    }]
    payload[0].update(extra)
    (tmp_path / "api_providers.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8")


# ---------- 1. 核心回归：保存 Key 后取用即带 Authorization（无需重启） ----------

def test_save_key_then_take_effect_without_restart(monkeypatch, tmp_path):
    """事故 1010 主回归：Key 保存前后取用同一 `provider:model`，
    后者必须拿到**持新 Key**的实例，且不是缓存里的旧实例。"""
    _write_providers(tmp_path)
    pid, model = "custom-api-7", "cn:deepseek-v4.1-flash"
    url = "http://127.0.0.1:7863/v1"

    # T1：Key 尚未配置（保存前）→ 实例持空 Key 并被缓存
    stale = AdapterFactory.get_or_create_chat_adapter(pid, url, "", model)
    assert stale.api_key == ""
    assert "Authorization" not in stale._headers()

    # T2：用户在设置页保存 Key（真实写 .env 路径）
    pcl.update_env_key(pcl.provider_key_env(pid), "sk-real-key-1Nww")

    # T3：再次取用——必须按当前 Key 重建，不得复用旧实例
    fresh = AdapterFactory.get_or_create_chat_adapter(
        pid, url, pcl.get_api_key(pid), model)
    assert fresh is not stale, "陈旧实例必须被替换，否则请求仍不带 Key"
    assert fresh.api_key == "sk-real-key-1Nww"
    assert fresh._headers()["Authorization"] == "Bearer sk-real-key-1Nww"


def test_same_key_still_reuses_instance(monkeypatch, tmp_path):
    """无变更时仍复用同一实例（连接池复用不得被修复破坏）。"""
    _write_providers(tmp_path)
    pid, model = "custom-api-7", "cn:deepseek-v4.1-flash"
    url = "http://127.0.0.1:7863/v1"
    pcl.update_env_key(pcl.provider_key_env(pid), "sk-stable")

    a1 = AdapterFactory.get_or_create_chat_adapter(pid, url, pcl.get_api_key(pid), model)
    a2 = AdapterFactory.get_or_create_chat_adapter(pid, url, pcl.get_api_key(pid), model)
    assert a1 is a2, "配置未变时必须复用同一实例及其连接池"


def test_key_rotation_rebuilds(monkeypatch, tmp_path):
    """换 Key（轮换）同样即时生效。"""
    _write_providers(tmp_path)
    pid, model = "custom-api-7", "cn:deepseek-v4.1-flash"
    url = "http://127.0.0.1:7863/v1"

    pcl.update_env_key(pcl.provider_key_env(pid), "sk-old-key")
    a1 = AdapterFactory.get_or_create_chat_adapter(pid, url, pcl.get_api_key(pid), model)
    assert a1.api_key == "sk-old-key"

    pcl.update_env_key(pcl.provider_key_env(pid), "sk-new-key")
    a2 = AdapterFactory.get_or_create_chat_adapter(pid, url, pcl.get_api_key(pid), model)
    assert a2.api_key == "sk-new-key"
    assert a2 is not a1


def test_base_url_change_takes_effect(monkeypatch, tmp_path):
    """Base URL 变更（不经过 resolve 对比的路径）由指纹校准覆盖。"""
    _write_providers(tmp_path)
    pid = "custom-api-7"
    pcl.update_env_key(pcl.provider_key_env(pid), "sk-k")

    AdapterFactory.register_from_config()
    before = AdapterFactory.get_chat_adapter(pid)
    assert before.base_url == "http://127.0.0.1:7863/v1"

    # 用户改 Base URL 并保存
    _write_providers(tmp_path, base_url="http://127.0.0.1:9999/v1")
    AdapterFactory.refresh_if_config_changed()

    after = AdapterFactory.get_chat_adapter(pid)
    assert after.base_url == "http://127.0.0.1:9999/v1"
    assert after is not before


def test_model_list_change_takes_effect(monkeypatch, tmp_path):
    """模型列表变更（首个模型换了）即时生效。"""
    _write_providers(tmp_path, chat_models=("cn:old-model",))
    pid = "custom-api-7"
    pcl.update_env_key(pcl.provider_key_env(pid), "sk-k")

    AdapterFactory.register_from_config()
    assert AdapterFactory.get_chat_adapter(pid).model == "cn:old-model"

    _write_providers(tmp_path, chat_models=("cn:new-model",))
    AdapterFactory.refresh_if_config_changed()
    assert AdapterFactory.get_chat_adapter(pid).model == "cn:new-model"


# ---------- 2. 指纹语义（配置变更判定的单一事实源） ----------

def test_fingerprint_changes_on_key_write(monkeypatch, tmp_path):
    """写 Key 必须改变指纹（同时间戳粒度内的连续写也要能识别）。"""
    _write_providers(tmp_path)
    before = pcl.config_fingerprint()
    pcl.update_env_key("API_PROVIDER_CUSTOM_API_7_KEY", "sk-a")
    assert pcl.config_fingerprint() != before


def test_fingerprint_changes_on_provider_save(monkeypatch, tmp_path):
    """保存供应商配置必须改变指纹。"""
    _write_providers(tmp_path)
    pcl.load_api_providers()  # 触发一次读取
    before = pcl.config_fingerprint()
    pcl.save_api_providers([{"id": "x", "name": "y"}])
    assert pcl.config_fingerprint() != before


def test_fingerprint_stable_when_nothing_changes(monkeypatch, tmp_path):
    """无写入时指纹稳定（否则每次取用都会重建，连接池复用失效）。"""
    _write_providers(tmp_path)
    assert pcl.config_fingerprint() == pcl.config_fingerprint()


def test_clear_key_changes_fingerprint(monkeypatch, tmp_path):
    """清除 Key 也要被识别（否则删了 Key 还在用旧的）。"""
    pcl.update_env_key("API_PROVIDER_CUSTOM_API_7_KEY", "sk-a")
    before = pcl.config_fingerprint()
    pcl.clear_env_key("API_PROVIDER_CUSTOM_API_7_KEY")
    assert pcl.config_fingerprint() != before


# ---------- 3. 边界：不得误伤其他供应商 ----------

def test_other_provider_instance_preserved(monkeypatch, tmp_path):
    """改一个供应商的 Key，不得替换/释放其他供应商的实例与连接池。

    回归点：整表重建会关掉别的供应商在途任务（如视频轮询）的连接池。
    """
    monkeypatch.setattr(pcl, "ENV_FILE", tmp_path / ".env")
    (tmp_path / "api_providers.json").write_text(json.dumps([
        {"id": "a", "name": "A", "protocol": "openai",
         "base_url": "http://a.example/v1", "enabled": True,
         "chat_models": ["m-a"], "image_models": [], "video_models": []},
        {"id": "b", "name": "B", "protocol": "openai",
         "base_url": "http://b.example/v1", "enabled": True,
         "chat_models": ["m-b"], "image_models": [], "video_models": []},
    ]), encoding="utf-8")
    pcl.update_env_key("API_PROVIDER_A_KEY", "sk-a")
    pcl.update_env_key("API_PROVIDER_B_KEY", "sk-b")

    AdapterFactory.register_from_config()
    b_before = AdapterFactory.get_chat_adapter("b")

    pcl.update_env_key("API_PROVIDER_A_KEY", "sk-a-rotated")  # 只动 A
    AdapterFactory.refresh_if_config_changed()

    assert AdapterFactory.get_chat_adapter("b") is b_before, \
        "未变更供应商的实例必须原样保留（连接池不得被误释放）"
    assert AdapterFactory.get_chat_adapter("a").api_key == "sk-a-rotated"


def test_disabled_provider_not_registered(monkeypatch, tmp_path):
    """enabled=False 的供应商不进注册表（既有语义不变）。"""
    (tmp_path / "api_providers.json").write_text(json.dumps([
        {"id": "off", "name": "Off", "protocol": "openai",
         "base_url": "http://off.example/v1", "enabled": False,
         "chat_models": ["m"], "image_models": [], "video_models": []},
    ]), encoding="utf-8")
    AdapterFactory.register_from_config()
    assert AdapterFactory.get_chat_adapter("off") is None
    with pytest.raises(ValueError):
        AdapterFactory.get_adapter("chat", "off")


def test_cli_adapter_not_churned_by_config_change(monkeypatch, tmp_path):
    """CLI 类适配器不持端点/凭证，不得被当成陈旧实例反复重建。

    回归点：CLI 适配器（AgyCliImageAdapter）无 api_key/base_url 属性，
    若按 `getattr(...) != ""` 判定会被误判为陈旧，每次配置变更都白建一次。
    """
    (tmp_path / "api_providers.json").write_text(json.dumps([
        {"id": "gemini-cli", "name": "Antigravity CLI", "protocol": "gemini-cli",
         "enabled": True, "chat_models": [], "image_models": ["auto"],
         "video_models": []},
    ]), encoding="utf-8")
    AdapterFactory.register_from_config()
    before = AdapterFactory.get_image_adapter("gemini-cli")
    assert before is not None

    # 触发一次配置变更（改 .env 指纹）
    pcl.update_env_key("API_PROVIDER_OTHER_KEY", "x")
    AdapterFactory.refresh_if_config_changed()

    assert AdapterFactory.get_image_adapter("gemini-cli") is before, \
        "无端点属性的 CLI 适配器不得被误判为陈旧而重建"
