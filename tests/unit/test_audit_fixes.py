"""2026-08 全面审计修复回归测试。

覆盖：
- P0-1 多步循环状态 JSON 按轮刷新（state_builder 惰性构建）
- P0-2 非流式 ChatResponse 补齐 image_urls/chat_inserts/action_log 字段
- P0-3 PlannerContext 不再有 extra_system 空转字段
- P1-4/P2-3 状态上下文出 system：history 尾部消息注入，system 字节跨步稳定
- P1-5 旧轮 read_* 全文回喂压缩
- P1-6 truncate_messages 增量减法语义不变
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
        """state_builder 每次构建都重新调用，反映最新状态（P2-3 后状态经
        history 尾部消息注入）；且 system 本体字节在状态变化时保持稳定"""
        planner = Planner()
        box = {"state": '{"version": 1}'}
        ctx = PlannerContext(
            use_studio_context=True,
            state_builder=lambda: box["state"],
        )
        p1 = planner._build_system_prompt(ctx)
        t1 = planner._prompt_builder.build_state_tail_message(ctx)
        assert '"version": 1' in t1          # 模型仍可见状态（尾部消息）
        assert '"version": 1' not in p1       # 状态不再进 system 段
        # 模拟第一轮执行后状态变更：尾部消息必须看到新状态，
        # system 本体字节逐字节不变（供应商前缀缓存命中前提）
        box["state"] = '{"version": 2, "newGroup": "grp-x"}'
        p2 = planner._build_system_prompt(ctx)
        t2 = planner._prompt_builder.build_state_tail_message(ctx)
        assert '"version": 2' in t2 and "grp-x" in t2
        assert '"version": 1' not in t2
        assert p1 == p2

    def test_legacy_state_json_string_still_works(self):
        """旧调用方式（固定字符串）兼容降级不破坏：经尾部消息可见"""
        planner = Planner()
        ctx = PlannerContext(use_studio_context=True, state_json='{"legacy": true}')
        prompt = planner._build_system_prompt(ctx)
        assert '"legacy": true' not in prompt
        tail = planner._prompt_builder.build_state_tail_message(ctx)
        assert '"legacy": true' in tail

    def test_state_json_out_of_system_into_tail(self):
        """P1-4/P2-3：逐轮变化的状态 JSON 不再殿后于 system，改以 history 尾部
        消息注入（近生成端，遵循度最高）；system（含 Skill 块）成跨步稳定前缀"""
        planner = Planner()
        ctx = PlannerContext(
            use_studio_context=True,
            state_builder=lambda: "STATE_AT_TAIL_MARKER",
        )
        prompt = planner._build_system_prompt(ctx)
        assert "STATE_AT_TAIL_MARKER" not in prompt
        tail = planner._prompt_builder.build_state_tail_message(ctx)
        assert tail.endswith("STATE_AT_TAIL_MARKER")
        # 协议段仍在 system（稳定前缀；audit-0819b：锚点随文本块退役
        # 改钉暂停协议表述，语义不变）
        assert "workflow_pause" in prompt


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
        """多条回喂：除最近 keep_recent 条外压缩（批 3.4 近因保护，
        默认 keep_recent=2 → 三条中最早一条被压缩）。"""
        messages = [
            {"role": "user", "content": "用户原始消息"},
            {"role": "user", "content": self.MARKER + "\n- read_skill：……最早轮三万字全文……"},
            {"role": "assistant", "content": "好的"},
            {"role": "user", "content": self.MARKER + "\n- read_uploaded_doc：中间全文。"},
            {"role": "assistant", "content": "继续"},
            {"role": "user", "content": self.MARKER + "\n- read_project_doc：最新全文。"},
        ]
        compress_prior_feedback(messages)
        assert messages[0]["content"] == "用户原始消息"
        assert messages[1]["content"] == FEEDBACK_COMPRESSED
        assert "三万字全文" not in str(messages[1]["content"])
        # 最近两条回喂受近因保护，全文保留
        assert "中间全文" in str(messages[3]["content"])
        assert "最新全文" in str(messages[5]["content"])

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


def test_truncate_messages_keeps_fc_pair_atomic():
    """批 3.4 钉死：del_end 轮组原子边界——FC 配对（assistant.tool_calls +
    系统回喂）整组删除或整组保留，绝不劈半（拆半边会被供应商 400）。"""
    from src.video_agent.core.token_budget import truncate_messages

    system = {"role": "system", "content": "协议"}

    def group(i):
        return [
            {"role": "user", "content": f"真实用户输入 {i}"},
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": f"call-{i}", "type": "function",
                 "function": {"name": "read_skill", "arguments": "{}"}}]},
            {"role": "user", "content": f"（系统）第 {i} 轮 read_skill 全文回喂"},
        ]

    recent_tail = [
        {"role": "user", "content": "最新真实请求"},
        {"role": "assistant", "content": "最终回复"},
    ]
    messages = [system]
    for i in range(8):
        messages.extend(group(i))
    messages.extend(recent_tail)

    out = truncate_messages(messages, max_tokens=200, keep_recent=2)
    assert len(out) < len(messages), "压力不足：截断未触发，用例失去意义"
    for idx, m in enumerate(out):
        if m.get("role") == "assistant" and m.get("tool_calls"):
            nxt = out[idx + 1] if idx + 1 < len(out) else None
            assert (
                nxt is not None and nxt.get("role") == "user"
                and str(nxt.get("content") or "").startswith("（系统）")
            ), f"FC 配对被劈半 @ index {idx}"
    # 不存在「真实用户 + 回喂」而缺中间 tool_calls 半边的残组：
    # 每个保留的真实用户轮，其后要么紧跟新 assistant 轮，要么紧跟其回喂
    for idx, m in enumerate(out[:-1]):
        if (m.get("role") == "user"
                and not str(m.get("content") or "").startswith("（系统）")):
            nxt = out[idx + 1]
            assert nxt.get("role") in ("assistant", "user"), (
                f"轮组边界异常 @ index {idx}: {nxt}")


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
