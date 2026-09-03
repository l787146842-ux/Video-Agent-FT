"""814R1 钉死回归：提示词加载器（include/分节）+ 协议单轨接线 + 回喂模板外置。

事故背景：8/12 回退丢失批次5「双协议瘦身/文案外置」接线——protocol.md 与
分节无人读取、feedback.md 分节无人读取。
本测试钉死恢复后的行为，防再次断线；P2e 后协议收敛为单一 protocol.md。
"""
import pytest

from src.video_agent.core import prompt_builder as pb_module
from src.video_agent.core.planner import PlannerContext
from src.video_agent.core.fc_feedback import (
    FEEDBACK_COMPRESSED,
    FEEDBACK_MARKER,
    format_tool_results,
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
    def test_protocol_loads_without_include_directives(self):
        """protocol.md 已内联共有段，不再含 {{include:}} 指令"""
        text = load_prompt("planner/protocol.md")
        assert "{{include:" not in text, "include 指令未被展开"
        # 内联段的关键标题应在结果里
        assert "回复输出纪律" in text
        assert "画布操作能力" in text
        assert "故事板媒体调用" in text
        assert "重要规则" in text

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

    def test_load_prompt_section_missing_returns_empty(self):
        assert load_prompt_section("planner/feedback.md", "NO_SUCH_KEY") == ""


class TestSingleProtocol:
    def test_protocol_is_slim_fc_only(self):
        """协议单轨（P2e）：唯一协议 = protocol.md 瘦身协议，
        不含 studio-actions 动作清单。"""
        builder = _make_builder()
        ctx = PlannerContext(use_studio_context=True)
        text = builder.build_system_prompt(ctx)
        assert "Tool 优先协议" in text
        assert "- add_group:" not in text, "FC 协议不应携带 studio-actions 动作清单"
        assert "可用 action:" not in text, "FC 协议不应携带文本轨动作定义段"

    def test_text_actions_never_injected_after_44(self):
        """4-4 双轨退役（协议单轨）：text_actions.md 已删除，
        协议不再注入文本动作定义。"""
        builder = _make_builder()
        ctx = PlannerContext(use_studio_context=True)
        text = builder.build_system_prompt(ctx)
        assert "- add_group:" not in text
        assert "studio-actions 文本协议" not in text


class TestFeedbackTemplates:
    def test_feedback_marker_from_external_file(self):
        """回喂模板与 feedback.md 分节同源（外置生效，非兜底漂移）"""
        assert FEEDBACK_MARKER == load_prompt_section("planner/feedback.md", "FEEDBACK_MARKER")
        assert FEEDBACK_COMPRESSED == load_prompt_section(
            "planner/feedback.md", "FEEDBACK_COMPRESSED"
        )

    def test_read_result_note_retired(self):
        """语气转化：READ_RESULT_NOTE 已退役，回喂不再注入引导说教。"""
        msg = format_tool_results([
            {"name": "read_skill", "ok": True, "data": {"name": "S", "content": "BODY"}},
        ])
        assert isinstance(msg, str)
        assert "- read_skill 执行成功，全文如下：" in msg, "数据体应为纯客观结果行"
        assert "后续任务必须遵守" not in msg, "语气转化：引导说教已退役"
    
    def test_image_result_note_retired(self):
        """语气转化：IMAGE_RESULT_NOTE 已退役，多模态回喂不再尾部注入引导说教。"""
        parts = format_tool_results([{
            "name": "view_storyboard_media", "ok": True,
            "data": {"images": [{"label": "L", "draft_id": "d",
                                 "data_uri": "data:image/png;base64,AA"}], "notes": []},
        }])
        assert isinstance(parts, list)
        assert not any("仅供当前" in str(p.get("text", "")) for p in parts), \
            "语气转化：IMAGE_RESULT_NOTE 已退役"

    # test_skill_reminder_from_external_file 已随 S09 退役删除（用户裁决 2026-09-02）

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
