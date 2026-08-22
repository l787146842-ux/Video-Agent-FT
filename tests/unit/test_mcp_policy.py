"""MCP 接入层策略面回归（任务#37 B4）：

- deny-first：无配置 = 零工具；deny_servers 整批 / deny_tools 单个，
  命中的工具连注册都不进（fail-closed）；
- risk 解析：tool_risk > risk_default > high；未声明/非法一律 high；
- 配置加载 fail-closed：非法条目跳过不截断整批；
- 启用集（白名单）读写只认 mcp__ 命名空间。
"""
import json

import pytest

from src.video_agent.tools.mcp import (
    register_mcp_tools,
    unregister_mcp_tools,
)
from src.video_agent.tools.mcp import policy as mcp_policy
from src.video_agent.tools.mcp.adapter import ADAPTERS
from src.video_agent.tools.mcp.client import BaseMcpClient
from src.video_agent.tools.mcp.config import load_mcp_config
from src.video_agent.tools.manager import ToolManager

SAMPLE_TOOLS = [
    {"name": "generate_subtitle", "description": "生成字幕", "inputSchema": {}},
    {"name": "list_styles", "description": "字幕样式清单", "inputSchema": {}},
]


class FakeMcpClient(BaseMcpClient):
    """内置假客户端：不经 SDK/外网（B4 验收口径）。"""

    def __init__(self, tools=None):
        self.tools = list(tools if tools is not None else SAMPLE_TOOLS)
        self.calls = []

    async def list_tools(self):
        return self.tools

    async def call_tool(self, name, arguments):
        self.calls.append((name, dict(arguments)))
        return {"echo": arguments}


def _factory(_server, _cfg):
    return FakeMcpClient()


@pytest.fixture(autouse=True)
def _clean_mcp():
    unregister_mcp_tools()
    yield
    unregister_mcp_tools()


def _patch_config(monkeypatch, servers, policy=None):
    import src.video_agent.tools.mcp as mcp_pkg
    monkeypatch.setattr(
        mcp_pkg, "load_mcp_config",
        lambda: {"servers": servers, "policy": policy or {}})


# ---------- 命名与 risk 解析 ----------

class TestNamingAndRisk:
    def test_qualified_name_sanitized(self):
        assert mcp_policy.qualified_name("Sub-Title!", "Gen.Sub") == \
            "mcp__sub_title__gen_sub"
        assert mcp_policy.is_mcp_tool("mcp__s__t")
        assert not mcp_policy.is_mcp_tool("document_write")

    def test_risk_priority_tool_over_default(self):
        cfg = {"risk_default": "low", "tool_risk": {"generate_subtitle": "high"}}
        assert mcp_policy.resolve_tool_risk(cfg, "generate_subtitle") == "high"
        assert mcp_policy.resolve_tool_risk(cfg, "list_styles") == "low"

    def test_risk_default_high_when_undeclared(self):
        assert mcp_policy.resolve_tool_risk({}, "anything") == "high"

    def test_risk_invalid_value_falls_to_high(self):
        cfg = {"risk_default": "danger", "tool_risk": {"t": "medium-plus"}}
        assert mcp_policy.resolve_tool_risk(cfg, "t") == "high"
        assert mcp_policy.resolve_tool_risk(cfg, "other") == "high"


# ---------- deny 规则 ----------

class TestDenyRules:
    def test_deny_server_wholesale(self):
        policy = {"deny_servers": ["subtitle"]}
        assert mcp_policy.is_server_denied(policy, "subtitle")
        assert mcp_policy.is_server_denied(policy, "SubTitle")  # 净化后同判
        assert not mcp_policy.is_server_denied(policy, "other")

    def test_deny_tool_individual(self):
        policy = {"deny_tools": ["mcp__subtitle__generate_subtitle"]}
        assert mcp_policy.is_tool_denied(policy, "mcp__subtitle__generate_subtitle")
        assert not mcp_policy.is_tool_denied(policy, "mcp__subtitle__list_styles")


# ---------- 注册期 deny-first ----------

class TestRegistrationDenyFirst:
    def test_no_config_zero_tools(self, monkeypatch):
        _patch_config(monkeypatch, {})
        assert register_mcp_tools(client_factory=_factory) == 0
        assert not ADAPTERS

    def test_master_switch_off_zero_tools(self, monkeypatch, set_global_setting):
        set_global_setting("mcp_enabled", False)
        _patch_config(monkeypatch, {"subtitle": {"transport": "stdio", "command": "x"}})
        assert register_mcp_tools(client_factory=_factory) == 0

    def test_denied_server_not_registered(self, monkeypatch):
        _patch_config(
            monkeypatch,
            {"subtitle": {"transport": "stdio", "command": "x"}},
            {"deny_servers": ["subtitle"]},
        )
        assert register_mcp_tools(client_factory=_factory) == 0
        assert "mcp__subtitle__generate_subtitle" not in ToolManager._tools
        assert not ADAPTERS

    def test_denied_tool_not_registered_sibling_kept(self, monkeypatch):
        _patch_config(
            monkeypatch,
            {"subtitle": {"transport": "stdio", "command": "x"}},
            {"deny_tools": ["mcp__subtitle__generate_subtitle"]},
        )
        assert register_mcp_tools(client_factory=_factory) == 1
        assert "mcp__subtitle__generate_subtitle" not in ToolManager._tools
        assert "mcp__subtitle__list_styles" in ToolManager._tools

    def test_undeclared_risk_registered_as_high(self, monkeypatch):
        _patch_config(monkeypatch, {"subtitle": {"transport": "stdio", "command": "x"}})
        assert register_mcp_tools(client_factory=_factory) == 2
        assert ToolManager.get_tool_risk("mcp__subtitle__generate_subtitle") == "high"
        assert ToolManager.get_tool_risk("mcp__subtitle__list_styles") == "high"
        # 目录工具随注册挂载（平台工具，risk=low 声明过注册期校验）
        assert ToolManager.get_tool_risk("mcp_tool_catalog") == "low"

    def test_server_disabled_flag_skipped(self, monkeypatch):
        _patch_config(monkeypatch, {
            "subtitle": {"transport": "stdio", "command": "x", "enabled": False}})
        assert register_mcp_tools(client_factory=_factory) == 0

    def test_listing_failure_degrades_not_crash(self, monkeypatch):
        class BrokenClient(BaseMcpClient):
            async def list_tools(self):
                raise RuntimeError("connection refused")
        _patch_config(monkeypatch, {"subtitle": {"transport": "stdio", "command": "x"}})
        assert register_mcp_tools(
            client_factory=lambda s, c: BrokenClient()) == 0


# ---------- 配置加载 fail-closed ----------

class TestConfigFailClosed:
    def test_missing_file_empty_config(self, tmp_path):
        cfg = load_mcp_config(tmp_path / "absent.json")
        assert cfg == {"servers": {}, "policy": {}}

    def test_invalid_json_empty_config(self, tmp_path):
        p = tmp_path / "mcp_servers.json"
        p.write_text("{not json", encoding="utf-8")
        assert load_mcp_config(p)["servers"] == {}

    def test_invalid_entry_skipped_batch_kept(self, tmp_path):
        p = tmp_path / "mcp_servers.json"
        p.write_text(json.dumps({"servers": {
            "bad": {"transport": "carrier-pigeon"},
            "good": {"transport": "stdio", "command": "uvx"},
            "stdio_no_cmd": {"transport": "stdio"},
        }}), encoding="utf-8")
        cfg = load_mcp_config(p)
        assert list(cfg["servers"].keys()) == ["good"]


# ---------- 启用集（白名单）读写 ----------

class TestEnabledSet:
    def test_roundtrip_and_namespace_filter(self):
        state: dict = {}
        mcp_policy.write_enabled_tools(
            ["mcp__s__t", "document_write", ""], state=state, save=False)
        assert mcp_policy.enabled_tool_names(state) == {"mcp__s__t"}

    def test_absent_key_empty_set(self):
        assert mcp_policy.enabled_tool_names({}) == set()
        assert mcp_policy.enabled_tool_names({"interaction": {}}) == set()

    def test_max_active_tools_policy_override(self, set_global_setting):
        set_global_setting("mcp_max_active_tools", 8)
        assert mcp_policy.max_active_tools({"max_active_tools": 3}) == 3
        assert mcp_policy.max_active_tools({}) == 8
