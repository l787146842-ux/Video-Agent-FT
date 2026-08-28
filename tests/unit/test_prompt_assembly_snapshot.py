# -*- coding: utf-8 -*-
"""P2（任务#15）：system prompt 组装快照锁 + 段落注册制 + 同源裁剪解释。

快照锁语义：改造（注册制重构）前后组装结果逐字节一致——golden 在改造前
由 build_snapshot_scenarios() 对现网代码采集落 tests/fixtures/prompt_assembly_golden.json；
stage_note 新增注入属行为变更场景，不在快照范围内，单独成对断言。
P2-3 段通道手术：状态上下文（状态 JSON/边界说明/故事板进度）移出
system 段，改经 build_state_tail_message 以 history 尾部消息（user 通道）
注入；golden 含尾部消息场景，同批重采。
"""
import json
import pathlib

import pytest

FIXTURE = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "prompt_assembly_golden.json"


class _StubSkillDocs:
    """确定性 Skill 文档提供者（与 data/skills 隔离，快照不受内容清扫影响）"""

    def list_skill_docs(self):
        return [
            {"name": "快照Skill-A", "description": "摘要甲"},
            {"slug": "snapshot-b", "name": "快照Skill-B", "description": "摘要乙"},
        ]

    def resolve_skill_content(self, name):
        if name == "快照Skill-A":
            return "快照Skill-A", "## 流程规划\n第一步：撰写规格。\n第二步：搭建故事板。"
        raise KeyError(name)

    def split_skill_sections(self, content):
        return {}

    def list_skill_sections(self, content):
        return []


def build_snapshot_scenarios():
    """构造确定性组装场景 → {场景名: system prompt}（序稳定）。"""
    from src.video_agent.core.planner import PlannerContext
    from src.video_agent.core.prompt_builder import PromptBuilder

    raw_with_ke = {
        "keyElements": [{"id": "ke-1", "title": "角色", "drafts": []}],
        "shots": [], "audioItems": [],
    }
    raw_empty = {"keyElements": [], "shots": [], "audioItems": []}

    def _pb(raw):
        return PromptBuilder(lambda: _StubSkillDocs(), lambda: "proj-snap",
                             lambda: raw)

    out = {}

    # S1 裸场景：无工作台上下文，仅目录段
    pb = _pb(raw_empty)
    out["bare"] = pb.build_system_prompt(PlannerContext(
        use_studio_context=False, state_json=""))

    # S2 工作台 + 状态 JSON + 选中草稿（无 Skill）
    pb = _pb(raw_with_ke)
    out["studio_state_draft"] = pb.build_system_prompt(PlannerContext(
        use_studio_context=True,
        state_json='{"project": "快照项目", "keyElements": 1}',
        selected_draft_id="draft-9", selected_type="shot",
    ))

    # S3 工作台 + 选中 Skill + state_builder + 故事板进度
    pb = _pb(raw_with_ke)
    out["studio_skill_progress"] = pb.build_system_prompt(PlannerContext(
        use_studio_context=True,
        state_builder=lambda: '{"phase": "storyboard"}',
        skill_name="快照Skill-A",
    ))

    # S4 无 raw state 提供者（聚焦/铁律/进度探测全缺省）
    pb = PromptBuilder(lambda: _StubSkillDocs(), lambda: "proj-snap", None)
    out["no_raw_state"] = pb.build_system_prompt(PlannerContext(
        use_studio_context=True, state_json='{"legacy": true}',
    ))

    # ---------- P2-3：状态上下文 history 尾部消息（user 通道）场景 ----------

    # T1 状态 JSON + 选中草稿指针（草稿指针留在 system，不进尾部消息）
    pb = _pb(raw_with_ke)
    ctx = PlannerContext(
        use_studio_context=True,
        state_json='{"project": "快照项目", "keyElements": 1}',
        selected_draft_id="draft-9", selected_type="shot",
    )
    out["tail_state_draft"] = pb.build_state_tail_message(ctx)

    # T2 状态 JSON + 故事板客观进度（选中 Skill + state_builder）
    pb = _pb(raw_with_ke)
    ctx = PlannerContext(
        use_studio_context=True,
        state_builder=lambda: '{"phase": "storyboard"}',
        skill_name="快照Skill-A",
    )
    out["tail_skill_progress"] = pb.build_state_tail_message(ctx)

    # T3 状态 JSON + 同源裁剪解释（stage_note 随状态同通道迁移）
    pb = _pb(raw_with_ke)
    ctx = PlannerContext(
        use_studio_context=True,
        state_json='{"phase": "planning"}',
        stage_note="== 当前阶段工具边界：部分工具本阶段不可用 ==",
    )
    out["tail_stage_note"] = pb.build_state_tail_message(ctx)

    return out


def test_assembly_snapshot_matches_golden():
    """组装输出逐字节与 golden 一致（P2-3 段通道手术后 golden 已同批重采：
    system 场景不再含状态上下文，新增尾部消息场景）"""
    assert FIXTURE.exists(), "golden 缺失：须先在改造前采集基线"
    golden = json.loads(FIXTURE.read_text(encoding="utf-8"))
    actual = build_snapshot_scenarios()
    assert sorted(actual) == sorted(golden), "场景集变化须同步重采 golden"
    for name, expect in golden.items():
        assert actual[name] == expect, f"场景 {name} 组装结果发生字节级漂移"


# ---------- 同源裁剪解释（任务#15 P2：裁剪⇔解释成对断言） ----------

@pytest.fixture
def svc(tmp_path):
    from src.video_agent.state.manager import StateManager
    StateManager.reset_instance()
    yield StateManager(str(tmp_path))
    StateManager.reset_instance()


def _make_planner(svc):
    from src.video_agent.core.planner import Planner
    planner = Planner.__new__(Planner)  # 绕过重量级构造，只测裁剪签发链路
    planner.state_manager = svc
    return planner


def _make_ctx(skill="剧本生视频（需上传剧本）"):
    from src.video_agent.core.planner import PlannerContext
    ctx = PlannerContext()
    ctx.use_studio_context = True
    ctx.skill_name = skill
    return ctx


def _build_with_ctx(ctx, svc):
    """按 planner 同链路组装（stage_note 已由 _compute_excluded_tools 签发）"""
    from src.video_agent.core.prompt_builder import PromptBuilder
    pb = PromptBuilder(lambda: _StubSkillDocs(), lambda: "proj-snap",
                       lambda: svc.state_dict)
    return pb.build_system_prompt(ctx)


def _tail_with_ctx(ctx, svc):
    """同链路的 history 尾部状态消息（P2-3 后裁剪解释的注入面）"""
    from src.video_agent.core.prompt_builder import PromptBuilder
    pb = PromptBuilder(lambda: _StubSkillDocs(), lambda: "proj-snap",
                       lambda: svc.state_dict)
    return pb.build_state_tail_message(ctx)


def test_stage_note_prune_explain_pairing(svc):
    """裁剪⇔解释成对：excluded 非空 → context 携带 note 且尾部消息可见解释
    （消灭「静默裁剪」：裁了工具却不告诉模型）；P2-3 后解释随状态同通道，
    不再进 system（system 成跨步稳定前缀）"""
    svc.state_dict["documents"] = []  # 无规格文档 → 阶段裁剪生效
    planner = _make_planner(svc)
    ctx = _make_ctx()
    excluded = planner._compute_excluded_tools(ctx)
    assert "storyboard_create_group" in excluded and "generate_video" in excluded
    assert "image_generate" not in excluded  # 单张应急轨任意阶段可见
    assert ctx.stage_excluded_tools and ctx.stage_note
    assert "当前阶段工具边界" in ctx.stage_note
    # 同源解释必须随尾部消息注入（非各自拼装），且不再出现在 system 段
    assert ctx.stage_note in _tail_with_ctx(ctx, svc)
    assert ctx.stage_note not in _build_with_ctx(ctx, svc)


def test_stage_note_absent_when_no_pruning(svc):
    """裁剪⇔解释成对（反向）：excluded 为空 → note 为空且不注入解释段"""
    svc.state_dict["documents"] = [{"name": "制片规格.md", "content": "正文"}]
    svc.state_dict["keyElements"] = [{"id": "ke-1", "drafts": []}]
    planner = _make_planner(svc)
    ctx = _make_ctx()
    excluded = planner._compute_excluded_tools(ctx)
    assert "image_generate" not in excluded  # 结构就位，阶段裁剪未生效
    assert ctx.stage_excluded_tools == frozenset() and ctx.stage_note == ""
    assert "当前阶段工具边界" not in _build_with_ctx(ctx, svc)
    assert "当前阶段工具边界" not in _tail_with_ctx(ctx, svc)


def test_stage_note_absent_without_skill(svc):
    """无 Skill 激活：不裁剪不解释（条件单一事实源归 planner）"""
    svc.state_dict["documents"] = []
    planner = _make_planner(svc)
    ctx = _make_ctx(skill="")
    excluded = planner._compute_excluded_tools(ctx)
    assert "storyboard_create_group" not in excluded
    assert ctx.stage_note == ""
    assert "当前阶段工具边界" not in _build_with_ctx(ctx, svc)
    assert "当前阶段工具边界" not in _tail_with_ctx(ctx, svc)


def test_stage_note_standalone_builder_fallback():
    """独立使用 PromptBuilder（不经 planner）：note 缺省为空 → 回退为不注入"""
    from src.video_agent.core.planner import PlannerContext
    from src.video_agent.core.prompt_builder import PromptBuilder
    pb = PromptBuilder(lambda: _StubSkillDocs(), lambda: "proj-snap",
                       lambda: {"keyElements": [], "shots": [], "audioItems": []})
    ctx = PlannerContext(use_studio_context=True, skill_name="快照Skill-A",
                         state_json='{"a": 1}')
    assert "当前阶段工具边界" not in pb.build_system_prompt(ctx)
    assert "当前阶段工具边界" not in pb.build_state_tail_message(ctx)


# ---------- 段落注册表（任务#15 P2：提示词注册制） ----------

def test_prompt_sections_registry_names_and_order():
    """8 个具名段全覆盖，段序与拼装顺序 1:1（保前缀缓存约束）；
    P2-2 段序手术：session_summary 15→65、selected_draft 50→75；
    P2-3 段通道手术：state_json/stage_note/storyboard_progress 移出
    system 段（改经 history 尾部消息注入），不再登记于注册表"""
    from src.video_agent.core.prompt_builder import PROMPT_SECTIONS
    assert [s.name for s in PROMPT_SECTIONS] == [
        "protocol", "catalog", "mcp_catalog", "iron_rules",
        "global_settings", "session_summary", "selected_draft",
        "selected_skill",
    ]
    orders = [s.order for s in PROMPT_SECTIONS]
    assert orders == sorted(orders) and len(set(orders)) == len(orders)


def test_prompt_sections_registry_rejects_duplicates():
    """模块加载期校验语义：重名/重序即 raise"""
    from src.video_agent.core.prompt_builder import (
        PromptSectionSpec,
        _validate_prompt_sections,
    )

    def _noop(pb, ctx):
        return ""

    with pytest.raises(ValueError, match="段名重复"):
        _validate_prompt_sections((
            PromptSectionSpec("dup", 1, _noop), PromptSectionSpec("dup", 2, _noop)))
    with pytest.raises(ValueError, match="段序重复"):
        _validate_prompt_sections((
            PromptSectionSpec("a", 1, _noop), PromptSectionSpec("b", 1, _noop)))


def test_telemetry_section_fields_format_locked(monkeypatch):
    """prompt_sections.jsonl 字段格式锁死：七个字段与现行顺序完全一致
    （消费方 check_prompt_budget.py 零改动；批次E：恒 0 兼容字段
    channels 已清偿）"""
    from src.video_agent.core import live_metrics
    from src.video_agent.core.planner import PlannerContext
    from src.video_agent.core.prompt_builder import PromptBuilder

    captured = {}
    monkeypatch.setattr(live_metrics, "record_sections",
                        lambda pid, sections: captured.update(sections))
    pb = PromptBuilder(lambda: _StubSkillDocs(), lambda: "proj-snap",
                       lambda: {"keyElements": [], "shots": [], "audioItems": []})
    pb.build_system_prompt(PlannerContext(use_studio_context=True,
                                          state_json='{"a": 1}'))
    assert list(captured) == ["protocol", "catalog", "mcp_catalog", "iron_rules",
                              "state", "skill", "total"]
    assert captured["state"] == len('{"a": 1}')
    assert captured["total"] > 0
