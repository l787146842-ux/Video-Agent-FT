"""MCP 客户端连接生命周期回归（三维度审查 M1/m1，任务#13）：

- 跨事件循环会话：注册期在临时 loop 建连（session/stdio 子进程绑定该 loop），
  运行期（另一 loop）复用时 _ensure_session 必须校验建连 loop 并 teardown 重建，
  不得复用已关闭 loop 上的会话；
- 注册期清单拉完即 aclose 释放临时会话与子进程（失败路径同样释放），
  运行期 call_tool 经懒重建走通；
- 目录工具上限判定消费注册期真实 policy 配置（不再传死配置 {}）。

假 SDK 组件替代真实 mcp SDK，不经外网/不起真实子进程。
"""
import asyncio
from contextlib import asynccontextmanager

import pytest

from src.video_agent.state.manager import StateManager
from src.video_agent.tools.mcp import (
    register_mcp_tools,
    unregister_mcp_tools,
)
from src.video_agent.tools.mcp import client as client_mod
from src.video_agent.tools.mcp.client import BaseMcpClient, SdkMcpClient


# ---------- 假 SDK 组件 ----------

_SDK_STATE = {"sessions": 0, "stdio_exits": 0}


class _FakeListResult:
    class _Tool:
        name = "remote_tool"
        description = "远端工具"
        inputSchema = {"type": "object"}

    tools = [_Tool()]


class _FakeCallResult:
    isError = False
    structuredContent = {"ok": True}
    content = []


class _FakeClientSession:
    def __init__(self, read, write):
        _SDK_STATE["sessions"] += 1
        self.initialized = False
        self.closed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        self.closed = True
        return False

    async def initialize(self):
        self.initialized = True

    async def list_tools(self):
        return _FakeListResult()

    async def call_tool(self, name, arguments):
        return _FakeCallResult()


@asynccontextmanager
async def _fake_stdio_client(params):
    try:
        yield "read-stream", "write-stream"
    finally:
        # 等价 stdio 子进程随上下文退出被回收（释放断言点）
        _SDK_STATE["stdio_exits"] += 1


@pytest.fixture
def fake_sdk(monkeypatch):
    """把 client 模块的 SDK 符号替换为假实现（_ensure_session 逻辑真实执行）。"""
    _SDK_STATE.update({"sessions": 0, "stdio_exits": 0})
    monkeypatch.setattr(client_mod, "_MCP_SDK_READY", True)
    monkeypatch.setattr(client_mod, "stdio_client", _fake_stdio_client)
    monkeypatch.setattr(client_mod, "StdioServerParameters", lambda **kw: kw)
    monkeypatch.setattr(client_mod, "ClientSession", _FakeClientSession)
    yield _SDK_STATE


# ---------- SdkMcpClient：跨事件循环校验与重建 ----------

def test_runtime_call_rebuilds_after_registration_loop_closed(fake_sdk):
    """注册期（临时 loop）建连拉清单 → loop 关闭 → 运行期 call_tool
    必须 teardown 旧会话并在当前 loop 重建（跨循环复用必失败的防御）。

    两段各自独立事件循环（不用 asyncio.run，避免其 asyncgen 收尾
    干扰子进程释放计数）：与生产形态同构——注册期同步上下文 vs
    运行期服务事件循环。
    """
    c = SdkMcpClient("srv", {"transport": "stdio", "command": "demo"})
    # 注册期模拟：在临时事件循环里建连并拉清单（loop 随后关闭）
    reg_loop = asyncio.new_event_loop()
    reg_loop.run_until_complete(c.list_tools())
    reg_loop.close()
    assert _SDK_STATE["sessions"] == 1
    assert c._session is not None
    assert _SDK_STATE["stdio_exits"] == 0, "未释放前子进程上下文仍在（缺陷现场）"

    # 运行期（另一个事件循环）：旧 loop 已关闭 → 不得复用，重建会话
    rt_loop = asyncio.new_event_loop()
    try:
        res = rt_loop.run_until_complete(c.call_tool("remote_tool", {"a": 1}))
        assert res == {"ok": True}
        assert _SDK_STATE["sessions"] == 2, "跨事件循环必须重建会话"
        # 旧会话上下文已 teardown 释放（stdio 子进程回收断言）
        assert _SDK_STATE["stdio_exits"] == 1
        # 收尾释放第二次会话（子进程不泄漏）
        rt_loop.run_until_complete(c.aclose())
        assert _SDK_STATE["stdio_exits"] == 2
        assert c._session is None
    finally:
        rt_loop.close()


async def test_same_loop_reuses_session(fake_sdk):
    """同一事件循环内复用会话：不重建、不重复起 stdio 上下文。"""
    c = SdkMcpClient("srv", {"transport": "stdio", "command": "demo"})
    await c.call_tool("remote_tool", {})
    await c.call_tool("remote_tool", {})
    assert _SDK_STATE["sessions"] == 1
    assert _SDK_STATE["stdio_exits"] == 0
    await c.aclose()
    assert _SDK_STATE["stdio_exits"] == 1


# ---------- 注册期会话释放（__init__._register_server） ----------

class _RecordingClient(BaseMcpClient):
    def __init__(self, fail_list=False):
        self.fail_list = fail_list
        self.aclose_calls = 0

    async def list_tools(self):
        if self.fail_list:
            raise RuntimeError("清单拉取失败")
        return [
            {"name": "t1", "description": "工具一", "inputSchema": {}},
            {"name": "t2", "description": "工具二", "inputSchema": {}},
        ]

    async def call_tool(self, name, arguments):
        return {"ok": True}

    async def aclose(self):
        self.aclose_calls += 1


@pytest.fixture(autouse=True)
def _mcp_env(monkeypatch):
    unregister_mcp_tools()
    monkeypatch.setattr(StateManager, "save", lambda self: None)
    inter = StateManager.get_instance().state_dict.setdefault("interaction", {})
    inter.pop("mcp_enabled", None)
    yield
    unregister_mcp_tools()
    inter = StateManager.get_instance().state_dict.get("interaction") or {}
    inter.pop("mcp_enabled", None)


def _register_with(monkeypatch, client, policy=None):
    import src.video_agent.tools.mcp as mcp_pkg
    monkeypatch.setattr(mcp_pkg, "load_mcp_config", lambda: {
        "servers": {"demo": {"transport": "stdio", "command": "x"}},
        "policy": policy or {},
    })
    return register_mcp_tools(
        client_factory=lambda server, cfg: client)


def test_registration_releases_client_session(monkeypatch):
    """注册期拉完清单即 aclose：临时 loop 的会话/子进程不滞留到运行期。"""
    client = _RecordingClient()
    assert _register_with(monkeypatch, client) == 2
    assert client.aclose_calls == 1, "注册期会话必须释放（防跨 loop 复用与子进程泄漏）"


def test_registration_releases_client_session_on_list_failure(monkeypatch):
    """清单拉取失败的降级路径同样释放会话（finally 口径）。"""
    client = _RecordingClient(fail_list=True)
    assert _register_with(monkeypatch, client) == 0
    assert client.aclose_calls == 1


def test_catalog_consumes_registration_policy_cfg(monkeypatch):
    """目录上限判定消费注册期真实 policy（死配置 {} 修复）：
    list 展示 policy 上限，enable 超限按 policy 拒收（而非回落 settings 默认 8）。"""
    client = _RecordingClient()
    assert _register_with(monkeypatch, client,
                          policy={"max_active_tools": 1}) == 2
    import asyncio as _asyncio
    from src.video_agent.tools.manager import ToolManager
    res = _asyncio.run(ToolManager.invoke_tool(
        "mcp_tool_catalog", {"action": "list"}))
    assert res.success and res.data["max_active_tools"] == 1
    res = _asyncio.run(ToolManager.invoke_tool(
        "mcp_tool_catalog", {"action": "enable",
                             "tools": ["mcp__demo__t1", "mcp__demo__t2"]}))
    assert not res.success, "policy.max_active_tools=1 必须拒收超限启用"
    assert "超过上限 1" in (res.error or "")
