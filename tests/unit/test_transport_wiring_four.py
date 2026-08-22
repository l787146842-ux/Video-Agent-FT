"""B0 批次回归：P0 接线四件（doc_written 四段链 / guidance 注册 / FC warnings / fallback 载荷）。

对应审核报告 F1/F2/F3/F4；每处修复钉死一条回归用例（宪法 §十）。
"""
import asyncio
import json

from src.video_agent.core.fc_tool_runner import FCToolRunner
from src.video_agent.core.sse_events import SSE_DOC_WRITTEN
from src.video_agent.adapters.base_chat import ChatResponse
from src.video_agent.tools.base import ToolResult
from src.video_agent.state.models import CAT_KEY_ELEMENTS


class _StubToolManager:
    """document_write 等工具的成功桩（F1 测试用）。"""

    def __init__(self) -> None:
        self.calls = []

    async def invoke_tool(self, name, args):
        self.calls.append(name)
        return ToolResult(success=True, data={})


def _fc_response(tool_name: str, arguments: dict) -> ChatResponse:
    return ChatResponse(content="", tool_calls=[
        {"id": "c1", "type": "function", "function": {
            "name": tool_name, "arguments": json.dumps(arguments, ensure_ascii=False)}},
    ])


def test_b0_f1_doc_written_emitted_on_fc_document_write(monkeypatch):
    """F1：FC 轨文档写入成功即发射 doc_written（3333 修复四段链第一段）。"""
    monkeypatch.setattr(FCToolRunner, "_raw_state", staticmethod(lambda: {}))
    runner = FCToolRunner(_StubToolManager())
    events = []

    async def collect(ev):
        events.append(ev)

    applied, *_rest = asyncio.run(
        runner.execute(
            _fc_response("document_write", {"name": "大纲.md", "content": "标题：测试"}),
            on_event=collect,
            # §2.7 预期收紧：document_write 属 high，gate_override="all" 模拟用户一次性同意
            gate_override="all",
        )
    )
    assert applied == 1
    doc_events = [e for e in events if e.get("type") == SSE_DOC_WRITTEN]
    assert doc_events == [{"type": SSE_DOC_WRITTEN, "name": "大纲.md"}]


def test_b0_f3_fc_gate_warnings_returned_in_tuple(monkeypatch):
    """F3：FC 轨闸机拦截文案随 execute 返回值外发（双轨可见性对齐）。"""
    state = {
        CAT_KEY_ELEMENTS: [{
            "id": "ke-1", "title": "Element_主角",
            "drafts": [{"id": "d1", "label": "概念图", "prompt": "一个角色", "tag": "Agent"}],
        }],
        # audit-0819e：结构三类就位，阶段前置闸放行生成类工具
        "shots": [{"id": "s1", "title": "镜1", "drafts": []}],
        "audioItems": [{"id": "a1", "title": "音1", "drafts": []}],
    }
    monkeypatch.setattr(FCToolRunner, "_raw_state", staticmethod(lambda: state))
    runner = FCToolRunner(_StubToolManager())
    applied, confirmation, _urls, _inserts, _log, _opts, _results, docs, warnings, _overflow = asyncio.run(
        runner.execute(
            _fc_response("image_generate", {"target": "all_keyElements"}),
            injected_skill="测试技能",
        )
    )
    assert applied == 0
    assert confirmation == ""
    assert docs == []
    assert any("生成确认闸拦截" in w for w in warnings)


def test_b0_f3_fc_warnings_flow_into_handle_fc_response(monkeypatch):
    """F3：planner._handle_fc_response 把 execute 的 warnings 合并进 collector。"""
    from src.video_agent.core.planner import Planner

    planner = Planner.__new__(Planner)

    async def fake_execute(*_a, **_k):
        return 0, "", [], [], [], [], [], [], ["警告A"], ""

    monkeypatch.setattr(planner, "_execute_fc_tools", fake_execute)
    collector = []
    asyncio.run(planner._handle_fc_response(
        _fc_response("document_write", {"name": "x.md", "content": "c"}),
        fc_warnings_collector=collector,
    ))
    assert collector == ["警告A"]


def test_b0_f4_fallback_retired_by_ruling():
    """F4 退役锁（用户裁决 2026-08-20）：聊天链路单一候选、不自动换厂商；
    _fallback_switch_payload 已自 chat_service 删除"""
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    src = (root / "src/video_agent/web/chat_service.py").read_text(encoding="utf-8")
    assert "_fallback_switch_payload" not in src.replace("（_fallback_candidates/_fallback_switch_payload/_is_retryable_adapter_error）", "")
    assert "candidates = [(body.provider, body.model)]" in src


def test_b0_f2_guidance_register_drain_clear():
    """F2：排队消息登记/消费/清空（轮间注入的服务端队列语义）。"""
    from src.video_agent.web.agent_task_manager import get_agent_task_manager

    async def main():
        tm = get_agent_task_manager()

        async def noop_worker():
            return None

        tm.create("p-test", noop_worker, task_id="b0-guidance-test")
        assert tm.add_pending_guidance("b0-guidance-test", {"id": "q1", "text": "继续"})
        assert tm.drain_pending_guidance("b0-guidance-test") == [{"id": "q1", "text": "继续"}]
        assert tm.drain_pending_guidance("b0-guidance-test") == []  # 单次消费
        tm.stop("b0-guidance-test")
        assert not tm.add_pending_guidance("b0-guidance-test", {"id": "q2", "text": "x"})
        tm.clear_pending_guidance("b0-guidance-test")

    asyncio.run(main())


def test_b0_f2_guidance_rejects_duplicate_id():
    """F2：同 id 重复登记被拒绝（防双注入）。"""
    from src.video_agent.web.agent_task_manager import get_agent_task_manager

    async def main():
        tm = get_agent_task_manager()

        async def noop_worker():
            return None

        tm.create("p-test", noop_worker, task_id="b0-guidance-dup")
        assert tm.add_pending_guidance("b0-guidance-dup", {"id": "q1", "text": "a"})
        assert not tm.add_pending_guidance("b0-guidance-dup", {"id": "q1", "text": "b"})
        tm.stop("b0-guidance-dup")

    asyncio.run(main())
