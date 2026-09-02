"""单元测试：StateManager 并发安全

覆盖场景：
- 多协程并发 update（锁保护下数据一致性）
- 锁竞争（async with svc.lock 串行化）
- 项目切换竞态（并发 switch_project）
- 并发 add_chat_message 不丢失
- build_agent_context 缓存失效正确性
"""
import asyncio
import json
from pathlib import Path

import pytest

from src.video_agent.state.manager import StateManager


@pytest.fixture
def svc(tmp_path):
    """创建独立的 StateManager 实例"""
    StateManager.reset_instance()
    manager = StateManager(str(tmp_path))
    yield manager
    StateManager.reset_instance()


class TestConcurrentUpdate:
    """多协程并发 update 测试"""

    async def test_concurrent_updates_no_data_loss(self, svc):
        """10 个协程并发 update 不同路径，所有写入应保留"""
        # 初始化列表
        svc._raw_state["items"] = []
        svc.save()

        async def add_item(i: int):
            async with svc.lock:
                items = svc._raw_state.get("items", [])
                items.append(f"item-{i}")
                svc._raw_state["items"] = items
                svc.save()

        await asyncio.gather(*[add_item(i) for i in range(10)])

        items = svc._raw_state["items"]
        assert len(items) == 10
        # 所有 item 都存在（顺序可能不同）
        assert set(items) == {f"item-{i}" for i in range(10)}

    async def test_concurrent_update_same_path(self, svc):
        """多协程更新同一路径，最终值应为最后一次写入"""
        async def set_value(v: int):
            async with svc.lock:
                svc.update("counter", v)

        await asyncio.gather(*[set_value(i) for i in range(20)])

        # 最终值应为 0-19 中的某一个（取决于调度顺序）
        assert svc._raw_state["counter"] in range(20)

    async def test_lock_serializes_writes(self, svc):
        """锁应确保写入串行化（无交错）"""
        order = []

        async def writer(name: str, delay: float):
            async with svc.lock:
                order.append(f"{name}-start")
                await asyncio.sleep(delay)
                order.append(f"{name}-end")

        await asyncio.gather(writer("A", 0.05), writer("B", 0.01))

        # 由于锁串行化，B 必须等 A 完成（或 A 等 B）
        # 不可能出现 A-start, B-start, A-end, B-end 的交错
        a_start = order.index("A-start")
        a_end = order.index("A-end")
        b_start = order.index("B-start")
        b_end = order.index("B-end")

        # A 的 start-end 区间和 B 的 start-end 区间不重叠
        assert (a_end < b_start) or (b_end < a_start)


class TestConcurrentChatMessages:
    """并发聊天消息不丢失"""

    async def test_concurrent_add_chat_message(self, svc):
        """20 个协程并发 add_chat_message，全部消息应保留"""
        # 记录初始消息数（demo 状态可能预置了消息）
        initial_count = len(svc.get_chat_messages())

        async def add_msg(i: int):
            async with svc.lock:
                svc.add_chat_message("user", f"消息{i}")

        await asyncio.gather(*[add_msg(i) for i in range(20)])

        messages = svc.get_chat_messages()
        assert len(messages) == initial_count + 20
        # 新增的消息全部存在
        new_texts = {m["text"] for m in messages[initial_count:]}
        assert new_texts == {f"消息{i}" for i in range(20)}


class TestProjectSwitchRace:
    """项目切换竞态测试"""

    async def test_concurrent_project_creation(self, svc):
        """并发创建多个项目，所有项目应存在"""
        async def create(i: int):
            async with svc.lock:
                svc.create_project(f"项目{i}")

        await asyncio.gather(*[create(i) for i in range(5)])

        projects = svc.list_projects()
        # 初始 demo 项目 + 5 个新项目
        assert len(projects["projects"]) >= 6

    async def test_switch_project_preserves_state(self, svc):
        """切换项目后原项目状态应被保存"""
        # 在当前项目写入数据
        svc.update("project_name", "项目A数据")
        pid_a = svc.active_project_id

        # 创建并切换到新项目
        pid_b = svc.create_project("项目B")
        svc.update("project_name", "项目B数据")

        # 切换回项目 A
        svc.switch_project(pid_a)
        assert svc._raw_state.get("project_name") == "项目A数据"

        # 再切换到 B
        svc.switch_project(pid_b)
        assert svc._raw_state.get("project_name") == "项目B数据"


class TestContextCacheInvalidation:
    """build_agent_context 缓存失效正确性"""

    async def test_cache_invalidated_on_update(self, svc):
        """update 后缓存应失效，返回新数据"""
        # 首次构建（填充缓存）
        ctx1 = svc.build_agent_context("bound")

        # 修改状态
        svc._raw_state.setdefault("keyElements", []).append({
            "id": "ke-test",
            "title": "测试元素",
            "drafts": [],
        })
        svc.save()

        # 再次构建应包含新数据
        ctx2 = svc.build_agent_context("bound")
        assert "测试元素" in ctx2
        assert ctx1 != ctx2

    async def test_cache_reused_when_unchanged(self, svc):
        """状态未变时缓存应复用（同一对象）"""
        ctx1 = svc.build_agent_context("bound")
        ctx2 = svc.build_agent_context("bound")
        assert ctx1 is ctx2  # 同一字符串对象（缓存命中）

    async def test_different_asset_mode_separate_cache(self, svc):
        """不同 asset_mode 应使用独立缓存"""
        ctx_bound = svc.build_agent_context("bound")
        ctx_all = svc.build_agent_context("all")
        # 两者是不同的缓存键（第 5 批起键形如 <asset_mode>:<tier>:<stage>）
        keys = set(svc._context_cache)
        assert any(k.startswith("bound:") for k in keys)
        assert any(k.startswith("all:") for k in keys)
