"""T5 结构化错误轴（批 3）：ToolResult.error_code/retryable 立轴与生产端标注。

口径对齐 core/fc_feedback.classify_tool_failure：validation/exception/
upstream/timeout/canvas/other；空串=未标注（消费端回落文本分类）。
"""
from pydantic import BaseModel

from src.video_agent.core.fc_feedback import compose_failure_feedback
from src.video_agent.tools.base import BaseTool, ToolResult
from src.video_agent.tools.manager import ToolManager


class TestToolResultErrorAxisDefaults:
    """新字段带默认值，既有构造不受影响（向后兼容）"""

    def test_success_result_defaults(self):
        r = ToolResult(success=True, data={"k": 1})
        assert r.error_code == ""
        assert r.retryable is False

    def test_failure_result_defaults(self):
        r = ToolResult(success=False, error="boom")
        assert r.error_code == ""
        assert r.retryable is False

    def test_explicit_codes_accepted(self):
        r = ToolResult(success=False, error="x", error_code="upstream", retryable=True)
        assert r.error_code == "upstream"
        assert r.retryable is True


class _T5Input(BaseModel):
    value: int


class _T5BoomTool(BaseTool):
    name = "t5_boom"
    risk = "low"

    def get_input_schema(self):
        return _T5Input

    async def aexecute(self, params):
        raise RuntimeError("boom")


class TestManagerErrorCodes:
    """manager 两条失败路径的 error_code 填充"""

    def setup_method(self):
        ToolManager.reset()
        ToolManager.register(_T5BoomTool())

    def teardown_method(self):
        ToolManager.reset()

    async def test_validation_failure_code(self):
        r = await ToolManager.invoke_tool("t5_boom", {"value": "not-an-int"})
        assert r.success is False
        assert r.error_code == "validation"
        assert r.retryable is False
        assert "Validation Error" in str(r.error)

    async def test_exception_fallback_code(self):
        r = await ToolManager.invoke_tool("t5_boom", {"value": 1})
        assert r.success is False
        assert r.error_code == "exception"
        assert r.retryable is False


class TestFailureFeedbackAxis:
    """compose_failure_feedback 按 error_code/retryable 微调，旧签名兼容"""

    def test_legacy_signature_unchanged(self):
        msg = compose_failure_feedback("script_analyze", "输出无法解析", 1)
        assert msg.startswith("[output_format]")
        assert "重试一次" in msg

    def test_error_code_as_kind_prefix(self):
        msg = compose_failure_feedback(
            "image_generate", "上游 500", 1, error_code="upstream", retryable=True,
        )
        assert msg.startswith("[upstream]")
        assert "可重试" in msg

    def test_validation_hint_forbids_same_args(self):
        msg = compose_failure_feedback(
            "image_generate", "未找到有提示词的草稿", 1, error_code="validation",
        )
        assert msg.startswith("[validation]")
        assert "修正入参" in msg and "原参" in msg

    def test_non_retryable_annotated_code(self):
        msg = compose_failure_feedback(
            "canvas_update_node", "节点不存在", 1, error_code="canvas",
        )
        assert msg.startswith("[canvas]")
        assert "盲重试" in msg

    def test_second_failure_still_escalates(self):
        msg = compose_failure_feedback(
            "generate_video", "上游失败", 2, error_code="upstream", retryable=True,
        )
        assert "不得再次重试" in msg


class TestModelFacingFailureTextNotTruncated:
    """批1（Q9，用户裁决 2026-09-23）：**回喂模型的失败正文一律不设固定字符上限**。

    口径 = dsh「按去向分流」而非「按内容分流」：模型读的那份完整，
    只有落库存档/UI 展示侧才设限（且必须带省略标记，见 fc_tool_runner
    的 _DISPLAY_ERR_LIMIT + tool_args_preview.truncate_text）。

    原 `[:120]` 砍掉的恰是行动指引尾部（如「去 write_media_prompt 阶段
    生成图像卡」），使模型拿到不可行动的残句——本类钉死该回归。
    """

    def test_long_error_kept_verbatim(self):
        """超 120 字的错误原文必须完整保留（不被砍头）。"""
        long_err = "卡片未生成：" + "请先到 write_media_prompt 阶段生成图像卡，" * 8
        msg = compose_failure_feedback("image_generate", long_err, 1)
        assert long_err in msg, "回喂正文被截断：行动指引尾部丢失"
        assert len(msg) > 120

    def test_action_guidance_beyond_120_preserved(self):
        """行动指引落在第 120 字之后时仍必须可见（原 bug 的精确复现）。"""
        tail_hint = "去 write_media_prompt 阶段生成图像卡"
        err = "前" * 200 + tail_hint
        msg = compose_failure_feedback("image_generate", err, 1)
        assert tail_hint in msg
        assert "已截断" not in msg, "回喂正文不应带展示侧的截断标记"

    def test_no_truncation_marker_on_model_facing_text(self):
        """回喂正文不得出现展示侧的省略标记（两者是不同的去向）。"""
        msg = compose_failure_feedback("script_analyze", "错" * 500, 1)
        assert "已截断" not in msg
        assert "…（已截断" not in msg
