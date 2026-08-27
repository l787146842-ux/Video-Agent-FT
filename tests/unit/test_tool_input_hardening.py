"""批 4a（T2 第一步「错误可见」）：写类入参未知字段可见报错 + target 结构化校验。

覆盖：
① manager 层未知字段可见性（字段名入文案、合法字段清单入文案、
   error_code="validation"、retryable=False，且工具未被执行）；
② 合法字段不误伤；
③ patch_draft/patch_group 白名单丢弃透出 + storyboard_patch_draft 原子拒收；
④ image_generate target 未命中/格式非法结构化报错。

回归锚点见 test_tool_error_axis.py（保持原样）。
"""
import pytest
from pydantic import BaseModel, ConfigDict

from src.video_agent.state import storyboard_ops as ops
from src.video_agent.state.manager import StateManager
from src.video_agent.tools.base import BaseTool, ToolResult
from src.video_agent.tools.manager import ToolManager, detect_unknown_fields
from src.video_agent.tools.storyboard_tools import PatchDraftInput, StoryboardPatchDraftTool


# ---------- 测试用工具 ----------

class _HardenInput(BaseModel):
    draft_id: str = ""
    prompt: str = ""


class _HardenTool(BaseTool):
    name = "harden_probe"
    risk = "low"
    executed = False

    def get_input_schema(self):
        return _HardenInput

    async def aexecute(self, params):
        _HardenTool.executed = True
        return ToolResult(success=True, data={"ok": 1})


@pytest.fixture
def manager_probe():
    ToolManager.reset()
    _HardenTool.executed = False
    ToolManager.register(_HardenTool())
    yield ToolManager
    ToolManager.reset()


@pytest.fixture
def svc(tmp_path):
    StateManager.reset_instance()
    instance = StateManager(str(tmp_path))
    StateManager._instance = instance  # 工具内部走 get_instance，需绑定夹具（同 test_storyboard_ops 口径）
    yield instance
    StateManager.reset_instance()


def _seed_draft(svc, prompt="白发老者站在冥王星冰原上，伦勃朗式光影。"):
    svc.state_dict["keyElements"] = [{
        "id": "ke-t", "title": "Element_测试",
        "drafts": [{"id": "d-ke1", "label": "概念图", "tag": "Agent", "prompt": prompt}],
    }]
    svc.state_dict.setdefault("shots", [])
    svc.state_dict.setdefault("audioItems", [])


# ---------- ① manager 层未知字段可见性 ----------

class TestDetectUnknownFields:
    def test_sorted_diff(self):
        got = detect_unknown_fields(_HardenInput, {"prompt": "x", "zz": 1, "aa": 2})
        assert got == ["aa", "zz"]

    def test_empty_when_all_known(self):
        assert detect_unknown_fields(_HardenInput, {"draft_id": "d1", "prompt": "x"}) == []


class TestManagerUnknownFieldVisibility:
    async def test_unknown_fields_rejected_with_structured_error(self, manager_probe):
        r = await manager_probe.invoke_tool(
            "harden_probe", {"prompt": "x", "negitive_prompt": "y", "seed": 42})
        assert r.success is False
        assert r.error_code == "validation"
        assert r.retryable is False
        # 被丢弃字段名入文案（排序后逐个列出）
        assert "negitive_prompt" in str(r.error) and "seed" in str(r.error)
        # 合法字段清单入文案，帮助模型一次改对
        assert "draft_id" in str(r.error) and "prompt" in str(r.error)
        # 拒收发生在执行前：工具未被调用
        assert _HardenTool.executed is False

    async def test_valid_fields_not_penalized(self, manager_probe):
        r = await manager_probe.invoke_tool("harden_probe", {"draft_id": "d1", "prompt": "x"})
        assert r.success is True
        assert _HardenTool.executed is True

    async def test_validation_failure_field_level_rendering(self, manager_probe):
        """ValidationError 走字段级渲染：逐字段清单 + 合法字段，保留 Validation Error 前缀"""
        r = await manager_probe.invoke_tool("harden_probe", {"draft_id": 1, "prompt": ["非字符串"]})
        assert r.error_code == "validation" and r.retryable is False
        assert "Validation Error" in str(r.error)
        assert "draft_id" in str(r.error)  # 出错字段名入清单（合法字段清单内）


class _PermissiveInput(BaseModel):
    model_config = ConfigDict(extra="allow")


class _PermissiveTool(BaseTool):
    name = "harden_permissive"
    risk = "low"

    def get_input_schema(self):
        return _PermissiveInput

    async def aexecute(self, params):
        return ToolResult(success=True, data={})


class TestPermissiveSchemaTolerated:
    """平台容忍路径：显式 extra='allow' 的自由入参模型（MCP 适配器同款口径）
    不参与未知字段比对，任意键放行"""

    async def test_free_form_kwargs_not_rejected(self):
        ToolManager.reset()
        ToolManager.register(_PermissiveTool())
        try:
            r = await ToolManager.invoke_tool("harden_permissive", {"text": "x", "anything": 1})
            assert r.success is True
        finally:
            ToolManager.reset()


# ---------- ③ patch_draft/patch_group 白名单丢弃透出 ----------

class TestPatchWhitelistDrop:
    def test_patch_draft_exposes_dropped(self):
        draft = {"id": "d1", "prompt": "旧"}
        changed, dropped = ops.patch_draft(draft, {"prompt": "新", "negitive_prompt": "x"})
        assert changed is True
        assert dropped == ["negitive_prompt"]
        assert draft["prompt"] == "新"
        assert "negitive_prompt" not in draft

    def test_patch_group_exposes_dropped(self):
        group = {"id": "g1", "title": "旧标题"}
        changed, dropped = ops.patch_group(group, {"title": "新标题", "color": "red"})
        assert changed is True
        assert dropped == ["color"]
        assert group["title"] == "新标题" and "color" not in group

    def test_dropped_patch_fields_references_whitelist(self):
        """差集只引用名单常量，不复制内容（P1）"""
        got = ops.dropped_patch_fields({"bogus": 1, "label": "x"}, ops.ALLOWED_DRAFT_FIELDS)
        assert got == ["bogus"]


class TestStoryboardPatchDraftAtomicReject:
    async def test_unknown_patch_field_rejected_and_not_written(self, svc):
        _seed_draft(svc)
        tool = StoryboardPatchDraftTool()
        r = await tool.aexecute(PatchDraftInput(
            draft_id="d-ke1", draft_type="keyElement",
            patch={"prompt": "新提示词", "negitive_prompt": "不要模糊"},
        ))
        assert r.success is False
        assert r.error_code == "validation" and r.retryable is False
        assert "negitive_prompt" in str(r.error)
        # 合法字段清单入文案
        assert "prompt" in str(r.error) and "label" in str(r.error)
        # 原子拒收：合法字段也不得部分写入
        assert svc.state_dict["keyElements"][0]["drafts"][0]["prompt"] != "新提示词"

    async def test_clean_patch_still_succeeds(self, svc):
        _seed_draft(svc)
        tool = StoryboardPatchDraftTool()
        r = await tool.aexecute(PatchDraftInput(
            draft_id="d-ke1", draft_type="keyElement",
            patch={"prompt": "新提示词，冷白主光。"},
        ))
        assert r.success is True
        assert svc.state_dict["keyElements"][0]["drafts"][0]["prompt"] == "新提示词，冷白主光。"


# ---------- ④ image_generate target 结构化校验 ----------

class TestImageGenerateTargetValidation:
    async def test_invalid_format_target(self, svc, monkeypatch):
        from src.video_agent.tools.document_tools import GenerateImageInput, ImageGenerateTool
        monkeypatch.setattr(StateManager, "_instance", svc)
        _seed_draft(svc)
        r = await ImageGenerateTool().aexecute(GenerateImageInput(target="角色概念图 第一张"))
        assert r.success is False
        assert r.error_code == "validation" and r.retryable is False
        assert "格式非法" in str(r.error)
        # 合法取值说明与可用 draft_id 采样入文案
        assert "all_keyElements" in str(r.error) and "d-ke1" in str(r.error)

    async def test_missing_target(self, svc, monkeypatch):
        from src.video_agent.tools.document_tools import GenerateImageInput, ImageGenerateTool
        monkeypatch.setattr(StateManager, "_instance", svc)
        _seed_draft(svc)
        r = await ImageGenerateTool().aexecute(GenerateImageInput(target="d-not-exist"))
        assert r.success is False
        assert r.error_code == "validation" and r.retryable is False
        assert "未命中" in str(r.error) and "d-ke1" in str(r.error)

    async def test_target_draft_without_prompt(self, svc, monkeypatch):
        from src.video_agent.tools.document_tools import GenerateImageInput, ImageGenerateTool
        monkeypatch.setattr(StateManager, "_instance", svc)
        _seed_draft(svc, prompt="")
        r = await ImageGenerateTool().aexecute(GenerateImageInput(target="d-ke1"))
        assert r.success is False
        assert r.error_code == "validation" and r.retryable is False
        assert "没有提示词" in str(r.error)

    async def test_current_keyword_not_silently_resolved(self, svc, monkeypatch):
        """target='current' 非具体 draft_id，不得被 find_draft 静默解析成首条草稿"""
        from src.video_agent.tools.document_tools import GenerateImageInput, ImageGenerateTool
        monkeypatch.setattr(StateManager, "_instance", svc)
        _seed_draft(svc)
        r = await ImageGenerateTool().aexecute(GenerateImageInput(target="current"))
        assert r.success is False and r.error_code == "validation"
