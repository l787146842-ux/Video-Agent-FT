"""P1-9 回归：防抖落盘合并 + flush_save 冲刷 + 同步上下文退化 + 聊天记录截断"""
import asyncio

import pytest

from src.video_agent.state.manager import StateManager


@pytest.fixture
def svc(tmp_path):
    StateManager.reset_instance()
    instance = StateManager(str(tmp_path))
    StateManager._instance = instance
    yield instance
    StateManager.reset_instance()


def _read_project_state(tmp_path, svc) -> dict:
    """任务 #18 / P10：落盘校验改经 repo 接口读回（后端无关：
    json 读 state.json / sqlite 读唯一事实源），断言强度不变。"""
    return svc._repo.load_project(svc.active_project_id)


class TestSaveDebounce:
    async def test_debounced_save_coalesces_and_persists(self, svc, tmp_path):
        """窗口内多次变更合并，窗口过后数据完整落盘"""
        svc.add_chat_message("user", "第一条")
        svc.add_chat_message("agent", "第二条")
        assert svc._save_dirty  # 已标记待落盘但未立即写盘
        await asyncio.sleep(0.5)  # 超过 0.3s 防抖窗口
        assert not svc._save_dirty
        data = _read_project_state(tmp_path, svc)
        texts = [m["text"] for m in data["chatMessages"]]
        assert "第一条" in texts
        assert "第二条" in texts

    async def test_flush_save_writes_immediately(self, svc, tmp_path):
        """flush_save 立即冲刷挂起变更，不等防抖窗口"""
        svc.add_chat_message("user", "紧急消息")
        svc.flush_save()
        data = _read_project_state(tmp_path, svc)
        assert any(m["text"] == "紧急消息" for m in data["chatMessages"])
        # 冲刷后无挂起任务
        assert svc._save_flush_task is None or svc._save_flush_task.done()

    def test_sync_context_falls_back_to_immediate_save(self, svc, tmp_path):
        """无运行中事件循环时 save_debounced 退化为同步立即落盘"""
        svc.add_chat_message("user", "同步消息")  # 同步上下文调用
        data = _read_project_state(tmp_path, svc)
        assert any(m["text"] == "同步消息" for m in data["chatMessages"])

    async def test_save_async_persists_off_loop(self, svc, tmp_path):
        """save_async 立即落盘（worker 线程执行）"""
        svc.state_dict["marker"] = "async-save"
        await svc.save_async()
        data = _read_project_state(tmp_path, svc)
        assert data.get("marker") == "async-save"

    def test_chat_history_truncated_at_limit(self, svc):
        """聊天记录超过 200 条自动截断最旧消息"""
        for i in range(210):
            svc.add_chat_message("user", f"msg-{i}")
        msgs = svc.get_chat_messages()
        assert len(msgs) == 200
        assert msgs[-1]["text"] == "msg-209"
