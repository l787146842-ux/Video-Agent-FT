# -*- coding: utf-8 -*-
"""B1 正宗子代理 run_subagent 契约单测。

钉死：①深度单调/上限；②白名单不含花钱生成与 run_subagent（防递归）；
③任务注入固定范围声明；④_compute_excluded_tools 白名单裁剪；
⑤fc_tool_runner 命中 run_subagent 经注入 launcher 拦截回摘要（通用形态、无类型）、
  未装配明确失败；⑥_launch_subagent 构建隔离子级（depth+1 / no_confirm / 白名单）
  并回摘要；⑦ 2026-09-11 批③A：具名类型退役→通用单一子代理（统一白名单、
  任务文本无类型块、委派策略段仅顶级轮条件注入，对齐 dsh tool:subagent）。

不驱动真实模型循环（handle_message 全链路靠集成/其它套件覆盖），用 monkeypatch 断言装配契约。
"""
import pytest

# 触发工具注册（导任一新工具子模块即拉起全局注册引导）
import src.video_agent.tools.document_tools  # noqa: F401
from src.video_agent.core import planner as pmod
from src.video_agent.core import session_log
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
    # 显式重注册全套：同 worker 其它文件的夹具会 ToolManager.reset() 清空全局注册表
    #（跨文件污染先例，见 test_hybrid_boundaries / test_tool_risk_gate 同口径），
    # 本文件不依赖导入副作用——类型白名单里的工具（含故事板族）必须全部在册。
    from src.video_agent.tools.analysis_tools import register_analysis_tools
    from src.video_agent.tools.document_tools import register_document_tools
    from src.video_agent.tools.storyboard_tools import register_storyboard_tools
    register_storyboard_tools()
    register_document_tools()
    register_analysis_tools()


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
    seen = {}

    async def launcher(task):
        seen["task"] = task
        return "子摘要:" + task

    runner.subagent_launcher = launcher
    res = await runner._dispatch_tool("run_subagent", {"task": "T"})
    assert res.success is True
    assert res.data["summary"] == "子摘要:T"
    assert seen["task"] == "T"

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
    assert captured["max_steps"] is None           # 步数上限退役（planner 不传）
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


# ---------- B3 后端地基：子线程清单 / 只读记录 / 任务落流 ----------

def test_subagent_threads_listing_and_scope(svc):
    sub = svc.create_scoped_conversation(
        {"kind": "subagent", "parent_conversation": "conv-main", "label": "拆解任务"},
        title="子代理")
    svc.create_scoped_conversation(  # 微调线程（非子代理）不入子代理清单
        {"kind": "adjust", "cat": "ke", "group_id": "g", "draft_id": "d"},
        title="微调线程")
    threads = svc.subagent_threads()
    assert [t["conversation_id"] for t in threads] == [sub["id"]]
    assert threads[0]["label"] == "拆解任务"
    assert threads[0]["parent_conversation"] == "conv-main"
    assert svc.get_conversation_scope(sub["id"]).get("kind") == "subagent"
    assert svc.get_conversation_scope("nope") == {}


def test_project_readable_record_and_status(svc):
    cid = "conv-sub-rec"
    session_log.append_user_message(svc, cid, "拆解为分镜")            # 真人任务
    session_log.append_user_message(svc, cid, "【状态】", source=session_log.SOURCE_STATE)  # 噪声
    session_log.append_assistant_message(
        svc, cid, 1, "先建组", reasoning_content="想想",
        tool_calls=[{"id": "c1", "function": {"name": "storyboard_create_group"}}])
    session_log.append_tool_result(svc, cid, 1, "c1", "storyboard_create_group", "ok", ok=True)
    session_log.append_step_feedback(svc, cid, 1, 1)                    # 噪声
    session_log.append_assistant_message(svc, cid, 2, "完成：3 个关键元素")

    rec = session_log.project_readable_record(svc, cid)
    senders = [e["sender"] for e in rec]
    # state/feedback/tool 不入（完成章 turn/stamp 已随盖章退役批退场，不产生 system 条目）
    assert senders == ["user", "assistant", "assistant"]
    assert rec[0]["text"] == "拆解为分镜"
    assert rec[1]["text"] == "先建组"
    assert rec[1]["reasoning_content"] == "想想"
    assert rec[1]["actionLog"] == ["storyboard_create_group"]
    assert rec[2]["text"] == "完成：3 个关键元素"

    assert session_log.thread_status(svc, cid)["status"] == "running"  # 无 turn/end
    session_log.append_turn_end(svc, cid)
    st = session_log.thread_status(svc, cid)
    assert st["status"] == "completed" and st["steps"] == 2


async def test_launch_subagent_lands_task_event(svc, monkeypatch):
    # 子级在 core 内联跑不经 web → _launch_subagent 必须自己把任务落为 user/message，
    # 否则只读记录缺首行（B3 数据源前提）。
    seen = {}

    class _FakeResp:
        text = "done"

    async def _fake_handle(self, user_message, context, **kw):
        seen["cid"] = str(getattr(context, "session_conversation_id", "") or "")
        return _FakeResp()

    monkeypatch.setattr(pmod.Planner, "handle_message", _fake_handle)
    parent = Planner(state_manager=svc, llm_adapter=None)
    await parent._launch_subagent("拆解《三体》为分镜", PlannerContext(subagent_depth=0))
    assert seen["cid"]  # 子会话已创建
    evs = session_log.load_events(svc, seen["cid"])
    task_events = [e for e in evs
                   if e.get("type") == "user/message" and e.get("source") == "user"
                   and "《三体》" in str(e.get("content") or "")]
    assert task_events, "子级任务应作为 user/message 事件落入隐藏线程"
    assert seen["cid"] in [t["conversation_id"] for t in svc.subagent_threads()]


# ---------- B4 账本合流：子级写共享 StateManager → 主线程天然认账 ----------

async def test_launch_subagent_shares_parent_state_manager(svc, monkeypatch):
    # 子级与父共享同一 StateManager 实例（父此刻挂起等待，无并发写冲突）：
    # 子级真实写工具改的就是主线程 sync_run/commit_turn 所读的同一 state_dict。
    seen = {}

    class _FakeResp:
        text = "ok"

    async def _fake_handle(self, user_message, context, **kw):
        seen["sm"] = self.state_manager
        return _FakeResp()

    monkeypatch.setattr(pmod.Planner, "handle_message", _fake_handle)
    parent = Planner(state_manager=svc, llm_adapter=None)
    await parent._launch_subagent("x", PlannerContext(subagent_depth=0))
    assert seen["sm"] is svc, "子级必须复用父 StateManager（否则子写入不入主账本）"


# ---------- 批③A 通用单一子代理（具名类型退役） ----------

def test_generic_whitelist_invariants():
    """通用白名单不变式：不花钱生成、不递归、不拿确认工具；列项工具须真实在册。"""
    from src.video_agent.core.subagent import SUBAGENT_TOOL_WHITELIST
    from src.video_agent.tools.manager import ToolManager

    wl = SUBAGENT_TOOL_WHITELIST
    assert wl
    assert "run_subagent" not in wl
    assert "image_generate" not in wl and "generate_video" not in wl
    assert "workflow_pause" not in wl
    assert "storyboard_create_group" in wl and "storyboard_patch_draft" in wl
    for tool_name in wl:
        assert ToolManager.get_tool(tool_name) is not None, tool_name


def test_resolve_kind_is_generic_single_type():
    """通用形态：任意传入 kind 都归一到 general，白名单恒等于全集白名单。"""
    from src.video_agent.core.subagent import (
        SUBAGENT_KIND_GENERAL, SUBAGENT_TOOL_WHITELIST,
        resolve_subagent_kind, whitelist_for_kind)

    assert resolve_subagent_kind("storyboard_split") == SUBAGENT_KIND_GENERAL
    assert resolve_subagent_kind("") == SUBAGENT_KIND_GENERAL
    assert whitelist_for_kind("media_prompt_write") == SUBAGENT_TOOL_WHITELIST


def test_build_subagent_task_generic_no_kind_block():
    """任务文本只含固定权限范围声明 + 任务书，不再前置【子代理类型】块。"""
    msg = build_subagent_task("把这段工作做完")
    assert "被委派的子代理" in msg
    assert "不要原地重试" in msg
    assert "【子代理类型" not in msg
    assert msg.rstrip().endswith("把这段工作做完")


def test_subagent_policy_is_generic_without_business_terms():
    """委派策略段通用、无业务专名（不写「拆结构/写提示词」这类），可覆盖新场景。
    2026-09-12 治理批：策略段含与主对话批次节奏的仲裁句（防「委派 vs 亲手
    分批」打架回潮）。"""
    from src.video_agent.core.subagent import subagent_policy

    policy = subagent_policy()
    assert policy and "run_subagent" in policy
    for narrow in ("拆成关键元素与分镜", "逐条撰写媒体提示词", "media_prompt_write"):
        assert narrow not in policy
    assert "批次节奏" in policy, "委派与主对话批次节奏的仲裁句丢失"


def test_subagent_section_injected_only_for_top_level():
    """A3 条件注入：顶级轮且开关开→注入委派段；子级白名单模式/关开关→不注入。"""
    from src.video_agent.core import prompt_builder as pb
    from src.video_agent.config import settings

    old = getattr(settings, "subagent_enabled", False)
    try:
        object.__setattr__(settings, "subagent_enabled", True)
        top = pb._sec_subagent(None, PlannerContext(use_studio_context=True))
        assert top and "run_subagent" in top
        # 子级（白名单模式）不注入委派策略（子级无 run_subagent，防递归）
        child = pb._sec_subagent(
            None, PlannerContext(subagent_whitelist=frozenset({"read_skill"})))
        assert child == ""
        # 开关关 → 不注入
        object.__setattr__(settings, "subagent_enabled", False)
        assert pb._sec_subagent(None, PlannerContext(use_studio_context=True)) == ""
    finally:
        object.__setattr__(settings, "subagent_enabled", old)


async def test_launch_subagent_uses_generic_whitelist(svc, monkeypatch):
    """子级拿通用白名单（含建组与写提示词），任务文本无类型块。"""
    seen = {}

    class _FakeResp:
        text = "ok"

    async def _fake_handle(self, user_message, context, **kw):
        seen["ctx"] = context
        seen["msg"] = user_message
        return _FakeResp()

    monkeypatch.setattr(pmod.Planner, "handle_message", _fake_handle)
    parent = Planner(state_manager=svc, llm_adapter=None)
    await parent._launch_subagent("为已建好的卡写提示词",
                                  PlannerContext(subagent_depth=0))
    from src.video_agent.core.subagent import SUBAGENT_TOOL_WHITELIST
    assert seen["ctx"].subagent_whitelist == SUBAGENT_TOOL_WHITELIST
    assert "【子代理类型" not in seen["msg"]
