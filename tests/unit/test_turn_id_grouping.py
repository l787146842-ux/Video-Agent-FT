"""五轮 S2/#2：轮次容器 turn_id 回归（消息流碎片化清偿）。

同轮的正文/文档卡/图片卡共用一个 turn_id：持久化侧（add_chat_message）
与下发侧（done payload）都要携带，前端据此聚合渲染。
"""
from pathlib import Path

import pytest

from src.video_agent.state.manager import StateManager

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture()
def svc(tmp_path):
    StateManager.reset_instance()
    instance = StateManager(str(tmp_path))
    StateManager._instance = instance
    yield instance
    StateManager.reset_instance()


def test_s2_add_chat_message_stores_turn_id(svc):
    svc.add_chat_message("agent", "正文", turn_id="turn-x")
    svc.add_chat_message("agent", "", doc_card="规格.md", turn_id="turn-x")
    svc.add_chat_message("agent", "旧消息无 turnId")
    msgs = svc.state_dict["chatMessages"]
    assert msgs[-3]["turnId"] == "turn-x"
    assert msgs[-2]["turnId"] == "turn-x"
    assert "turnId" not in msgs[-1]  # 未携带时不落键（旧数据兼容）


def test_s2_stream_and_nonstream_paths_carry_turn_id():
    """G4 同类覆盖：流式/非流式两条路径的持久化与 done payload 均带 turn_id"""
    cs = (ROOT / "src/video_agent/web/chat_service.py").read_text(encoding="utf-8")
    # 流式：生成一次、持久化共用、done payload 下发
    # （v2 批2 向导规格卡投影已随用户裁决 2026-08-31 退役删除，D-08 清偿，指纹 -1）
    # （任务 #17 +2：停止路径痕迹消息持久化——有文本正文与无文本轻量气泡
    #  均属同一停止轮，带同轮 turn_id，与既有四处同语义；该两处随任务 #17
    #  收尾抽至 web/stop_manager.py（行数棘轮清偿），故指纹改为两文件合计）
    # （影响面修复批 +1：视频内联预览卡持久化——videoCard 与 imageCard 对称，
    #  done 结算独立条目带同轮 turn_id）
    sm = (ROOT / "src/video_agent/web/stop_manager.py").read_text(encoding="utf-8")
    assert cs.count("turn_id=turn_id") + sm.count("turn_id=turn_id") == 6
    assert '"turn_id": turn_id' in cs
    # 非流式路径同样携带
    assert "turn_id=ns_turn_id" in cs
