# -*- coding: utf-8 -*-
"""批8（用户裁决「**完全照抄 dsh `todo_write`**」）：任务进度清单。

## 事故根因（本工具要治什么）

2222/3333 实跑：子代理**首个规划响应推理 12867 字（占全会话 48.2%）**，
之后 seq=75~129 推理≈0 字纯批量执行 —— 「一次性想完全部再动手」。
平台对「分批」只有散文劝告，实跑只被吸收一半
（`随想随写`/`预先起草全部` 零命中）。

dsh 对照（`packages/todo/tool-todo/src/index.ts`）：不靠劝，
**给模型一个工具把进度状态外在化**。

## 本批对齐口径（逐项，用户要求完全照抄）

| 维度 | dsh | 本实现 |
|---|---|---|
| 工具名 | `todo_write` | 同 |
| 入参名 | `todos` | 同 |
| 条目键 | 只 content/status（`additionalProperties:false`） | `extra="forbid"` |
| 状态枚举 | 严格三值，非法拒收 | `Literal` 拒收 |
| 覆盖语义 | 整表覆盖 | 同 |
| 并行档 | `allowParallelInProgress` | 取 **true**（用户：「能并行就并行，不能并行就排队」） |
| 作用域 | 每会话一份 | 每会话一份（修掉主/子代理互相覆盖） |
"""
import pytest

from src.video_agent.core.prompt_builder import PromptBuilder
from src.video_agent.state.manager import StateManager
from src.video_agent.tools.manager import ToolManager
from src.video_agent.tools.todo_tools import (
    ALLOW_PARALLEL_IN_PROGRESS, register_todo_tools,
)


@pytest.fixture(autouse=True)
def _ensure_todo_tool():
    """自足注册（**每个用例前**都补一次）：别的测试文件的 autouse fixture
    会 reset ToolManager（如 test_storyboard_tools 只重注册故事板工具），
    跨文件同跑时本文件会丢工具——此处保证任何用例都拿得到 todo_write。"""
    register_todo_tools()
    yield


@pytest.fixture
def svc(tmp_path):
    StateManager.reset_instance()
    instance = StateManager(str(tmp_path))
    StateManager._instance = instance
    yield instance
    StateManager.reset_instance()


def _pb(svc) -> PromptBuilder:
    return PromptBuilder(
        get_skill_docs=lambda: None, get_project_id=lambda: "",
        get_raw_state=lambda: svc._raw_state)


class TestToolShapeMatchesDsh:
    """形状逐项对齐 dsh `todo_write`（用户裁决：完全照抄）。"""

    def test_name_is_todo_write(self):
        t = ToolManager.get_tool("todo_write")
        assert t is not None, "工具名必须是 dsh 原名 todo_write"
        assert t.name == "todo_write"

    def test_param_name_is_todos(self):
        """入参名 = dsh 的 `todos`（不是 items）。"""
        from src.video_agent.tools.todo_tools import TodoWriteInput

        assert "todos" in TodoWriteInput.model_fields
        assert "items" not in TodoWriteInput.model_fields

    def test_item_keys_are_content_and_status(self):
        from src.video_agent.tools.todo_tools import TodoItem

        assert set(TodoItem.model_fields) == {"content", "status"}

    def test_extra_item_key_rejected(self):
        """多余键拒收（对齐 dsh `additionalProperties: false`）。"""
        from pydantic import ValidationError
        from src.video_agent.tools.todo_tools import TodoItem

        with pytest.raises(ValidationError):
            TodoItem(content="x", status="pending", extra_field="y")

    def test_status_enum_is_strict(self):
        """状态只收三值，非法**拒收**（对齐 dsh 枚举校验，不静默回落）。"""
        from pydantic import ValidationError
        from src.video_agent.tools.todo_tools import TodoItem

        assert TodoItem(content="x", status="pending").status == "pending"
        assert TodoItem(content="x", status="in_progress").status == "in_progress"
        assert TodoItem(content="x", status="completed").status == "completed"
        with pytest.raises(ValidationError):
            TodoItem(content="x", status="乱写")

    def test_risk_is_low(self):
        """纯记账：risk=low（无外部副作用）。"""
        assert ToolManager.get_tool_risk("todo_write") == "low"

    def test_visible_to_child_only(self):
        """**仅子代理持有**（2026-09-23 批13，用户裁决）。

        批8 原为「主代理与子代理都持有」；批13 收窄为子代理专属，依据是
        dsh 原版对照取证：dsh 的 Skill **无步骤流**（todo 是流程唯一来源），
        而本平台 16/16 Skill 都有 `<planner>` 段（步骤 + 依赖全文注入）——
        主代理的 todo 只是把同一份步骤誊第二遍（同一事实源两份，P1 违规）。
        子代理拿到的是**单个阶段章节**而非全流程，todo 在那边仍是填空缺。
        """
        from src.video_agent.core.subagent import (
            CHILD_ONLY_TOOLS, MAIN_AGENT_DENY, SUBAGENT_TOOL_DENY,
            STAGE_TOOL_DENY_EXTRA,
        )

        assert "todo_write" in CHILD_ONLY_TOOLS, "主代理面未摘除 todo_write"
        # 摘除走 CHILD_ONLY_TOOLS（子代理专属机制），不是阶段 deny 集：
        # 后者语义是「不允许任何子代理持有」，与「仅子代理持有」正相反。
        assert "todo_write" not in SUBAGENT_TOOL_DENY
        assert "todo_write" not in STAGE_TOOL_DENY_EXTRA
        # MAIN_AGENT_DENY 是「阶段产物写入工具」集，有 fail-loud 校验要求
        # 成员必须属某 _STAGE_TOOLS 阶段；todo 不是阶段产物工具，不该进去。
        assert "todo_write" not in MAIN_AGENT_DENY

    def test_main_agent_excluded_child_keeps_it(self, svc):
        """可见性按 depth 分流：主代理被裁、子代理保留（端到端裁剪断言）。"""
        from src.video_agent.core.planner import Planner, PlannerContext
        from src.video_agent.core.subagent import child_deny_set

        planner = Planner(state_manager=svc, llm_adapter=None)
        SKILL = "AI-短剧一站式生成"
        main = planner._compute_excluded_tools(
            PlannerContext(skill_name=SKILL, subagent_depth=0,
                           use_studio_context=True))
        assert "todo_write" in main, "主代理（生产编排上下文）应看不到 todo_write"
        child = planner._compute_excluded_tools(PlannerContext(
            skill_name=SKILL, subagent_depth=1, use_studio_context=True,
            subagent_deny=child_deny_set("script_analyze")))
        assert "todo_write" not in child, "子代理必须保留 todo_write"


class TestParallelPolicy:
    """并行档 = true（用户裁决「能并行就并行，不能并行就排队」）。"""

    def test_parallel_enabled(self):
        assert ALLOW_PARALLEL_IN_PROGRESS is True

    async def test_multiple_in_progress_accepted(self, svc):
        """true 档：同时多件 in_progress 必须被接受（不报 dsh 的 at most one）。"""
        r = await ToolManager.invoke_tool("todo_write", {"todos": [
            {"content": "登记角色", "status": "in_progress"},
            {"content": "登记场景", "status": "in_progress"},
        ]})
        assert r.success is True, r.error
        assert len(r.data["in_progress"]) == 2

    def test_description_carries_parallel_clause(self):
        """文案与档位成对（dsh 注释：本开关唯一改变的就是那条指令）。"""
        t = ToolManager.get_tool("todo_write")
        assert "同时标几件" in t.description, "并行档文案未生效"
        assert "至少有一件是 in_progress" in t.description


class TestDescriptionFaithfulToDsh:
    """描述照翻 dsh（用户选「乙」：中文照翻 + 门禁登记豁免）。"""

    def test_carries_do_not_batch_clause(self):
        """dsh `do not batch completions` 的照翻必须在场（豁免就是为它登记的）。"""
        t = ToolManager.get_tool("todo_write")
        assert "不要攒着批量标" in t.description

    def test_carries_add_one_per_step(self):
        """dsh `add one todo per concrete step before you start` 的照翻。"""
        t = ToolManager.get_tool("todo_write")
        assert "开工前" in t.description and "每个具体步骤" in t.description

    def test_carries_skip_trivial(self):
        """dsh `Skip the list for trivial single-step tasks` 的照翻。"""
        t = ToolManager.get_tool("todo_write")
        assert "单步任务" in t.description

    def test_three_statuses_documented(self):
        """三态在描述里有说明（pending/in_progress/completed）。"""
        t = ToolManager.get_tool("todo_write")
        for s in ("pending", "in_progress", "completed"):
            assert s in t.description


class TestWholeTableOverwrite:
    async def test_overwrite_not_append(self, svc):
        await ToolManager.invoke_tool("todo_write", {"todos": [
            {"content": "A", "status": "pending"},
            {"content": "B", "status": "pending"},
        ]})
        await ToolManager.invoke_tool("todo_write", {"todos": [
            {"content": "A", "status": "completed"},
        ]})
        from src.video_agent.tools.todo_tools import read_session_todos

        left = read_session_todos(svc)
        assert len(left) == 1, "整表覆盖：旧条目应被替换而非追加"
        assert left[0]["status"] == "completed"

    async def test_empty_clears(self, svc):
        from src.video_agent.tools.todo_tools import read_session_todos

        await ToolManager.invoke_tool("todo_write", {"todos": [
            {"content": "A", "status": "pending"}]})
        await ToolManager.invoke_tool("todo_write", {"todos": []})
        assert read_session_todos(svc) == []

    async def test_receipt_counts(self, svc):
        r = await ToolManager.invoke_tool("todo_write", {"todos": [
            {"content": "A", "status": "completed"},
            {"content": "B", "status": "in_progress"},
            {"content": "C", "status": "pending"},
        ]})
        assert r.data["count"] == 3
        assert r.data["completed"] == 1
        assert "B" in r.data["in_progress"]


class TestSessionScope:
    """作用域照抄 dsh：**每会话一份**。

    这同时修掉一处实现缺陷：此前清单存项目级 state_dict，
    而主代理与子代理**共享同一 StateManager** ⇒ 两边清单互相覆盖。
    """

    async def test_two_sessions_isolated(self, svc):
        from src.video_agent.tools.todo_tools import read_session_todos

        # 主代理会话写清单
        svc.bound_conversation_id = "conv-main"
        await ToolManager.invoke_tool("todo_write", {"todos": [
            {"content": "主代理步骤", "status": "in_progress"}]})
        # 子代理会话写自己的清单
        svc.bound_conversation_id = "conv-child"
        await ToolManager.invoke_tool("todo_write", {"todos": [
            {"content": "子代理步骤", "status": "in_progress"}]})

        assert [t["content"] for t in read_session_todos(svc, "conv-main")] == ["主代理步骤"]
        assert [t["content"] for t in read_session_todos(svc, "conv-child")] == ["子代理步骤"]


class TestTailInjectionRetired:
    """尾部注入**已整段退役**（2026-09-23 批13，用户裁决：回到 dsh 原版）。

    dsh 原版不回注模型——投影 README「模型体验：无」，原版注释原文
    「the complete `todo/write` session event is UI and replay state,
    **not a second model message**」。批8 自加的尾部注入与 Skill
    `<planner>` 段构成同一事实源两份（P1），故删除。
    """

    def test_note_builder_is_gone(self):
        """`build_todo_note` 必须真的删掉（不是留空壳）。"""
        assert not hasattr(_pb(None), "build_todo_note"), \
            "build_todo_note 仍在 = 注入链路未真正删除（禁止留兼容空壳）"

    def test_reader_helper_is_gone(self):
        """`_read_todos_from_raw`（注入侧读取器）必须一并删掉。"""
        import src.video_agent.core.prompt_builder as pb_mod

        assert not hasattr(pb_mod, "_read_todos_from_raw"), \
            "_read_todos_from_raw 仍在 = 死代码未清"

    async def test_list_not_injected_into_state_tail(self, svc):
        """即便写了清单，尾部消息也**不得**再出现清单内容（无第二条模型消息）。"""
        from src.video_agent.core.planner import PlannerContext

        svc.bound_conversation_id = "conv-main"
        await ToolManager.invoke_tool("todo_write", {"todos": [
            {"content": "登记角色", "status": "in_progress"}]})
        ctx = PlannerContext(use_studio_context=True)
        ctx.state_builder = lambda: '{"keyElements":[],"shots":[],"audioItems":[]}'
        tail = _pb(svc).build_state_tail_message(ctx)
        assert "登记角色" not in tail, "清单仍被注入尾部（未回到 dsh 原版口径）"
        assert "进度清单" not in tail

    def test_list_sections_removed_from_prompt_file(self):
        """外置文案的 LIST_* 分节必须同批删除（无消费方=不得留孤立文案）。"""
        from src.video_agent.utils.prompts import load_prompt_section

        for key in ("LIST_HEADER", "LIST_FOOTER"):
            assert load_prompt_section("shared/todo_write.md", key) == "", \
                f"{key} 分节仍在（注入已删，属孤立文案）"


class TestDshValidationParity:
    """补齐 dsh 漏抄项：空/重复 content 一律 **fail-loud**（批13）。

    dsh `toTodoList`（lib/index.js:45-62）对二者都 `throw`，注释原文：
    「the logged snapshot must equal what the model believes it wrote...
    **fails loud at the schema boundary instead of silently flattening**」。
    批8 只抄了 schema 层形状，漏了这条；旧实现空 content `continue` 静默跳过、
    重复项照收——恰好是原版点名禁止的 silently flattening（账本≠模型所写）。
    """

    async def test_empty_content_rejected(self, svc):
        r = await ToolManager.invoke_tool("todo_write", {"todos": [
            {"content": "  ", "status": "pending"}]})
        assert r.success is False
        assert "non-empty" in r.error

    async def test_duplicate_content_rejected(self, svc):
        r = await ToolManager.invoke_tool("todo_write", {"todos": [
            {"content": "登记角色", "status": "pending"},
            {"content": "登记角色", "status": "in_progress"}]})
        assert r.success is False
        assert "duplicate" in r.error

    async def test_rejection_is_not_silent(self, svc):
        """拒收必须**不落盘**（账本不得被部分写入）。"""
        from src.video_agent.tools.todo_tools import read_session_todos

        await ToolManager.invoke_tool("todo_write", {"todos": [
            {"content": "A", "status": "pending"},
            {"content": "A", "status": "completed"}]})
        assert read_session_todos(svc) == [], "非法提交污染了账本"

    async def test_over_count_rejected_not_truncated(self, svc):
        """超条数上限**拒收**而非静默截断（截断即 silently flatten）。"""
        from src.video_agent.tools.todo_tools import ITEM_MAX_COUNT

        r = await ToolManager.invoke_tool("todo_write", {"todos": [
            {"content": f"步骤{i}", "status": "pending"}
            for i in range(ITEM_MAX_COUNT + 1)]})
        assert r.success is False
        assert "at most" in r.error

    async def test_over_length_rejected_not_truncated(self, svc):
        """超单条长度上限**拒收**而非静默截断（落盘内容必须等于模型所写）。"""
        from src.video_agent.tools.todo_tools import ITEM_MAX_CHARS

        r = await ToolManager.invoke_tool("todo_write", {"todos": [
            {"content": "长" * (ITEM_MAX_CHARS + 1), "status": "pending"}]})
        assert r.success is False
        assert "exceeds" in r.error

    async def test_valid_list_still_passes(self, svc):
        """正常清单不受新校验影响（回归护栏）。"""
        r = await ToolManager.invoke_tool("todo_write", {"todos": [
            {"content": "A", "status": "completed"},
            {"content": "B", "status": "in_progress"}]})
        assert r.success is True, r.error
        assert r.data["count"] == 2
