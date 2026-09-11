# -*- coding: utf-8 -*-
"""三通道分离 C 回归：「继续」选项由 Skill 流程声明机械派生（1111 事故正向修复）。

模型自造「继续故事板拆分」跳过规格阶段 → 下一步 label 改由系统按
流程声明（steps 消费通道仅存于内存 manifest：生产 frontmatter 已废除
该键，正文 planner 是唯一流程源） + 客观状态推导；阶段边界暂停卡剔除
模型继续类选项、前置系统派生项；规格向导前移到阶段 1 边界（软候选回落）。
"""
import asyncio
import json

from src.video_agent.adapters.base_chat import ChatResponse
from src.video_agent.core import gates_cards, prompt_gates
from src.video_agent.core.fc_tool_runner import FCToolRunner
from src.video_agent.tools.base import ToolResult

_FLOW = {"flow": {"steps": {
    "1": "读取并分析剧本", "2": "写入制作规格", "3": "设计 Storyboard"},
    # v2 批4：阶段短名由声明驱动（平台硬编码退役）
    "step_short_titles": {"1": "剧本分析", "2": "制作规格", "3": "关键元素拆解"}}}


def _register_flow_skill(monkeypatch):
    """注册零声明文档条目，流程声明经内存 manifest 注入（steps 消费
    通道保留于编排器/闸机通用代码；生产 frontmatter 声明 steps = fail-hard）。"""
    from src.video_agent.skill_runtime import registry
    from src.video_agent.web import skill_docs as sd

    sd.save_skill_doc(
        "流程测试",
        "---\nname: 流程测试\ndescription: 测试桩\n---\n"
        "# 流程测试\n> 调用规则：测试\n")
    registry.register_skill("流程测试")
    monkeypatch.setattr(
        registry, "skill_manifest_of",
        lambda name: _FLOW if name == "流程测试" else None)


def test_current_flow_step_objective_derivation(monkeypatch):
    """step1=分析存档；step2=规格文档；无声明=0。"""
    _register_flow_skill(monkeypatch)
    state1 = {"analysis": {"summary": "x"}, "documents": []}
    assert gates_cards.current_flow_step(state1, "流程测试") == 1
    state2 = {"analysis": {"summary": "x"}, "documents": [
        {"name": "Final_Video_Spec.md", "content": "画幅：16:9"}]}
    assert gates_cards.current_flow_step(state2, "流程测试") == 2
    assert gates_cards.current_flow_step(state1, "未声明Skill") == 0


def test_flow_continue_note_for_next_turn(monkeypatch):
    """用户点选 flow_continue 后回喂模型的机械指令含阶段号与短标题。"""
    _register_flow_skill(monkeypatch)
    note = gates_cards.flow_continue_note(
        {"analysis": {"summary": "x"}, "documents": []}, "流程测试")
    assert "阶段 2" in note and "制作规格" in note


class _TM:
    async def invoke_tool(self, name, args):
        return ToolResult(success=True, data={})

    def get_tool(self, name):
        """确认闸双保险（ctx.tool_risk_of 经 get_tool().risk 读数）的最小桩：
        桩内工具一律声明 low（只读桩）。"""
        return type("_StubTool", (), {"risk": "low"})


def test_boundary_pause_keeps_model_options_only(monkeypatch):
    """2026-09-10 阶段规则去代码化批：阶段边界系统派生「继续」项退役——
    平台不再判阶段完成，无边界可派生；选项面 = 模型选项原样保留。"""
    _register_flow_skill(monkeypatch)
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
    labels = [str(o.get("label")) for o in opts]
    # 系统派生「继续」项不再出现
    assert not any(l.startswith("确认，进入「") for l in labels)
    # 模型选项原样保留（顺序不变）
    assert labels[0].startswith("分析结果没问题")
    assert any("需要调整分析" in l for l in labels)


def test_mid_stage_pause_not_decorated(monkeypatch):
    """本批未命中阶段边界（仅 workflow_pause）→ 不挂系统继续选项。"""
    _register_flow_skill(monkeypatch)
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


# （规格向导合并测试（merge_spec_param_wizard）已随用户裁决 2026-08-31 退役删除，
# D-08 清偿：向导机械合并整体退役。）
