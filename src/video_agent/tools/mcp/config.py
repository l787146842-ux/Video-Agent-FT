"""MCP 接入层：服务器配置加载（任务#37 B4 §2.5 config.py）。

配置文件 = data/mcp_servers.json（风格对齐 data/api_providers.json）；
无配置文件 = 零工具（deny-first 的配置面：不声明即不存在）。
fail-closed：JSON 非法/结构不符 → 视为无配置；单个条目非法 →
跳过该条并 warning，不截断整批（与 registry.sync_all 同款防御）。
"""
import json
from pathlib import Path
from typing import Any, Dict, Optional

from loguru import logger

from src.video_agent.utils.paths import PROJECT_ROOT

# 传输方式白名单（官方 SDK 支持的两种本地/远程形态；SSE 已弃用不收）
ALLOWED_TRANSPORTS = ("stdio", "streamable_http")

try:  # mcp SDK 为可选依赖：未安装时诚实降级（日志可见），不阻断主链路
    import mcp as _mcp_sdk  # noqa: F401
    MCP_SDK_AVAILABLE = True
except Exception:
    _mcp_sdk = None
    MCP_SDK_AVAILABLE = False


def mcp_config_path() -> Path:
    """配置文件路径（.example 为模板，运行时只认无后缀正式文件）。"""
    return PROJECT_ROOT / "data" / "mcp_servers.json"


def mcp_sdk_available() -> bool:
    """mcp SDK 是否可导入（注册与建连的前置；False 时整层诚实降级）。"""
    return MCP_SDK_AVAILABLE


def load_mcp_config(path: Optional[Path] = None) -> Dict[str, Any]:
    """读取并净化配置，返回 {"servers": {...}, "policy": {...}}。

    fail-closed 口径：任何读取/解析失败都回落为空配置（零工具），
    非法条目逐条跳过不牵连整批。
    """
    p = Path(path) if path else mcp_config_path()
    if not p.exists():
        return {"servers": {}, "policy": {}}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning(f"[mcp.config] 配置文件解析失败，视为无配置: {p} ({e})")
        return {"servers": {}, "policy": {}}
    if not isinstance(raw, dict):
        logger.warning(f"[mcp.config] 配置顶层必须是对象，视为无配置: {p}")
        return {"servers": {}, "policy": {}}
    servers_raw = raw.get("servers")
    servers: Dict[str, Any] = {}
    if isinstance(servers_raw, dict):
        for name, entry in servers_raw.items():
            ok, why = _validate_server_entry(entry)
            if not ok:
                logger.warning(f"[mcp.config] 跳过非法条目 '{name}': {why}")
                continue
            servers[str(name)] = entry
    elif servers_raw not in (None, {}):
        logger.warning("[mcp.config] servers 必须是对象，已忽略")
    policy = raw.get("policy") if isinstance(raw.get("policy"), dict) else {}
    return {"servers": servers, "policy": policy}


def _validate_server_entry(entry: Any) -> "tuple[bool, str]":
    """单条目结构校验（fail-closed）：transport 白名单 + stdio 必备 command。"""
    if not isinstance(entry, dict):
        return False, "条目必须是对象"
    transport = str(entry.get("transport") or "").strip().lower()
    if transport not in ALLOWED_TRANSPORTS:
        return False, f"transport 必须是 {ALLOWED_TRANSPORTS}"
    if transport == "stdio" and not str(entry.get("command") or "").strip():
        return False, "stdio 传输必须声明 command"
    if transport == "streamable_http" and not str(entry.get("url") or "").strip():
        return False, "streamable_http 传输必须声明 url"
    return True, ""
