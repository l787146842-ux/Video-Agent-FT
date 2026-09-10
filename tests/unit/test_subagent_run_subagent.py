# -*- coding: utf-8 -*-
"""B1 正宗子代理 run_subagent 契约单测。

钉死：①深度单调/上限；②白名单不含花钱生成与 run_subagent（防递归）；
③任务注入固定范围声明；④_compute_excluded_tools 白名单裁剪；
⑤fc_tool_runner 命中 run_subagent 经注入 launcher 拦截回摘要、未装配明确失败；
⑥_launch_subagent 构建隔离子级（depth+1 / no_confirm / 白名单 / subagent_max_steps）并回摘要。

不驱动真实模型循环（handle_message 全链路靠集成/其它套件覆盖），用 monkeypatch 断言装配契约。
"""
import pytest

# 触发工具注册（导任一新工具子模块即拉起全局注册引导）
import src.video_agent.tools.document_tools  # noqa: F401
from src.video_agent.core import planner as pmod
from src.video_agent.core.planner import Planner, PlannerContext
from src.video_agent.core.fc_tool_runner import FCToolRunner
from src.video_agent.core.subagent import (
    SUBAGENT_TOOL_WHITELIST, build_subagent_task, resolve_child_depth,
    SubagentDepthError,
)
from src.video_agent.state.manager import StateManager


@pytest.fixture
def svc(tmp_path):
    StateManager.reset_instance()
    instance = StateManager(str(tmp_path))
    StateManager._instance = instance
    yield instance
    StateManager.reset_instance()


@pytest.fixture(autouse=True)
def _ensure_platform_tools():
    # 显式重注册：同 worker 其它文件的夹具会 ToolManager.reset() 清空全局注册表
    #（跨文件污染先例，见 test_hybrid_boundaries / test_tool_risk_gate 同口径），
    # 本文件不依赖导入副作用——run_subagent / image_generate 等由 register_document_tools 落表。
    from src.video_agent.tools.document_tools import register_document_tools
    register_document_tools()


# ---------- 纯契约 ----------

def test_resolve_child_depth_monotone_and_capped():
    assert resolve_child_depth(0) == 1
    with pytest.raises(SubagentDepthError):
        resolve_child_depth(1)  # 1+1=2 > max 1


def test_whitelist_excludes_generation_and_recursion():
    assert "run_subagent" not in SUBAGENT_TOOL_WHITELIST      # 防递归
    assert "image_generate" not in SUBAGENT_TOOL_WHITELIST    # 花钱生成留主线程
    assert "generate_video" not in SUBAGENT_TOOL_WHITELIST
    assert "storyboard_create_group" in SUBAGENT_TOOL_WHITELIST


def test_build_subagent_task_carries_delegation_context():
    msg = build_subagent_task("拆解《三体》为分镜")
    assert "被委派的子代理" in msg          # 固定范围声明
    assert "不要原地重试" in msg            # 撞闸不重试
    assert "拆解《三体》为分镜" in msg


# ---------- 工具注册 ----------

def test_run_subagent_tool_registered_control_plane():
    from src.video_agent.tools.manager import ToolManager
    tool = ToolManager.get_tool("run_subagent")
    assert tool is not None
    assert tool.risk == "medium"
    assert getattr(tool, "provider_kind", "") == ""     # 非 provider 工具，可被 runner 按名拦截
    assert getattr(tool, "costly", False) is False


# ---------- 子级工具面裁剪 ----------

def test_compute_excluded_tools_whitelist_mode(svc):
    planner = Planner(state_manager=svc, llm_adapter=None)
    wl = frozenset({"read_skill", "document_write"})
    excluded = planner._compute_excluded_tools(PlannerContext(subagent_whitelist=wl))
    assert "read_skill" not in excluded
    assert "document_write" not in excluded
    assert "run_subagent" in excluded       # 子级看不到 → 结构防递归
    assert "image_generate" in excluded     # 花钱生成不下发给子级
    # 顶级（无白名单）应能看到 run_subagent
    top_excluded = planner._compute_excluded_tools(PlannerContext(use_studio_context=True))
    assert "run_subagent" not in top_excluded


# ---------- runner 拦截 ----------

async def test_dispatch_intercepts_run_subagent():
    runner = FCToolRunner(tool_manager=object())  # invoke_tool 不应被调用

    async def launcher(task):
        return "子摘要:" + task

    runner.subagent_launcher = launcher
    res = await runner._dispatch_tool("run_subagent", {"task": "T"})
    assert res.success is True
    assert res.data["summary"] == "子摘要:T"

    # 未装配（子级内 / 关开关）→ 明确失败，不静默
    runner.subagent_launcher = None
    res2 = await runner._dispatch_tool("run_subagent", {"task": "T"})
    assert res2.success is False


# ---------- _launch_subagent 装配契约 ----------

async def test_launch_subagent_builds_isolated_child(svc, monkeypatch):
    captured = {}

    class _FakeResp:
        text = "子代理完成：建了 3 个关键元素"

    async def _fake_handle(self, user_message, context, stream_hook=None,
                           on_event=None, max_steps=None):
        captured["msg"] = user_message
        captured["ctx"] = context
        captured["max_steps"] = max_steps
        return _FakeResp()

    monkeypatch.setattr(pmod.Planner, "handle_message", _fake_handle)
    parent = Planner(state_manager=svc, llm_adapter=None)
    out = await parent._launch_subagent(
        "拆解剧本为分镜", PlannerContext(subagent_depth=0))

    assert out == "子代理完成：建了 3 个关键元素"
    ctx = captured["ctx"]
    assert ctx.subagent_depth == 1                 # 父+1
    assert ctx.subagent_no_confirm is True         # 审批=never（不发确认卡）
    assert "run_subagent" not in ctx.subagent_whitelist
    assert captured["max_steps"] == 6              # settings.subagent_max_steps
    assert "被委派的子代理" in captured["msg"]      # 固定范围声明注入


async def test_launch_subagent_depth_guard_no_recursion(svc, monkeypatch):
    # 父已在 depth=1 → 再委派越限，直接返回提示，不构建子级
    called = {"hit": False}

    async def _fake_handle(self, user_message, context, **kw):
        called["hit"] = True
        raise AssertionError("不应被调用")

    monkeypatch.setattr(pmod.Planner, "handle_message", _fake_handle)
    parent = Planner(state_manager=svc, llm_adapter=None)
    out = await parent._launch_subagent("x", PlannerContext(subagent_depth=1))
    assert "深度上限" in out
    assert called["hit"] is False


# ---------- B2：子级模型档（resolve_role("subagent")）----------

async def test_launch_subagent_follows_parent_when_unset(svc, monkeypatch):
    # 未配 subagent 行（默认）→ 子级完全继承父 adapter/思考（跟随主模型）
    captured = {}

    class _FakeResp:
        text = "ok"

    async def _fake_handle(self, user_message, context, **kw):
        captured["adapter"] = self.llm_adapter
        captured["provider"] = self.chat_provider
        captured["model"] = self.chat_model
        captured["thinking"] = context.thinking_level
        return _FakeResp()

    monkeypatch.setattr(pmod.Planner, "handle_message", _fake_handle)
    from src.video_agent.config import settings
    old = getattr(settings, "model_policy", {}) or {}
    object.__setattr__(settings, "model_policy", {})
    try:
        parent = Planner(state_manager=svc, llm_adapter="PARENT",
                         chat_provider="prov_main", chat_model="model_main",
                         chat_adapter_factory=lambda p, m: "SHOULD_NOT_BE_USED")
        await parent._launch_subagent("x", PlannerContext(
            subagent_depth=0, thinking_level="high"))
        assert captured["adapter"] == "PARENT"       # 跟随父
        assert captured["provider"] == "prov_main"
        assert captured["model"] == "model_main"
        assert captured["thinking"] == "high"         # 继承父思考（无预置降档）
    finally:
        object.__setattr__(settings, "model_policy", old)


async def test_launch_subagent_honors_subagent_role_override(svc, monkeypatch):
    # 显式配 subagent provider + 注入工厂 → 子级接管为快模型，思考按配置降档
    captured = {}

    class _FakeResp:
        text = "ok"

    async def _fake_handle(self, user_message, context, **kw):
        captured["adapter"] = self.llm_adapter
        captured["provider"] = self.chat_provider
        captured["model"] = self.chat_model
        captured["thinking"] = context.thinking_level
        return _FakeResp()

    monkeypatch.setattr(pmod.Planner, "handle_message", _fake_handle)
    from src.video_agent.config import settings
    old = getattr(settings, "model_policy", {}) or {}
    object.__setattr__(settings, "model_policy", {
        "subagent": {"provider": "p_fast", "model": "m_fast", "thinking_level": "low"}})
    try:
        parent = Planner(state_manager=svc, llm_adapter="PARENT",
                         chat_provider="prov_main", chat_model="model_main",
                         chat_adapter_factory=lambda p, m: f"CHILD::{p}:{m}")
        await parent._launch_subagent("x", PlannerContext(subagent_depth=0))
        assert captured["adapter"] == "CHILD::p_fast:m_fast"
        assert captured["provider"] == "p_fast"
        assert captured["model"] == "m_fast"
        assert captured["thinking"] == "low"           # 显式降档生效
    finally:
        object.__setattr__(settings, "model_policy", old)
