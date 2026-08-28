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
