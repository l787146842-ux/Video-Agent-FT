# -*- coding: utf-8 -*-
"""任务#14：frontmatter flow.stages 数组形态（workflow 结构声明）数据驱动。

钉死：
① schema 门禁（validate_manifest 口径）：非法声明 ERROR 级拒入——
   无探针/review 双缺、未知探针键、review 作首节点、probe+review 并存、
   key 重复、未知子键、空数组、非对象项；dict 覆盖形态语义不变；
② compile_definition 优先从声明派生节点拓扑与标题（标题随声明自带），
   未声明回落 default_v2_workflow（零回归红线）；
③ 运行时探针语义：probe 节点认客观探针；review 节点 = 前置探针在场 +
   账本 DecisionResolved（前置产物在场但未落账决议不予完成，fail-closed）；
④ 注册 fail-hard：非法声明的 Skill 拒注册、workflow 拒入。

夹具：tests/fixtures/flow_stages_decl_sample.md（生产 skill 零改动）。
"""
import pathlib
import shutil

import pytest

from src.video_agent.skill_runtime.manifest_schema import (
    split_issue_warnings,
    validate_manifest_data,
)

FIXTURE = (pathlib.Path(__file__).resolve().parents[1]
           / "fixtures" / "flow_stages_decl_sample.md")
SLUG = "流程声明样例技能"


@pytest.fixture
def declared_skill(tmp_path, monkeypatch):
    from src.video_agent.web import skill_docs as sd
    from src.video_agent.skill_runtime import registry
    from src.video_agent.core import workflow_runtime as wr

    d = tmp_path / "skills"
    (d / SLUG).mkdir(parents=True)
    shutil.copyfile(FIXTURE, d / SLUG / "SKILL.md")
    monkeypatch.setattr(sd, "SKILL_DOCS_DIR", d)
    registry.reset_registry()
    wr.clear_compile_cache()
    registry.sync_all(force=True)
    yield SLUG
    registry.reset_registry()
    wr.clear_compile_cache()


# ---------- ① schema 门禁 ----------

def test_schema_accepts_fixture_decl(declared_skill):
    from src.video_agent.skill_runtime import frontmatter

    manifest = frontmatter.load_manifest(SLUG)
    assert manifest is not None
    errors, _ = split_issue_warnings(validate_manifest_data(manifest))
    assert errors == []


@pytest.mark.parametrize("stages", [
    [{"key": "a", "title": "t"}],                     # 无探针且非 review
    [{"key": "a", "title": "t", "probe": "ghost"}],   # 未知探针键
    [{"key": "a", "title": "t", "review": True}],     # review 作首节点
    [{"key": "a", "title": "t", "probe": "analysis", "review": True}],  # 互斥
    [{"key": "a", "title": "t", "probe": "analysis"},
     {"key": "a", "title": "u", "probe": "spec"}],    # key 重复
    [{"key": "a", "title": "t", "probe": "analysis", "after": "x"}],  # 未知子键
    [],                                               # 空数组
    ["not-an-object"],                                # 非对象项
    [{"key": "", "title": "t", "probe": "analysis"}],  # 空 key
    [{"key": "a", "probe": "analysis"}],              # 缺 title
    [{"key": "a", "title": "t", "probe": "analysis", "deterministic": "yes"}],
    [{"key": "a", "title": "t", "probe": "analysis"},
     {"key": "b", "title": "u", "review": True, "executor": "x"}],  # review 声明 executor
])
def test_schema_rejects_invalid_workflow_stages(stages):
    errors, _ = split_issue_warnings(
        validate_manifest_data({"flow": {"stages": stages}}))
    assert errors, f"非法声明必须 ERROR 级拒入: {stages!r}"


def test_schema_dict_form_override_unchanged():
    """既有 dict 覆盖形态（规范阶段键→done/skip/executors）零影响。"""
    errors, _ = split_issue_warnings(validate_manifest_data(
        {"flow": {"stages": {"assembly": {"skip": True},
                              "spec": {"done": "document:X.md"}}}}))
    assert errors == []


def test_schema_stages_shape_error_mentions_both_forms():
    errors, _ = split_issue_warnings(
        validate_manifest_data({"flow": {"stages": "not-a-container"}}))
    assert errors and "数组" in errors[0]


# ---------- ② compile_definition 数据驱动 ----------

def test_compile_derives_topology_and_titles_from_decl(declared_skill):
    from src.video_agent.core import workflow_runtime as wr

    definition = wr.compile_definition(SLUG)
    assert definition is not None
    assert definition["workflow_id"] == f"skill:{SLUG}"
    nodes = definition["nodes"]
    assert [n["node_id"] for n in nodes] == [
        "draft_script", "review_draft", "finalize_spec"]
    assert [n["title"] for n in nodes] == ["剧本草稿", "草稿评审", "规格定稿"]
    # 线性前置链随声明次序派生
    assert nodes[0]["prerequisites"] == []
    assert nodes[1]["prerequisites"] == ["draft_script"]
    assert nodes[2]["prerequisites"] == ["review_draft"]
    # review 节点 = workflow_pause 暂停；声明执行器/确定性生效
    assert nodes[1]["executor"] == "workflow_pause" and nodes[1]["executors"] == []
    assert nodes[1]["approval_policy"] == {"required": True}
    assert nodes[2]["executor"] == "document_write"
    assert nodes[2]["executors"] == ["document_write"]
    assert nodes[2]["deterministic"] is True


def test_compile_fallback_default_when_undeclared():
    """零回归红线：未声明 flow.stages → 默认 8 节点 + 默认标题表。"""
    from src.video_agent.core import workflow_runtime as wr
    from src.video_agent.skill_runtime import registry

    registry.reset_registry()
    wr.clear_compile_cache()
    try:
        definition = wr.compile_definition("AI-短剧一站式生成")
        assert definition["workflow_id"] == "video_storyboard_v2"
        assert len(definition["nodes"]) == 8
        assert definition["nodes"][0]["node_id"] == "analyze_script"
        assert definition["nodes"][0]["title"] == "剧本分析"
        assert definition["nodes"][3]["title"] == "规格审核"
    finally:
        registry.reset_registry()
        wr.clear_compile_cache()


# ---------- ③ 运行时探针语义（fail-closed） ----------

def test_sync_run_probe_and_review_semantics(declared_skill):
    from src.video_agent.core import workflow_runtime as wr
    from src.video_agent.core.workflow_events import EventLedger

    state = {"usedSkills": [SLUG]}
    run = wr.sync_run(state, SLUG)
    assert run["current_node"] == "draft_script"  # 声明首节点（非 analyze_script）
    assert run["completed_nodes"] == []

    state["analysis"] = {"summary": "草稿摘要。"}
    run = wr.sync_run(state, SLUG)
    assert run["completed_nodes"] == ["draft_script"]
    assert run["current_node"] == "review_draft"

    # fail-closed：前置产物在场但未落账决议 → 评审不予完成
    run = wr.sync_run(state, SLUG)
    assert "review_draft" not in run["completed_nodes"]

    EventLedger(state).append(
        "DecisionResolved", run_id=run["run_id"], node_id="review_draft",
        idempotency_key="k1")
    run = wr.sync_run(state, SLUG)
    assert run["completed_nodes"] == ["draft_script", "review_draft"]
    assert run["current_node"] == "finalize_spec"

    state["documents"] = [{"name": "Final_Video_Spec.md", "content": "x"}]
    run = wr.sync_run(state, SLUG)
    assert run["completed_nodes"][-1] == "finalize_spec"


def test_start_run_input_gate_on_declared_first_node(declared_skill):
    from src.video_agent.core.workflow_runtime import WorkflowRuntime

    rt = WorkflowRuntime({"usedSkills": [SLUG]}, SLUG)
    run = rt.start_run(input_present=False)
    assert run["status"] == "waiting_user"
    assert run["pending_decision"]["node_id"] == "draft_script"


def test_stage_table_ignores_list_decl(declared_skill):
    """阶段裁剪通道只消费 dict 覆盖声明；数组形态不破坏阶段表。"""
    from src.video_agent.core import stage_probes as po

    table = po.stage_table(SLUG)
    assert isinstance(table, list) and table
    assert all(s.key for s in table)


# ---------- ④ 注册 fail-hard ----------

def test_invalid_decl_rejected_at_registration(tmp_path, monkeypatch):
    from src.video_agent.web import skill_docs as sd
    from src.video_agent.skill_runtime import registry
    from src.video_agent.core import workflow_runtime as wr

    d = tmp_path / "skills"
    (d / "bad-flow").mkdir(parents=True)
    (d / "bad-flow" / "SKILL.md").write_text(
        "---\nname: bad-flow\ndescription: 无效声明测试桩\n"
        "flow:\n  stages:\n    - key: a\n      title: t\n---\n"
        "# 坏声明技能\n> 调用规则：测试\n正文", encoding="utf-8")
    monkeypatch.setattr(sd, "SKILL_DOCS_DIR", d)
    registry.reset_registry()
    wr.clear_compile_cache()
    try:
        registry.sync_all(force=True)
        assert registry.resolve_entry("bad-flow") is None, "无探针声明 fail-hard 拒注册"
        assert wr.compile_definition("bad-flow") is None
    finally:
        registry.reset_registry()
        wr.clear_compile_cache()
