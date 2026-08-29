"""宪法 §2.7 工具风险分级落地回归：

- BaseTool.risk 声明位 + 注册期 deny-by-default 强制校验；
- 23 个平台工具逐一声明且与审核定级表一致（任务#36 B5：8 个 Skill
  执行器工具已随执行器一步退役物理删除，不再计入；双生图工具合并后
  generate_image 已并入 image_generate 的 mode='single'）；
- 确认闸数据驱动（P0-1）：生效条件 = approval_tier=confirm（推导含
  high→confirm、未注册→confirm）+ risk=high 双保险；
- generate_video 漏闸补齐两态：无同意硬拒 / 同意回携放行；
- image_generate single 模式同类漏闸补齐（行为变更，高危默认拦）；
- 拦截/豁免均经 platform.tool_risk verdict 入审计。
"""
import json

import pytest
from pydantic import BaseModel

from src.video_agent.adapters.base_chat import ChatResponse
from src.video_agent.core import guard_pipeline, prompt_gates
from src.video_agent.core.fc_tool_runner import FCToolRunner
from src.video_agent.core.tracer import AgentTracer
from src.video_agent.tools.base import BaseTool, ToolResult
from src.video_agent.tools.manager import ToolManager

# ---------- 审核定级表（用户拍板，照此核对） ----------

EXPECTED_RISK = {
    # low（9）：只读/可逆
    "canvas_list": "low",
    "canvas_read_nodes": "low",
    "canvas_list_assets": "low",
    "read_uploaded_doc": "low",
    "read_skill": "low",
    "read_project_doc": "low",
    "storyboard_media_to_chat": "low",
    "read_draft": "low",
    "view_storyboard_media": "low",
    # medium（7）：写状态但可撤销
    "workflow_pause": "medium",
    "flow_directive": "medium",
    "storyboard_create_group": "medium",
    "storyboard_patch_draft": "medium",
    "storyboard_add_draft": "medium",
    "storyboard_delete_group": "medium",
    "storyboard_confirm_draft": "medium",
    # high（7）：生成/文档写入/外部副作用（双生图工具合并：
    # generate_image 已并入 image_generate 的 mode='single'）
    "image_generate": "high",
    "generate_video": "high",
    "canvas_add_node": "high",
    "canvas_update_node": "high",
    "canvas_delete_node": "high",
    "canvas_batch_add_nodes": "high",
    "document_write": "high",
    # （原 8 个 skill 执行器工具的定级条目已随任务#36 B5 执行器一步
    # 退役删除；同名未注册工具经 deny-by-default 一律按 high 对待。）
}


def _all_tool_classes():
    from src.video_agent.tools.canvas_tools import (
        CanvasBatchUpdateTool,
        CanvasDeleteNodeTool,
        CanvasListAssetsTool,
        CanvasListTool,
        CanvasReadNodesTool,
        CanvasAddNodeTool,
        CanvasUpdateNodeTool,
    )
    from src.video_agent.tools.document_tools import (
        DocumentWriteTool,
        FlowDirectiveTool,
        ImageGenerateTool,
        ReadProjectDocTool,
        ReadSkillTool,
        ReadUploadedDocTool,
        WorkflowPauseTool,
    )
    from src.video_agent.tools.storyboard_tools import (
        StoryboardAddDraftTool,
        StoryboardConfirmDraftTool,
        StoryboardCreateGroupTool,
        StoryboardDeleteGroupTool,
        StoryboardMediaToChatTool,
        StoryboardPatchDraftTool,
        StoryboardReadDraftTool,
        ViewStoryboardMediaTool,
    )
    from src.video_agent.tools.video.generate_video import GenerateVideoTool

    return [
        CanvasListTool, CanvasReadNodesTool, CanvasListAssetsTool,
        ReadUploadedDocTool, ReadSkillTool, ReadProjectDocTool,
        StoryboardMediaToChatTool, StoryboardReadDraftTool, ViewStoryboardMediaTool,
        WorkflowPauseTool, FlowDirectiveTool,
        StoryboardCreateGroupTool, StoryboardPatchDraftTool, StoryboardAddDraftTool,
        StoryboardDeleteGroupTool, StoryboardConfirmDraftTool,
        ImageGenerateTool, GenerateVideoTool,
        CanvasAddNodeTool, CanvasUpdateNodeTool, CanvasDeleteNodeTool,
        CanvasBatchUpdateTool, DocumentWriteTool,
    ]


class TestDeclarationCoverage:
    def test_all_platform_tools_declare_expected_risk(self):
        classes = _all_tool_classes()
        assert len(classes) == 23
        declared = {}
        for cls in classes:
            assert cls.name in EXPECTED_RISK, f"定级表缺少 {cls.name}"
            assert cls.risk == EXPECTED_RISK[cls.name], (
                f"{cls.name} 声明 risk={cls.risk!r}，定级表要求 {EXPECTED_RISK[cls.name]!r}"
            )
            declared[cls.name] = cls.risk
        assert declared == EXPECTED_RISK


# ---------- 注册期 deny-by-default 校验 ----------

class _ProbeInput(BaseModel):
    pass


class _NoRiskTool(BaseTool):
    name = "_probe_no_risk"
    description = "未声明 risk 的探针工具"

    def get_input_schema(self):
        return _ProbeInput

    async def aexecute(self, params):
        return ToolResult(success=True)


class _BadRiskTool(_NoRiskTool):
    name = "_probe_bad_risk"
    risk = "danger"  # 非法取值同样拒收


class _OkRiskTool(_NoRiskTool):
    name = "_probe_ok_risk"
    risk = "low"


class _BadApprovalTool(_NoRiskTool):
    name = "_probe_bad_approval"
    risk = "low"
    approval_tier = "sign-off"  # 非法取值：注册期拒收（任务 P2-5）


class TestRegistrationEnforcement:
    def test_register_rejects_undeclared_risk(self):
        with pytest.raises(ValueError):
            ToolManager.register(_NoRiskTool())
        assert "_probe_no_risk" not in ToolManager._tools

    def test_register_rejects_invalid_risk(self):
        with pytest.raises(ValueError):
            ToolManager.register(_BadRiskTool())
        assert "_probe_bad_risk" not in ToolManager._tools

    def test_register_accepts_declared_risk(self):
        ToolManager.register(_OkRiskTool())
        try:
            assert ToolManager.get_tool("_probe_ok_risk").risk == "low"
        finally:
            ToolManager._tools.pop("_probe_ok_risk", None)
            ToolManager._schema_cache = None

    def test_get_tool_risk_deny_by_default(self):
        # 未注册/未声明一律 high（deny-by-default）；注册表可能被其他
        # 测试 fixture 重置，此处自行补注册真实工具再断言
        from src.video_agent.tools.document_tools import (
            DocumentWriteTool,
            ReadSkillTool,
        )
        ToolManager.register(DocumentWriteTool())
        ToolManager.register(ReadSkillTool())
        assert ToolManager.get_tool_risk("__not_registered__") == "high"
        assert ToolManager.get_tool_risk("document_write") == "high"
        assert ToolManager.get_tool_risk("read_skill") == "low"


# ---------- 审批分级正交轴（任务 P2-5） ----------

class TestApprovalTier:
    def test_generation_family_declares_confirm(self):
        """生成族首批显式声明 approval_tier（与 risk 正交的第二轴）。"""
        from src.video_agent.tools.document_tools import ImageGenerateTool
        from src.video_agent.tools.video.generate_video import GenerateVideoTool
        for cls in (GenerateVideoTool, ImageGenerateTool):
            assert cls.approval_tier == "confirm", (
                f"生成族 {cls.name} 应首批显式声明 approval_tier=confirm"
            )

    def test_register_rejects_invalid_approval_tier(self):
        with pytest.raises(ValueError):
            ToolManager.register(_BadApprovalTool())
        assert "_probe_bad_approval" not in ToolManager._tools

    def test_effective_tier_declared_then_derived(self):
        """生效档：显式声明优先；未声明按 risk 推导（high→confirm，其余 none）；
        未注册工具按 high 口径一律 confirm（deny-by-default 同口径）。"""
        from src.video_agent.tools.document_tools import (
            DocumentWriteTool,
            ImageGenerateTool,
            ReadSkillTool,
        )
        ToolManager.register(ImageGenerateTool())
        ToolManager.register(DocumentWriteTool())
        ToolManager.register(ReadSkillTool())
        assert ToolManager.get_tool_approval_tier("image_generate") == "confirm"
        assert ToolManager.get_tool_approval_tier("document_write") == "confirm"
        assert ToolManager.get_tool_approval_tier("read_skill") == "none"
        assert ToolManager.get_tool_approval_tier("__not_registered__") == "confirm"

    def test_get_tool_approval_tiers_covers_registry(self):
        """全量生效档表收录已注册工具（sidecar 导出的单一事实源）。"""
        from src.video_agent.tools.video.generate_video import GenerateVideoTool
        ToolManager.register(GenerateVideoTool())
        tiers = ToolManager.get_tool_approval_tiers()
        assert tiers["generate_video"] == "confirm"
        assert all(v in ("none", "confirm", "review") for v in tiers.values())


# ---------- platform.tool_risk 确认闸（FC 轨消费） ----------

class _StubTM:
    async def invoke_tool(self, name, args):
        return ToolResult(success=True, data={})


def _fc_call(name, args):
    return ChatResponse(content="", tool_calls=[
        {"id": "c1", "type": "function",
         "function": {"name": name, "arguments": json.dumps(args)}},
    ])


def _run(monkeypatch, name, args, *, gate_override=False, state=None):
    runner = FCToolRunner(tool_manager=_StubTM())
    monkeypatch.setattr(
        FCToolRunner, "_raw_state", staticmethod(lambda: state or {}))
    res = asyncio_run(runner.execute(_fc_call(name, args), gate_override=gate_override))
    return runner, res


def asyncio_run(coro):
    import asyncio
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _reset_tracer():
    AgentTracer.reset()
    yield
    AgentTracer.reset()


class TestToolRiskGate:
    def test_document_write_blocked_without_consent(self, monkeypatch):
        runner, res = _run(monkeypatch, "document_write",
                           {"name": "大纲.md", "content": "x"})
        applied, _confirm = res[0], res[1]
        assert applied == 0, "未经用户确认的 high 级工具不得执行"
        assert any("高风险工具确认闸拦截" in w for w in runner.gate_warnings)
        tool_results = res[6]
        assert tool_results and tool_results[0]["ok"] is False

    def test_canvas_write_blocked_without_consent(self, monkeypatch):
        for name in ("canvas_add_node", "canvas_update_node",
                     "canvas_delete_node", "canvas_batch_add_nodes"):
            runner, res = _run(monkeypatch, name, {"canvas_id": "cv-1"})
            assert res[0] == 0, f"{name} 未经确认不得执行"
            assert any("高风险工具确认闸拦截" in w for w in runner.gate_warnings)

    def test_user_override_allows_with_trace(self, monkeypatch):
        tracer = AgentTracer.get_instance()
        tracer.start_trace("t")
        tracer.start_step()
        runner, res = _run(monkeypatch, "document_write",
                           {"name": "大纲.md", "content": "x"}, gate_override="all")
        assert res[0] == 1, "用户「本次放行」（scope=all）应放行"
        assert any("用户坚持放行高风险工具确认闸" in w for w in runner.gate_warnings)
        recent = tracer.get_recent_gates(10)
        assert any(g["rule_id"] == "platform.tool_risk" and g["overridden"]
                   for g in recent), "豁免必须留痕（platform.tool_risk verdict）"

    def test_flow_directive_consent_allows(self, monkeypatch):
        state = {"interaction": {"auto_continue": True}}
        runner, res = _run(monkeypatch, "document_write",
                           {"name": "大纲.md", "content": "x"}, state=state)
        assert res[0] == 1, "一条龙指令 = 本批显式同意（留痕）"
        assert any("显式同意" in w for w in runner.gate_warnings)

    def test_block_verdict_audited(self, monkeypatch):
        tracer = AgentTracer.get_instance()
        tracer.start_trace("t")
        tracer.start_step()
        _run(monkeypatch, "document_write", {"name": "大纲.md", "content": "x"})
        recent = tracer.get_recent_gates(10)
        assert any(g["rule_id"] == "platform.tool_risk" and g["ok"] is False
                   for g in recent), "拦截必须经 audit_verdicts 留痕"

    def test_low_and_medium_tools_unaffected(self, monkeypatch):
        # 显式重注册：同 worker 其它用例的 ToolManager.reset() 可能清空全局
        # 注册表（本文件 generate_video 用例同口径），不依赖导入副作用
        from src.video_agent.tools.document_tools import register_document_tools
        from src.video_agent.tools.storyboard_tools import register_storyboard_tools

        register_storyboard_tools()
        register_document_tools()
        # low 直执行、medium 按现状（无新闸行为变化）
        for name in (("read_draft", {"draft_id": "1-1"}),
                     ("storyboard_patch_draft", {"draft_id": "d1", "patch": {}}),
                     ("workflow_pause", {"message": "确认？"})):
            _runner, res = _run(monkeypatch, name[0], name[1])
            assert res[0] == 1, f"{name[0]}（low/medium）不受新闸影响"

    def test_evaluate_tool_risk_no_silent_pass(self):
        err, warns = guard_pipeline.evaluate_tool_risk("document_write")
        assert err and warns, "无同意必须硬拒，禁止静默放行"
        assert prompt_gates.GATE_RULES["platform.tool_risk"].layer == "platform"


class TestGenerateVideoConfirmGate:
    """P0-1 数据驱动后 generate_video 漏闸补齐：无同意硬拒 / 有同意放行。"""

    def test_generate_video_blocked_without_consent(self, monkeypatch):
        from src.video_agent.tools.video.generate_video import GenerateVideoTool
        ToolManager.register(GenerateVideoTool())
        runner, res = _run(monkeypatch, "generate_video", {"target": "all_shots"})
        assert res[0] == 0, "generate_video 未经用户确认不得执行（花钱操作）"
        assert any("高风险工具确认闸拦截" in w for w in runner.gate_warnings)
        tool_results = res[6]
        assert tool_results and tool_results[0]["ok"] is False

    def test_generate_video_override_allows_with_trace(self, monkeypatch):
        from src.video_agent.tools.video.generate_video import GenerateVideoTool
        ToolManager.register(GenerateVideoTool())
        tracer = AgentTracer.get_instance()
        tracer.start_trace("t")
        tracer.start_step()
        runner, res = _run(monkeypatch, "generate_video", {"target": "all_shots"},
                           gate_override="all")
        assert res[0] == 1, "用户「本次放行」（scope=all）应放行"
        assert any("用户坚持放行高风险工具确认闸" in w for w in runner.gate_warnings)
        recent = tracer.get_recent_gates(10)
        assert any(g["rule_id"] == "platform.tool_risk" and g["overridden"]
                   for g in recent), "豁免必须留痕（platform.tool_risk verdict）"

    def test_generate_video_flow_directive_consent_allows(self, monkeypatch):
        from src.video_agent.tools.video.generate_video import GenerateVideoTool
        ToolManager.register(GenerateVideoTool())
        state = {"interaction": {"auto_continue": True}}
        runner, res = _run(monkeypatch, "generate_video", {"target": "all_shots"},
                           state=state)
        assert res[0] == 1, "一条龙指令 = 本批显式同意（留痕）"
        assert any("显式同意" in w for w in runner.gate_warnings)


class TestImageGenerateSingleRiskGate:
    """image_generate mode='single' 同类漏闸补齐（行为变更：高危默认拦，
    对齐业界；批量轨仍由 gen_confirm 闸专属覆盖，不双闸）。"""

    def test_single_blocked_without_consent(self, monkeypatch):
        runner, res = _run(monkeypatch, "image_generate",
                           {"mode": "single", "prompt": "一只猫",
                            "adapter_provider": "prov-x"})
        assert res[0] == 0, "single 模式花钱生图未经用户确认不得执行"
        assert any("高风险工具确认闸拦截" in w for w in runner.gate_warnings)
        tool_results = res[6]
        assert tool_results and tool_results[0]["ok"] is False

    def test_single_override_allows_with_trace(self, monkeypatch):
        tracer = AgentTracer.get_instance()
        tracer.start_trace("t")
        tracer.start_step()
        runner, res = _run(monkeypatch, "image_generate",
                           {"mode": "single", "prompt": "一只猫",
                            "adapter_provider": "prov-x"},
                           gate_override="all")
        assert res[0] == 1, "用户「本次放行」应放行（留痕）"
        recent = tracer.get_recent_gates(10)
        assert any(g["rule_id"] == "platform.tool_risk" and g["overridden"]
                   for g in recent)

    def test_batch_not_gated_by_tool_risk(self):
        """批量轨豁免：被 gen_confirm 闸专属覆盖，本闸不双拦。"""
        from src.video_agent.core import fc_gates
        ctx = fc_gates.GateContext(state=lambda: {})
        assert fc_gates.tool_risk_gate(ctx, "image_generate", {"mode": "batch"}) is None
        assert fc_gates.tool_risk_gate(ctx, "image_generate", {}) is None  # 缺省=batch
        assert fc_gates.tool_risk_gate(ctx, "image_generate") is None

    def test_single_predicate_arms_for_registered_and_unregistered(self):
        """未注册工具同口径 deny-by-default：tier=confirm + risk=high 双命中。"""
        from src.video_agent.core import fc_gates
        ctx = fc_gates.GateContext(
            state=lambda: {}, tool_risk_of=lambda name: "high")
        err = fc_gates.tool_risk_gate(
            ctx, "__not_registered__", {})
        assert err and "高风险工具确认闸拦截" in err
