"""宪法 §2.7 工具风险分级落地回归：

- BaseTool.risk 声明位 + 注册期 deny-by-default 强制校验；
- 24 个平台工具逐一声明且与审核定级表一致（任务#36 B5：8 个 Skill
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
from src.video_agent.core import gate_registry, guard_pipeline
from src.video_agent.core.fc_tool_runner import FCToolRunner
from src.video_agent.core.tracer import AgentTracer
from src.video_agent.tools.base import BaseTool, ToolResult
from src.video_agent.tools.manager import ToolManager

# ---------- 审核定级表（用户拍板，照此核对） ----------

EXPECTED_RISK = {
    # low（10）：只读/可逆
    "canvas_list": "low",
    "canvas_read_nodes": "low",
    "canvas_list_assets": "low",
    "read_uploaded_doc": "low",
    "read_skill": "low",
    "read_project_doc": "low",
    "storyboard_media_to_chat": "low",
    "read_draft": "low",
    "read_state_group": "low",
    "view_storyboard_media": "low",
    # medium（6）：写状态但可撤销（Q2 裁决 2026-09-01：flow_directive 工具退役）
    "workflow_pause": "medium",
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
        StoryboardReadStateGroupTool,
        ViewStoryboardMediaTool,
    )
    from src.video_agent.tools.video.generate_video import GenerateVideoTool

    return [
        CanvasListTool, CanvasReadNodesTool, CanvasListAssetsTool,
        ReadUploadedDocTool, ReadSkillTool, ReadProjectDocTool,
        StoryboardMediaToChatTool, StoryboardReadDraftTool, ViewStoryboardMediaTool,
        StoryboardReadStateGroupTool, WorkflowPauseTool,
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
    approval_tier = "sign-off"  # F1：声明轴退役——非法声明忽略不拒收


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


# ---------- 审批生效档（F1 裁决 2026-08-31：双轴并单轴，risk 单轴推导） ----------

class TestApprovalTier:
    def test_generation_family_confirm_derived_from_risk(self):
        """F1：确认档由 risk 单轴推导（确认只挂高危），不再显式声明。"""
        from src.video_agent.tools.document_tools import ImageGenerateTool
        from src.video_agent.tools.video.generate_video import GenerateVideoTool
        for cls in (GenerateVideoTool, ImageGenerateTool):
            assert cls.risk == "high"
            assert not getattr(cls, "approval_tier", ""), (
                f"生成族 {cls.name} 不应再显式声明 approval_tier（F1 声明轴退役）"
            )

    def test_register_ignores_stale_approval_declaration(self):
        """F1：approval_tier 声明轴退役——残留非法声明忽略不拒收，
        生效档按 risk 推导（low → none）。"""
        ToolManager.register(_BadApprovalTool())
        try:
            assert "_probe_bad_approval" in ToolManager._tools
            assert ToolManager.get_tool_approval_tier("_probe_bad_approval") == "none"
        finally:
            ToolManager._tools.pop("_probe_bad_approval", None)
            ToolManager._schema_cache = None

    def test_effective_tier_derived_from_risk_single_axis(self):
        """生效档：risk 单轴纯推导（high→confirm，其余 none）；
        未注册工具按最严口径一律 confirm（未声明=最严）。"""
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


def _run(monkeypatch, name, args, *, gate_override=False, state=None,
         injected_skill=""):
    runner = FCToolRunner(tool_manager=_StubTM())
    monkeypatch.setattr(
        FCToolRunner, "_raw_state", staticmethod(lambda: state or {}))
    res = asyncio_run(runner.execute(
        _fc_call(name, args), gate_override=gate_override,
        injected_skill=injected_skill))
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

    def test_spec_write_allowed_with_pause_consent(self, monkeypatch):
        """批 12 章程（闸级端到端）：暂停卡 accept（账本登记轮号匹配）后
        重提 document_write 写规格文档 → 放行（规格确认卡兑现，1000 清偿）。"""
        state = {"turn_seq": 2, "interaction": {"generation_consented_turn": 2}}
        runner, res = _run(monkeypatch, "document_write",
                           {"name": "制片规格.md", "content": "# 制片规格"},
                           state=state)
        assert res[0] == 1, "规格写入在同意账本命中时应放行（章程 spec_write）"
        assert any("consent=pause_accept" in w for w in runner.gate_warnings)

    def test_spec_write_ledger_stale_still_blocked(self, monkeypatch):
        """规格写入但账本轮号失配（同意过期）→ 仍拦（fail-closed 保持）。"""
        state = {"turn_seq": 3, "interaction": {"generation_consented_turn": 2}}
        runner, res = _run(monkeypatch, "document_write",
                           {"name": "制片规格.md", "content": "# 制片规格"},
                           state=state)
        assert res[0] == 0, "账本轮号失配的规格写入不得放行"
        assert any("高风险工具确认闸拦截" in w for w in runner.gate_warnings)

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
        assert gate_registry.GATE_RULES["platform.tool_risk"].layer == "platform"


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

    def test_batch_exempt_only_when_gen_confirm_active(self, monkeypatch):
        """批量轨豁免为「有条件」：仅当覆盖它的 gen_confirm 闸 active
        （injected_skill 非空 且 gate_mode=strict）时才让位；覆盖闸未激活时
        不豁免，回本闸正常 risk 判定拦截（高危默认拦，杜绝零确认）。"""
        from src.video_agent.core import fc_gates
        from src.video_agent.tools.document_tools import ImageGenerateTool
        ToolManager.register(ImageGenerateTool())
        # gen_confirm active（skill 在场 + strict）：豁免，交给 gen_confirm 覆盖
        monkeypatch.setattr(
            "src.video_agent.core.prompt_gates.gate_mode", lambda: "strict")
        ctx_active = fc_gates.GateContext(
            state=lambda: {}, injected_skill="在场 Skill")
        assert fc_gates.tool_risk_gate(
            ctx_active, "image_generate", {"mode": "batch"}) is None
        assert fc_gates.tool_risk_gate(ctx_active, "image_generate", {}) is None  # 缺省=batch
        assert fc_gates.tool_risk_gate(ctx_active, "image_generate") is None
        # gen_confirm 未激活（无 injected_skill）：不豁免 → 本闸拦截
        ctx_no_skill = fc_gates.GateContext(state=lambda: {})
        for m in ({"mode": "batch"}, {}, None):
            err = fc_gates.tool_risk_gate(ctx_no_skill, "image_generate", m)
            assert err and "高风险工具确认闸拦截" in err
        # gen_confirm 未激活（gate_mode != strict）：不豁免 → 本闸拦截
        monkeypatch.setattr(
            "src.video_agent.core.prompt_gates.gate_mode", lambda: "off")
        ctx_off = fc_gates.GateContext(
            state=lambda: {}, injected_skill="在场 Skill")
        err = fc_gates.tool_risk_gate(ctx_off, "image_generate", {"mode": "batch"})
        assert err and "高风险工具确认闸拦截" in err

    def test_single_predicate_arms_for_registered_and_unregistered(self):
        """未注册工具同口径 deny-by-default：tier=confirm + risk=high 双命中。"""
        from src.video_agent.core import fc_gates
        ctx = fc_gates.GateContext(
            state=lambda: {}, tool_risk_of=lambda name: "high")
        err = fc_gates.tool_risk_gate(
            ctx, "__not_registered__", {})
        assert err and "高风险工具确认闸拦截" in err


# ---------- 批 B 执行偏好：costly 声明轴 + 三档分流 ----------

class _BadCostlyTool(_NoRiskTool):
    name = "_probe_bad_costly"
    risk = "low"
    costly = "yes"  # 非 bool 值注册期拒收（仿 approval_tier 校验）


class TestCostlyAxis:
    def test_only_generation_family_declares_costly(self):
        """花钱声明轴仅两个生成工具显式声明，其余默认 False
        （偏好不放宽；数据驱动，不硬编码工具名单）。"""
        costly = {cls.name for cls in _all_tool_classes()
                  if getattr(cls, "costly", False)}
        assert costly == {"image_generate", "generate_video"}

    def test_register_rejects_non_bool_costly(self):
        with pytest.raises(ValueError):
            ToolManager.register(_BadCostlyTool())
        assert "_probe_bad_costly" not in ToolManager._tools

    def test_is_costly_tool_default_false_and_unregistered(self):
        from src.video_agent.tools.document_tools import (
            DocumentWriteTool,
            ImageGenerateTool,
        )
        from src.video_agent.tools.video.generate_video import GenerateVideoTool
        ToolManager.register(ImageGenerateTool())
        ToolManager.register(GenerateVideoTool())
        ToolManager.register(DocumentWriteTool())
        assert ToolManager.is_costly_tool("image_generate") is True
        assert ToolManager.is_costly_tool("generate_video") is True
        assert ToolManager.is_costly_tool("document_write") is False
        assert ToolManager.is_costly_tool("__not_registered__") is False


class TestExecPreferenceToolRisk:
    """批 B：执行偏好只放宽花钱生成（costly 轴）；非花钱高危 /
    未注册兜底拦截语义零改动（红线）。"""

    def test_generate_directly_costly_passes_with_trace(self, monkeypatch,
                                                        set_global_setting):
        from src.video_agent.tools.video.generate_video import GenerateVideoTool
        ToolManager.register(GenerateVideoTool())
        set_global_setting("execution_preference", "generate_directly")
        tracer = AgentTracer.get_instance()
        runner, res = _run(monkeypatch, "generate_video", {"target": "all_shots"})
        assert res[0] == 1, "generate_directly：花钱生成免确认放行"
        assert any("执行偏好「直接生成」" in w for w in runner.gate_warnings)
        recent = tracer.get_recent_gates(10)
        assert any(g["rule_id"] == "platform.tool_risk" and g["overridden"]
                   for g in recent), "偏好放行必须留痕（platform.tool_risk）"

    def test_generate_directly_non_costly_still_blocked(self, monkeypatch,
                                                        set_global_setting):
        """红线：非花钱高危（document_write / canvas_*）在 generate_directly 下仍拦。"""
        set_global_setting("execution_preference", "generate_directly")
        runner, res = _run(monkeypatch, "document_write",
                           {"name": "大纲.md", "content": "x"})
        assert res[0] == 0, "document_write 不受偏好放宽，必须拦"
        assert any("高风险工具确认闸拦截" in w for w in runner.gate_warnings)
        for name in ("canvas_add_node", "canvas_delete_node"):
            _r, r2 = _run(monkeypatch, name, {"canvas_id": "cv-1"})
            assert r2[0] == 0, f"{name} 不受偏好放宽，必须拦"

    def test_generate_directly_unregistered_still_blocked(self, monkeypatch,
                                                          set_global_setting):
        """红线：未注册工具仍按 deny-by-default 拦截，偏好不放宽。"""
        set_global_setting("execution_preference", "generate_directly")
        _runner, res = _run(monkeypatch, "__ghost_tool__", {})
        assert res[0] == 0

    def test_auto_decide_with_skill_passes_with_trace(self, monkeypatch,
                                                      set_global_setting):
        from src.video_agent.core import stage_probes
        from src.video_agent.tools.video.generate_video import GenerateVideoTool
        ToolManager.register(GenerateVideoTool())
        set_global_setting("execution_preference", "auto_decide")
        tracer = AgentTracer.get_instance()
        runner, res = _run(monkeypatch, "generate_video", {"target": "all_shots"},
                           injected_skill="未注册的在场 Skill")
        assert res[0] == 1, "auto_decide：活跃 Skill 指导在场放行"
        assert any("执行偏好「自动决定」" in w for w in runner.gate_warnings)
        recent = tracer.get_recent_gates(10)
        assert any(g["rule_id"] == "platform.tool_risk" and g["overridden"]
                   for g in recent), "偏好放行必须留痕"

    def test_auto_decide_without_skill_still_blocked(self, monkeypatch,
                                                     set_global_setting):
        from src.video_agent.tools.video.generate_video import GenerateVideoTool
        ToolManager.register(GenerateVideoTool())
        set_global_setting("execution_preference", "auto_decide")
        runner, res = _run(monkeypatch, "generate_video", {"target": "all_shots"})
        assert res[0] == 0, "auto_decide：无活跃 Skill 时仍拦（现状语义）"
        assert any("高风险工具确认闸拦截" in w for w in runner.gate_warnings)

    def test_auto_decide_non_costly_still_blocked(self, monkeypatch,
                                                  set_global_setting):
        """红线：非花钱高危在 auto_decide + 活跃 Skill 下仍拦。"""
        set_global_setting("execution_preference", "auto_decide")
        _runner, res = _run(monkeypatch, "document_write",
                            {"name": "大纲.md", "content": "x"},
                            injected_skill="未注册的在场 Skill")
        assert res[0] == 0

    def test_default_pref_costly_still_blocked(self, monkeypatch,
                                               set_global_setting):
        """默认档语义不变：花钱生成无同意仍拦。"""
        from src.video_agent.tools.video.generate_video import GenerateVideoTool
        ToolManager.register(GenerateVideoTool())
        set_global_setting("execution_preference", "confirm_before_gen")
        _runner, res = _run(monkeypatch, "generate_video", {"target": "all_shots"})
        assert res[0] == 0

    def test_gate_ctx_injects_skill_active_branch(self, set_global_setting):
        """单元直测：tool_risk_gate 经 GateContext 注入 skill_active，
        判定归 evaluate_tool_risk（宪法 §2.0 单一判定点）。"""
        from src.video_agent.core import fc_gates
        from src.video_agent.tools.video.generate_video import GenerateVideoTool
        ToolManager.register(GenerateVideoTool())
        set_global_setting("execution_preference", "auto_decide")
        ctx = fc_gates.GateContext(state=lambda: {}, injected_skill="未注册的在场 Skill")
        assert fc_gates.tool_risk_gate(
            ctx, "generate_video", {"target": "all_shots"}) is None
        ctx2 = fc_gates.GateContext(state=lambda: {})
        assert fc_gates.tool_risk_gate(
            ctx2, "generate_video", {"target": "all_shots"})


# ---------- P0 组合不变量：花钱/高危工具无零确认路径 ----------

class TestCostlyToolNoZeroConfirmPath:
    """组合级不变量（P0 修复回归）：花钱/高危工具在任何
    覆盖集 × injected_skill（空/非空）× gate_mode（strict/off/warn）
    × mode（single/batch）组合下，tool_risk 与 gen_confirm 两道闸
    至少有一道生效（不存在两道闸都关的零确认路径）。
    背景：image_generate 批量轨曾「豁免无条件、覆盖有条件」，
    模型自主调用且 injected_skill 为空时两道闸都关→花钱零确认。"""

    @pytest.mark.parametrize("name", ["image_generate", "generate_video"])
    @pytest.mark.parametrize("injected_skill", ["", "在场 Skill"])
    @pytest.mark.parametrize("gate_mode", ["strict", "off", "warn"])
    @pytest.mark.parametrize("mode", ["single", "batch"])
    def test_at_least_one_gate_fires(self, monkeypatch, name, injected_skill,
                                     gate_mode, mode):
        from src.video_agent.core import fc_gates
        from src.video_agent.tools.document_tools import ImageGenerateTool
        from src.video_agent.tools.video.generate_video import GenerateVideoTool
        ToolManager.register(ImageGenerateTool())
        ToolManager.register(GenerateVideoTool())
        monkeypatch.setattr(
            "src.video_agent.core.prompt_gates.gate_mode", lambda: gate_mode)
        # 未确认草稿（tag != 已确认）：gen_confirm active 时会拦，确保覆盖闸真生效
        state = {"keyElements": [{"drafts": [
            {"id": "d1", "prompt": "深空中的二向箔，冷白荧光。", "tag": "Agent"},
        ]}]}
        ctx = fc_gates.GateContext(
            state=lambda: state, injected_skill=injected_skill)
        args = {"mode": mode, "target": "all_keyElements"}
        risk_err = fc_gates.tool_risk_gate(ctx, name, args)
        gen_err = fc_gates.gen_confirm_gate(ctx, name, args)
        assert risk_err is not None or gen_err is not None, (
            f"零确认路径：{name} mode={mode} skill={injected_skill!r} "
            f"gate_mode={gate_mode} 两道闸都放行（花钱无确认）")
