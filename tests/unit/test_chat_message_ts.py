# -*- coding: utf-8 -*-
"""消息时间戳持久化（任务 #17 W1）。

钉死契约：
1. StateManager.add_chat_message 落盘写入 ts（epoch ms 整数）；
2. 历史装载透传带回：get_chat_messages / get_full_snapshot /
   list_conversations 活跃对话消息原样携带 ts（前端悬停工具条 HH:MM 的数据源）。
"""
import time

import pytest

from src.video_agent.state.manager import StateManager


@pytest.fixture
def svc(tmp_path):
    StateManager.reset_instance()
    instance = StateManager(str(tmp_path / "ws"))
    # 清空 demo 预置消息，保证用例从空对话起步
    del instance.get_chat_messages()[:]
    instance.save()
    StateManager._instance = instance
    yield instance
    StateManager.reset_instance()


def test_add_chat_message_writes_ts_epoch_ms(svc):
    before = int(time.time() * 1000)
    svc.add_chat_message("user", "你好")
    svc.add_chat_message("agent", "你好，我在", model_name="mock")
    msgs = svc.get_chat_messages()
    for entry in msgs[-2:]:
        ts = entry.get("ts")
        assert isinstance(ts, int), "ts 必须为整数（epoch ms）"
        # 允许少量时钟余量，只钉「当下时刻」量级而非历史/未来值
        assert before - 1000 <= ts <= int(time.time() * 1000) + 1000


def test_ts_passthrough_on_history_load(svc):
    """快照/对话装载路径原样带回 ts（前端历史消息工具条显示时间的依据）。"""
    svc.add_chat_message("user", "第一问")
    expected = svc.get_chat_messages()[-1]["ts"]
    # 全量快照（刷新/replay 恢复路径）
    snap = svc.get_full_snapshot()
    assert snap["chatMessages"][-1]["ts"] == expected
    # 活跃对话消息（对话切换装载路径）
    convs = svc.list_conversations()
    active = next(
        c for c in convs["conversations"]
        if c["id"] == convs["active_conversation_id"]
    )
    assert active["messages"][-1]["ts"] == expected
