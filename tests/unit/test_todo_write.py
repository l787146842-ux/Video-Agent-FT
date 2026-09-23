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

    def test_visible_to_both_agents(self):
        """主代理与子代理都持有（记账是两边共同需求）。"""
        from src.video_agent.core.subagent import (
            MAIN_AGENT_DENY, SUBAGENT_TOOL_DENY, STAGE_TOOL_DENY_EXTRA,
        )

        assert "todo_write" not in MAIN_AGENT_DENY
        assert "todo_write" not in SUBAGENT_TOOL_DENY
        assert "todo_write" not in STAGE_TOOL_DENY_EXTRA


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


class TestTailInjection:
    """清单随状态尾部注入（模型每轮看得见自己写到哪）。"""

    async def test_note_marks(self, svc):
        svc.bound_conversation_id = "conv-main"
        await ToolManager.invoke_tool("todo_write", {"todos": [
            {"content": "已做", "status": "completed"},
            {"content": "在做", "status": "in_progress"},
            {"content": "未做", "status": "pending"},
        ]})
        note = _pb(svc).build_todo_note()
        assert "[x] 已做" in note
        assert "[>] 在做" in note
        assert "[ ] 未做" in note

    def test_empty_not_injected(self, svc):
        assert _pb(svc).build_todo_note() == ""

    async def test_reaches_state_tail(self, svc):
        from src.video_agent.core.planner import PlannerContext

        svc.bound_conversation_id = "conv-main"
        await ToolManager.invoke_tool("todo_write", {"todos": [
            {"content": "登记角色", "status": "in_progress"}]})
        ctx = PlannerContext(use_studio_context=True)
        ctx.state_builder = lambda: '{"keyElements":[],"shots":[],"audioItems":[]}'
        tail = _pb(svc).build_state_tail_message(ctx)
        assert "登记角色" in tail, "清单未进尾部消息（模型看不见=白记）"
