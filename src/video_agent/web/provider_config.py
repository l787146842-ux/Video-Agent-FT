"""
供应商配置与 API Key 的唯一读写入口。

之前 routes/agent.py、routes/generate.py、routes/providers.py 各自维护一份
_get_provider_config / _get_api_key / 模型分类逻辑，已全部收敛到这里。

- 供应商配置：data/api_providers.json
- API Key：进程环境变量优先，其次 API/.env
- .env 写入带消毒（去换行）与线程锁，防止 value 注入其他键
"""
import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import httpx
from loguru import logger

from src.video_agent.config import settings
from src.video_agent.utils.fileio import atomic_write_text
from src.video_agent.utils.paths import DATA_DIR, API_DIR, PROVIDERS_FILE, ENV_FILE

# 同时保护 providers 文件与 .env 文件的读写
_config_lock = threading.Lock()

_ENV_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")

# CLI 协议集合（无 Base URL，通过本机 CLI 工具通信）
CLI_PROTOCOLS = {"jimeng", "codex", "gemini-cli"}

# ---------- 默认 Provider 配置 ----------
DEFAULT_PROVIDERS: List[Dict[str, Any]] = [
    {
        "id": "mock",
        "name": "Mock (本地测试)",
        "base_url": "",
        "protocol": "mock",
        "enabled": True,
        "primary": False,
        "image_models": ["mock-image"],
        "chat_models": ["mock-chat"],
        "video_models": ["mock-video"],
    },
    {
        "id": "modelscope",
        "name": "ModelScope",
        "base_url": "https://api-inference.modelscope.cn/v1",
        "protocol": "openai",
        "enabled": True,
        "primary": False,
        "image_models": ["Tongyi-MAI/Z-Image-Turbo", "Qwen/Qwen-Image-2512"],
        "chat_models": ["Qwen/Qwen3-235B-A22B", "Qwen/Qwen2.5-72B-Instruct"],
        "video_models": ["Wan-AI/Wan2.1-T2V-14B"],
    },
]


# ---------- 供应商配置 ----------

def load_api_providers() -> List[Dict[str, Any]]:
    """从 JSON 文件加载 provider 配置；不存在或损坏时回退默认配置"""
    with _config_lock:
        if PROVIDERS_FILE.exists():
            try:
                data = json.loads(PROVIDERS_FILE.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    return data
                logger.warning("[ProviderConfig] api_providers.json 不是列表，回退默认配置")
            except Exception as e:
                logger.warning(f"[ProviderConfig] 读取配置失败: {e}，回退默认配置")
        return [dict(p) for p in DEFAULT_PROVIDERS]


def save_api_providers(providers: List[Dict[str, Any]]) -> None:
    """保存 provider 配置（原子写）"""
    with _config_lock:
        atomic_write_text(PROVIDERS_FILE, json.dumps(providers, ensure_ascii=False, indent=2))
    logger.info(f"[ProviderConfig] 已保存 {len(providers)} 个供应商配置")


# ---------- 熊布配置共享（本地兜底 + 熊布增强） ----------

# 缓存熊布 provider id 集合（路由判断用）
_canvas_ids_cache: Optional[Set[str]] = None
_canvas_ids_cache_time: float = 0.0


def load_canvas_providers() -> List[Dict[str, Any]]:
    """从熊布读取 provider 配置（HTTP 优先，文件兜底）。
    任何异常均静默返回 []，不影响 Agent 正常运行。"""
    # 1. 尝试 HTTP API
    try:
        resp = httpx.get(settings.canvas_providers_url, timeout=3.0, trust_env=False)
        if resp.status_code == 200:
            data = resp.json()
            providers = data.get("providers", [])
            if isinstance(providers, list) and providers:
                logger.debug(f"[ProviderConfig] 从熊布 HTTP 读取到 {len(providers)} 个 provider")
                return providers
    except Exception:
        pass  # 熊布不在线，静默跳过

    # 2. 兜底：读磁盘文件
    try:
        canvas_file = Path(settings.canvas_providers_file)
        if canvas_file.exists():
            data = json.loads(canvas_file.read_text(encoding="utf-8"))
            if isinstance(data, list) and data:
                logger.debug(f"[ProviderConfig] 从熊布文件读取到 {len(data)} 个 provider")
                return data
    except Exception:
        pass  # 文件不存在或损坏，静默跳过

    return []


def load_merged_providers() -> List[Dict[str, Any]]:
    """合并本地 + 熊布的 provider 列表（按 id 去重，本地优先）。
    同时更新 canvas_provider_ids 缓存供路由层使用。"""
    global _canvas_ids_cache, _canvas_ids_cache_time

    local = load_api_providers()
    canvas = load_canvas_providers()

    local_ids = {p.get("id") for p in local}
    merged = list(local)

    # 熊布中 id 不在本地的追加到末尾，并标记来源
    for p in canvas:
        pid = p.get("id", "")
        if pid and pid not in local_ids:
            item = dict(p)
            item["_source"] = "canvas"
            merged.append(item)

    # 更新缓存（路由层用于判断 provider 是否熊布可处理）
    _canvas_ids_cache = {p.get("id") for p in canvas if p.get("id")}
    _canvas_ids_cache_time = time.time()

    return merged


def get_canvas_provider_ids() -> Set[str]:
    """获取熊布的 provider id 集合（带缓存，供路由层判断用）"""
    global _canvas_ids_cache, _canvas_ids_cache_time
    cache_ttl = settings.canvas_health_cache_seconds
    if _canvas_ids_cache is None or (time.time() - _canvas_ids_cache_time) > cache_ttl:
        # 重新加载以刷新缓存
        load_merged_providers()
    return _canvas_ids_cache or set()


def get_provider_config(provider_id: str) -> Optional[Dict[str, Any]]:
    """按 id 查找单个供应商配置（从合并列表中查找）"""
    if not provider_id:
        return None
    for p in load_merged_providers():
        if p.get("id") == provider_id:
            return p
    return None


def is_mock_provider(provider_id: str, model: str = "") -> bool:
    """判定是否应走 mock 路径：仅当用户显式选择 mock（或什么都没配）"""
    if not provider_id or provider_id == "mock":
        return True
    if model.startswith("mock"):
        return True
    cfg = get_provider_config(provider_id)
    return bool(cfg and cfg.get("protocol") == "mock")


# ---------- API Key 管理 ----------

def provider_key_env(provider_id: str) -> str:
    """根据 provider id 生成环境变量名"""
    mapping = {
        "modelscope": "MODELSCOPE_API_KEY",
        "volcengine": "ARK_API_KEY",
        "gemini-cli": "GEMINI_API_KEY",
    }
    if provider_id in mapping:
        return mapping[provider_id]
    sanitized = re.sub(r"[^A-Z0-9_]", "_", provider_id.upper().replace("-", "_"))
    return f"API_PROVIDER_{sanitized}_KEY"


def read_env_keys() -> Dict[str, str]:
    """读取 .env 文件中所有键值对"""
    keys: Dict[str, str] = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                keys[k.strip()] = v.strip()
    return keys


def _read_canvas_env_keys() -> Dict[str, str]:
    """读取熊布的 API/.env 文件中的键值对（第三级 fallback）"""
    keys: Dict[str, str] = {}
    try:
        canvas_env = Path(settings.canvas_env_file)
        if canvas_env.exists():
            for line in canvas_env.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    keys[k.strip()] = v.strip()
    except Exception:
        pass
    return keys


def get_api_key(provider_id: str) -> str:
    """解析某供应商的 API Key：
    1. 进程环境变量
    2. Agent 本地 API/.env
    3. 熊布 API/.env（仅对来源于熊布的 provider 启用）
    """
    env_name = provider_key_env(provider_id)
    val = os.getenv(env_name, "")
    if val:
        return val
    val = read_env_keys().get(env_name, "")
    if val:
        return val
    # 第三级：如果该 provider 来源于熊布，尝试读熊布的 .env
    canvas_ids = get_canvas_provider_ids()
    if provider_id in canvas_ids:
        val = _read_canvas_env_keys().get(env_name, "")
        if val:
            logger.debug(f"[ProviderConfig] Key '{env_name}' 从熊布 .env 解析")
            return val
    return ""


def resolve_api_key(api_key: str, provider_id: str) -> str:
    """优先使用调用方传入的 key，否则按 provider 解析"""
    if api_key:
        return api_key
    if provider_id:
        return get_api_key(provider_id)
    return ""


def _sanitize_env_value(value: str) -> str:
    # 去掉换行/回车，防止一条 value 注入出第二个键值对
    return value.replace("\r", "").replace("\n", "").strip()


def update_env_key(env_name: str, value: str) -> None:
    """更新 .env 文件中的某个 key（消毒 + 加锁 + 原子写）"""
    if not _ENV_NAME_RE.match(env_name):
        raise ValueError(f"非法环境变量名: {env_name!r}")
    value = _sanitize_env_value(value)

    with _config_lock:
        lines = ENV_FILE.read_text(encoding="utf-8").splitlines() if ENV_FILE.exists() else []
        new_lines, found = [], False
        for line in lines:
            if line.strip().startswith(f"{env_name}="):
                new_lines.append(f"{env_name}={value}")
                found = True
            else:
                new_lines.append(line)
        if not found:
            new_lines.append(f"{env_name}={value}")
        atomic_write_text(ENV_FILE, "\n".join(new_lines) + "\n")
    os.environ[env_name] = value


def clear_env_key(env_name: str) -> None:
    """清除 .env 文件中的某个 key"""
    if not _ENV_NAME_RE.match(env_name):
        raise ValueError(f"非法环境变量名: {env_name!r}")
    with _config_lock:
        if ENV_FILE.exists():
            lines = ENV_FILE.read_text(encoding="utf-8").splitlines()
            new_lines = [l for l in lines if not l.strip().startswith(f"{env_name}=")]
            atomic_write_text(ENV_FILE, "\n".join(new_lines) + "\n")
    os.environ.pop(env_name, None)


def get_key_preview(env_name: str) -> Tuple[bool, str]:
    """返回 (has_key, key_preview)，preview 只露末 4 位"""
    value = os.getenv(env_name, "") or read_env_keys().get(env_name, "")
    if value:
        return True, f"••••••••{value[-4:]}" if len(value) > 4 else "••••"
    return False, ""


# ---------- 模型分类 / 协议检测 ----------

IMAGE_KEYWORDS = ["image", "img", "flux", "sdxl", "dall", "kolors", "z-image",
                  "wanx", "cogview", "jimeng", "imagen", "gpt-image"]
VIDEO_KEYWORDS = ["video", "veo", "sora", "kling", "seedance", "wan2", "cogvideo",
                  "runway", "pika", "t2v", "i2v"]


def classify_models(all_models: List[str]) -> Dict[str, List[str]]:
    """自动将模型列表分类为 image/chat/video"""
    image_models: List[str] = []
    video_models: List[str] = []
    chat_models: List[str] = []
    for m in all_models:
        ml = m.lower()
        if any(kw in ml for kw in VIDEO_KEYWORDS):
            video_models.append(m)
        elif any(kw in ml for kw in IMAGE_KEYWORDS):
            image_models.append(m)
        else:
            chat_models.append(m)
    return {"image_models": image_models, "chat_models": chat_models, "video_models": video_models}


def detect_protocol(base_url: str, fallback: str = "openai") -> str:
    """根据 URL 特征检测协议类型"""
    bl = base_url.lower()
    if "runninghub" in bl:
        return "runninghub"
    if "volces.com" in bl or "volcengine" in bl or "ark.cn" in bl:
        return "volcengine"
    return fallback
