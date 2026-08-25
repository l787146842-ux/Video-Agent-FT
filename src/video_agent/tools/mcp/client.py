"""MCP 接入层：连接管理。

基于 mcp SDK 的懒连接客户端：首次需要才建连/起子进程；工具清单
健康缓存（仿 canvas_health_cache_seconds 模式）；任何异常统一收敛为
McpClientError 由调用方降级，不抛进对话循环（断连即降级不阻断主链路）。
测试可不经 SDK 直接注入实现 BaseMcpClient 契约的假客户端。
"""
import asyncio
import time
from contextlib import AsyncExitStack
from typing import Any, Dict, List, Optional

from loguru import logger

from src.video_agent.config import settings

# SDK 子模块顶层守卫导入（可选依赖：缺失时整层诚实降级，不用方法内 import）
try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from mcp.client.streamable_http import streamablehttp_client
    _MCP_SDK_READY = True
except Exception:
    ClientSession = None
    StdioServerParameters = None
    stdio_client = None
    streamablehttp_client = None
    _MCP_SDK_READY = False


class McpClientError(Exception):
    """MCP 连接/调用失败统一出口（调用方诚实降级，不阻断主链路）。"""


class BaseMcpClient:
    """传输层契约（测试假客户端与真实 SDK 客户端同形）。"""

    async def list_tools(self) -> List[Dict[str, Any]]:
        raise NotImplementedError

    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> Any:
        raise NotImplementedError

    async def aclose(self) -> None:
        return None


class SdkMcpClient(BaseMcpClient):
    """官方 SDK 客户端封装（stdio / Streamable HTTP，懒连接）。"""

    def __init__(self, server_name: str, cfg: Dict[str, Any]) -> None:
        self.server_name = str(server_name or "")
        self.cfg = cfg if isinstance(cfg, dict) else {}
        self._session: Any = None
        self._stack: Optional[AsyncExitStack] = None
        # 建连时的事件循环（跨循环复用 session/stdio 子进程必失败：
        # 复用前校验，不一致即 teardown 重建）
        self._session_loop: Optional[asyncio.AbstractEventLoop] = None
        self._tools_cache: Optional[List[Dict[str, Any]]] = None
        self._tools_cache_at: float = 0.0

    async def _ensure_session(self) -> Any:
        if self._session is not None:
            loop = self._session_loop
            if loop is not None and not loop.is_closed() \
                    and loop is asyncio.get_running_loop():
                return self._session
            # 跨事件循环/旧循环已关闭（注册期临时 loop 建的会话被运行期
            # 复用等场景）：会话与 stdio 子进程绑定旧 loop，直接重建
            logger.info(
                f"[mcp.client] '{self.server_name}' 会话所属事件循环已失效，重建连接")
            await self._teardown()
        if not _MCP_SDK_READY:
            raise McpClientError("mcp SDK 未安装（pip install mcp 后重启生效）")
        try:
            stack = AsyncExitStack()
            transport = str(self.cfg.get("transport") or "").strip().lower()
            if transport == "stdio":
                params = StdioServerParameters(
                    command=str(self.cfg.get("command") or ""),
                    args=list(self.cfg.get("args") or []),
                    env=dict(self.cfg.get("env") or {}) or None,
                )
                read, write = await stack.enter_async_context(stdio_client(params))
            else:
                read, write, _ = await stack.enter_async_context(
                    streamablehttp_client(str(self.cfg.get("url") or "")))
            session = await stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            self._session, self._stack = session, stack
            self._session_loop = asyncio.get_running_loop()
            return session
        except McpClientError:
            raise
        except Exception as e:
            await self._teardown()
            raise McpClientError(
                f"server '{self.server_name}' 建连失败: {e}") from e

    async def _teardown(self) -> None:
        stack, self._stack, self._session, self._session_loop = (
            self._stack, None, None, None)
        if stack is not None:
            try:
                await stack.aclose()
            except Exception:
                pass

    async def list_tools(self) -> List[Dict[str, Any]]:
        """工具清单（健康缓存：窗口内复用，窗口外刷新失败回落旧缓存）。"""
        now = time.monotonic()
        ttl = max(1, int(getattr(settings, "canvas_health_cache_seconds", 30)))
        if self._tools_cache is not None and now - self._tools_cache_at < ttl:
            return self._tools_cache
        try:
            session = await self._ensure_session()
            res = await session.list_tools()
            tools = []
            for t in getattr(res, "tools", []) or []:
                tools.append({
                    "name": str(getattr(t, "name", "") or ""),
                    "description": str(getattr(t, "description", "") or ""),
                    "inputSchema": getattr(t, "inputSchema", None) or {},
                })
            self._tools_cache = [t for t in tools if t["name"]]
            self._tools_cache_at = now
            return self._tools_cache
        except McpClientError:
            raise
        except Exception as e:
            if self._tools_cache is not None:
                logger.warning(
                    f"[mcp.client] '{self.server_name}' 清单刷新失败，回落旧缓存: {e}")
                return self._tools_cache
            raise McpClientError(
                f"server '{self.server_name}' 工具清单获取失败: {e}") from e

    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> Any:
        """远端工具调用；结果收敛为文本/结构化内容，失败抛 McpClientError。"""
        try:
            session = await self._ensure_session()
            res = await session.call_tool(name, arguments or {})
        except McpClientError:
            raise
        except Exception as e:
            await self._teardown()  # 断连即降级：下次调用重建会话
            raise McpClientError(
                f"server '{self.server_name}' 调用 '{name}' 失败: {e}") from e
        if getattr(res, "isError", False):
            raise McpClientError(
                f"server '{self.server_name}' 工具 '{name}' 返回错误: "
                f"{_content_text(res)[:300]}")
        structured = getattr(res, "structuredContent", None)
        return structured if isinstance(structured, dict) else _content_text(res)

    async def aclose(self) -> None:
        await self._teardown()


def _content_text(res: Any) -> str:
    """把 SDK content 块列表拼成纯文本（非文本块忽略）。"""
    parts: List[str] = []
    for block in getattr(res, "content", []) or []:
        text = getattr(block, "text", None)
        if isinstance(text, str):
            parts.append(text)
    return "\n".join(parts)


def build_client(server_name: str, cfg: Dict[str, Any]) -> BaseMcpClient:
    """默认客户端工厂（注册期可注入替身工厂，测试不经 SDK/外网）。"""
    return SdkMcpClient(server_name, cfg)
