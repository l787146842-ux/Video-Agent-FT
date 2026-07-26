"""
/api/providers — Provider 配置管理端点
支持：GET（读取）、PUT（保存）、POST fetch-models（拉取模型）、POST test-connection（测试连接）

配置/Key 的读写、模型分类、协议检测统一走 web/provider_config.py（唯一入口）。
"""
import os
from typing import Any, Dict, List

import httpx
from fastapi import APIRouter, Request
from loguru import logger
from pydantic import BaseModel

from src.video_agent.web.provider_config import (
    CLI_PROTOCOLS,
    classify_models,
    clear_env_key,
    detect_protocol,
    get_key_preview,
    load_api_providers,
    provider_key_env,
    resolve_api_key,
    save_api_providers,
    update_env_key,
)

router = APIRouter()


# ---------- 公开数据（脱敏） ----------
def public_provider(p: Dict[str, Any]) -> Dict[str, Any]:
    """返回脱敏后的 provider 数据（不含完整 key）"""
    env_name = provider_key_env(p.get("id", ""))
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

        # 处理 API Key（写入已消毒 + 加锁 + 原子写）
        try:
            if p.get("api_key"):
                update_env_key(env_name, p["api_key"])
            if p.get("clear_key"):
                clear_env_key(env_name)
        except ValueError as e:
            logger.warning(f"[Providers] key 写入被拒绝: {e}")

        # 存储配置（不含敏感字段）
        clean = {k: v for k, v in p.items() if k not in ("api_key", "clear_key", "has_key", "key_preview")}
        saved.append(clean)

    save_api_providers(saved)
    return {"providers": [public_provider(p) for p in saved]}


class ProviderProbeRequest(BaseModel):
    base_url: str = ""
    api_key: str = ""
    provider_id: str = ""
    protocol: str = "openai"
    image_request_mode: str = "openai"


async def _fetch_model_list(base_url: str, api_key: str) -> List[str]:
    """GET {base_url}/models，返回排序后的模型 id 列表（OpenAI 兼容格式）"""
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(f"{base_url}/models", headers=headers)
        resp.raise_for_status()
        data = resp.json()
    models_data = data.get("data", [])
    return sorted(m.get("id", "") for m in models_data if m.get("id"))


# CLI 协议的预设模型
_CLI_MODELS = {
    "gemini-cli": ["auto"],
    "codex": ["gpt-image-2", "gpt-5.5"],
    "jimeng": ["5.0", "4.6", "4.5", "4.1", "4.0", "3.1", "3.0"],
}


@router.post("/providers/fetch-models")
async def fetch_models(req: ProviderProbeRequest):
    """从供应商 API 拉取可用模型列表并自动分类"""
    base_url = req.base_url.rstrip("/")
    protocol = (req.protocol or "openai").lower()

    # CLI 协议：返回预设模型列表
    if protocol in CLI_PROTOCOLS:
        models = _CLI_MODELS.get(protocol, ["auto"])
        return {
            "all": models,
            "image_models": models,
            "chat_models": models,
            "video_models": [],
            "total": len(models),
            "protocol": protocol,
        }

    api_key = resolve_api_key(req.api_key, req.provider_id)
    if not base_url:
        return {"error": "缺少 Base URL", "all": [], "total": 0}

    try:
        all_models = await _fetch_model_list(base_url, api_key)
        classified = classify_models(all_models)
        return {
            "all": all_models,
            **classified,
            "total": len(all_models),
            "protocol": detect_protocol(base_url, req.protocol),
        }
    except httpx.TimeoutException:
        return {"error": "连接超时（15s）", "all": [], "total": 0}
    except httpx.HTTPStatusError as e:
        return {"error": f"HTTP {e.response.status_code}: {e.response.text[:200]}", "all": [], "total": 0}
    except Exception as e:
        return {"error": str(e), "all": [], "total": 0}


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
        models = _CLI_MODELS["gemini-cli"]
    elif protocol == "codex":
        exe = find_exe("codex") or find_exe("codex.cmd")
        cli_name = "OpenAI Codex CLI"
        models = _CLI_MODELS["codex"]
    elif protocol == "jimeng":
        exe = find_exe("dreamina") or find_exe("dreamina.cmd")
        cli_name = "即梦 CLI (dreamina)"
        models = _CLI_MODELS["jimeng"][:3]
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
async def test_connection(req: ProviderProbeRequest):
    """测试与供应商 API 的连接，返回模型列表（前端验证地址按钮调用）"""
    base_url = req.base_url.rstrip("/")
    protocol = (req.protocol or "openai").lower()

    if protocol in CLI_PROTOCOLS:
        return await _check_cli_protocol(protocol)

    if not base_url:
        return {"ok": False, "status": 0, "message": "缺少 Base URL", "model_count": 0}

    api_key = resolve_api_key(req.api_key, req.provider_id)
    try:
        all_models = await _fetch_model_list(base_url, api_key)
        classified = classify_models(all_models)
        return {
            "ok": True,
            "status": 200,
            "protocol": detect_protocol(base_url, req.protocol),
            "model_count": len(all_models),
            "all": all_models,
            **classified,
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


@router.post("/providers/probe-async")
async def probe_async(req: ProviderProbeRequest):
    """探测供应商协议类型（前端验证协议按钮调用）"""
    base_url = req.base_url.rstrip("/")
    protocol = (req.protocol or "openai").lower()

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

    api_key = resolve_api_key(req.api_key, req.provider_id)
    try:
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        async with httpx.AsyncClient(timeout=12) as client:
            resp = await client.get(f"{base_url}/models", headers=headers)
            status_code = resp.status_code
            raw = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {"text": resp.text[:500]}

        detected_protocol = detect_protocol(base_url, "openai")

        # 检查是否是异步 API（apimart 风格）
        if isinstance(raw, dict):
            if "tasks" in str(raw.get("object", "")) or "/v1/tasks/" in base_url:
                detected_protocol = "apimart"

        if status_code == 200:
            return {
                "ok": True,
                "protocol": detected_protocol,
                "message": f"连接正常 · 检测到 {detected_protocol.upper()} 协议",
                "status_code": status_code,
                "raw": raw,
                "image_request_mode": req.image_request_mode or "openai",
            }
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
