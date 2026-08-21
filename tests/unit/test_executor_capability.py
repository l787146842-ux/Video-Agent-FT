# -*- coding: utf-8 -*-
"""执行器 capability 注册表测试（审核整改批 2：欠账显性化）。

钉死：能力级别数据源、description 标注派生、trace 条目 planning 标记、
棘轮登记全覆盖（deny-by-default）。
"""
import sys
from pathlib import Path

from src.video_agent.skill_runtime.capability import (
    CAPABILITY_EXECUTION,
    CAPABILITY_PLANNING,
    EXECUTOR_CAPABILITY,
    PLANNING_NOTE,
    capability_of,
    is_planning,
    planning_note,
)
from src.video_agent.skill_runtime.registry import SKILL_EXECUTOR_TOOLS


def test_planning_executors_are_the_known_debt():
    """欠账显性化基线：audio_generate / video_assembler 为规划级，其余执行级。"""
    assert EXECUTOR_CAPABILITY["audio_generate"] == CAPABILITY_PLANNING
    assert EXECUTOR_CAPABILITY["video_assembler"] == CAPABILITY_PLANNING
    assert EXECUTOR_CAPABILITY["script_analyze"] == CAPABILITY_EXECUTION
    assert EXECUTOR_CAPABILITY["storyboard_shots"] == CAPABILITY_EXECUTION


def test_capability_of_and_is_planning():
    assert capability_of("audio_generate") == CAPABILITY_PLANNING
    assert is_planning("video_assembler") is True
    assert is_planning("script_analyze") is False
    # 未登记/空名视为执行级（登记强制归棘轮门禁管）
    assert capability_of("") == CAPABILITY_EXECUTION
    assert capability_of("nonexistent_tool") == CAPABILITY_EXECUTION


def test_planning_note_single_source():
    assert planning_note("audio_generate") == PLANNING_NOTE
    assert planning_note("script_analyze") == ""
    assert planning_note("") == ""


def test_executor_descriptions_carry_capability_note():
    """规划级执行器的 tool description 携带标准化能力标注（模型可见）。"""
    from src.video_agent.skill_runtime.executors import (
        AudioGenerateTool,
        ScriptAnalyzeTool,
        VideoAssemblerTool,
    )
    assert PLANNING_NOTE in AudioGenerateTool.description
    assert PLANNING_NOTE in VideoAssemblerTool.description
    assert PLANNING_NOTE not in ScriptAnalyzeTool.description


def test_trace_action_carries_planning_flag():
    """record_action(planning=True) 条目携带 planning 标记（前端徽标数据源）。"""
    from src.video_agent.core.tracer import AgentTracer
    tracer = AgentTracer()
    entry = tracer.record_action(
        name="audio_generate", summary="音频规划", elapsed_ms=1.0,
        ok=True, stage="音频生成", planning=True,
    )
    assert entry["planning"] is True
    entry2 = tracer.record_action(name="script_analyze", summary="剧本分析")
    assert "planning" not in entry2


def test_all_registered_executors_have_capability_entry():
    """棘轮断言同款：SKILL_EXECUTOR_TOOLS 全部在 capability 注册表登记。"""
    missing = [t for t in SKILL_EXECUTOR_TOOLS if t not in EXECUTOR_CAPABILITY]
    assert missing == [], f"执行器未登记 capability：{missing}"


def test_ratchet_script_detects_unregistered_executor():
    """棘轮脚本的登记检查函数：全覆盖时返回空名单。"""
    scripts_dir = Path(__file__).resolve().parents[2] / "scripts"
    sys.path.insert(0, str(scripts_dir))
    try:
        import check_executor_skill_drift as gate
        assert gate.check_capability_registration() == []
        # 负面用例：从注册表剔除一个名字即应被检出
        names = gate._executor_tool_names()
        registered = gate._capability_registered()
        assert names and names <= registered
    finally:
        sys.path.remove(str(scripts_dir))


def test_skills_api_exposes_planning_executors():
    """/api/plugins/ftdyb-agent/config 下发规划级执行器名单（契约面）。"""
    from src.video_agent.web.routes.plugins import _planning_executors_of
    # 一站式生成 Skill 声明 audio_generate/video_assembler 章节 → 两者入名单
    planning = _planning_executors_of("AI 短剧一站式生成")
    assert "audio_generate" in planning
    assert "video_assembler" in planning
    assert "script_analyze" not in planning
    # 未注册 Skill 返回空名单（不报错）
    assert _planning_executors_of("不存在的技能") == []
