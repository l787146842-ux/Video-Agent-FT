# -*- coding: utf-8 -*-
"""整改批 3.1 集成回归：账本无自报——8/8 节点客观探针判定。

钉死四件事：
① 结构/分析/规格节点的完成只认状态事实（stage_done 探针链）；
② 评审节点的完成只认账本 DecisionResolved 事件（决议未落账即不完成，
   文档在场也不跳过评审暂停）；
③ turn_commit 的自报 completed_node 不再具有账本效力（sync_run 全量重算
   即被清偿）；
④ （C1b 裁决 2026-08-31：frontmatter stages.<key>.done 声明通道随机械
   工作流层整体退役——声明忽略，恒走平台探针。）
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


