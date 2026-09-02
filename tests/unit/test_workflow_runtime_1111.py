# -*- coding: utf-8 -*-
"""1111 黄金轮次契约（宪法 Rule2 主体回归，用户审定裁决钉死；决策史见 git tag adr-archive-20260901）。

对照 tests/fixtures/workflow_1111_baseline.json（修复前基线）断言：
① 轮1 缺剧本 → 正文提醒 + quick-actions 芯片（层 9 兜底，由代码执行不依赖模型自觉；批 B 出槽：不占暂停槽）；
② 轮3 带附件推进 → 交接模型循环（主体回归：模型永远唯一行动主体，
   runtime 不自主执行执行器；stage_precondition 越阶硬闸已随 C1b 裁决 2026-08-31 退役）；
③ 自由提问（无推进信号）→ 交接模型循环（不错抓）；
④ 向导发送 → 机械落盘进产物账本 + 文档卡补落同轮可见；
⑤ read_skill canonical 身份归一（去连字符误差不报错）。
"""
import asyncio
import json
import pathlib

import pytest

SKILL = "AI-短剧一站式生成"
BASELINE = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "workflow_1111_baseline.json"


def _baseline_has_planning_rounds() -> bool:
    """修复前基线含 model_reasoning 规划轮（本文件断言修复后为零）。"""
    data = json.loads(BASELINE.read_text(encoding="utf-8"))
    return any(
        a.get("name") == "model_reasoning"
        for m in data.get("messages") or []
        for s in m.get("traceSteps") or []
        for a in s.get("actions") or []
    )


def test_baseline_records_pre_fix_planning_rounds():
    assert _baseline_has_planning_rounds()


@pytest.mark.asyncio
async def test_attachment_turn_handed_to_model(tmp_path, monkeypatch):
    """② 附件推进轮 → 交接模型循环（主体回归）：模型被调用。
    （原「script_analyze 未被系统代跑」探针已随任务#36 B5 执行器一步
    退役删除：系统代跑路径不复存在，主体回归由探针适配器 calls 钉死。）"""
    from src.video_agent.core.planner import Planner, PlannerContext
    from src.video_agent.state.manager import StateManager
    from src.video_agent.adapters.base_chat import BaseChatAdapter, ChatResponse
    from src.video_agent.tools.manager import ToolManager

    class ProbeAdapter(BaseChatAdapter):
        def __init__(self):
            self.calls = 0

        @property
        def supports_function_calling(self):
            return False

        async def chat(self, messages, **kwargs):
            self.calls += 1
            return ChatResponse(content="收到剧本，我来分析。", finish_reason="stop")

        async def chat_stream(self, messages, **kwargs):
            self.calls += 1
            yield ChatResponse(content="收到剧本，我来分析。", finish_reason="stop")

    StateManager.reset_instance()
    svc = StateManager(str(tmp_path / "ws"))
    StateManager._instance = svc
    svc.state_dict["uploadedDocs"] = [
        {"id": "d1", "name": "剧本.md", "content": "剧本正文：程心苏醒。"}]
    adapter = ProbeAdapter()
    planner = Planner(state_manager=svc, llm_adapter=adapter,
                      tool_manager=ToolManager)
    result = await planner.handle_message(
        "请查看我上传的素材",
        PlannerContext(skill_name=SKILL, advance_signal="attachment"))
    assert adapter.calls >= 1, "主体回归：附件轮必须交接模型（模型是唯一行动主体）"
    assert result.text.strip()
    StateManager.reset_instance()


@pytest.mark.asyncio
async def test_question_turn_handoff_to_model(tmp_path):
    """③ 自由提问（无推进信号）→ 交接模型循环。"""
    from src.video_agent.core.planner import Planner, PlannerContext
    from src.video_agent.state.manager import StateManager
    from src.video_agent.adapters.base_chat import BaseChatAdapter, ChatResponse

    class ProbeAdapter(BaseChatAdapter):
        def __init__(self):
            self.calls = 0

        @property
        def supports_function_calling(self):
            return False

        async def chat(self, messages, **kwargs):
            self.calls += 1
            return ChatResponse(content="我是创作助手。", finish_reason="stop")

        async def chat_stream(self, messages, **kwargs):
            self.calls += 1
            yield ChatResponse(content="我是创作助手。", finish_reason="stop")

    StateManager.reset_instance()
    svc = StateManager(str(tmp_path / "ws"))
    StateManager._instance = svc
    svc.state_dict["uploadedDocs"] = [
        {"id": "d1", "name": "剧本.md", "content": "剧本正文。"}]
    adapter = ProbeAdapter()
    planner = Planner(state_manager=svc, llm_adapter=adapter, tool_manager=None)
    await planner.handle_message(
        "这个剧本讲什么？", PlannerContext(skill_name=SKILL))
    assert adapter.calls >= 1, "提问轮必须交接模型循环"
    StateManager.reset_instance()


# （④ 向导发送→write_spec 节点提交测试已随用户裁决 2026-08-31 退役删除，
# D-08 清偿：_consume_spec_wizard 机械落盘链整体退役。）


@pytest.mark.asyncio
async def test_read_skill_canonical_identity(tmp_path):
    """⑤ 模型名字误差（去连字符）经 canonical 归一不再报错。"""
    from src.video_agent.tools.document_tools import ReadSkillTool

    tool = ReadSkillTool()
    params = tool.get_input_schema()(name="AI短剧一站式生成")
    result = await tool.aexecute(params)
    assert result.success, f"canonical 归一应命中：{result.error}"
    assert (result.data or {}).get("content")
