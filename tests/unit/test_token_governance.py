"""批次3 Token 治理：工具裁剪 / 紧凑 JSON / 降级快照 / 窗口表 / 图片缩放 / read_skill 短路"""
import json

import pytest

from src.video_agent.config import settings
from src.video_agent.core.token_budget import (
    context_window_for_model,
    estimate_tokens,
    truncate_messages,
)
from src.video_agent.state.context_builder import build_agent_context
from src.video_agent.state.models import CAT_KEY_ELEMENTS
from src.video_agent.tools.manager import ToolManager
from src.video_agent.tools.base import BaseTool, ToolResult
from pydantic import BaseModel


class _DummyInput(BaseModel):
    pass


class _DummyTool(BaseTool):
    def __init__(self, name):
        self.name = name
        self.description = f"dummy {name}"

    def get_input_schema(self):
        return _DummyInput

    async def aexecute(self, params):
        return ToolResult(success=True)


@pytest.fixture
def tool_registry():
    ToolManager.reset()
    for name in ("storyboard_patch_draft", "canvas_add_node", "read_skill"):
        ToolManager.register(_DummyTool(name))
    yield
    ToolManager.reset()


def test_tool_schemas_exclude_filter(tool_registry):
    full = ToolManager.get_all_tool_schemas()
    assert len(full) == 3
    filtered = ToolManager.get_all_tool_schemas(exclude={"canvas_add_node"})
    names = {s["function"]["name"] for s in filtered}
    assert names == {"storyboard_patch_draft", "read_skill"}
    # 裁剪不污染全集缓存
    assert len(ToolManager.get_all_tool_schemas()) == 3


def test_context_window_for_model():
    assert context_window_for_model("gemini-3-flash") == 1_000_000
    assert context_window_for_model("gpt-4o-2024") == 128_000
    assert context_window_for_model("unknown-model-x") == settings.context_window_size
    assert context_window_for_model("") == settings.context_window_size


def test_compact_json_roundtrip():
    raw = {CAT_KEY_ELEMENTS: [{"id": "g1", "title": "组", "desc": "", "drafts": []}],
           "assets": [], "documents": [], "uploadedDocs": []}
    # settings 是 frozen dataclass，monkeypatch.setattr 不可用，直接 object.__setattr__
    object.__setattr__(settings, "context_json_compact", True)
    try:
        compact = build_agent_context(raw)
        assert "\n" not in compact  # 紧凑无换行
        assert json.loads(compact)[CAT_KEY_ELEMENTS][0]["id"] == "g1"  # 语义无损
        object.__setattr__(settings, "context_json_compact", False)
        pretty = build_agent_context(raw)
        assert "\n" in pretty
        assert len(compact) < len(pretty)  # 紧凑确实更小
    finally:
        object.__setattr__(settings, "context_json_compact", True)


def test_degraded_context_only_titles():
    raw = {
        CAT_KEY_ELEMENTS: [{
            "id": "g1", "title": "主角", "desc": "x" * 500,
            "drafts": [{"id": "d1", "label": "卡", "prompt": "y" * 2000, "imgUrl": "u"}],
        }],
        "assets": [{"id": "a1"}], "documents": [{"name": "剧本", "content": "z" * 3000}],
        "uploadedDocs": [],
    }
    degraded = json.loads(build_agent_context(raw, degraded=True))
    assert degraded["degraded"] is True
    assert degraded[CAT_KEY_ELEMENTS][0]["draft_count"] == 1
    assert "drafts" not in degraded[CAT_KEY_ELEMENTS][0]
    # 降级体积远小于完整版
    assert len(json.dumps(degraded, ensure_ascii=False)) < len(build_agent_context(raw)) // 2


def test_truncate_system_degrader_fuse():
    """保险丝：历史删到保护边界仍超预算时，system_degrader 重建首条 system"""
    big_system = "system " * 5000
    messages = [{"role": "system", "content": big_system}] + [
        {"role": "user", "content": f"msg{i}"} for i in range(6)
    ]
    result = truncate_messages(messages, max_tokens=100, keep_recent=4)
    assert result[0]["content"] == big_system  # 无降级器：维持原样（旧行为）

    result2 = truncate_messages(
        messages, max_tokens=100, keep_recent=4,
        system_degrader=lambda _s: "degraded-system",
    )
    assert result2[0]["content"] == "degraded-system"


def test_estimate_tokens_fallback_works():
    assert estimate_tokens("") == 0
    assert estimate_tokens("你好世界") >= 2


def test_downscale_image():
    """图片缩放：超限长边被压到 llm_image_max_edge，格式保持"""
    import io
    PIL = pytest.importorskip("PIL")
    from PIL import Image
    from src.video_agent.web.multimodal_builder import _downscale_image

    img = Image.new("RGB", (3000, 1500), "red")
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    raw = buf.getvalue()

    out, mime = _downscale_image(raw, ".jpg")
    assert mime == "image/jpeg"
    resized = Image.open(io.BytesIO(out))
    assert max(resized.size) <= settings.llm_image_max_edge
    assert len(out) < len(raw)

    # 未超限：原样返回
    small = Image.new("RGB", (100, 100), "blue")
    buf2 = io.BytesIO()
    small.save(buf2, format="JPEG")
    raw2 = buf2.getvalue()
    out2, mime2 = _downscale_image(raw2, ".jpg")
    assert out2 == raw2 and mime2 == ""


@pytest.mark.asyncio
async def test_read_skill_short_circuit():
    """read_skill 对已硬注入的 Skill 短路，不真正调用工具"""
    from src.video_agent.core.planner import Planner
    from src.video_agent.adapters.base_chat import ChatResponse

    invoked = []

    class _SpyTool(BaseTool):
        name = "read_skill"
        description = "spy"

        def get_input_schema(self):
            class In(BaseModel):
                name: str = ""
            return In

        async def aexecute(self, params):
            invoked.append(params.name)
            return ToolResult(success=True, data={"content": "全文"})

    ToolManager.reset()
    ToolManager.register(_SpyTool())
    try:
        planner = Planner()
        response = ChatResponse(
            content="",
            tool_calls=[{"id": "c1", "type": "function",
                         "function": {"name": "read_skill", "arguments": '{"name": "分镜师"}'}}],
        )
        # 已注入同名 Skill → 短路
        applied, *_rest, tool_results, _docs, _warnings = await planner._execute_fc_tools(
            response, injected_skill="分镜师"
        )
        assert invoked == []  # 工具未被调用
        assert tool_results[0]["ok"] and tool_results[0]["data"].get("already_injected")

        # 读取另一个 Skill → 正常调用
        response2 = ChatResponse(
            content="",
            tool_calls=[{"id": "c2", "type": "function",
                         "function": {"name": "read_skill", "arguments": '{"name": "编剧"}'}}],
        )
        await planner._execute_fc_tools(response2, injected_skill="分镜师")
        assert invoked == ["编剧"]
    finally:
        ToolManager.reset()
