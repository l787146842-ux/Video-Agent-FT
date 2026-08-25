"""MCP 外部工具接入层。

deny-first 三层纵深（外部工具不可信，宪法 §2.7 同口径）：
1. 配置面：无 data/mcp_servers.json = 零工具；deny_servers/deny_tools
   命中的工具连注册都不进（fail-closed）；
2. 可见性面：两段式注入——目录文本块常驻 system prompt，完整 schema
   仅对 interaction.mcp_enabled 白名单内工具注入 FC tools（planner 裁剪）；
3. 执行面：未启用直调拒执行（adapter）+ high 级工具经 guard_pipeline
   的 platform.tool_risk 确认闸（fc_gates 接线），无用户同意硬拒。

模块分工：config.py 配置 / client.py 连接 / adapter.py 适配 /
policy.py deny 与 risk / catalog.py 目录与启停。
"""
import asyncio
from typing import Any, Callable, Dict, Optional

from loguru import logger

from src.video_agent.config import settings
from src.video_agent.tools.manager import ToolManager
from src.video_agent.tools.mcp import policy as mcp_policy
from src.video_agent.tools.mcp.adapter import (
    ADAPTERS,
    McpToolAdapter,
    forget_all,
    remember,
)
from src.video_agent.tools.mcp import catalog as mcp_catalog
from src.video_agent.tools.mcp.catalog import McpToolCatalogTool
from src.video_agent.tools.mcp.client import BaseMcpClient, build_client
from src.video_agent.tools.mcp.config import load_mcp_config, mcp_sdk_available

ClientFactory = Callable[[str, Dict[str, Any]], BaseMcpClient]


def register_mcp_tools(client_factory: Optional[ClientFactory] = None) -> int:
    """按配置注册 MCP 工具，返回注册数（诚实降级：任何失败只减不炸）。

    client_factory：客户端工厂替身（测试注入假客户端，不经 SDK/外网）；
    缺省用官方 SDK 客户端，SDK 未安装时整层降级返回 0。
    """
    forget_all()
    if not bool(getattr(settings, "mcp_enabled", True)):
        logger.info("[mcp] 总开关 MCP_ENABLED=off，接入层整体停用")
        return 0
    cfg = load_mcp_config()
    servers: Dict[str, Any] = cfg.get("servers") or {}
    policy_cfg: Dict[str, Any] = cfg.get("policy") or {}
    # 注册期 policy 配置写入目录模块上下文（catalog enable 上限判定
    # 消费真实配置）
    mcp_catalog.set_policy_cfg(policy_cfg)
    if not servers:
        return 0
    factory = client_factory or build_client
    if client_factory is None and not mcp_sdk_available():
        logger.warning(
            "[mcp] mcp SDK 未安装，MCP 接入层诚实降级为零工具"
            "（pip install mcp 后重启生效）")
        return 0
    registered = 0
    for server_name, scfg in servers.items():
        if not isinstance(scfg, dict) or scfg.get("enabled", True) is False:
            continue
        if mcp_policy.is_server_denied(policy_cfg, server_name):
            logger.info(f"[mcp] server '{server_name}' 命中 deny_servers，整批不注册")
            continue
        registered += _register_server(server_name, scfg, policy_cfg, factory)
    if registered:
        ToolManager.register(McpToolCatalogTool())
        logger.info(f"[mcp] 注册 MCP 工具 {registered} 个（目录工具已挂载）")
    return registered


def _register_server(
    server_name: str,
    scfg: Dict[str, Any],
    policy_cfg: Dict[str, Any],
    factory: ClientFactory,
) -> int:
    """单 server 注册：懒清单拉取失败即降级跳过（不阻断整批）。

    清单拉完即 aclose 释放注册期临时会话：注册期在临时事件循环里建连
    （stdio 子进程绑定该 loop），loop 关闭后运行期复用必失败且泄漏子进程；
    释放后运行期 call_tool 经 _ensure_session 懒重建（跨循环校验在 client）。
    """
    client = factory(server_name, scfg)
    try:
        try:
            tools = _run_sync(client.list_tools())
        except Exception as e:
            logger.warning(f"[mcp] server '{server_name}' 工具清单获取失败，跳过: {e}")
            return 0
    finally:
        try:
            _run_sync(client.aclose())
        except Exception as e:
            logger.debug(f"[mcp] server '{server_name}' 注册期会话释放忽略异常: {e}")
    count = 0
    for t in tools:
        tool_name = str(t.get("name") or "").strip()
        if not tool_name:
            continue
        full = mcp_policy.qualified_name(server_name, tool_name)
        if mcp_policy.is_tool_denied(policy_cfg, full):
            logger.info(f"[mcp] '{full}' 命中 deny_tools，不注册（fail-closed）")
            continue
        risk = mcp_policy.resolve_tool_risk(scfg, tool_name)
        adapter = McpToolAdapter(
            server_name, tool_name,
            description=str(t.get("description") or ""),
            risk=risk,
            remote_schema=t.get("inputSchema") or {},
            client=client,
        )
        try:
            ToolManager.register(adapter)
        except ValueError as e:
            logger.warning(f"[mcp] '{full}' 注册被拒（risk 校验）: {e}")
            continue
        remember(adapter)
        count += 1
    return count


def _run_sync(coro):
    """同步取异步结果（注册期处于同步上下文；已有事件循环时另起环）。"""
    try:
        return asyncio.run(coro)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()


def unregister_mcp_tools() -> None:
    """卸载全部 MCP 工具（测试/热重置用；平台工具目录一并移除）。"""
    for name in list(ADAPTERS.keys()):
        ToolManager._tools.pop(name, None)
    ToolManager._tools.pop(mcp_policy.CATALOG_TOOL_NAME, None)
    ToolManager._schema_cache = None
    mcp_catalog.set_policy_cfg({})
    forget_all()
