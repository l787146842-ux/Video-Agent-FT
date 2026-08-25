"""audit-0819e 阶段 1 钉死回归：阶段前置闸（platform.stage_precondition）。

1111 事故根治的第一道不变量：工具归属阶段的前置阶段未完成 → 拒收，
机械强制不依赖控制流入口的运气（Claude Code hooks 姿势：保证而非建议；
Anthropic RFC#45427 教训：强制内嵌执行路径，无旁路可绕）。

钉死：越阶必拒 / 前置就位放行 / 用户坚持豁免留痕 / 无 Skill 不启用 /
无依赖声明回落线性前置（与 3A 调度同构）/ 未映射工具不受管。
"""
from types import SimpleNamespace

import pytest

from src.video_agent.core import pipeline_orchestrator as po
from src.video_agent.core.fc_tool_runner import FCToolRunner
from src.video_agent.skill_runtime import registry
from src.video_agent.state.manager import StateManager

_SKILL = "precondition-test-skill"

_MANIFEST = {
    "flow": {
        "spec_wizard": True,
        "stage_executors": {
            "1": ["script_analyze"],
            "3": ["storyboard_key_elements", "storyboard_shots", "storyboard_audio"],
        },
        "steps": {
            "1": "读取并分析用户上传的剧本文件，提取角色、场景、关键道具",
            "2": "将全局制作参数写入 Final_Video_Spec.md",
            "3": "设计 Storyboard：登记所有 key_element，拆解 shot 列表",
        },
        # 整改批 3.5：描述关键词启发式已退役（声明权威）——step→stage 映射
        # 一律显式声明，不再依赖 hints 文案猜测
        "step_stages": {"1": "analysis", "2": "spec", "3": "structure"},
        "dependencies": {"3": [1, 2]},
    }
}

_ENTRY = SimpleNamespace(available_tools=[
    "script_analyze", "storyboard_key_elements", "storyboard_shots",
    "storyboard_audio", "write_media_prompt",
])


@pytest.fixture
def dag_env(monkeypatch):
    monkeypatch.setattr(registry, "skill_manifest_of", lambda name: _MANIFEST)
    monkeypatch.setattr(registry, "resolve_entry", lambda name: _ENTRY)
    return monkeypatch


@pytest.fixture
def svc(tmp_path):
    return StateManager(str(tmp_path))


def _analysis_done(state):
    state["analysis"] = {"summary": "一句话总结"}


def _spec_done(state):
    state["documents"] = [{"name": "Final_Video_Spec.md", "content": "- 画幅：16:9\n"}]


# ---------- 判定层（单一事实源复用） ----------

def test_structure_tool_blocked_without_spec(dag_env):
    """1111 现场复现：分析已做、规格未写 → 拆解执行器必拒，拒因点名缺失阶段"""
    state = {}
    _analysis_done(state)
    err = po.evaluate_stage_precondition("storyboard_key_elements", state, _SKILL)
    assert err is not None
    assert "成片规格" in err and "storyboard_key_elements" in err


def test_platform_storyboard_ops_blocked_without_spec(dag_env):
    """结构操作类工具同受前置约束（裁剪名单的历史漏洞一并钉死）"""
    state = {}
    _analysis_done(state)
    for tool in ("storyboard_create_group", "storyboard_add_draft"):
        assert po.evaluate_stage_precondition(tool, state, _SKILL) is not None, tool


def test_media_tools_blocked_before_structure(dag_env):
    """提示词编写/生成工具：结构未完成必拒（前置=structure 探针）"""
    state = {}
    _analysis_done(state)
    _spec_done(state)
    for tool in ("write_media_prompt", "image_generate", "generate_video"):
        assert po.evaluate_stage_precondition(tool, state, _SKILL) is not None, tool


def test_passes_after_preconditions_done(dag_env, svc):
    """前置就位即放行；script_analyze 无前置恒放行"""
    state = svc.state_dict
    _analysis_done(state)
    _spec_done(state)
    assert po.evaluate_stage_precondition("storyboard_key_elements", state, _SKILL) is None
    assert po.evaluate_stage_precondition("script_analyze", {}, _SKILL) is None


def test_unmapped_tools_never_blocked(dag_env):
    """未归属阶段的工具（读/暂停/文档）不受前置约束"""
    state = {}
    for tool in ("read_skill", "workflow_pause", "document_write", "read_uploaded_doc"):
        assert po.evaluate_stage_precondition(tool, state, _SKILL) is None, tool


def test_no_skill_no_gate(dag_env):
    assert po.evaluate_stage_precondition("storyboard_key_elements", {}, "") is None


def test_linear_fallback_without_dependencies(monkeypatch):
    """无依赖声明的 Skill：线性前置回落（structure←spec←analysis），不误伤不越权"""
    monkeypatch.setattr(registry, "skill_manifest_of", lambda name: {"flow": {"spec_wizard": True}})
    monkeypatch.setattr(registry, "resolve_entry", lambda name: _ENTRY)
    state = {}
    assert po.evaluate_stage_precondition("storyboard_key_elements", state, _SKILL) is not None
    _analysis_done(state)
    assert po.evaluate_stage_precondition("storyboard_key_elements", state, _SKILL) is not None
    _spec_done(state)
    assert po.evaluate_stage_precondition("storyboard_key_elements", state, _SKILL) is None


# ---------- 执行路径层（fc_tool_runner 闸机链首位） ----------

def test_runner_gate_rejects_and_override_passes(dag_env, svc, monkeypatch):
    """FC 执行路径：越阶调用被闸机链拒；用户坚持（gate_override）豁免并留痕"""
    monkeypatch.setattr(StateManager, "get_instance", classmethod(lambda cls: svc))
    svc.state_dict["analysis"] = {"summary": "一句话总结"}

    runner = FCToolRunner(tool_manager=None)
    err = runner._stage_precondition_gate("storyboard_key_elements", _SKILL)
    assert err is not None and "成片规格" in err

    runner.gate_override = True
    assert runner._stage_precondition_gate("storyboard_key_elements", _SKILL) is None
    assert any("用户坚持放行" in w for w in runner.gate_warnings)


def test_runner_gate_inactive_without_skill(dag_env, svc, monkeypatch):
    """无 Skill 注入时闸机不启用（日常对话零误伤）"""
    monkeypatch.setattr(StateManager, "get_instance", classmethod(lambda cls: svc))
    runner = FCToolRunner(tool_manager=None)
    assert runner._stage_precondition_gate("storyboard_key_elements", "") is None
