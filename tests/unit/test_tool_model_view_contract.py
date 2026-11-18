"""工具模型可见输出契约（对齐 dsh 的 output/render，2026-11-11）。

dsh 的硬约束：工具必须声明 output，并把值 render 成模型可见 content；
渲染不出来就不算成功。本项目等价约束（不引入框架，只落规矩）：

1. 每个注册工具都有可调用的 ``model_view``（BaseTool 默认读 data.detail）；
2. 成功且带 data 的结果，回喂正文不得只剩「执行成功」——
   工具没渲染时由 fc_feedback 兜底原始返回并告警。

这两条一旦变红，说明新工具又回到了「成功但对模型静默为空」的老路
（6666 / 2026-11-10：canvas_list 的 data 被整包丢弃）。
"""
import pytest

from src.video_agent.core.fc_feedback import (
    FEEDBACK_FULL_TOOLS,
    FEEDBACK_IMAGE_TOOL,
    format_tool_results,
)
from src.video_agent.tools.manager import ToolManager

# 平台工具在包导入时注册（props：tools/__init__.py 顶部注册）
import src.video_agent.tools  # noqa: F401,E402
from src.video_agent.tools.canvas_tools import register_canvas_tools  # noqa: E402

register_canvas_tools()

TOOLS = list(ToolManager._tools.values())
# 全文回喂/多模态分支的渲染按各自 data 形状定制，已由专项用例覆盖；
# 本契约针对「detail/model_view/兜底」这条通用通道。
GENERIC_TOOLS = [
    t for t in TOOLS
    if t.name not in FEEDBACK_FULL_TOOLS
    and t.name not in (FEEDBACK_IMAGE_TOOL, "read_skill")  # 专项分支，见 test_fc_tool_feedback
]


@pytest.fixture(scope="module", autouse=True)
def _restore_registry():
    """隔离本模块的注册副作用，避免污染同 worker 的其他用例。"""
    saved = dict(ToolManager._tools)
    yield
    ToolManager._tools = saved
    ToolManager._schema_cache = None


def test_registry_not_empty():
    assert TOOLS, "工具注册表为空，契约测试无从校验"


@pytest.mark.parametrize("tool", TOOLS, ids=lambda t: t.name)
def test_tool_has_model_view(tool):
    assert callable(getattr(tool, "model_view", None)), (
        f"{tool.name} 缺少 model_view：模型可见内容必须由工具自述")


@pytest.mark.parametrize("tool", GENERIC_TOOLS, ids=lambda t: t.name)
def test_success_with_data_is_visible(tool):
    """成功 + data 非空 ⇒ 模型必须看到内容（工具渲染或兜底）。"""
    msg = format_tool_results([{
        "name": tool.name, "ok": True,
        "data": {"probe_marker": "CONTRACT_MARK"},
    }])
    assert "CONTRACT_MARK" in msg, f"{tool.name} 的成功结果对模型静默为空"


def test_runner_attaches_tool_model_view():
    """执行器必须把工具自述渲染挂进 tool_results（否则契约只停在工具里）。"""
    from src.video_agent.core.fc_tool_runner import FCToolRunner
    from src.video_agent.tools.canvas_tools import CanvasListTool

    class _Manager:
        def get_tool(self, name):
            return CanvasListTool()

    runner = FCToolRunner(tool_manager=_Manager())
    view = runner._model_view_of(
        "canvas_list", {"canvases": [{"id": "c1", "title": "测试画布", "node_count": 1}]})
    assert "c1" in view
    msg = format_tool_results([{
        "name": "canvas_list", "ok": True,
        "data": {"canvases": [{"id": "c1", "title": "测试画布", "node_count": 1}]},
        "model_view": view,
    }])
    assert "c1" in msg


def test_canvas_list_renders_structured_ids_not_fallback():
    """画布读工具用例：id/标题/节点数由工具自己渲染（不是靠兜底 JSON）。"""
    from src.video_agent.tools.canvas_tools import CanvasListTool

    view = CanvasListTool().model_view({
        "canvases": [{"id": "c1", "title": "测试画布", "node_count": 2}],
        "count": 1,
    })
    assert "c1" in view and "测试画布" in view and "2 节点" in view
