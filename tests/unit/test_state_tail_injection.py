# -*- coding: utf-8 -*-
"""状态注入（二期 G3 事件化前身后世）：

钉死核心断言（新语义）：
1. 「state 内容仍被模型可见」：轮首状态事件（build_state_tail_message
   全家）经 planner._build_and_log_state_event 构建 + 落 source=state 事件，
   run_agent_loop 组装时追加在 user 消息之后（与日志 seq 同序）；
2. 「system 字节在 state 变化时保持稳定」：状态变化只改状态事件正文，
   system 本体逐字节不变——供应商前缀缓存命中前提。

（二期 G3 退役：每步尾部消息装配 _state_tail_message / _degrade_state_tail
 ——状态注入改轮首事件一次落流，轮内步间零注入，模型按需调
 read_state_group；退役记录见 CHANGELOG 2026-09-09 二期批 G3。）

另钉：非工作台上下文/空状态不注入（零增量）；偏好/模式 note 随状态
事件正文注入；降级引导段按客观标志位独立成段。
"""
import pytest

from src.video_agent.adapters.base_chat import BaseChatAdapter, ChatResponse
from src.video_agent.core.agent_loop import run_agent_loop
from src.video_agent.core.planner import Planner, PlannerContext
from src.video_agent.state.manager import StateManager


class _EchoAdapter(BaseChatAdapter):
    """非流式假 adapter：捕获模型实际收到的消息"""

    def __init__(self):
        self.seen = []

    @property
    def supports_function_calling(self) -> bool:
        return False

    async def chat(self, messages, **kwargs) -> ChatResponse:
        self.seen.append(list(messages))
        return ChatResponse(content="好", finish_reason="stop", token_usage=10)

    async def chat_stream(self, messages, **kwargs):
        yield  # pragma: no cover


@pytest.fixture
def svc(tmp_path):
    StateManager.reset_instance()
    instance = StateManager(str(tmp_path))
    StateManager._instance = instance
    yield instance
    StateManager.reset_instance()


def _executor(svc, adapter=None):
    planner = Planner(state_manager=svc, llm_adapter=adapter or _EchoAdapter())
    return planner, planner._turn_executor


# ---------- 断言类一：state 内容仍被模型可见（G3 事件化） ----------

async def test_state_visible_to_model_via_state_event(svc):
    """状态事件构建 + 落流（planner 轮始单一落点）：正文含状态 JSON
    全家，日志落 source=state 事件（dsh inject 同位）。"""
    planner, _ = _executor(svc)
    ctx = PlannerContext(
        use_studio_context=True, state_builder=lambda: '{"ke": "主角"}',
        session_conversation_id="conv-g3")
    content = planner._build_and_log_state_event(ctx)
    assert "当前工作台状态 JSON 如下" in content
    assert '{"ke": "主角"}' in content
    # 落流：source=state 的 user/message 事件
    from src.video_agent.core import session_log
    events = session_log.load_events(svc, "conv-g3")
    state_events = [e for e in events if e.get("type") == "user/message"
                    and e.get("source") == session_log.SOURCE_STATE]
    assert len(state_events) == 1 and state_events[0]["content"] == content
    session_log._SEQ_CACHE.clear()


async def test_state_event_appended_after_user_in_messages(svc):
    """run_agent_loop 组装：状态事件正文追加在 user 消息之后（与日志
    seq 同序 user → state → steps；回放=请求逐字节，缓存结构性保证）。"""
    from src.video_agent.core.action_executor import StateOperationExecutor
    seen = []

    async def llm(system_prompt, messages, stream_hook=None):
        seen.append(list(messages))
        return ("好的，收到。", "stop", 0, 0.0, {})

    result = await run_agent_loop(
        "开工", llm_call=llm, context_builder=lambda: "ctx",
        executor=StateOperationExecutor(svc), history=[],
        state_event_content="当前工作台状态 JSON 如下\n\n{\"ke\": 1}")
    assert result.steps == 1
    msgs = seen[0]
    assert [m["role"] for m in msgs] == ["user", "user"]
    assert msgs[0]["content"] == "开工"
    assert "当前工作台状态 JSON" in msgs[1]["content"]


async def test_no_state_event_content_zero_injection(svc):
    """状态事件为空串：messages 只有 user 消息（零注入零增量）。"""
    from src.video_agent.core.action_executor import StateOperationExecutor
    seen = []

    async def llm(system_prompt, messages, stream_hook=None):
        seen.append(list(messages))
        return ("好", "stop", 0, 0.0, {})

    await run_agent_loop(
        "x", llm_call=llm, context_builder=lambda: "ctx",
        executor=StateOperationExecutor(svc), history=[],
        state_event_content="")
    assert seen[0] == [{"role": "user", "content": "x"}]


async def test_state_refreshed_per_turn(svc):
    """按轮刷新：每轮轮首构建一次状态事件（原每步刷新语义随每步装配退役），
    状态变化反映在下一轮的状态事件正文。"""
    planner, _ = _executor(svc)
    box = {"state": '{"version": 1}'}
    ctx = PlannerContext(use_studio_context=True, state_builder=lambda: box["state"])
    first = planner._build_and_log_state_event(ctx)
    box["state"] = '{"version": 2}'
    ctx2 = PlannerContext(use_studio_context=True, state_builder=lambda: box["state"])
    second = planner._build_and_log_state_event(ctx2)
    assert '"version": 1' in first and '"version": 2' in second
    assert first != second


def test_no_state_event_without_studio_context(svc):
    """非工作台上下文：构建返回空串（零注入）；llm_call 不再装配尾部消息"""
    planner, _ = _executor(svc)
    ctx = PlannerContext(use_studio_context=False, state_json='{"a":1}')
    assert planner._build_and_log_state_event(ctx) == ""


async def test_no_tail_message_when_state_empty(svc):
    """空状态：构建返回空串（不制造注入）"""
    planner, _ = _executor(svc)
    ctx = PlannerContext(use_studio_context=True, state_json="")
    # state_builder 为 None → 构建跳过（空状态零注入）
    assert planner._build_and_log_state_event(ctx) == ""


def test_state_event_fails_open_without_builder(svc):
    """构建器缺失/异常：返回空串不抛（本轮零注入，回落语义）"""
    planner, _ = _executor(svc)
    ctx = PlannerContext(use_studio_context=True)  # state_builder=None
    assert planner._build_and_log_state_event(ctx) == ""
    def _boom():
        raise RuntimeError("状态构建故障")
    ctx2 = PlannerContext(use_studio_context=True, state_builder=_boom)
    assert planner._build_and_log_state_event(ctx2) == ""


# ---------- 断言类二：system 字节在 state 变化时保持稳定 ----------

async def test_system_bytes_stable_when_state_changes(svc):
    """状态变化只改状态事件正文：system 本体逐字节稳定，llm_call 路径
    零注入（状态已随 messages 进来，executor 不再装配尾部消息）"""
    planner, executor = _executor(svc)
    executor._context = PlannerContext(
        use_studio_context=True, state_builder=lambda: '{"version": 1}')
    adapter = planner.llm_adapter
    await executor.llm_call("SYSTEM-BODY", [
        {"role": "user", "content": "a"},
        {"role": "user", "content": "当前工作台状态 JSON 如下\n\n{\"version\": 1}"}])
    executor._context.state_builder = lambda: '{"version": 2, "extra": "x"}'
    await executor.llm_call("SYSTEM-BODY", [
        {"role": "user", "content": "a"},
        {"role": "user", "content": "当前工作台状态 JSON 如下\n\n{\"version\": 2}"}])
    first, second = adapter.seen
    assert first[0]["content"] == second[0]["content"] == "SYSTEM-BODY"
    # 状态差异由消息区承载（system 前缀稳定）
    assert first[-1]["content"] != second[-1]["content"]
    # executor 不再追加任何尾部消息（G3：装配退役）
    assert len(first) == 3 and len(second) == 3


def test_system_prompt_stable_across_state_rebuilds(svc):
    """prompt_builder 层：状态变化两次构建 system 逐字节一致；
    状态经状态事件正文可见（两类断言的组装层镜像）"""
    planner, _ = _executor(svc)
    box = {"state": '{"a": 1}'}
    ctx = PlannerContext(use_studio_context=True, state_builder=lambda: box["state"])
    p1 = planner._build_system_prompt(ctx)
    box["state"] = '{"a": 2}'
    p2 = planner._build_system_prompt(ctx)
    assert p1 == p2
    assert '{"a": 2}' in planner._prompt_builder.build_state_tail_message(ctx)


# ---------- 零增量：非工作台上下文 / 空状态不注入 ----------

async def test_no_tail_message_without_studio_context(svc):
    planner, executor = _executor(svc)
    executor._context = PlannerContext(use_studio_context=False, state_json='{"a":1}')
    adapter = planner.llm_adapter
    await executor.llm_call("S", [{"role": "user", "content": "你好"}])
    assert len(adapter.seen[0]) == 2  # 仅 system + user，零注入


# （test_no_tail_message_when_context_missing / test_degrade_state_tail_*
#   已随二期 G3 退役删除：_state_tail_message / _degrade_state_tail 整体
#   退役，状态注入改轮首事件一次落流，预算保险由 truncate_messages 兜底）


# （test_degrade_state_tail_noop_within_budget / test_degrade_state_tail_noop_without_degraded_builder
#   已随二期 G3 退役删除：_degrade_state_tail 整体退役）


# ---------- 批 10：执行偏好注入 + 工具边界注释每步刷新（V6 计划） ----------

class TestExecutionPrefNoteInjection:
    """偏好进 Agent 上下文（外部标杆同款）：轮始按档位签发，随轮首状态
    事件正文注入（G3：经 build_state_tail_message 全家）。"""

    def test_note_lands_in_tail_message(self, svc):
        planner, executor = _executor(svc)
        executor._context = PlannerContext(
            use_studio_context=True, state_json='{"ke": 1}',
            execution_pref_note="当前执行偏好：生成前确认",
        )
        tail = planner._prompt_builder.build_state_tail_message(executor._context)
        assert "当前执行偏好：生成前确认" in tail

    def test_loads_note_per_tier(self, svc, monkeypatch):
        from src.video_agent.config import settings
        planner = Planner(state_manager=svc, llm_adapter=None)
        cases = {
            "confirm_before_gen": "生成前确认",
            "auto_decide": "自动决定",
            "generate_directly": "直接生成",
        }
        for tier, marker in cases.items():
            old = settings.execution_preference
            object.__setattr__(settings, "execution_preference", tier)
            try:
                note = planner._load_execution_pref_note()
                assert note and marker in note, f"{tier} 档应命中对应分节"
            finally:
                object.__setattr__(settings, "execution_preference", old)

    def test_dirty_pref_falls_back_to_default_section(self, svc, monkeypatch):
        from src.video_agent.config import settings
        planner = Planner(state_manager=svc, llm_adapter=None)
        old = settings.execution_preference
        object.__setattr__(settings, "execution_preference", "yolo")
        try:
            note = planner._load_execution_pref_note()
            assert note and "生成前确认" in note, "脏值回落默认档分节"
        finally:
            object.__setattr__(settings, "execution_preference", old)


# ---------- 2026-09-06：执行模式注入（对齐批） ----------

class TestExecutionModeNoteInjection:
    """执行模式四档注入：非默认档按分节签发、经尾部消息可见；
    ai_decide 默认档 = 空串不注入（行为与现状一致）；脏值回落默认档。"""

    def test_note_lands_in_tail_message(self, svc):
        planner, executor = _executor(svc)
        executor._context = PlannerContext(
            use_studio_context=True, state_json='{"ke": 1}',
            execution_mode_note="当前执行模式：关键步骤手动确认",
        )
        tail = planner._prompt_builder.build_state_tail_message(executor._context)
        assert "当前执行模式：关键步骤手动确认" in tail

    def test_loads_note_per_mode(self, svc, monkeypatch):
        from src.video_agent.config import settings
        planner = Planner(state_manager=svc, llm_adapter=None)
        cases = {
            "auto_full": "自动执行全流程",
            "key_steps_confirm": "关键步骤手动确认",
            "pause_all": "全部暂停确认",
        }
        for mode, marker in cases.items():
            old = settings.execution_mode
            object.__setattr__(settings, "execution_mode", mode)
            try:
                note = planner._load_execution_mode_note()
                assert note and marker in note, f"{mode} 档应命中对应分节"
            finally:
                object.__setattr__(settings, "execution_mode", old)

    def test_default_mode_injects_nothing(self, svc, monkeypatch):
        """ai_decide 默认档不注入任何内容，且跳过分节查找
        （文件无对应分节属设计约定，不得当缺失打警告）。"""
        from src.video_agent.config import settings
        import src.video_agent.core.planner as planner_mod
        planner = Planner(state_manager=svc, llm_adapter=None)
        old = settings.execution_mode
        object.__setattr__(settings, "execution_mode", "ai_decide")
        try:
            def _fail(*_a, **_k):
                raise AssertionError("ai_decide 档不应触发分节查找")
            monkeypatch.setattr(planner_mod, "load_prompt_section", _fail)
            assert planner._load_execution_mode_note() == ""
        finally:
            object.__setattr__(settings, "execution_mode", old)

    def test_dirty_mode_falls_back_to_default_no_injection(self, svc, monkeypatch):
        from src.video_agent.config import settings
        import src.video_agent.core.planner as planner_mod
        planner = Planner(state_manager=svc, llm_adapter=None)
        old = settings.execution_mode
        object.__setattr__(settings, "execution_mode", "yolo")
        try:
            def _fail(*_a, **_k):
                raise AssertionError("脏值回落默认档=不注入，不应触发分节查找")
            monkeypatch.setattr(planner_mod, "load_prompt_section", _fail)
            assert planner._load_execution_mode_note() == "", "脏值回落默认档=不注入"
        finally:
            object.__setattr__(settings, "execution_mode", old)


class TestStageNoteRefreshedPerStep:
    """阶段边界注释（stage_note）已随批 B2 工具全量常驻退役——
    本类保留为「注释不再注入 + 工具集轮始冻结」的回归口径。"""

    def test_no_boundary_note_after_resident_tools(self, svc):
        """批 B2 工具全量常驻：阶段边界注释退役，任何阶段都不再注入。"""
        planner = Planner(state_manager=svc, llm_adapter=None)
        ctx = PlannerContext(use_studio_context=True, skill_name="某 Skill")
        # demo 态自带 shots 组：三类全清才是「故事板为空」客观态
        for cat in ("keyElements", "shots", "audioItems"):
            svc.state_dict[cat] = []

        # 故事板为空：无边界注释（阶段裁剪已退役）
        planner._build_system_prompt(ctx)
        assert not getattr(ctx, "stage_note", "")

        # 建组后同样无注释；尾部消息不含旧边界文案
        svc.state_dict["keyElements"] = [{"id": "g1", "title": "主角", "drafts": []}]
        planner._build_system_prompt(ctx)
        executor = planner._turn_executor
        executor._context = ctx
        tail = planner._prompt_builder.build_state_tail_message(ctx)
        assert "仅开放单张应急出图" not in tail

    def test_excluded_tools_round_start_frozen(self, svc):
        """批 B1 轮始冻结：_excluded_tools 不随轮内状态翻转（tools 跨步稳定）。"""
        planner = Planner(state_manager=svc, llm_adapter=None)
        ctx = PlannerContext(use_studio_context=True, skill_name="某 Skill")
        for cat in ("keyElements", "shots", "audioItems"):
            svc.state_dict[cat] = []
        # 模拟轮始计算（handle_message 入口）
        planner._excluded_tools = planner._compute_excluded_tools(ctx)
        excluded_empty = planner._excluded_tools
        assert "generate_video" not in excluded_empty  # 全量常驻
        # 轮内建组后再构建 system prompt：_excluded_tools 不被改写
        svc.state_dict["keyElements"] = [{"id": "g1", "title": "主角", "drafts": []}]
        planner._build_system_prompt(ctx)
        assert planner._excluded_tools == excluded_empty


# ---------- P3 载体改造：降级引导段按客观标志位独立成段注入 ----------

def test_degradation_note_injected_by_flag(svc):
    """状态 JSON 只留 degraded/compacted 客观标志位（note 字段已废除），
    引导语从 shared/degradation.md 同源加载、随状态尾部独立成段真注入
    （杠杀孤儿分节）；无标志位零增量，system 段不参与（保 KV-cache 前缀）。"""
    from src.video_agent.utils.prompts import load_prompt_section

    planner, _ = _executor(svc)
    deg_sec = load_prompt_section("shared/degradation.md", "STATE_DEGRADED")
    ctx = PlannerContext(use_studio_context=True, state_json='{"degraded": true}')
    tail = planner._prompt_builder.build_state_tail_message(ctx)
    assert deg_sec and deg_sec in tail
    assert tail.index('{"degraded": true}') < tail.index(deg_sec), "引导段应紧随状态数据体"

    comp_sec = load_prompt_section("shared/degradation.md", "STATE_COMPACTED")
    ctx2 = PlannerContext(use_studio_context=True, state_json='{"compacted": true}')
    tail2 = planner._prompt_builder.build_state_tail_message(ctx2)
    assert comp_sec and comp_sec in tail2

    # 无标志位：零增量（不注入任何降级引导段）
    ctx3 = PlannerContext(use_studio_context=True, state_json='{"plain": true}')
    tail3 = planner._prompt_builder.build_state_tail_message(ctx3)
    assert deg_sec not in tail3 and comp_sec not in tail3

    # system 段保持不变（引导段只走尾部消息通道）
    assert deg_sec not in planner._build_system_prompt(ctx)
