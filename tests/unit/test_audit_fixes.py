"""2026-08 全面审计修复回归测试。

覆盖：
- P0-1 多步循环状态 JSON 按轮刷新（state_builder 惰性构建）
- P0-2 非流式 ChatResponse 补齐 image_urls/chat_inserts/action_log 字段
- P0-3 PlannerContext 不再有 extra_system 空转字段
- P1-4 system prompt 顺序：状态 JSON 殿后（利于前缀缓存）
- P1-5 旧轮 read_* 全文回喂压缩
- P1-6 truncate_messages 增量减法语义不变
- P1-8 记忆系统项目维度隔离
- P2-9 快照深拷贝防回写 + 请求幂等槽位
"""
import pytest

from src.video_agent.core.fc_tool_runner import (
    FEEDBACK_COMPRESSED,
    FEEDBACK_MARKER,
    compress_prior_feedback,
    should_compress_feedback,
)
from src.video_agent.core.planner import Planner, PlannerContext
from src.video_agent.core.token_budget import truncate_messages
from src.video_agent.memory.manager import MemoryManager
from src.video_agent.memory.models import MemoryRecord
from src.video_agent.state.manager import StateManager
from src.video_agent.web.chat_service import _acquire_request_slot, _release_request_slot
from src.video_agent.web.routes.agent import ChatResponse


@pytest.fixture
def svc(tmp_path):
    StateManager.reset_instance()
    instance = StateManager(str(tmp_path))
    StateManager._instance = instance
    yield instance
    StateManager.reset_instance()


# ---------- P0-1：状态按轮刷新 ----------

class TestStateRefreshPerStep:
    def test_state_builder_called_each_build(self):
        """state_builder 每次构建 prompt 都重新调用，反映最新状态"""
        planner = Planner()
        box = {"state": '{"version": 1}'}
        ctx = PlannerContext(
            use_studio_context=True,
            state_builder=lambda: box["state"],
        )
        p1 = planner._build_system_prompt(ctx)
        assert '"version": 1' in p1
        # 模拟第一轮执行后状态变更：第二次构建必须看到新状态
        box["state"] = '{"version": 2, "newGroup": "grp-x"}'
        p2 = planner._build_system_prompt(ctx)
        assert '"version": 2' in p2 and "grp-x" in p2
        assert '"version": 1' not in p2

    def test_legacy_state_json_string_still_works(self):
        """旧调用方式（固定字符串）兼容降级不破坏"""
        planner = Planner()
        ctx = PlannerContext(use_studio_context=True, state_json='{"legacy": true}')
        prompt = planner._build_system_prompt(ctx)
        assert '"legacy": true' in prompt

    def test_state_json_is_last_section(self):
        """P1-4：逐轮变化的状态 JSON 殿后，稳定内容构成可缓存前缀"""
        planner = Planner()
        ctx = PlannerContext(
            use_studio_context=True,
            state_builder=lambda: "STATE_AT_TAIL_MARKER",
        )
        prompt = planner._build_system_prompt(ctx)
        assert prompt.endswith("STATE_AT_TAIL_MARKER")
        # 协议段在状态段之前（稳定前缀；audit-0819b：锚点随文本块退役
        # 改钉暂停协议表述，语义不变）
        assert prompt.index("workflow_pause") < prompt.index("STATE_AT_TAIL_MARKER")


# ---------- P0-2：响应模型字段 ----------

def test_chat_response_keeps_media_fields():
    """非流式响应不再被 response_model 静默过滤生图/插入/操作日志字段"""
    resp = ChatResponse(
        text="ok",
        image_urls=["/workspace/assets/a.png"],
        chat_inserts=[{"kind": "image", "url": "/x.png"}],
        action_log=["新建分组「A」"],
    )
    dumped = resp.model_dump()
    assert dumped["image_urls"] == ["/workspace/assets/a.png"]
    assert dumped["chat_inserts"][0]["url"] == "/x.png"
    assert dumped["action_log"] == ["新建分组「A」"]


# ---------- P0-3：extra_system 已移除 ----------

def test_planner_context_has_no_extra_system():
    fields = PlannerContext.__dataclass_fields__
    assert "extra_system" not in fields
    assert "state_builder" in fields


# ---------- P1-5：旧轮回喂压缩 ----------

class TestFeedbackCompression:
    MARKER = FEEDBACK_MARKER

    def test_prior_feedback_compressed(self):
        messages = [
            {"role": "user", "content": "用户原始消息"},
            {"role": "user", "content": self.MARKER + "\n- read_skill：……三万字全文……"},
            {"role": "assistant", "content": "好的"},
        ]
        compress_prior_feedback(messages)
        assert messages[0]["content"] == "用户原始消息"
        assert messages[1]["content"] == FEEDBACK_COMPRESSED
        assert "三万字全文" not in messages[1]["content"]
        assert messages[2]["content"] == "好的"

    def test_non_feedback_messages_untouched(self):
        messages = [{"role": "user", "content": "（系统）第 1 轮的 2 个 Tool 已执行完毕"}]
        compress_prior_feedback(messages)
        assert messages[0]["content"].startswith("（系统）第 1 轮")


# ---------- P1-6：token 截断语义不变 ----------

def test_truncate_messages_semantics():
    system = {"role": "system", "content": "协议" * 10}
    old = [{"role": "user", "content": "历史消息" * 100} for _ in range(10)]
    recent = [{"role": "user", "content": f"最近{i}"} for i in range(4)]
    messages = [system] + old + recent
    out = truncate_messages(messages, max_tokens=300, keep_recent=4)
    # 首条 system 与最近 4 条必保
    assert out[0] is system
    assert out[-4:] == recent
    # 中间旧消息被删除（不是首尾）
    assert len(out) < len(messages)
    for m in old:
        assert m not in out
    # 原列表未被修改
    assert len(messages) == 15


# ---------- P1-8：记忆项目隔离 ----------

@pytest.fixture
def mem(tmp_path):
    return MemoryManager(persist_dir=tmp_path / "memory", backend="json", summary_interval=1)


class TestMemoryProjectIsolation:
    def test_retrieve_filters_other_projects(self, mem):
        mem._store.add(MemoryRecord(
            content="赛博朋克风格短片规划已确认", keywords=["赛博朋克"], project_id="proj-A",
        ))
        # 同项目可见
        assert mem.retrieve("赛博朋克", project_id="proj-A")
        # 跨项目不可见
        assert mem.retrieve("赛博朋克", project_id="proj-B") == []
        # 未指定项目（兼容路径）可见
        assert mem.retrieve("赛博朋克")

    def test_legacy_records_without_project_stay_visible(self, mem):
        mem._store.add(MemoryRecord(content="赛博朋克风格偏好", keywords=["赛博朋克"]))
        assert mem.retrieve("赛博朋克", project_id="any-project")

    async def test_record_dialog_tags_project(self, mem):
        rec = await mem.record_dialog("我要做赛博朋克短片", "好的已规划", project_id="proj-X")
        assert rec is not None and rec.project_id == "proj-X"


# ---------- P2-9：快照深拷贝 + 幂等槽位 ----------

def test_snapshot_deep_copy(svc):
    svc.update("project_name", "原项目名")
    snap = svc.get_full_snapshot()
    snap["project_name"] = "被篡改"
    snap["keyElements"].append({"id": "grp-injected"})
    assert svc.state_dict["project_name"] == "原项目名"
    assert not any(g.get("id") == "grp-injected" for g in svc.state_dict.get("keyElements", []))


def test_request_slot_idempotency():
    rid = "req-test-1"
    assert _acquire_request_slot(rid) is True
    assert _acquire_request_slot(rid) is False  # 处理中重复提交被拒
    _release_request_slot(rid)
    assert _acquire_request_slot(rid) is True   # 完成后可再次提交
    _release_request_slot(rid)
    # 未携 id 恒放行
    assert _acquire_request_slot("") is True
