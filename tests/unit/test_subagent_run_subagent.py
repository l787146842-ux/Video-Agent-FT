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
    SUBAGENT_TOOL_DENY, build_subagent_task, resolve_child_depth,
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
    # generate_video 仅经 tools 包导入副作用注册（1111 批 deny 集含它），reset 后须补。
    from src.video_agent.tools.analysis_tools import register_analysis_tools
    from src.video_agent.tools.document_tools import register_document_tools
    from src.video_agent.tools.storyboard_tools import register_storyboard_tools
    from src.video_agent.tools.manager import ToolManager
    from src.video_agent.tools.video.generate_video import GenerateVideoTool
    register_storyboard_tools()
    register_document_tools()
    register_analysis_tools()
    ToolManager.register(GenerateVideoTool())


# ---------- 纯契约 ----------

def test_resolve_child_depth_monotone_and_capped():
    assert resolve_child_depth(0) == 1
    with pytest.raises(SubagentDepthError):
        resolve_child_depth(1)  # 1+1=2 > max 1


def test_deny_excludes_generation_and_recursion():
    """2026-09-15 1111 批（dsh inherit∩restrict）：子级面=主代理面−deny；
    deny 只收四条硬约束，落账/落点工具不在 deny（子代理拿得到）。"""
    assert "run_subagent" in SUBAGENT_TOOL_DENY        # 防递归
    assert "image_generate" in SUBAGENT_TOOL_DENY      # 花钱生成留主线程
    assert "generate_video" in SUBAGENT_TOOL_DENY
    assert "workflow_pause" in SUBAGENT_TOOL_DENY      # 子级不确认
    assert "storyboard_create_group" not in SUBAGENT_TOOL_DENY
    assert "script_analysis_report" not in SUBAGENT_TOOL_DENY


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

def test_compute_excluded_tools_deny_mode(svc):
    """子级 deny 模式：deny 集进 excluded，其余工具继承主代理面（不下发=仅 deny）。"""
    planner = Planner(state_manager=svc, llm_adapter=None)
    excluded = planner._compute_excluded_tools(
        PlannerContext(subagent_deny=SUBAGENT_TOOL_DENY))
    assert "run_subagent" in excluded       # 子级看不到 → 结构防递归
    assert "image_generate" in excluded     # 花钱生成不下发给子级
    # 非 deny 工具继承父面（含阶段落点工具）→ 不再漏授
    assert "storyboard_create_group" not in excluded
    assert "script_analysis_report" not in excluded
    # 顶级（无 deny）应能看到 run_subagent
    top_excluded = planner._compute_excluded_tools(PlannerContext(use_studio_context=True))
    assert "run_subagent" not in top_excluded


# ---------- runner 拦截 ----------

async def test_dispatch_intercepts_run_subagent():
    runner = FCToolRunner(tool_manager=object())  # invoke_tool 不应被调用
    seen = {}

    async def launcher(task, kind="", stage="", on_event=None):
        seen["task"] = task
        seen["stage"] = stage
        return "子摘要:" + task

    runner.subagent_launcher = launcher
    res = await runner._dispatch_tool("run_subagent", {"task": "T"})
    assert res.success is True
    assert res.data["summary"] == "子摘要:T"
    assert seen["task"] == "T"
    assert seen["stage"] == ""          # 缺省不带阶段（通用形态）

    # 阶段执行器（2026-09-15 试点；R4 批后委派集只余两阶段）：stage 透传给 launcher
    res_s = await runner._dispatch_tool(
        "run_subagent", {"task": "T2", "stage": "write_media_prompt"})
    assert res_s.success is True
    assert seen["stage"] == "write_media_prompt"

    # 未装配（子级内 / 关开关）→ 明确失败，不静默
    runner.subagent_launcher = None
    res2 = await runner._dispatch_tool("run_subagent", {"task": "T"})
    assert res2.success is False


async def test_launch_subagent_forwards_on_event(svc, monkeypatch):
    """2026-09-15 1111 批（子活动流式可见）：父 on_event 透传给子循环，
    子级增量事件进父 SSE（故事板增量亮卡，不再做完一次性弹出）。
    流式二期起子级拿到的是 tagger 包装件（非父回调本体），
    包装只加 subagent 字段、不改原事件（打标契约见下方二期组用例）。"""
    seen = {}
    forwarded = []

    class _FakeResp:
        text = "ok"

    async def _fake_handle(self, user_message, context, stream_hook=None,
                           on_event=None, **kw):
        seen["on_event"] = on_event
        return _FakeResp()

    async def _parent_on_event(ev):
        forwarded.append(ev)

    monkeypatch.setattr(pmod.Planner, "handle_message", _fake_handle)
    parent = Planner(state_manager=svc, llm_adapter=None)
    await parent._launch_subagent(
        "拆解", PlannerContext(subagent_depth=0), on_event=_parent_on_event)
    assert seen["on_event"] is not None          # 子级有事件出口（一期语义）
    assert seen["on_event"] is not _parent_on_event  # 二期：经 tagger 包装
    # 包装件仍把事件送回父回调（出口不断）
    await seen["on_event"]({"type": "status", "text": "子级进度"})
    assert len(forwarded) == 1
    assert forwarded[0]["type"] == "status" and forwarded[0]["text"] == "子级进度"
    assert "subagent" in forwarded[0]


async def test_dispatch_passes_runner_on_event_to_launcher():
    """run_subagent 派发把本轮 SSE on_event 交给 launcher（流式透传链路起点）。"""
    runner = FCToolRunner(tool_manager=object())
    seen = {}

    async def launcher(task, kind="", stage="", on_event=None):
        seen["on_event"] = on_event
        return "摘要"

    sentinel = object()
    runner.subagent_launcher = launcher
    runner._subagent_on_event = sentinel
    await runner._dispatch_tool("run_subagent", {"task": "T"})
    assert seen["on_event"] is sentinel


# ---------- _launch_subagent 装配契约 ----------

async def test_launch_subagent_builds_isolated_child(svc, monkeypatch):
    captured = {}

    class _FakeResp:
        text = "子代理完成：建了 3 个关键元素"

    async def _fake_handle(self, user_message, context, stream_hook=None,
                           on_event=None, **kwargs):
        captured["msg"] = user_message
        captured["ctx"] = context
        captured["extra_kwargs"] = kwargs
        return _FakeResp()

    monkeypatch.setattr(pmod.Planner, "handle_message", _fake_handle)
    parent = Planner(state_manager=svc, llm_adapter=None)
    out = await parent._launch_subagent(
        "拆解剧本为分镜", PlannerContext(subagent_depth=0))

    assert out == "子代理完成：建了 3 个关键元素"
    ctx = captured["ctx"]
    assert ctx.subagent_depth == 1                 # 父+1
    assert ctx.subagent_no_confirm is True         # 审批=never（不发确认卡）
    assert "run_subagent" in ctx.subagent_deny
    assert "max_steps" not in captured["extra_kwargs"]  # 步数上限退役（参数已整体删除）
    assert "被委派的子代理" in captured["msg"]      # 固定范围声明注入


async def test_launch_subagent_degrades_on_state_conflict(svc, monkeypatch):
    # 8888 委派失踪批·批 A：隐藏线程落盘被版本闸拒绝且重放失败 → 抛
    # StateConflictError；委派不得因此中断，降级为不落流（child_cid=""）仍跑完子级。
    from src.video_agent.exceptions import StateConflictError
    from src.video_agent.state import conversation_ops as conv_ops

    called = {"hit": False}

    class _FakeResp:
        text = "子代理仍跑完"

    async def _fake_handle(self, user_message, context, stream_hook=None,
                           on_event=None, **kwargs):
        called["hit"] = True
        return _FakeResp()

    def _boom(*a, **k):
        raise StateConflictError("版本闸拒绝且重放失败")

    monkeypatch.setattr(pmod.Planner, "handle_message", _fake_handle)
    monkeypatch.setattr(conv_ops, "create_scoped_conversation", _boom)
    parent = Planner(state_manager=svc, llm_adapter=None)
    out = await parent._launch_subagent(
        "拆解剧本为分镜", PlannerContext(subagent_depth=0))

    assert out == "子代理仍跑完"
    assert called["hit"] is True   # 落流失败不阻断委派，子级照跑


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

def test_generic_deny_invariants():
    """通用 deny 不变式（dsh inherit∩restrict）：deny 只收硬约束且均为真实在册工具。"""
    from src.video_agent.core.subagent import SUBAGENT_TOOL_DENY
    from src.video_agent.tools.manager import ToolManager

    deny = SUBAGENT_TOOL_DENY
    assert deny
    assert "run_subagent" in deny
    assert "image_generate" in deny and "generate_video" in deny
    assert "workflow_pause" in deny
    for tool_name in deny:
        assert ToolManager.get_tool(tool_name) is not None, tool_name


def test_resolve_kind_is_generic_single_type():
    """通用形态：任意传入 kind 都归一到 general；deny 与 kind 无关、只随 stage 变。"""
    from src.video_agent.core.subagent import (
        SUBAGENT_KIND_GENERAL, SUBAGENT_TOOL_DENY,
        resolve_subagent_kind, child_deny_set)

    assert resolve_subagent_kind("storyboard_split") == SUBAGENT_KIND_GENERAL
    assert resolve_subagent_kind("") == SUBAGENT_KIND_GENERAL
    assert child_deny_set("") == SUBAGENT_TOOL_DENY


def test_build_subagent_task_generic_no_kind_block():
    """任务文本只含固定权限范围声明 + 一句目标（2026-09-15 1111 批对齐 flova
    精简：待建清单/幂等锚包装退役），不再前置【子代理类型】块。"""
    msg = build_subagent_task("把这段工作做完")
    assert "被委派的子代理" in msg
    assert "不要原地重试" in msg
    assert "【子代理类型" not in msg
    assert "待建清单" not in msg and "task_id" not in msg  # 精简：只留目标
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
        # 子级（deny 模式）不注入委派策略（子级无 run_subagent，防递归）
        child = pb._sec_subagent(
            None, PlannerContext(subagent_deny=SUBAGENT_TOOL_DENY))
        assert child == ""
        # 开关关 → 不注入
        object.__setattr__(settings, "subagent_enabled", False)
        assert pb._sec_subagent(None, PlannerContext(use_studio_context=True)) == ""
    finally:
        object.__setattr__(settings, "subagent_enabled", old)


async def test_launch_subagent_uses_generic_deny(svc, monkeypatch):
    """子级拿通用 deny（继承父面−硬约束），任务文本无类型块。"""
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
    from src.video_agent.core.subagent import SUBAGENT_TOOL_DENY
    assert seen["ctx"].subagent_deny == SUBAGENT_TOOL_DENY
    assert "【子代理类型" not in seen["msg"]


# ---------- P0-C label 截断修复（R5） ----------

async def test_subagent_label_truncation(svc, monkeypatch):
    """子代理标题截断：超过 40 字符取前 39 + …，否则原样。"""
    from src.video_agent.core.planner import _SUBAGENT_LABEL_MAX
    from src.video_agent.state import conversation_ops

    labels_seen: list = []

    class _FakeResp:
        text = "ok"

    async def _fake_handle(self, user_message, context, **kw):
        return _FakeResp()

    monkeypatch.setattr(pmod.Planner, "handle_message", _fake_handle)

    # 拦截 conversation_ops.create_scoped_conversation 记录实际传入的 label
    _orig_create = conversation_ops.create_scoped_conversation

    def _spy_create(state_manager, scope, **kw):
        labels_seen.append(scope.get("label", ""))
        return _orig_create(state_manager, scope, **kw)

    monkeypatch.setattr(conversation_ops, "create_scoped_conversation", _spy_create)
    parent = Planner(state_manager=svc, llm_adapter=None)

    # Case 1: 短于 40 字符——原样保留
    short_task = "拆解任务"
    await parent._launch_subagent(short_task, PlannerContext(subagent_depth=0))
    assert labels_seen[-1] == short_task

    # Case 2: 恰好 40 字符——不截断
    exact_task = "a" * _SUBAGENT_LABEL_MAX
    await parent._launch_subagent(exact_task, PlannerContext(subagent_depth=0))
    assert labels_seen[-1] == exact_task
    assert len(labels_seen[-1]) == _SUBAGENT_LABEL_MAX

    # Case 3: 超过 40 字符——截断为 39 + "…"
    long_task = "把这段工作做完" * 20  # 远超 40
    await parent._launch_subagent(long_task, PlannerContext(subagent_depth=0))
    label = labels_seen[-1]
    assert len(label) == _SUBAGENT_LABEL_MAX  # 39 + 1 = 40
    assert label.endswith("\u2026")
    assert label == long_task[:_SUBAGENT_LABEL_MAX - 1] + "\u2026"

    # Case 4: 41 字符（刚好超 1）
    over_by_one = "b" * (_SUBAGENT_LABEL_MAX + 1)
    await parent._launch_subagent(over_by_one, PlannerContext(subagent_depth=0))
    label = labels_seen[-1]
    assert len(label) == _SUBAGENT_LABEL_MAX
    assert label == "b" * (_SUBAGENT_LABEL_MAX - 1) + "\u2026"


# ---------- 流式二期：子事件打标（actor 归组数据源） ----------

async def test_launch_subagent_tags_every_child_event(svc, monkeypatch):
    """流式二期①：子循环发出的每个事件都带 subagent={cid,stage,label,depth}，
    且原有 type/payload 一字不改（一期消费方零感知，只加字段）。"""
    from src.video_agent.skill_runtime.registry import STAGE_LABELS

    got: list = []
    seen = {}

    class _FakeResp:
        text = "ok"

    async def _fake_handle(self, user_message, context, stream_hook=None,
                           on_event=None, **kw):
        seen["cid"] = str(getattr(context, "session_conversation_id", "") or "")
        # 子级真实发射面：工具起止（含事件卡/时间线子步）+ state_refresh
        await on_event({"type": "tool_started", "id": "t1",
                        "name": "storyboard_create_group", "summary": "建组"})
        await on_event({"type": "actions_applied", "count": 1})
        await on_event({"type": "tool_finished", "id": "t1", "ok": True,
                        "elapsed_ms": 3.0, "result_summary": "建组"})
        return _FakeResp()

    async def _parent_on_event(ev):
        got.append(ev)

    monkeypatch.setattr(pmod.Planner, "handle_message", _fake_handle)
    parent = Planner(state_manager=svc, llm_adapter=None)
    await parent._launch_subagent(
        "拆解剧本", PlannerContext(subagent_depth=0),
        stage="script_analyze", on_event=_parent_on_event)

    assert [e["type"] for e in got] == [
        "tool_started", "actions_applied", "tool_finished"]
    # 原字段保真（打标不改子事件本体）
    assert got[0]["name"] == "storyboard_create_group" and got[0]["id"] == "t1"
    assert got[2]["ok"] is True and got[2]["elapsed_ms"] == 3.0
    assert seen["cid"]                            # 子隐藏线程已建
    for ev in got:
        meta = ev["subagent"]
        assert set(meta) == {"cid", "stage", "label", "depth"}
        assert meta["cid"] == seen["cid"]         # 归组键 = 子隐藏线程 id
        assert meta["stage"] == "script_analyze"
        assert meta["label"] == STAGE_LABELS["script_analyze"]  # 阶段展示名后端权威
        assert meta["depth"] == 1                 # 父 0 → 子 1


async def test_launch_subagent_label_falls_back_to_task_excerpt(svc, monkeypatch):
    """流式二期②：无 stage 的通用委派 → label 取任务摘要前段（actor 卡标题不空）。"""
    from src.video_agent.core.planner import _SUBAGENT_ACTOR_LABEL_MAX

    got: list = []
    task_text = "为已建好的关键元素逐条撰写媒体提示词并保持风格一致"

    class _FakeResp:
        text = "ok"

    async def _fake_handle(self, user_message, context, stream_hook=None,
                           on_event=None, **kw):
        await on_event({"type": "tool_started", "id": "t1",
                        "name": "prompt_draft", "summary": "写提示词"})
        return _FakeResp()

    async def _parent_on_event(ev):
        got.append(ev)

    monkeypatch.setattr(pmod.Planner, "handle_message", _fake_handle)
    parent = Planner(state_manager=svc, llm_adapter=None)
    await parent._launch_subagent(
        task_text, PlannerContext(subagent_depth=0), on_event=_parent_on_event)

    meta = got[0]["subagent"]
    assert meta["stage"] == ""
    assert meta["label"] == task_text[:_SUBAGENT_ACTOR_LABEL_MAX]
    assert len(meta["label"]) == _SUBAGENT_ACTOR_LABEL_MAX   # 长任务被截断


async def test_launch_subagent_without_on_event_not_wrapped(svc, monkeypatch):
    """流式二期③：on_event=None（CLI/单测/无前端）不包装、不崩——子级拿到 None。"""
    captured = {}

    class _FakeResp:
        text = "ok"

    async def _fake_handle(self, user_message, context, stream_hook=None,
                           on_event=None, **kw):
        captured["on_event"] = on_event
        return _FakeResp()

    monkeypatch.setattr(pmod.Planner, "handle_message", _fake_handle)
    parent = Planner(state_manager=svc, llm_adapter=None)
    out = await parent._launch_subagent("x", PlannerContext(subagent_depth=0))
    assert captured["on_event"] is None
    assert out == "ok"                            # 无事件通道仍正常回摘要


async def test_launch_subagent_tags_empty_cid_on_degrade(svc, monkeypatch):
    """流式二期④：子会话创建失败（降级不落流）仍打标，cid=""
    ——前端按 label+depth 兜底归组（风险 C），不因降级而丢失归组能力。"""
    from src.video_agent.state import conversation_ops as conv_ops

    got: list = []

    class _FakeResp:
        text = "ok"

    async def _fake_handle(self, user_message, context, stream_hook=None,
                           on_event=None, **kw):
        await on_event({"type": "tool_started", "id": "t1",
                        "name": "script_analysis_report", "summary": "交分析"})
        return _FakeResp()

    def _boom(*a, **k):
        raise RuntimeError("hidden thread persist failed")

    async def _parent_on_event(ev):
        got.append(ev)

    monkeypatch.setattr(pmod.Planner, "handle_message", _fake_handle)
    monkeypatch.setattr(conv_ops, "create_scoped_conversation", _boom)
    parent = Planner(state_manager=svc, llm_adapter=None)
    out = await parent._launch_subagent(
        "拆解剧本", PlannerContext(subagent_depth=0), on_event=_parent_on_event)

    assert out == "ok"                            # 降级不阻断委派
    meta = got[0]["subagent"]
    assert meta["cid"] == ""                      # 不落流仍打标
    assert meta["label"] and meta["depth"] == 1    # 兜底归组键齐备


def test_chat_service_preserves_subagent_tag_on_state_refresh():
    """流式二期⑤：actions_applied 在 web 透传层是**重建帧**（附故事板投影），
    重建时必须保留子代理打标——否则前端 actor 卡的计步腿静默断
    （「数据不静默丢」同纪律；源码扫描钉死，同 test_status_i18n_keys 口径）。"""
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    src = (root / "src/video_agent/web/chat_service.py").read_text(encoding="utf-8")
    assert '_sa = _ap.get("subagent")' in src
    assert '**({"subagent": _sa} if _sa else {})' in src
