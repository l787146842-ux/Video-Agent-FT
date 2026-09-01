"""MCP 接入层执行面回归（任务#37 B4）：

- 适配器：deny-first 运行时拒执行（未启用直调被拒）、required+type
  最小自校验、结果超长截断附警告；
- 两段式注入：段 1 目录块只给名称+摘要（schema 不进 FC tools），
  段 2 enable 后次回合 schema 才进 FC payload（planner 裁剪面断言）；
- risk 闸接线：high 级 MCP 工具经 FCToolRunner 闸机链过
  guard_pipeline.evaluate_tool_risk（platform.tool_risk），无同意硬拒、
  用户坚持放行留痕；low 级不受影响。

内置假 MCP 客户端，不依赖外网/SDK。
"""
import asyncio
import json

import pytest

from src.video_agent.adapters.base_chat import ChatResponse
from src.video_agent.core.fc_tool_runner import FCToolRunner
from src.video_agent.core.tracer import AgentTracer
from src.video_agent.state.manager import StateManager
from src.video_agent.tools.mcp import (
    register_mcp_tools,
    unregister_mcp_tools,
)
from src.video_agent.tools.mcp import catalog as mcp_catalog
from src.video_agent.tools.mcp import policy as mcp_policy
from src.video_agent.tools.mcp.client import BaseMcpClient
from src.video_agent.tools.manager import ToolManager

HIGH_TOOL = "mcp__subtitle__generate_subtitle"
LOW_TOOL = "mcp__subtitle__list_styles"

SUBTITLE_SCHEMA = {
    "type": "object",
    "properties": {
        "text": {"type": "string"},
        "count": {"type": "integer"},
    },
    "required": ["text"],
}


class FakeMcpClient(BaseMcpClient):
    def __init__(self, tools=None, result=None):
        self.tools = tools if tools is not None else [
            {"name": "generate_subtitle", "description": "生成字幕" * 60,
             "inputSchema": SUBTITLE_SCHEMA},
            {"name": "list_styles", "description": "字幕样式清单",
             "inputSchema": {}},
        ]
        self.result = result if result is not None else {"ok": True}
        self.calls = []

    async def list_tools(self):
        return self.tools

    async def call_tool(self, name, arguments):
        self.calls.append((name, dict(arguments)))
        return self.result


_LAST_CLIENT = {}


def _factory(server, cfg):
    client = _LAST_CLIENT.get("client") or FakeMcpClient()
    _LAST_CLIENT["client"] = client
    return client


def _register(monkeypatch, policy=None, client=None):
    import src.video_agent.tools.mcp as mcp_pkg
    _LAST_CLIENT["client"] = client or FakeMcpClient()
    monkeypatch.setattr(mcp_pkg, "load_mcp_config", lambda: {
        "servers": {"subtitle": {
            "transport": "stdio", "command": "x",
            "tool_risk": {"list_styles": "low"},
        }},
        "policy": policy or {},
    })
    return register_mcp_tools(client_factory=_factory)


@pytest.fixture(autouse=True)
def _mcp_env(monkeypatch):
    """注册面清理 + 启用集清理 + 落盘 no-op（测试不污染真实工作区）。"""
    unregister_mcp_tools()
    monkeypatch.setattr(StateManager, "save", lambda self: None)
    inter = StateManager.get_instance().state_dict.setdefault("interaction", {})
    inter.pop("mcp_enabled", None)
    yield
    unregister_mcp_tools()
    inter = StateManager.get_instance().state_dict.get("interaction") or {}
    inter.pop("mcp_enabled", None)


def _enable(names):
    mcp_policy.write_enabled_tools(names)


def _run_tool(name, args):
    return asyncio.run(ToolManager.invoke_tool(name, args))


# ---------- 适配器：deny-first 运行时面 ----------

class TestAdapterDenyFirst:
    def test_unenabled_direct_call_rejected(self, monkeypatch):
        _register(monkeypatch)
        res = _run_tool(HIGH_TOOL, {"text": "hi"})
        assert not res.success
        assert "未启用" in res.error and "mcp_tool_catalog" in res.error
        assert not _LAST_CLIENT["client"].calls, "未启用工具到不了远端"

    def test_enabled_call_passes_to_remote(self, monkeypatch):
        _register(monkeypatch)
        _enable([HIGH_TOOL])
        res = _run_tool(HIGH_TOOL, {"text": "hi"})
        assert res.success and res.data["result"] == {"ok": True}
        assert _LAST_CLIENT["client"].calls == [("generate_subtitle", {"text": "hi"})]

    def test_missing_required_rejected(self, monkeypatch):
        _register(monkeypatch)
        _enable([HIGH_TOOL])
        res = _run_tool(HIGH_TOOL, {})
        assert not res.success and "缺少必填参数" in res.error

    def test_wrong_type_rejected(self, monkeypatch):
        _register(monkeypatch)
        _enable([HIGH_TOOL])
        res = _run_tool(HIGH_TOOL, {"text": "hi", "count": "three"})
        assert not res.success and "类型不符" in res.error

    def test_description_truncated_200(self, monkeypatch):
        _register(monkeypatch)
        tool = ToolManager.get_tool(HIGH_TOOL)
        assert len(tool.description) <= 200

    def test_result_truncation_with_warning(self, monkeypatch, set_global_setting):
        set_global_setting("mcp_result_max_chars", 500)
        _register(monkeypatch, client=FakeMcpClient(result={"blob": "x" * 5000}))
        _enable([HIGH_TOOL])
        res = _run_tool(HIGH_TOOL, {"text": "hi"})
        assert res.success and res.data.get("truncated") is True
        assert len(res.data["result"]) <= 500
        assert any("截断" in w for w in res.data.get("warnings", []))


# ---------- 两段式注入 ----------

class TestTwoStageInjection:
    def test_stage1_catalog_block_names_only(self, monkeypatch):
        _register(monkeypatch)
        block = mcp_catalog.catalog_block()
        # 段 1：名称 + 摘要 + enable 指引
        assert HIGH_TOOL in block and LOW_TOOL in block
        assert "mcp_tool_catalog" in block and "enable" in block
        # schema 不进目录块（完整 schema 属段 2）
        assert '"properties"' not in block and '"required"' not in block

    def test_stage1_empty_without_registration(self):
        assert mcp_catalog.catalog_block() == ""

    def test_stage2_schema_excluded_until_enabled(self, monkeypatch):
        _register(monkeypatch)
        # 未启用：全部 MCP 工具 schema 不进 FC payload
        excluded = mcp_catalog.inactive_tool_names()
        assert HIGH_TOOL in excluded and LOW_TOOL in excluded
        schemas = ToolManager.get_all_tool_schemas(exclude=excluded)
        names = {s["function"]["name"] for s in schemas}
        assert HIGH_TOOL not in names and LOW_TOOL not in names
        # enable 后次回合：被启用工具 schema 进 payload，其余仍裁剪
        _enable([LOW_TOOL])
        excluded = mcp_catalog.inactive_tool_names()
        assert LOW_TOOL not in excluded and HIGH_TOOL in excluded
        schemas = ToolManager.get_all_tool_schemas(exclude=excluded)
        names = {s["function"]["name"] for s in schemas}
        assert LOW_TOOL in names and HIGH_TOOL not in names

    def test_catalog_enable_writes_whitelist(self, monkeypatch):
        _register(monkeypatch)
        res = _run_tool("mcp_tool_catalog", {
            "action": "enable", "tools": [LOW_TOOL]})
        assert res.success and LOW_TOOL in res.data["enabled"]
        assert mcp_policy.enabled_tool_names() == {LOW_TOOL}

    def test_catalog_enable_unknown_rejected(self, monkeypatch):
        _register(monkeypatch)
        res = _run_tool("mcp_tool_catalog", {
            "action": "enable", "tools": ["mcp__ghost__tool"]})
        assert not res.success and "deny" in res.error

    def test_catalog_enable_over_limit_rejected(self, monkeypatch, set_global_setting):
        set_global_setting("mcp_max_active_tools", 1)
        _register(monkeypatch)
        res = _run_tool("mcp_tool_catalog", {
            "action": "enable", "tools": [HIGH_TOOL, LOW_TOOL]})
        assert not res.success and "超过上限" in res.error
        assert mcp_policy.enabled_tool_names() == set()

    def test_catalog_detail_returns_full_schema(self, monkeypatch):
        _register(monkeypatch)
        res = _run_tool("mcp_tool_catalog", {
            "action": "detail", "tools": [HIGH_TOOL]})
        assert res.success
        detail = res.data["tools"][0]
        assert detail["parameters"] == SUBTITLE_SCHEMA
        assert detail["risk"] == "high"

    def test_catalog_disable_removes_from_whitelist(self, monkeypatch):
        _register(monkeypatch)
        _enable([HIGH_TOOL, LOW_TOOL])
        res = _run_tool("mcp_tool_catalog", {
            "action": "disable", "tools": [HIGH_TOOL]})
        assert res.success and mcp_policy.enabled_tool_names() == {LOW_TOOL}


# ---------- risk 闸接线（guard_pipeline 不旁路） ----------

def _fc_call(name, args):
    return ChatResponse(content="", tool_calls=[
        {"id": "c1", "type": "function",
         "function": {"name": name, "arguments": json.dumps(args)}},
    ])


def _run_fc(monkeypatch, name, args, *, gate_override=False):
    runner = FCToolRunner(tool_manager=ToolManager)
    state = StateManager.get_instance().state_dict
    monkeypatch.setattr(
        FCToolRunner, "_raw_state", staticmethod(lambda: state))
    res = asyncio.run(runner.execute(_fc_call(name, args),
                                     gate_override=gate_override))
    return runner, res


@pytest.fixture(autouse=True)
def _reset_tracer():
    AgentTracer.reset()
    yield
    AgentTracer.reset()


class TestRiskGateWiring:
    def test_high_mcp_blocked_without_consent(self, monkeypatch):
        _register(monkeypatch)
        _enable([HIGH_TOOL])  # 白名单已放行，但 risk 闸独立判：无同意仍拒
        runner, res = _run_fc(monkeypatch, HIGH_TOOL, {"text": "hi"})
        assert res.applied == 0, "high 级 MCP 工具未经用户确认不得执行"
        assert any("高风险工具确认闸拦截" in w for w in runner.gate_warnings)
        assert not _LAST_CLIENT["client"].calls, "risk 闸拦截后到不了远端"
        assert res.tool_results and res.tool_results[0]["ok"] is False

    def test_high_mcp_override_allows_with_trace(self, monkeypatch):
        tracer = AgentTracer.get_instance()
        tracer.start_trace("t")
        tracer.start_step()
        _register(monkeypatch)
        _enable([HIGH_TOOL])
        runner, res = _run_fc(monkeypatch, HIGH_TOOL, {"text": "hi"},
                              gate_override="all")
        assert res.applied == 1, "用户「本次放行」应放行（留痕）"
        assert _LAST_CLIENT["client"].calls
        recent = tracer.get_recent_gates(10)
        assert any(g["rule_id"] == "platform.tool_risk" and g["overridden"]
                   for g in recent), "豁免必须留痕（platform.tool_risk verdict）"

    def test_high_mcp_block_verdict_audited(self, monkeypatch):
        tracer = AgentTracer.get_instance()
        tracer.start_trace("t")
        tracer.start_step()
        _register(monkeypatch)
        _enable([HIGH_TOOL])
        _run_fc(monkeypatch, HIGH_TOOL, {"text": "hi"})
        recent = tracer.get_recent_gates(10)
        assert any(g["rule_id"] == "platform.tool_risk" and g["ok"] is False
                   for g in recent), "拦截必须经 audit_verdicts 入审计"

    def test_low_mcp_not_gated(self, monkeypatch):
        _register(monkeypatch)
        _enable([LOW_TOOL])
        _runner, res = _run_fc(monkeypatch, LOW_TOOL, {})
        assert res.applied == 1, "low 级 MCP 工具启用后直执行（无确认闸）"

    def test_unenabled_mcp_never_reaches_remote_via_fc(self, monkeypatch):
        _register(monkeypatch)
        # 未启用 + low 级：risk 闸不管，adapter 运行时 deny-first 兜底
        _runner, res = _run_fc(monkeypatch, LOW_TOOL, {})
        assert res.applied == 0
        assert res.tool_results and res.tool_results[0]["ok"] is False
        assert not _LAST_CLIENT["client"].calls
