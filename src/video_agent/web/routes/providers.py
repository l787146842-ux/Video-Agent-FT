"""
/api/providers — Provider 配置管理端点
支持：GET（读取）、PUT（保存）、POST fetch-models（拉取模型）、POST test-connection（测试连接）

配置/Key 的读写、模型分类、协议检测统一走 web/provider_config.py（唯一入口）。
"""
import glob as glob_mod
import ipaddress
import os
import shutil
from typing import Any, Dict, List
from urllib.parse import urlparse

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
    load_merged_providers,
    provider_key_env,
    resolve_api_key,
    save_api_providers,
    update_env_key,
)
from src.video_agent.adapters.canvas_adapter import get_canvas_adapter

router = APIRouter()


# ---------- Response Models ----------

class ProvidersResponse(BaseModel):
    providers: List[Dict[str, Any]] = []
    canvas_online: bool = False


class FetchModelsResponse(BaseModel):
    all: List[str] = []
    image_models: List[str] = []
    chat_models: List[str] = []
    video_models: List[str] = []
    total: int = 0
    protocol: str = "openai"
    error: str = ""


class TestConnectionResponse(BaseModel):
    ok: bool = False
    status: int = 0
    protocol: str = "openai"
    message: str = ""
    model_count: int = 0
    all: List[str] = []
    image_models: List[str] = []
    chat_models: List[str] = []
    video_models: List[str] = []
    image_request_mode: str = "openai"


# ---------- SSRF 防护：内网地址黑名单 ----------
_BLOCKED_NETWORKS = [
    # 注意：127.0.0.0/8 不在此列表中——本地反代（如 Gemini 反代 127.0.0.1:8045）
    # 是合法使用场景，本项目为本地工具，无需阻止回环地址。
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("fc00::/7"),
]

# 明确允许的本地地址（不受 _BLOCKED_NETWORKS 限制）
_LOCAL_ALLOWED_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}


def _validate_external_url(url: str) -> None:
    """校验 URL 不指向内网地址，违反则抛 ValueError。
    本地回环地址（127.x / localhost / ::1）明确放行，供本地反代等场景使用。"""
    parsed = urlparse(url)
    host = parsed.hostname or ""
    # 本地地址直接放行
    if host in _LOCAL_ALLOWED_HOSTS:
        return
    try:
        ip = ipaddress.ip_address(host)
        # 回环地址放行（127.0.0.0/8 全段）
        if ip.is_loopback:
            return
        for net in _BLOCKED_NETWORKS:
            if ip in net:
                raise ValueError(f"禁止访问内网地址: {host}")
    except ValueError as e:
        if "禁止" in str(e):
            raise
        # host 是域名，允许通过（DNS 解析由 httpx 处理）


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
@router.get("/providers", response_model=ProvidersResponse)
async def get_providers():
    """获取所有 provider 配置（脱敏，合并本地 + 熊布）"""
    providers = load_merged_providers()
    adapter = get_canvas_adapter()
    canvas_online = await adapter.is_online()
    return {
        "providers": [public_provider(p) for p in providers],
        "canvas_online": canvas_online,
    }


@router.get("/canvas-assets")
async def get_canvas_assets():
    """代理获取熊布素材库管理系统的完整数据（前端“素材库”按钮调用）"""
    adapter = get_canvas_adapter()
    try:
        library = await adapter.list_asset_library()
        return {"library": library, "canvas_online": True}
    except Exception as e:
        logger.warning(f"[Providers] 获取熊布素材库失败: {e}")
        return {"library": None, "canvas_online": False, "error": str(e)}


@router.get("/asset-picker")
async def asset_picker(type: str = "image"):
    """统一素材选择器代理端点。
    type: image(图片资产) | canvas(画布资产) | local(本地素材)
    返回标准化结构: {items: [{id, name, url, thumb, category}], canvas_online}
    """
    adapter = get_canvas_adapter()
    base_url = adapter.base_url
    try:
        if type == "image":
            library = await adapter.list_asset_library()
            items = _flatten_asset_library(library, base_url)
        elif type == "canvas":
            raw = await adapter.list_assets()
            items = _flatten_canvas_assets(raw, base_url)
        elif type == "local":
            raw = await adapter.list_local_assets()
            items = _flatten_local_assets(raw, base_url)
        else:
            items = []
        return {"items": items, "canvas_online": True}
    except Exception as e:
        logger.warning(f"[Providers] asset-picker({type}) 失败: {e}")
        return {"items": [], "canvas_online": False, "error": str(e)}


def _flatten_asset_library(library: Any, base_url: str) -> List[Dict[str, Any]]:
    """将熊布 asset-library 结构平坦化为标准 items"""
    items: List[Dict[str, Any]] = []
    if not library or not isinstance(library, dict):
        return items
    libraries = library.get("libraries") or []
    active_id = library.get("active_library_id", "")
    active_lib = next((l for l in libraries if l.get("id") == active_id), None) or (libraries[0] if libraries else None)
    categories = (active_lib.get("categories") if active_lib else None) or library.get("categories") or []
    for cat in categories:
        cat_name = cat.get("name", "")
        for item in (cat.get("items") or []):
            url = item.get("url") or item.get("path") or ""
            if url and not url.startswith("http"):
                url = f"{base_url}{url}" if url.startswith("/") else f"{base_url}/{url}"
            items.append({
                "id": item.get("id", ""),
                "name": item.get("name", ""),
                "url": url,
                "thumb": url,
                "category": cat_name,
            })
    return items


def _flatten_canvas_assets(raw: Any, base_url: str) -> List[Dict[str, Any]]:
    """将熊布 canvas-assets 平坦化"""
    items: List[Dict[str, Any]] = []
    entries = raw if isinstance(raw, list) else (raw.get("items", []) if isinstance(raw, dict) else [])
    for entry in entries[:200]:
        url = entry.get("url") or entry.get("image_url") or entry.get("path") or ""
        if url and not url.startswith("http"):
            url = f"{base_url}{url}" if url.startswith("/") else f"{base_url}/{url}"
        items.append({
            "id": entry.get("id", ""),
            "name": entry.get("name") or entry.get("title") or "",
            "url": url,
            "thumb": url,
            "category": entry.get("canvas_title") or entry.get("source") or "画布",
        })
    return items


def _flatten_local_assets(raw: Any, base_url: str) -> List[Dict[str, Any]]:
    """将熊布 local-assets 平坦化"""
    items: List[Dict[str, Any]] = []
    entries = raw if isinstance(raw, list) else []
    for entry in entries[:200]:
        url = entry.get("url") or entry.get("path") or ""
        if url and not url.startswith("http"):
            url = f"{base_url}{url}" if url.startswith("/") else f"{base_url}/{url}"
        items.append({
            "id": entry.get("id") or entry.get("name", ""),
            "name": entry.get("name") or entry.get("filename") or "",
            "url": url,
            "thumb": url,
            "category": entry.get("folder") or "本地",
        })
    return items


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


def _normalize_openai_base_url(base_url: str) -> str:
    """与熊布保持一致：若 base_url 未以 /v1 结尾则自动补全，避免用户手填时漏掉路径段。"""
    url = base_url.rstrip("/")
    if not url.endswith("/v1"):
        url += "/v1"
    return url


async def _fetch_model_list(base_url: str, api_key: str) -> List[str]:
    """GET {base_url}/models，返回排序后的模型 id 列表（OpenAI 兼容格式）"""
    url = _normalize_openai_base_url(base_url)
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(f"{url}/models", headers=headers)
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


@router.post("/providers/fetch-models", response_model=FetchModelsResponse)
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
        _validate_external_url(base_url)
    except ValueError as e:
        return {"error": str(e), "all": [], "total": 0}

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


@router.post("/providers/test-connection", response_model=TestConnectionResponse)
async def test_connection(req: ProviderProbeRequest):
    """测试与供应商 API 的连接，返回模型列表（前端验证地址按钮调用）"""
    base_url = req.base_url.rstrip("/")
    protocol = (req.protocol or "openai").lower()

    if protocol in CLI_PROTOCOLS:
        return await _check_cli_protocol(protocol)

    if not base_url:
        return {"ok": False, "status": 0, "message": "缺少 Base URL", "model_count": 0}

    try:
        _validate_external_url(base_url)
    except ValueError as e:
        return {"ok": False, "status": 0, "message": str(e), "model_count": 0}

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

    try:
        _validate_external_url(base_url)
    except ValueError as e:
        return {"ok": False, "protocol": "openai", "message": str(e), "status_code": 0, "raw": {}}

    api_key = resolve_api_key(req.api_key, req.provider_id)
    try:
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        probe_url = _normalize_openai_base_url(base_url)
        async with httpx.AsyncClient(timeout=12) as client:
            resp = await client.get(f"{probe_url}/models", headers=headers)
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
