# -*- coding: utf-8 -*-
"""三通道分离 C 回归：「继续」选项由 sidecar 流程机械派生（1111 事故正向修复）。

模型自造「继续故事板拆分」跳过规格阶段 → 下一步 label 改由系统按
sidecar flow.steps + 客观状态推导；阶段边界暂停卡剔除模型继续类选项、
前置系统派生项；规格向导前移到阶段 1 边界（软候选回落）。
"""
import asyncio
import json

from src.video_agent.adapters.base_chat import ChatResponse
from src.video_agent.core import gates_cards, prompt_gates
from src.video_agent.core.fc_tool_runner import FCToolRunner
from src.video_agent.tools.base import ToolResult

_FLOW = {"flow": {"steps": {
    "1": "读取并分析剧本", "2": "写入制作规格", "3": "设计 Storyboard"},
    # v2 批4：阶段短名由 sidecar 声明（平台硬编码退役）
    "step_short_titles": {"1": "剧本分析", "2": "制作规格", "3": "关键元素拆解"}}}


def _register_flow_skill():
    from src.video_agent.skill_runtime import registry, sidecar
    from src.video_agent.web import skill_docs as sd

    sd.save_skill_doc("流程测试", "# 流程测试\n> 调用规则：测试\n")
    sidecar.write_sidecar("流程测试", _FLOW)
    registry.register_skill("流程测试")


def test_current_flow_step_objective_derivation():
    """step1=分析存档；step2=规格文档；无声明=0。"""
    _register_flow_skill()
    state1 = {"analysis": {"summary": "x"}, "documents": []}
    assert gates_cards.current_flow_step(state1, "流程测试") == 1
    state2 = {"analysis": {"summary": "x"}, "documents": [
        {"name": "Final_Video_Spec.md", "content": "画幅：16:9"}]}
    assert gates_cards.current_flow_step(state2, "流程测试") == 2
    assert gates_cards.current_flow_step(state1, "未声明Skill") == 0


def test_system_continue_option_labels():
    """阶段 1 边界 → 「确认，进入『制作规格』」；阶段 2 边界 → 关键元素拆解。"""
    _register_flow_skill()
    opt = gates_cards.system_continue_option(
        {"analysis": {"summary": "x"}, "documents": []}, "流程测试")
    assert opt["label"] == "确认，进入「制作规格」"
    assert opt["value"] == opt["label"]  # 值人类可读（前端向导会拼进用户消息）
    opt2 = gates_cards.system_continue_option(
        {"analysis": {"summary": "x"}, "documents": [
            {"name": "Final_Video_Spec.md", "content": "画幅：16:9"}]},
        "流程测试")
    assert opt2["label"] == "确认，进入「关键元素拆解」"
    # 无 flow 声明 → None（零声明=零预设）
    assert gates_cards.system_continue_option({}, "未声明Skill") is None


def test_flow_continue_note_for_next_turn():
    """用户点选 flow_continue 后回喂模型的机械指令含阶段号与短标题。"""
    _register_flow_skill()
    note = gates_cards.flow_continue_note(
        {"analysis": {"summary": "x"}, "documents": []}, "流程测试")
    assert "阶段 2" in note and "制作规格" in note


class _TM:
    async def invoke_tool(self, name, args):
        return ToolResult(success=True, data={})


def test_boundary_pause_strips_model_continue_and_prepends_system(monkeypatch):
    """v2 批4：阶段边界选项面 = 系统派生唯一入口——
    模型「继续故事板拆分」与调整类选项均直接拒收（不做模糊清洗）。"""
    _register_flow_skill()
    runner = FCToolRunner(tool_manager=_TM())
    monkeypatch.setattr(FCToolRunner, "_raw_state", staticmethod(lambda: {
        "analysis": {"summary": "x"}, "documents": [],
        "usedSkills": ["流程测试"], "interaction": {},
    }))
    response = ChatResponse(content="", tool_calls=[
        {"id": "c1", "type": "function", "function": {
            "name": "script_analyze", "arguments": "{}"}},
        {"id": "c2", "type": "function", "function": {
            "name": "workflow_pause", "arguments": json.dumps({
                "message": "请确认分析结果。",
                "options": [
                    {"label": "分析结果没问题，继续故事板拆分",
                     "description": "进入拆分"},
                    {"label": "需要调整分析", "description": "告诉我修改方向"},
                ],
            })}},
    ])
    res = asyncio.run(runner.execute(response, injected_skill="流程测试"))
    opts = res[5]
    assert opts[0].get("value") == opts[0].get("label") == "确认，进入「制作规格」"
    assert not any("继续故事板拆分" in str(o.get("label")) for o in opts)
    assert not any("需要调整分析" in str(o.get("label")) for o in opts), \
        "边界模型选项直接拒收"


def test_mid_stage_pause_not_decorated(monkeypatch):
    """本批未命中阶段边界（仅 workflow_pause）→ 不挂系统继续选项。"""
    _register_flow_skill()
    runner = FCToolRunner(tool_manager=_TM())
    monkeypatch.setattr(FCToolRunner, "_raw_state", staticmethod(lambda: {
        "analysis": {"summary": "x"}, "documents": [],
        "usedSkills": ["流程测试"], "interaction": {},
    }))
    response = ChatResponse(content="", tool_calls=[
        {"id": "c1", "type": "function", "function": {
            "name": "workflow_pause", "arguments": json.dumps({
                "message": "请确认。",
                "options": [{"label": "继续推进", "description": ""}]})}},
    ])
    res = asyncio.run(runner.execute(response, injected_skill="流程测试"))
    opts = res[5]
    assert not any(
        str(o.get("label") or "").startswith("确认，进入「") for o in opts)
    assert any("继续推进" in str(o.get("label")) for o in opts)


def test_is_flow_continue_value_line_wise():
    """向导多组拼装 value 逐行判定；单组直发/自由打字不命中。"""
    assert gates_cards.is_flow_continue_value("确认，进入「制作规格」")
    assert gates_cards.is_flow_continue_value(
        "确认，进入「制作规格」\n画幅：16:9 横屏\n目标时长：约60秒")
    assert not gates_cards.is_flow_continue_value("需要调整分析")
    assert not gates_cards.is_flow_continue_value("")
    assert not gates_cards.is_flow_continue_value("确认后进入「制作规格」阶段")


def test_spec_wizard_merges_from_soft_candidates_without_spec_doc(monkeypatch):
    """无规格文档但软候选在场（阶段 1 边界）→ 向导合并生效，
    模型自造同 group 选项被标准「键：值」替换。"""
    monkeypatch.setattr(
        prompt_gates, "skill_spec_dimensions", lambda skill: ["画幅"])
    state = {
        "documents": [],
        "usedSkills": ["流程测试"],
        "interaction": {"spec_soft_candidates": {
            "画幅": ["16:9 横屏", "9:16 竖屏"]}},
    }
    _msg, opts, merged = prompt_gates.merge_spec_param_wizard(
        state, "请确认分析结果",
        [{"label": "16:9", "description": "", "group": "画幅"}])
    assert merged
    assert any(o.get("group") == "画幅" and "：" in o.get("label", "")
               for o in opts)
    assert not any(o.get("label") == "16:9" for o in opts)


def test_spec_wizard_still_absent_without_candidates():
    """无规格文档且无软候选（分析未跑）→ 不合并（行为不变）。"""
    state = {"documents": [], "interaction": {}}
    _msg, opts, merged = prompt_gates.merge_spec_param_wizard(
        state, "请确认", [{"label": "x"}])
    assert not merged
    assert opts == [{"label": "x"}]
