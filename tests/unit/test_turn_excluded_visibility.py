"""R11 裁剪可见性测试：turn_excluded 非空时状态尾消息可见标注不可用工具及替代路由。

覆盖：
1. build_state_tail_message 输出含 UNAVAILABLE + 工具名（turn_excluded 非空）
2. build_state_tail_message 输出不含 UNAVAILABLE（turn_excluded 为空）
3. fc_tool_runner 拒收信封包含替代路由信息
4. fc_tool_runner 拒收信封不含 image_generate/generate_video 字面量
"""
import asyncio
from unittest.mock import MagicMock, patch

import pytest

from src.video_agent.core import prompt_builder as pb_module
from src.video_agent.core.planner import PlannerContext
from src.video_agent.utils import prompts as prompts_mod


@pytest.fixture(autouse=True)
def _clear_prompt_cache():
    prompts_mod.clear_cache()
    yield
    prompts_mod.clear_cache()


class _StubSkillDocs:
    def list_skill_docs(self):
        return []

    def resolve_skill_content(self, name):
        return (name, "")

    def list_skill_sections(self, content):
        return []


def _make_builder():
    return pb_module.PromptBuilder(
        get_skill_docs=lambda: _StubSkillDocs(),
        get_project_id=lambda: "p1",
        get_raw_state=lambda: {},
    )


class TestTurnExcludedVisibility:
    """build_state_tail_message 的 UNAVAILABLE 段渲染。"""

    def test_turn_excluded_nonempty_renders_unavailable(self):
        """turn_excluded 非空时输出包含 UNAVAILABLE 和被裁工具名。"""
        builder = _make_builder()
        ctx = PlannerContext(
            use_studio_context=True,
            state_json='{"keyElements":[]}',
            turn_excluded=frozenset({"storyboard_create_group", "read_skill"}),
        )
        result = builder.build_state_tail_message(ctx)
        assert "UNAVAILABLE" in result
        assert "storyboard_create_group" in result
        assert "read_skill" in result
        assert "委派" in result or "run_subagent" in result

    def test_turn_excluded_empty_no_unavailable(self):
        """turn_excluded 为空时输出不含 UNAVAILABLE。"""
        builder = _make_builder()
        ctx = PlannerContext(
            use_studio_context=True,
            state_json='{"keyElements":[]}',
            turn_excluded=frozenset(),
        )
        result = builder.build_state_tail_message(ctx)
        assert "UNAVAILABLE" not in result

    def test_turn_excluded_none_no_unavailable(self):
        """turn_excluded 为 None（默认）时输出不含 UNAVAILABLE。"""
        builder = _make_builder()
        ctx = PlannerContext(
            use_studio_context=True,
            state_json='{"keyElements":[]}',
        )
        result = builder.build_state_tail_message(ctx)
        assert "UNAVAILABLE" not in result


class TestFcToolRunnerRejection:
    """fc_tool_runner 拒收信封的替代路由信息。"""

    def _make_runner(self):
        """构造最小 FCToolRunner 实例（不依赖完整 tool_manager）。"""
        from src.video_agent.core.fc_tool_runner import FCToolRunner

        tool_mgr = MagicMock()
        runner = FCToolRunner(tool_mgr)
        return runner

    def test_rejection_contains_route(self):
        """拒收信封包含替代路由信息（R4 批后取仍可委派阶段工具为例）。"""
        runner = self._make_runner()
        runner.turn_excluded = frozenset({"storyboard_add_draft"})
        result = asyncio.run(
            runner._dispatch_tool("storyboard_add_draft", {})
        )
        assert not result.success
        assert "替代路由" in (result.error or "")
        assert "委派" in (result.error or "") or "run_subagent" in (result.error or "")

    def test_rejection_no_provider_tool_literals(self):
        """拒收信封不含 image_generate/generate_video 字面量（门禁红线）。"""
        runner = self._make_runner()
        # 模拟生产轮裁剪集（含 provider 工具名的集合由 PRODUCTION_MAIN_PRUNE 定义）
        from src.video_agent.core.subagent import PRODUCTION_MAIN_PRUNE

        runner.turn_excluded = PRODUCTION_MAIN_PRUNE
        # 对裁剪集中的每个工具调用 _dispatch_tool，检查错误消息
        for tool_name in sorted(PRODUCTION_MAIN_PRUNE):
            result = asyncio.run(
                runner._dispatch_tool(tool_name, {})
            )
            error_msg = result.error or ""
            assert "image_generate" not in error_msg, (
                f"拒收信封含禁止字面量 image_generate（工具 {tool_name}）"
            )
            assert "generate_video" not in error_msg, (
                f"拒收信封含禁止字面量 generate_video（工具 {tool_name}）"
            )

    def test_non_production_excluded_gets_generic_route(self):
        """非 PRODUCTION_MAIN_PRUNE 的被裁工具使用通用路由描述。"""
        runner = self._make_runner()
        runner.turn_excluded = frozenset({"some_canvas_tool"})
        result = asyncio.run(
            runner._dispatch_tool("some_canvas_tool", {})
        )
        assert not result.success
        assert "替代路由" in (result.error or "")
        assert "不在可见面" in (result.error or "")
