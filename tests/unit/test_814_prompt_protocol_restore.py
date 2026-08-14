"""814R1 钉死回归：提示词加载器（include/分节）+ 双协议瘦身 + 回喂模板外置。

事故背景：8/12 回退丢失批次5「双协议瘦身/文案外置」接线——system_fc.md 与
{{include}} 无人加载、feedback.md 分节无人读取、text_actions.md 永注入不了。
本测试钉死恢复后的行为，防再次断线。
"""
import pytest

from src.video_agent.core import prompt_builder as pb_module
from src.video_agent.core.planner import PlannerContext, _SKILL_REMINDER
from src.video_agent.core.fc_tool_runner import (
    FEEDBACK_COMPRESSED,
    FEEDBACK_MARKER,
    should_compress_feedback,
)
from src.video_agent.utils import prompts as prompts_mod
from src.video_agent.utils.prompts import load_prompt, load_prompt_section


@pytest.fixture(autouse=True)
def _clear_prompt_cache():
    prompts_mod.clear_cache()
    yield
    prompts_mod.clear_cache()


class _StubSkillDocs:
    def list_skill_docs(self):
        return []


def _make_builder():
    return pb_module.PromptBuilder(
        get_skill_docs=lambda: _StubSkillDocs(),
        get_project_id=lambda: "p1",
        get_raw_state=None,
    )


class TestPromptLoader:
    def test_include_expands_shared_files(self):
        """system_fc.md 的 {{include:shared/*}} 必须被展开为正文"""
        text = load_prompt("planner/system_fc.md")
        assert "{{include:" not in text, "include 指令未被展开"
        # shared/output_discipline.md 的标题应在展开结果里
        assert "回复输出纪律" in text
        assert "画布操作能力" in text  # shared/canvas_tools.md
        assert "故事板媒体调用" in text  # shared/media_rules.md
        assert "重要规则" in text  # shared/important_rules.md

    def test_include_depth_limit_no_cycle_crash(self, tmp_path, monkeypatch):
        """include 递归深度受限，自引用不得死循环"""
        monkeypatch.setattr(prompts_mod, "PROMPTS_DIR", tmp_path)
        (tmp_path / "a.md").write_text("A {{include:a.md}} {{include:b.md}}", encoding="utf-8")
        (tmp_path / "b.md").write_text("B {{include:a.md}}", encoding="utf-8")
        text = load_prompt("a.md")
        assert text.startswith("A"), "递归 include 应被深度限制截断而非崩溃"

    def test_load_prompt_section_reads_key_block(self):
        assert load_prompt_section("planner/feedback.md", "FEEDBACK_MARKER") == (
            "（系统）本轮调用的工具已执行完毕，结果如下："
        )
        assert "此前轮次工具读回的文档全文已从上下文移除" in load_prompt_section(
            "planner/feedback.md", "FEEDBACK_COMPRESSED"
        )
        assert "阶段划分与暂停点" in load_prompt_section(
            "planner/feedback.md", "SKILL_REMINDER"
        )

    def test_load_prompt_section_missing_returns_empty(self):
        assert load_prompt_section("planner/feedback.md", "NO_SUCH_KEY") == ""


class TestDualProtocol:
    def test_fc_mode_uses_slim_protocol(self):
        """FC 通道：system_fc.md 瘦身协议，不含 studio-actions 动作清单"""
        builder = _make_builder()
        ctx = PlannerContext(use_studio_context=True)
        text = builder.build_system_prompt(ctx, fc_mode=True)
        assert "Tool 优先协议" in text
        assert "- add_group:" not in text, "FC 协议不应携带 studio-actions 动作清单"
        assert "可用 action:" not in text, "FC 协议不应携带文本轨动作定义段"

    def test_text_mode_uses_full_protocol(self):
        """文本通道：system.md 完整协议（含 studio-actions 清单）"""
        builder = _make_builder()
        ctx = PlannerContext(use_studio_context=True)
        text = builder.build_system_prompt(ctx, fc_mode=False)
        assert "- add_group:" in text

    def test_text_protocol_injects_text_actions(self):
        """text_protocol=True 时追加 text_actions.md 全量动作定义"""
        builder = _make_builder()
        ctx = PlannerContext(use_studio_context=True, text_protocol=True)
        text = builder.build_system_prompt(ctx, fc_mode=False)
        actions_md = load_prompt("planner/text_actions.md")
        head = actions_md.splitlines()[0].strip()
        assert head and head in text

    def test_fc_mode_does_not_inject_text_actions(self):
        builder = _make_builder()
        ctx = PlannerContext(use_studio_context=True, text_protocol=False)
        text = builder.build_system_prompt(ctx, fc_mode=True)
        actions_md = load_prompt("planner/text_actions.md")
        head = actions_md.splitlines()[0].strip()
        assert head not in text


class TestFeedbackTemplates:
    def test_feedback_marker_from_external_file(self):
        """回喂模板与 feedback.md 分节同源（外置生效，非兜底漂移）"""
        assert FEEDBACK_MARKER == load_prompt_section("planner/feedback.md", "FEEDBACK_MARKER")
        assert FEEDBACK_COMPRESSED == load_prompt_section(
            "planner/feedback.md", "FEEDBACK_COMPRESSED"
        )

    def test_skill_reminder_from_external_file(self):
        assert _SKILL_REMINDER == load_prompt_section("planner/feedback.md", "SKILL_REMINDER")

    def test_compress_threshold_follows_model_window(self):
        """窗口感知压缩：阈值随传入窗口变化（814R1 恢复批次6 X1 语义）"""
        from src.video_agent.config import settings

        ratio = settings.feedback_compress_ratio
        if ratio >= 1.0 or ratio <= 0.0:
            pytest.skip("默认比例不在 (0,1) 区间，无法构造边界")
        small_window = 1000
        big_window = 10_000_000
        # tiktoken 可用时估算更小，取足够长的内容确保越过小窗口阈值
        msgs = [{"role": "user", "content": "x" * 60000}]
        assert should_compress_feedback(msgs, small_window) is True
        assert should_compress_feedback(msgs, big_window) is False
