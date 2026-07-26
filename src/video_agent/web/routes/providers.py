"""
/api/providers — Provider 配置管理端点
支持：GET（读取）、PUT（保存）、POST fetch-models（拉取模型）、POST test-connection（测试连接）
数据持久化：data/api_providers.json + API/.env
"""
import json
import os
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Request
from loguru import logger
from pydantic import BaseModel

router = APIRouter()

# 路径配置
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
API_DIR = PROJECT_ROOT / "API"
PROVIDERS_FILE = DATA_DIR / "api_providers.json"
ENV_FILE = API_DIR / ".env"

# 确保目录存在
DATA_DIR.mkdir(parents=True, exist_ok=True)
API_DIR.mkdir(parents=True, exist_ok=True)

# 文件锁
_config_lock = threading.Lock()

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


# ---------- 持久化读写 ----------
def load_api_providers() -> List[Dict[str, Any]]:
    """从 JSON 文件加载 provider 配置"""
    with _config_lock:
        if PROVIDERS_FILE.exists():
            try:
                data = json.loads(PROVIDERS_FILE.read_text(encoding="utf-8"))
                return data if isinstance(data, list) else DEFAULT_PROVIDERS.copy()
            except Exception as e:
                logger.warning(f"[Providers] 读取配置失败: {e}, 使用默认配置")
        return DEFAULT_PROVIDERS.copy()


def save_api_providers(providers: List[Dict[str, Any]]):
    """保存 provider 配置到 JSON 文件"""
    with _config_lock:
        PROVIDERS_FILE.write_text(
            json.dumps(providers, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
    logger.info(f"[Providers] 已保存 {len(providers)} 个供应商配置")


# ---------- API Key 管理 (.env) ----------
def provider_key_env(provider_id: str) -> str:
    """根据 provider id 生成环境变量名"""
    mapping = {
        "modelscope": "MODELSCOPE_API_KEY",
        "volcengine": "ARK_API_KEY",
        "gemini-cli": "GEMINI_API_KEY",
    }
    if provider_id in mapping:
        return mapping[provider_id]
    return f"API_PROVIDER_{provider_id.upper().replace('-', '_')}_KEY"


def read_env_keys() -> Dict[str, str]:
    """读取 .env 文件中所有键值对"""
    keys = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                keys[k.strip()] = v.strip()
    return keys


def update_env_key(env_name: str, value: str):
    """更新 .env 文件中的某个 key"""
    lines = []
    found = False
    if ENV_FILE.exists():
        lines = ENV_FILE.read_text(encoding="utf-8").splitlines()

    new_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(f"{env_name}="):
            new_lines.append(f"{env_name}={value}")
            found = True
        else:
            new_lines.append(line)

    if not found:
        new_lines.append(f"{env_name}={value}")

    ENV_FILE.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    os.environ[env_name] = value


def clear_env_key(env_name: str):
    """清除 .env 文件中的某个 key"""
    if not ENV_FILE.exists():
        return
    lines = ENV_FILE.read_text(encoding="utf-8").splitlines()
    new_lines = [l for l in lines if not l.strip().startswith(f"{env_name}=")]
    ENV_FILE.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    os.environ.pop(env_name, None)


def get_key_preview(env_name: str) -> tuple:
    """返回 (has_key: bool, key_preview: str)"""
    value = os.getenv(env_name, "")
    if not value:
        keys = read_env_keys()
        value = keys.get(env_name, "")
    if value:
        return True, f"••••••••{value[-4:]}" if len(value) > 4 else "••••"
    return False, ""


# ---------- 公开数据（脱敏） ----------
def public_provider(p: Dict[str, Any]) -> Dict[str, Any]:
    """返回脱敏后的 provider 数据（不含完整 key）"""
    env_name = provider_key_env(p["id"])
    has_key, preview = get_key_preview(env_name)
    result = {k: v for k, v in p.items() if k not in ("api_key", "clear_key")}
    result["has_key"] = has_key
    result["key_preview"] = preview
    return result


# ---------- API 端点 ----------
@router.get("/providers")
async def get_providers():
    """获取所有 provider 配置（脱敏）"""
    providers = load_api_providers()
    return {"providers": [public_provider(p) for p in providers]}


@router.put("/providers")
async def save_providers(request: Request):
    """保存全部 provider 配置 + API Key"""
    body = await request.json()
    incoming: List[Dict[str, Any]] = body if isinstance(body, list) else body.get("providers", [])

    saved = []
    for p in incoming:
        pid = p.get("id", "")
        env_name = provider_key_env(pid)

        # 处理 API Key
        if p.get("api_key"):
            update_env_key(env_name, p["api_key"])
        if p.get("clear_key"):
            clear_env_key(env_name)

        # 存储配置（不含敏感字段）
        clean = {k: v for k, v in p.items() if k not in ("api_key", "clear_key", "has_key", "key_preview")}
        saved.append(clean)

    save_api_providers(saved)
    return {"providers": [public_provider(p) for p in saved]}


class FetchModelsRequest(BaseModel):
    base_url: str = ""
    api_key: str = ""
    provider_id: str = ""
    protocol: str = "openai"
    image_request_mode: str = "openai"


@router.post("/providers/fetch-models")
async def fetch_models(req: FetchModelsRequest):
    """从供应商 API 拉取可用模型列表并自动分类"""
    base_url = req.base_url.rstrip("/")
    api_key = req.api_key
    protocol = (req.protocol or "openai").lower()

    # CLI 协议：返回预设模型列表
    if protocol in CLI_PROTOCOLS:
        cli_models = {
            "gemini-cli": ["auto"],
            "codex": ["gpt-image-2", "gpt-5.5"],
            "jimeng": ["5.0", "4.6", "4.5", "4.1", "4.0", "3.1", "3.0"],
        }
        models = cli_models.get(protocol, ["auto"])
        return {
            "all": models,
            "image_models": models,
            "chat_models": models,
            "video_models": [],
            "total": len(models),
            "protocol": protocol,
        }

    # 如果没有传 key，尝试从 .env 读取
    if not api_key and req.provider_id:
        env_name = provider_key_env(req.provider_id)
        api_key = os.getenv(env_name, "")
        if not api_key:
            keys = read_env_keys()
            api_key = keys.get(env_name, "")

    if not base_url:
        return {"error": "缺少 Base URL", "all": [], "total": 0}

    try:
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(f"{base_url}/models", headers=headers)
            resp.raise_for_status()
            data = resp.json()

        # 解析模型列表（OpenAI 兼容格式）
        models_data = data.get("data", [])
        all_models = [m.get("id", "") for m in models_data if m.get("id")]
        all_models.sort()

        # 自动分类
        image_keywords = ["image", "img", "flux", "sdxl", "dall", "kolors", "z-image",
                          "wanx", "cogview", "jimeng", "imagen", "gpt-image"]
        video_keywords = ["video", "veo", "sora", "kling", "seedance", "wan2", "cogvideo",
                          "runway", "pika", "t2v", "i2v"]
        chat_keywords = ["gpt", "qwen", "llama", "claude", "gemini", "deepseek", "glm",
                         "chat", "instruct", "doubao", "mistral", "phi"]

        image_models = []
        video_models = []
        chat_models = []

        for m in all_models:
            ml = m.lower()
            if any(kw in ml for kw in video_keywords):
                video_models.append(m)
            elif any(kw in ml for kw in image_keywords):
                image_models.append(m)
            elif any(kw in ml for kw in chat_keywords):
                chat_models.append(m)
            else:
                chat_models.append(m)  # 默认归为对话模型

        # 检测协议
        detected_protocol = req.protocol
        if "runninghub" in base_url.lower():
            detected_protocol = "runninghub"
        elif "volces.com" in base_url or "volcengine" in base_url:
            detected_protocol = "volcengine"

        return {
            "all": all_models,
            "image_models": image_models,
            "chat_models": chat_models,
            "video_models": video_models,
            "total": len(all_models),
            "protocol": detected_protocol,
        }

    except httpx.TimeoutException:
        return {"error": "连接超时（15s）", "all": [], "total": 0}
    except httpx.HTTPStatusError as e:
        return {"error": f"HTTP {e.response.status_code}: {e.response.text[:200]}", "all": [], "total": 0}
    except Exception as e:
        return {"error": str(e), "all": [], "total": 0}


class TestConnectionRequest(BaseModel):
    base_url: str = ""
    api_key: str = ""
    provider_id: str = ""
    protocol: str = "openai"
    image_request_mode: str = "openai"


def _classify_models(all_models: List[str]) -> Dict[str, List[str]]:
    """自动将模型列表分类为 image/chat/video"""
    image_keywords = ["image", "img", "flux", "sdxl", "dall", "kolors", "z-image",
                      "wanx", "cogview", "jimeng", "imagen", "gpt-image"]
    video_keywords = ["video", "veo", "sora", "kling", "seedance", "wan2", "cogvideo",
                      "runway", "pika", "t2v", "i2v"]

    image_models, video_models, chat_models = [], [], []
    for m in all_models:
        ml = m.lower()
        if any(kw in ml for kw in video_keywords):
            video_models.append(m)
        elif any(kw in ml for kw in image_keywords):
            image_models.append(m)
        else:
            chat_models.append(m)
    return {"image_models": image_models, "chat_models": chat_models, "video_models": video_models}


def _detect_protocol(base_url: str, fallback: str = "openai") -> str:
    """根据 URL 特征检测协议类型"""
    bl = base_url.lower()
    if "runninghub" in bl:
        return "runninghub"
    if "volces.com" in bl or "volcengine" in bl or "ark.cn" in bl:
        return "volcengine"
    return fallback


def _resolve_api_key(api_key: str, provider_id: str) -> str:
    """解析 API Key：优先使用传入值，否则从 .env 读取"""
    if api_key:
        return api_key
    if provider_id:
        env_name = provider_key_env(provider_id)
        val = os.getenv(env_name, "")
        if not val:
            val = read_env_keys().get(env_name, "")
        return val
    return ""


# CLI 协议集合（无需 Base URL，通过本机 CLI 工具通信）
CLI_PROTOCOLS = {"jimeng", "codex", "gemini-cli"}


async def _check_cli_protocol(protocol: str) -> Dict[str, Any]:
    """对 CLI 协议执行本机检测，返回 test-connection 兼容格式"""
    import shutil
    import glob as glob_mod

    def find_exe(name: str, winget_pattern: str = ""):
        exe = shutil.which(name)
        if exe:
            return exe
        if winget_pattern:
            local_app = os.getenv("LOCALAPPDATA", "")
            if local_app:
                pattern = os.path.join(local_app, winget_pattern)
                matches = sorted(glob_mod.glob(pattern), reverse=True)
                if matches:
                    return matches[0]
        return None

    if protocol == "gemini-cli":
        exe = find_exe("agy", r"Microsoft\WinGet\Packages\Google.AntigravityCLI_*\agy.exe")
        cli_name = "Antigravity CLI (agy)"
        models = ["auto"]
    elif protocol == "codex":
        exe = find_exe("codex") or find_exe("codex.cmd")
        cli_name = "OpenAI Codex CLI"
        models = ["gpt-image-2", "gpt-5.5"]
    elif protocol == "jimeng":
        exe = find_exe("dreamina") or find_exe("dreamina.cmd")
        cli_name = "即梦 CLI (dreamina)"
        models = ["5.0", "4.6", "4.5"]
    else:
        exe = None
        cli_name = protocol
        models = []

    if not exe:
        return {
            "ok": False,
            "status": 0,
            "protocol": protocol,
            "message": f"{cli_name} 未安装，请先安装 CLI 文件夹中的依赖",
            "model_count": 0,
        }

    return {
        "ok": True,
        "status": 200,
        "protocol": protocol,
        "model_count": len(models),
        "all": models,
        "image_models": models,
        "chat_models": models,
        "video_models": [],
        "image_request_mode": "openai",
        "message": f"{cli_name} 已就绪 ({exe})",
    }


@router.post("/providers/test-connection")
async def test_connection(req: TestConnectionRequest):
    """测试与供应商 API 的连接，返回模型列表（前端验证地址按钮调用）"""
    base_url = req.base_url.rstrip("/")
    api_key = _resolve_api_key(req.api_key, req.provider_id)
    protocol = (req.protocol or "openai").lower()

    # CLI 协议无需 Base URL，直接检测本机 CLI
    if protocol in CLI_PROTOCOLS:
        return await _check_cli_protocol(protocol)

    if not base_url:
        return {"ok": False, "status": 0, "message": "缺少 Base URL", "model_count": 0}

    try:
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(f"{base_url}/models", headers=headers)
            status_code = resp.status_code
            resp.raise_for_status()
            data = resp.json()

        models_data = data.get("data", [])
        all_models = sorted([m.get("id", "") for m in models_data if m.get("id")])
        classified = _classify_models(all_models)
        detected_protocol = _detect_protocol(base_url, req.protocol)

        return {
            "ok": True,
            "status": status_code,
            "protocol": detected_protocol,
            "model_count": len(all_models),
            "all": all_models,
            "image_models": classified["image_models"],
            "chat_models": classified["chat_models"],
            "video_models": classified["video_models"],
            "image_request_mode": req.image_request_mode or "openai",
            "message": f"连接成功，发现 {len(all_models)} 个模型",
        }

    except httpx.TimeoutException:
        return {"ok": False, "status": 0, "message": "连接超时（15s）", "model_count": 0}
    except httpx.HTTPStatusError as e:
        msg = "认证失败：API Key 无效或未提供" if e.response.status_code == 401 else f"HTTP {e.response.status_code}"
        return {"ok": False, "status": e.response.status_code, "message": msg, "model_count": 0}
    except Exception as e:
        return {"ok": False, "status": 0, "message": str(e), "model_count": 0}


class ProbeAsyncRequest(BaseModel):
    base_url: str = ""
    api_key: str = ""
    provider_id: str = ""
    protocol: str = "openai"
    image_request_mode: str = "openai"


@router.post("/providers/probe-async")
async def probe_async(req: ProbeAsyncRequest):
    """探测供应商协议类型（前端验证协议按钮调用）"""
    base_url = req.base_url.rstrip("/")
    api_key = _resolve_api_key(req.api_key, req.provider_id)
    protocol = (req.protocol or "openai").lower()

    # CLI 协议无需网络探测，直接返回已确认的协议
    if protocol in CLI_PROTOCOLS:
        return {
            "ok": True,
            "protocol": protocol,
            "message": f"CLI 协议 ({protocol}) 已确认",
            "status_code": 200,
            "raw": {},
            "image_request_mode": "openai",
        }

    if not base_url:
        return {"ok": False, "protocol": "openai", "message": "缺少 Base URL", "status_code": 0, "raw": {}}

    try:
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        async with httpx.AsyncClient(timeout=12) as client:
            resp = await client.get(f"{base_url}/models", headers=headers)
            status_code = resp.status_code
            raw = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {"text": resp.text[:500]}

        detected_protocol = _detect_protocol(base_url, "openai")

        # 检查是否是异步 API（apimart 风格）
        is_async = False
        if isinstance(raw, dict):
            if "tasks" in str(raw.get("object", "")) or "/v1/tasks/" in base_url:
                is_async = True
                detected_protocol = "apimart"

        if resp.status_code == 200:
            msg = f"连接正常 · 检测到 {detected_protocol.upper()} 协议"
            return {
                "ok": True,
                "protocol": detected_protocol,
                "message": msg,
                "status_code": status_code,
                "raw": raw,
                "image_request_mode": req.image_request_mode or "openai",
            }
        else:
            return {
                "ok": None,
                "protocol": detected_protocol,
                "message": f"HTTP {status_code}，协议已设为 OpenAI 兼容",
                "status_code": status_code,
                "raw": raw,
                "image_request_mode": "openai",
            }

    except httpx.TimeoutException:
        return {"ok": False, "protocol": "openai", "message": "连接超时", "status_code": 0, "raw": {}}
    except Exception as e:
        return {"ok": False, "protocol": "openai", "message": str(e), "status_code": 0, "raw": {}}
