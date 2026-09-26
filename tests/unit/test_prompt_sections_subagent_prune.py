"""R10 子代理段裁剪测试：subagent_depth ≥ 1 时 catalog/mcp_catalog/global_settings 返回空串。

覆盖：
1. subagent_depth=1 时 _sec_catalog 返回空
2. subagent_depth=1 时 _sec_mcp_catalog 返回空
3. subagent_depth=1 时 _sec_global_settings 返回空
4. subagent_depth=0 时上述三段正常返回内容（非空）
5. PROMPT_SECTIONS 键序快照不变（注册表未被意外修改）
"""
from unittest.mock import MagicMock, patch

import pytest

from src.video_agent.core import prompt_builder as pb_module
from src.video_agent.core.planner import PlannerContext


# ---------- helpers ----------

def _make_builder():
    """最小 PromptBuilder，build_skill_catalog / build_global_settings_note 返回固定文本。"""
    builder = pb_module.PromptBuilder(
        get_skill_docs=lambda: MagicMock(list_skill_docs=lambda: []),
        get_project_id=lambda: "test",
        get_raw_state=lambda: {"mcp_servers": {}},
    )
    # mock 方法使其不依赖真实 Skill 文件
    builder.build_skill_catalog = MagicMock(return_value="[CATALOG_CONTENT]")
    builder.build_global_settings_note = MagicMock(return_value="[GLOBAL_SETTINGS]")
    return builder


def _ctx(depth: int, **kwargs) -> PlannerContext:
    """构造带 subagent_depth 的 PlannerContext。"""
    defaults = dict(use_studio_context=True, state_json="{}")
    defaults.update(kwargs)
    ctx = PlannerContext(**defaults)
    # PlannerContext dataclass 已有 subagent_depth 字段
    object.__setattr__(ctx, "subagent_depth", depth)
    return ctx


# ---------- subagent_depth=1 裁剪 ----------

class TestSubagentPruneDepth1:
    """subagent_depth=1 时三段均返回空串。"""

    def test_sec_catalog_pruned(self):
        builder = _make_builder()
        ctx = _ctx(depth=1)
        assert pb_module._sec_catalog(builder, ctx) == ""

    def test_sec_mcp_catalog_pruned(self):
        builder = _make_builder()
        ctx = _ctx(depth=1)
        assert pb_module._sec_mcp_catalog(builder, ctx) == ""

    def test_sec_global_settings_pruned(self):
        builder = _make_builder()
        ctx = _ctx(depth=1)
        assert pb_module._sec_global_settings(builder, ctx) == ""


class TestSubagentGlobalSettingsStageGated:
    """Q2(a)：子代理仅故事板/提示词阶段注入「仅分镜最大时长」，其余阶段仍不注入。"""

    def test_storyboard_stage_injects_duration_only(self):
        builder = _make_builder()
        ctx = _ctx(depth=1, subagent_stage="storyboard_design")
        assert pb_module._sec_global_settings(builder, ctx) != ""
        builder.build_global_settings_note.assert_called_once_with(duration_only=True)

    def test_write_media_prompt_stage_injects(self):
        builder = _make_builder()
        ctx = _ctx(depth=1, subagent_stage="write_media_prompt")
        assert pb_module._sec_global_settings(builder, ctx) != ""
        builder.build_global_settings_note.assert_called_once_with(duration_only=True)

    def test_other_stage_still_pruned(self):
        builder = _make_builder()
        ctx = _ctx(depth=1, subagent_stage="script_analyze")
        assert pb_module._sec_global_settings(builder, ctx) == ""
        builder.build_global_settings_note.assert_not_called()


# ---------- subagent_depth=0 正常注入 ----------

class TestSubagentPruneDepth0:
    """subagent_depth=0 时三段正常返回非空内容。"""

    def test_sec_catalog_not_pruned(self):
        builder = _make_builder()
        ctx = _ctx(depth=0)
        result = pb_module._sec_catalog(builder, ctx)
        assert result != ""

    def test_sec_mcp_catalog_not_pruned(self):
        builder = _make_builder()
        ctx = _ctx(depth=0)
        with patch.object(
            pb_module.mcp_catalog, "catalog_block", return_value="[MCP_BLOCK]"
        ):
            result = pb_module._sec_mcp_catalog(builder, ctx)
        assert result != ""

    def test_sec_global_settings_not_pruned(self):
        builder = _make_builder()
        ctx = _ctx(depth=0)
        result = pb_module._sec_global_settings(builder, ctx)
        assert result != ""


# ---------- PROMPT_SECTIONS 键序快照 ----------

class TestPromptSectionsKeyOrder:
    """PROMPT_SECTIONS 注册表键序不可被意外修改。"""

    EXPECTED_KEYS = [
        "protocol",
        "catalog",
        "mcp_catalog",
        "iron_rules",
        "global_settings",
        "session_summary",
        "adjust_discipline",
        "subagent",
        "selected_skill",
    ]

    def test_key_order_snapshot(self):
        actual = [spec.name for spec in pb_module.PROMPT_SECTIONS]
        assert actual == self.EXPECTED_KEYS, (
            f"PROMPT_SECTIONS 键序发生变化！\n"
            f"  期望: {self.EXPECTED_KEYS}\n"
            f"  实际: {actual}"
        )
