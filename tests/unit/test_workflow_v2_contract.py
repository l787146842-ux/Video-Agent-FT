# -*- coding: utf-8 -*-
"""Workflow Runtime v2 契约不变量（重构计划批0：schema + reducer 不变量测试）。

钉死（Workflow Runtime v2 契约；决策史见 git tag adr-archive-20260901）：
① 已退役（2026-09-10 阶段规则去代码化批）：WorkflowDefinition / 16 节点 DAG
   契约整链删除，compile_definition 恒 None —— 节点 schema 校验用例同批退役；
② EventLedger：run 内 sequence 单调、幂等键重放返回同事件、载荷冲突报
   EventIdempotencyConflict；
③ commit_turn：同 turn_id 重放幂等（不重复写文档/事件）、run_version 并发
   校验、artifact 文档同事务落 documents+run.artifacts+ArtifactCommitted、
   decision_request → pending_decision+waiting_user、next_transition 推进
   completed_nodes/current_node/StageSucceeded、中途异常状态回滚；
④ WorkflowRuntime：缺原料 start_run → waiting_user+InputRequested；
   resolve_decision 旧 token 拒绝；recover_run 恢复 sequence/status；
⑤ registry.sync_all 非法包不截断批次（Codex 中断1 修复钉死）。
"""
import pytest

from src.video_agent.core.workflow_events import (
    EventIdempotencyConflict,
    EventLedger,
)
from src.video_agent.core.turn_commit import (
    TurnResult,
    WorkflowConcurrencyError,
    commit_turn,
)
from src.video_agent.core.workflow_runtime import WorkflowRuntime


# ---------- ① DAG 契约退役钉死（防复活） ----------

def test_definition_dag_contract_retired():
    """2026-09-10 阶段规则去代码化批：16 节点 DAG 契约整链退役——
    WorkflowDefinition 类族不再存在，compile_definition 恒 None
    （平台不判流程完成；账本按平铺节点清单跑客观探针）。"""
    from src.video_agent.core import workflow_contract, workflow_runtime

    for name in ("WorkflowDefinition", "WorkflowNode", "default_v2_workflow",
                 "WorkflowDefinitionError"):
        assert not hasattr(workflow_contract, name), f"workflow_contract 残留 {name}"
    assert workflow_runtime.compile_definition("任意 Skill") is None


def test_spec_collect_wizard_residual_retired():
    """Q3② 规格收集向导残留清退批（2026-09-20，8888 取证）防复活：
    ① collect_spec「制片规格收集」节点退役——与 write_spec 同探针 "spec"、
       功能重复，且「收集」语义属已退役的规格向导概念（对齐 flova
       「无独立收集阶段、直接写规格」）；
    ② option_groups 兜底归组模块退役——运行时零消费者（group 分页
       交互唯一家 = workflow_pause options 参数描述，2026-09-12 裁决）。"""
    from src.video_agent.core import workflow_contract, workflow_runtime

    # collect_spec 不再出现在任何节点词表/探针映射
    assert "collect_spec" not in workflow_contract.NODE_TITLES
    assert "collect_spec" not in workflow_runtime._FLAT_NODES
    assert "collect_spec" not in workflow_runtime._NODE_PROBE_KEYS
    # write_spec 仍承载 spec 探针（收集与撰写同证同源，删冗余节点不丢探针）
    assert workflow_runtime._NODE_PROBE_KEYS.get("write_spec") == "spec"
    # option_groups 模块已退役（防复活：不得重新引入兜底归组）
    with pytest.raises(ImportError):
        import src.video_agent.core.option_groups  # noqa: F401


# ---------- ② EventLedger ----------

def test_ledger_sequence_monotonic_per_run():
    st = {}
    ledger = EventLedger(st)
    e1 = ledger.append("RunStarted", run_id="r1", idempotency_key="k1")
    e2 = ledger.append("StageStarted", run_id="r1", idempotency_key="k2")
    e3 = ledger.append("RunStarted", run_id="r2", idempotency_key="k3")
    assert (e1.sequence, e2.sequence) == (1, 2)
    assert e3.sequence == 1  # 跨 run 独立计数


def test_ledger_idempotent_replay_same_payload():
    st = {}
    ledger = EventLedger(st)
    e1 = ledger.append("ToolSucceeded", run_id="r1", idempotency_key="k",
                       payload={"a": 1})
    e2 = ledger.append("ToolSucceeded", run_id="r1", idempotency_key="k",
                       payload={"a": 1})
    assert e1.event_id == e2.event_id
    assert len(st["workflow_events"]) == 1


def test_ledger_idempotency_conflict_on_payload_diff():
    st = {}
    ledger = EventLedger(st)
    ledger.append("ToolSucceeded", run_id="r1", idempotency_key="k",
                  payload={"a": 1})
    with pytest.raises(EventIdempotencyConflict):
        ledger.append("ToolSucceeded", run_id="r1", idempotency_key="k",
                      payload={"a": 2})


# ---------- ③ commit_turn ----------

def test_commit_turn_idempotent_replay():
    st = {}
    c1 = commit_turn(st, TurnResult(turn_id="t1", body="hi",
                                    artifacts=[{"name": "a.md", "kind": "document",
                                                "content": "x"}]), persist=False)
    docs = len(st["documents"])
    events = len(st["workflow_events"])
    c2 = commit_turn(st, TurnResult(turn_id="t1", body="hi",
                                    artifacts=[{"name": "a.md", "kind": "document",
                                                "content": "x"}]), persist=False)
    assert c2.idempotent is True
    assert len(st["documents"]) == docs
    assert len(st["workflow_events"]) == events
    assert c1.run["run_version"] == c2.run["run_version"]


def test_commit_turn_version_concurrency():
    st = {}
    commit_turn(st, TurnResult(turn_id="t1", body="a"), persist=False)
    with pytest.raises(WorkflowConcurrencyError):
        commit_turn(st, TurnResult(turn_id="t2", body="b", run_version=0),
                    persist=False)


def test_commit_turn_artifact_and_transition():
    st = {}
    c = commit_turn(st, TurnResult(
        turn_id="t1", body="分析完成",
        artifacts=[{"name": "analysis.json", "kind": "artifact"}],
        next_transition={"completed_node": "analyze_script",
                         "next_node": "write_spec"}), persist=False)
    run = st["workflow_run"]
    assert "analyze_script" in run["completed_nodes"]
    assert run["current_node"] == "write_spec"
    assert "analysis.json" in run["artifacts"]
    types = [e.event_type for e in c.events]
    assert "ArtifactCommitted" in types and "StageSucceeded" in types \
        and types[-1] == "TurnCommitted"


def test_commit_turn_decision_opens_waiting_user():
    st = {}
    c = commit_turn(st, TurnResult(
        turn_id="t1", body="请确认",
        decision_request={"token": "tok1", "prompt": "确认？",
                          "options": [{"value": "yes"}, {"value": "no"}]}),
        persist=False)
    assert st["workflow_run"]["status"] == "waiting_user"
    assert st["workflow_run"]["pending_decision"]["token"] == "tok1"
    assert any(e.event_type == "DecisionOpened" for e in c.events)


def test_commit_turn_rolls_back_on_conflict_inside():
    st = {}
    # 预置同幂等键不同载荷：commit 内部 ledger append 将冲突 → 状态回滚
    EventLedger(st).append("ToolSucceeded", run_id="run_x",
                           idempotency_key="t9:timeline:0", payload={"x": 1})
    st["workflow_run"] = {"run_id": "run_x"}
    with pytest.raises(EventIdempotencyConflict):
        commit_turn(st, TurnResult(turn_id="t9", body="boom",
                                   timeline_events=[{"event_type": "ToolSucceeded",
                                                     "payload": {"x": 2}}]),
                    persist=False)
    # 回滚钉死：冲突事件的载荷未写入、turn 未登记
    assert len(st["workflow_events"]) == 1
    assert not any(isinstance(t, dict) and t.get("turn_id") == "t9"
                   for t in st.get("workflow_turns") or [])


# ---------- ④ WorkflowRuntime ----------

def test_runtime_start_run_waiting_user_without_input():
    st = {"usedSkills": ["AI-短剧一站式生成"]}
    rt = WorkflowRuntime(st, "AI-短剧一站式生成")
    run = rt.start_run(input_present=False)
    assert run["status"] == "waiting_user"
    assert run["pending_decision"]
    ledger = EventLedger(st)
    types = [e.event_type for e in ledger.by_run(run["run_id"])]
    assert "RunStarted" in types and "InputRequested" in types


def test_runtime_resolve_decision_rejects_stale_token():
    st = {}
    rt = WorkflowRuntime(st, "AI-短剧一站式生成")
    run = rt.start_run(input_present=False)
    from src.video_agent.core.turn_commit import WorkflowCommitError
    with pytest.raises(WorkflowCommitError):
        rt.resolve_decision("wrong-token", "yes")


def test_runtime_recover_run_restores_sequence_and_status():
    st = {}
    rt = WorkflowRuntime(st, "AI-短剧一站式生成")
    run = rt.start_run(input_present=False)
    seq = run["event_sequence"]
    st["workflow_run"]["event_sequence"] = 0  # 模拟旧视图
    rec = rt.recover_run()
    assert rec["event_sequence"] == seq
    assert rec["status"] == "waiting_user"


# ---------- ⑤ 注册隔离 ----------

def test_sync_run_backfills_legacy_run_without_clearing():
    """重构计划批4：在途旧 run 一次性导入——新字段补齐，
    artifacts/completed_nodes 不清空（禁止 clear 式回滚）。"""
    from src.video_agent.core import workflow_runtime

    st = {"workflow_run": {"run_id": "run_old", "current_node": "analyze_script",
                           "completed_nodes": ["analyze_script"],
                           "artifacts": ["a.md"]},
          "usedSkills": ["AI-短剧一站式生成"]}
    run = workflow_runtime.sync_run(st, "AI-短剧一站式生成")
    assert run["artifacts"] == ["a.md"]
    for key in ("run_version", "event_sequence", "status"):
        assert key in run, f"旧 run 缺字段补齐: {key}"


def test_alias_collision_rejected_at_registration(tmp_path, monkeypatch):
    """计划§6：归一碰撞 = 配置错误——同身份第二个文件拒注册。"""
    from src.video_agent.web import skill_docs as sd
    from src.video_agent.skill_runtime import registry

    d = tmp_path / "skills"
    # 批3 单一包形态：<slug>/SKILL.md（name/description 注册期必填）
    for slug, h1 in (("AI-短剧一站式生成", "# A"), ("AI短剧一站式生成", "# B")):
        pkg = d / slug
        pkg.mkdir(parents=True)
        (pkg / "SKILL.md").write_text(
            f"---\nname: {slug}\ndescription: 测试桩\n---\n"
            f"{h1}\n> 调用规则：测试\n正文", encoding="utf-8")
    monkeypatch.setattr(sd, "SKILL_DOCS_DIR", d)
    registry.reset_registry()
    try:
        registry.sync_all(force=True)
        entries = set()
        for slug in ("AI-短剧一站式生成", "AI短剧一站式生成"):
            e = registry.resolve_entry(slug)
            if e is not None:
                entries.add(e.slug)
        assert entries == {"AI-短剧一站式生成"}, "碰撞者拒注册"
    finally:
        registry.reset_registry()


def test_invalid_manifest_rejected_from_workflow(tmp_path, monkeypatch):
    """计划§1/§6：无效 frontmatter 声明不得进入运行时。

    （2026-09-10 阶段规则去代码化批：DAG 编译退役、compile_definition 恒 None，
    「驱动 workflow」这一入口已不复存在 ⇒ 本用例改钉**注册期门禁**这一唯一
    入口：零声明合法放行、白名单外闸键/已废除流程抄本键一律拒收。）"""
    from src.video_agent.core import workflow_runtime
    from src.video_agent.skill_runtime import frontmatter, registry
    from src.video_agent.web import skill_docs as sd

    slug = "门禁技能"
    d = tmp_path / "skills"
    d.mkdir()
    monkeypatch.setattr(sd, "SKILL_DOCS_DIR", d)
    sd.save_skill_doc(
        slug,
        f"---\nname: {slug}\ndescription: 测试桩\n---\n"
        "# 门禁技能\n> 调用规则：测试\n正文")
    registry.reset_registry()
    try:
        registry.sync_all(force=True)
        workflow_runtime.clear_compile_cache()
        # 零声明合法：注册期门禁放行 + Skill 已注册可用
        assert frontmatter.validate_manifest(
            {"name": slug, "description": "测试桩"}) == []
        assert registry.resolve_entry(slug) is not None
        # DAG 编译退役：任何 Skill 都不再驱动 workflow（恒 None）
        assert workflow_runtime.compile_definition(slug) is None
        # 注入非法声明（白名单外闸键 + 已废除流程抄本键）→ 注册期门禁拒绝
        issues = frontmatter.validate_manifest({
            "name": slug, "description": "测试桩",
            "gates": {"unknown_gate": True},
            "flow": {"steps": {"1": "a"}}})
        assert issues, "非法声明必须被注册期门禁拒绝"
    finally:
        registry.reset_registry()


def test_sync_all_skips_invalid_file_without_aborting_batch(tmp_path, monkeypatch):
    from src.video_agent.web import skill_docs as sd
    from src.video_agent.skill_runtime import registry

    d = tmp_path / "skills"
    # 批3 单一包形态：<slug>/SKILL.md；name/description 注册期必填
    good = d / "good"
    good.mkdir(parents=True)
    (good / "SKILL.md").write_text(
        "---\nname: good\ndescription: 测试桩\n---\n"
        "# 好技能\n> 调用规则：测试\n正文", encoding="utf-8")
    # 非法标识（含空格/特殊字符的 slug 由包目录名带入）→ _load_entry 校验失败
    bad = d / "bad slug!"
    bad.mkdir()
    (bad / "SKILL.md").write_text("# x", encoding="utf-8")
    monkeypatch.setattr(sd, "SKILL_DOCS_DIR", d)
    registry.reset_registry()
    try:
        registry.sync_all(force=True)
        assert registry.resolve_entry("good") is not None
    finally:
        registry.reset_registry()
