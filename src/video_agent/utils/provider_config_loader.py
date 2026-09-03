"""供应商配置加载/解析/Key 管理（跨切面基础设施）。

职责边界：纯配置 I/O 与格式化工具函数，不含业务映射逻辑
（CLI_PROTOCOLS / exclude_retired_mock_providers 等业务常量与过滤归
core/provider_config.py）。

- 供应商配置：data/api_providers.json
- API Key：进程环境变量优先，其次 API/.env
- .env 写入带消毒（去换行）与线程锁，防止 value 注入其他键

所有权声明：api_providers.json 定位「配置文件」而非运行时数据（用户在
api-settings 页面手工维护、需 diff/备份语义），豁免迁入 sqlite，
维持文件为唯一权威源不动。
"""
import asyncio
import json
import os
import re
import threading
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from src.video_agent.utils.fileio import atomic_write_text
from src.video_agent.utils.paths import DATA_DIR, API_DIR, PROVIDERS_FILE, ENV_FILE
from src.video_agent.core.provider_models import validate_providers

# 同时保护 providers 文件与 .env 文件的读写
_config_lock = threading.Lock()

_ENV_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")

# ---------- 默认 Provider 配置 ----------
DEFAULT_PROVIDERS: List[Dict[str, Any]] = [
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


# ---------- 供应商配置加载 ----------

def load_api_providers() -> List[Dict[str, Any]]:
    """从 JSON 文件加载 provider 配置；不存在或损坏时回退默认配置。加载后进行 Pydantic 校验。"""
    with _config_lock:
        if PROVIDERS_FILE.exists():
            try:
                data = json.loads(PROVIDERS_FILE.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    return validate_providers(data)
                logger.warning("[ProviderConfig] api_providers.json 不是列表，回退默认配置")
            except Exception as e:
                logger.warning(f"[ProviderConfig] 读取配置失败: {e}，回退默认配置")
        return [dict(p) for p in DEFAULT_PROVIDERS]


def save_api_providers(providers: List[Dict[str, Any]]) -> None:
    """保存 provider 配置（原子写）"""
    with _config_lock:
        atomic_write_text(PROVIDERS_FILE, json.dumps(providers, ensure_ascii=False, indent=2))
    logger.info(f"[ProviderConfig] 已保存 {len(providers)} 个供应商配置")


# ---------- provider 列表入口 ----------

def load_merged_providers() -> List[Dict[str, Any]]:
    """provider 列表唯一入口（纯本地文件源 data/api_providers.json）。

    保留函数名与签名（调用面广），历史画布合并逻辑已随画布通道退役移除。"""
    return load_api_providers()


async def load_merged_providers_async() -> List[Dict[str, Any]]:
    """异步入口（聊天/工具/生成链路）：事件循环内不阻塞。"""
    return await asyncio.to_thread(load_merged_providers)


def get_provider_config(provider_id: str) -> Optional[Dict[str, Any]]:
    """按 id 查找单个供应商配置（从合并列表中查找）"""
    if not provider_id:
        return None
    for p in load_merged_providers():
        if p.get("id") == provider_id:
            return p
    return None


async def get_provider_config_async(provider_id: str) -> Optional[Dict[str, Any]]:
    """异步版：按 id 查找单个供应商配置（从合并列表中查找）"""
    if not provider_id:
        return None
    for p in await load_merged_providers_async():
        if p.get("id") == provider_id:
            return p
    return None


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


def runninghub_wallet_key_env() -> str:
    """RunningHub 账户余额 Key 的环境变量名（标准模型/视频模型走余额）"""
    return "RUNNINGHUB_WALLET_API_KEY"


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


def get_api_key(provider_id: str) -> str:
    """解析某供应商的 API Key：
    1. 进程环境变量
    2. Agent 本地 API/.env
    """
    env_name = provider_key_env(provider_id)
    val = os.getenv(env_name, "")
    if val:
        return val
    return read_env_keys().get(env_name, "")


async def get_api_key_async(provider_id: str) -> str:
    """异步版：解析某供应商的 API Key"""
    return get_api_key(provider_id)


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
