"""B1 回归：提示词预算门禁 + 双协议瘦身 + 动作定义唯一源 + 矛盾统一 + F10-1 下沉。

对应审核报告 F5/F6/F7/F8/F9/F10；快照锁语义（Rule 6）。
"""
import asyncio
import json

from src.video_agent.utils.prompts import load_prompt
from src.video_agent.adapters.base_chat import ChatResponse


def test_b1_system_md_under_budget_and_slimmed():
    """F5：system.md ≤7KB 且不再内联动作清单（text_actions.md 为唯一动作定义源）。"""
    from pathlib import Path

    f = Path("prompts/planner/system.md")
    text = f.read_text(encoding="utf-8")
    assert f.stat().st_size <= 7168
    for anchor in ("- add_group:", "- write_document:", "- generate_image:", "```studio-actions"):
        assert anchor not in text


def test_b1_prompt_budget_gate_passes():
    """13.6 预算 CI 门禁：模型可见「严禁/不得」≤8（当前应远低于预算）。"""
    import scripts.check_prompt_budget as gate

    assert gate.main() == 0


def test_b1_system_md_include_expansion():
    """F7：shared 段经 {{include}} 拼装（分身消除，单一事实源）。"""
    text = load_prompt("planner/system.md")
    assert "渐进式披露" in text          # shared/important_rules.md
    assert "结构化短交代" in text                    # shared/output_discipline.md
    assert "看图再动笔" in text or "故事板媒体调用" in text  # shared/media_rules.md


def test_b1_text_actions_deleted_after_44():
    """4-4 双轨退役（ADR-0001）：text_actions.md 文件已删除，
    生成确认拦截语义唯一承载 = FC 工具层闸机（prompt_gates/gen gate）。"""
    from pathlib import Path

    assert not Path("prompts/planner/text_actions.md").exists()


def test_b1_no_text_action_protocol_injected_after_44():
    """4-4：两种协议模式都不再注入文本动作定义；FC 通道仍用 system_fc.md。"""
    from src.video_agent.core.planner import PlannerContext
    from src.video_agent.core.prompt_builder import PromptBuilder

    class _Docs:
        def list_skill_docs(self):
            return []

    builder = PromptBuilder(
        lambda: _Docs(),
        lambda: "proj-test",
        lambda: {},
    )
    ctx = PlannerContext(history=[], use_studio_context=True)
    text_mode = builder.build_system_prompt(ctx, fc_mode=False)
    assert "storyboard_key_elements" not in text_mode  # 文本动作定义已删
    fc_mode = builder.build_system_prompt(ctx, fc_mode=True)
    assert "Tool 优先协议" in fc_mode                   # system_fc.md 注入
    assert "storyboard_key_elements" not in fc_mode


def test_b1_generate_image_once_per_batch():
    """F10-1 下沉：对话内单图工具每批最多一次（prose 禁令 → 工具层计数器）。"""
    from src.video_agent.core.fc_tool_runner import FCToolRunner
    from src.video_agent.tools.base import ToolResult

    class _Stub:
        async def invoke_tool(self, name, args):
            return ToolResult(success=True, data={"image_urls": ["http://x/1.png"]})

    runner = FCToolRunner(_Stub())
    calls = [
        {"id": "c1", "type": "function", "function": {
            "name": "generate_image",
            "arguments": json.dumps({"prompt": "一只猫", "adapter_provider": "mock"})}},
        {"id": "c2", "type": "function", "function": {
            "name": "generate_image",
            "arguments": json.dumps({"prompt": "一只狗", "adapter_provider": "mock"})}},
    ]
    applied, confirmation, _u, _i, _l, _o, tool_results, _d, warnings = asyncio.run(
        runner.execute(ChatResponse(content="", tool_calls=calls))
    )
    assert applied == 1  # 第二个被拦截
    assert any("每轮只调用一次" in str(t.get("error") or "") for t in tool_results)
