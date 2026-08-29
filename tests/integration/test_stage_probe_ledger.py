# -*- coding: utf-8 -*-
"""整改批 3.1 集成回归：账本无自报——8/8 节点客观探针判定。

钉死四件事：
① 结构/分析/规格节点的完成只认状态事实（stage_done 探针链）；
② 评审节点的完成只认账本 DecisionResolved 事件（决议未落账即不完成，
   文档在场也不跳过评审暂停）；
③ turn_commit 的自报 completed_node 不再具有账本效力（sync_run 全量重算
   即被清偿）；
④ frontmatter stages.<key>.done 声明通道对 spec 节点生效（document: 覆盖
   平台探针）。
"""
import pytest

from src.video_agent.core import workflow_runtime as wr
from src.video_agent.core.workflow_events import EventLedger
from src.video_agent.state.manager import StateManager


@pytest.fixture()
def svc(tmp_path):
    StateManager.reset_instance()
    yield StateManager(str(tmp_path))
    StateManager.reset_instance()


def _spec_doc(state, name="Final_Video_Spec.md", content="# 规格\n正文"):
    state.setdefault("documents", []).append(
        {"id": f"doc-{name}", "name": name, "content": content})


def _ke_groups(state):
    state["keyElements"] = [{"id": "g1", "title": "角色", "drafts": []}]


def test_artifact_nodes_probe_chain(svc):
    """分析→规格→三结构节点：产物到位即在账，缺位即不在账（fail-closed）。"""
    st = svc.state_dict
    # 默认 demo 项目自带示例分组：清空后从零验证探针链
    st["keyElements"] = []
    st["shots"] = []
    st["audioItems"] = []
    run = wr.sync_run(st, "剧本生视频需上传剧本")
    assert run["completed_nodes"] == []
    assert run["current_node"] == "analyze_script"

    st["analysis"] = {"summary": "一句话"}
    run = wr.sync_run(st, "剧本生视频需上传剧本")
    assert "analyze_script" in run["completed_nodes"]

    _spec_doc(st)
    _ke_groups(st)
    st["shots"] = [{"id": "s1", "drafts": []}]
    st["audioItems"] = [{"id": "a1", "drafts": []}]
    run = wr.sync_run(st, "剧本生视频需上传剧本")
    assert set(run["completed_nodes"]) == {
        "analyze_script", "collect_spec", "write_spec",
        "storyboard_key_elements", "storyboard_shots", "storyboard_audio"}
    # 两个评审节点未落账决议：不得自动完成，current 停在首个未决评审位
    assert "review_spec" not in run["completed_nodes"]
    assert "review_key_elements" not in run["completed_nodes"]
    assert run["current_node"] == "review_spec"


def test_review_nodes_gated_by_decision_ledger(svc):
    """评审节点：前置产物在场且账本有 DecisionResolved 才在账。"""
    st = svc.state_dict
    st["analysis"] = {"summary": "一句话"}
    _spec_doc(st)
    _ke_groups(st)
    st["shots"] = [{"id": "s1", "drafts": []}]
    st["audioItems"] = [{"id": "a1", "drafts": []}]
    run = wr.sync_run(st, "剧本生视频需上传剧本")
    rid = run["run_id"]
    ledger = EventLedger(st)
    ledger.append("DecisionResolved", run_id=rid, node_id="review_spec",
                  idempotency_key=f"d:{rid}:review_spec",
                  payload={"value": "继续"})
    ledger.append("DecisionResolved", run_id=rid, node_id="review_key_elements",
                  idempotency_key=f"d:{rid}:review_ke",
                  payload={"value": "继续"})
    run = wr.sync_run(st, "剧本生视频需上传剧本")
    assert set(run["completed_nodes"]) >= {
        "review_spec", "review_key_elements", "storyboard_shots",
        "storyboard_audio"}
    assert run["current_node"] == "storyboard_key_elements" or \
        run["status"] in ("ready", "running")


def test_self_report_has_no_ledger_authority(svc):
    """自报清偿：turn_commit 自报 storyboard_audio 完成而产物缺席，
    下一次 sync_run 重算即从账本剔除。"""
    st = svc.state_dict
    st["analysis"] = {"summary": "一句话"}
    _spec_doc(st)
    _ke_groups(st)
    st["shots"] = [{"id": "s1", "drafts": []}]
    run = wr.sync_run(st, "剧本生视频需上传剧本")
    rid = run["run_id"]
    # 模拟历史自报路径：直接往 completed_nodes 塞无证据条目
    run.setdefault("completed_nodes", []).append("storyboard_audio")
    run = wr.sync_run(st, "剧本生视频需上传剧本")
    assert "storyboard_audio" not in run["completed_nodes"], (
        "自报条目残留账本——探针重算未生效")


def test_declaration_channel_covers_spec_stage(svc, tmp_path, monkeypatch):
    """声明通道：stages.spec.done=document:<定制名> 覆盖平台默认探针。"""
    import src.video_agent.web.skill_docs as sd
    from src.video_agent.skill_runtime import frontmatter, registry

    monkeypatch.setattr(sd, "SKILL_DOCS_DIR", tmp_path / "skills")
    registry.reset_registry()
    try:
        sd.save_skill_doc("声明覆盖Skill", "# A\n> 调用规则：测试\n<planner>x</planner>")
        frontmatter.write_manifest("声明覆盖Skill", {
            "name": "声明覆盖Skill", "description": "测试桩",
            "flow": {"stages": {"spec": {"done": "document:定制规格.md"}}}})
        registry.register_skill("声明覆盖Skill")

        st = svc.state_dict
        _spec_doc(st, name="Final_Video_Spec.md")          # 默认名不作数
        run = wr.sync_run(st, "声明覆盖Skill")
        assert "collect_spec" not in run["completed_nodes"]
        assert "write_spec" not in run["completed_nodes"]
        _spec_doc(st, name="定制规格.md")                   # 声明名命中
        run = wr.sync_run(st, "声明覆盖Skill")
        assert {"collect_spec", "write_spec"} <= set(run["completed_nodes"])
    finally:
        registry.reset_registry()
