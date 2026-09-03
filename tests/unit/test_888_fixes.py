# -*- coding: utf-8 -*-
"""888 项目九项反馈修复回归：时长补全、盲捡收敛、概述裁剪、铁律措辞、
流式逐条落盘、实时上下文用量。"""
import pytest

from src.video_agent.core import prompt_gates, spec_rules
from src.video_agent.utils.live_metrics import get_live_context, record_live_context


# ---------- item 6：分镜提示词时长客观补全（C1a 裁决 2026-08-31 退役：
# require_duration 技能闸与 autofill 补印随技能级闸层删除） ----------

# test_executor_shot_prompt_missing_duration_passes_gate 已随 Q2 裁决 2026-09-01 退役删除：
# 文本轨 update_draft 随执行器家族退役；时长不再校验的口径由 FC 轨提示词闸
# （evaluate_prompt_write 唯一实现）相关用例钉死。


# ---------- item 6：add_draft 盲捡收敛 ----------
# test_add_draft_rejects_blind_pickup_with_many_groups /
# test_add_draft_single_group_fallback_still_works 已随 Q2 裁决 2026-09-01 退役删除：
# 文本轨 add_draft 随执行器家族退役；FC 轨 storyboard_add_draft 的分组定位经
# storyboard_ops.find_group（current/编号/标签匹配），多分组歧义时工具报错回喂。


# ---------- item 8：分镜概述裁剪 ----------
# test_shot_rough_desc_clamped 已随 Q2 裁决 2026-09-01 退役删除：
# 文本轨 add_group 的 roughDesc 钳制随执行器家族退役（FC 轨建组不经该口径）。


# ---------- item 9：执行铁律优先级含制片规格 ----------

def test_iron_rules_priority_mentions_spec_doc():
    state = {"documents": []}
    assert spec_rules.ensure_iron_rules_doc(state) is True
    iron = spec_rules.find_iron_rules_doc(state)
    assert "用户最新指令 > 本文档 + 制片规格 > Skill/系统默认" in iron["content"]
    # 幂等
    assert spec_rules.ensure_iron_rules_doc(state) is False


def test_iron_rules_old_priority_upgraded_in_place():
    """老项目已有铁律文档：仅精确替换旧优先级措辞，其余内容不动。"""
    old = (
        "# 执行铁律（系统约定，按优先级执行：用户指令 > 本文档 > Skill/系统默认）\n\n"
        "0. 执行优先：用户说什么就做什么。\n9. 用户自定义条款：保持原样。\n"
    )
    state = {"documents": [{"name": "执行铁律.md", "content": old}]}
    assert spec_rules.ensure_iron_rules_doc(state) is True
    content = spec_rules.find_iron_rules_doc(state)["content"]
    assert "用户最新指令 > 本文档 + 制片规格 > Skill/系统默认" in content
    assert "用户自定义条款：保持原样" in content
    assert spec_rules.ensure_iron_rules_doc(state) is False


# ---------- item 5：流式逐条落盘 ----------
# test_extract_complete_objects_incremental / test_extract_complete_objects_braces_in_strings /
# test_stream_progressive_applies_in_batches 已随任务#36 B5 执行器一步退役删除：
# 被测对象（executors._extract_complete_objects / _stream_actions_progressive）不复存在，
# 管线阶段改由通用主路径直走平台工具。


# ---------- item 7：sceneRefs ID 兼容（后端解析链路） ----------

def test_resolve_scene_refs_matches_by_id_and_title():
    """888 现场：sceneRefs 存的是 ke-xxx ID，生视频参考图注入只认标题会全部丢失。"""
    from src.video_agent.state.storyboard_ops import resolve_scene_refs

    state = {"keyElements": [
        {"id": "ke-1", "title": "三维木星", "drafts": [{"imgUrl": "http://x/j.png"}]},
        {"id": "ke-2", "title": "程心", "drafts": [{"imgUrl": "http://x/c.png"}]},
    ]}
    group = {"id": "shot-1", "sceneRefs": ["ke-1", "程心", "ke-404"]}
    refs = resolve_scene_refs(state, group)
    assert [r["url"] for r in refs] == ["http://x/j.png", "http://x/c.png"]


# ---------- item 1：实时上下文用量 ----------

def test_live_metrics_record_and_expiry(monkeypatch):
    record_live_context("proj-x", [{"role": "user", "content": "你好" * 100}])
    rec = get_live_context("proj-x")
    assert rec and rec["est_tokens"] > 0
    # 过期回落
    import src.video_agent.utils.live_metrics as lm
    monkeypatch.setitem(lm._LIVE, "proj-x", {"est_tokens": 5, "ts": rec["ts"] - 999})
    assert get_live_context("proj-x") is None
    assert get_live_context("") is None


# ============================================================
# 888 事故二轮修复回归（2026-08-10）：版本账本统一 /
# 流程事件账本 / 截断禁报成功 / 铁律保护 / 回话模板去矛盾
# ============================================================

# ---------- B1：版本账本全站统一（重启不断号、双实例同一本账） ----------

def test_board_version_shared_between_instances(tmp_path):
    """888 现场：常驻单例 110 号对任务实例 9 号，正常保存被拒。
    修复后同项目所有实例共享一本账。"""
    from src.video_agent.state.manager import StateManager

    a = StateManager(str(tmp_path / "ws"))
    pid = a.active_project_id
    b = StateManager(str(tmp_path / "ws"))  # 第二个实例（模拟任务注册表路径）
    assert b.active_project_id == pid
    v0 = a.board_version
    a.state_dict["marker"] = 1
    a.save()
    # 同项目另一实例立即看到同一版号（各算各的 bug 已修）
    assert b.board_version == v0 + 1


def test_board_version_persisted_across_reload(tmp_path):
    """版号随项目文件落盘：换实例/重启都从上次的号继续数，不从 0 重数。"""
    from src.video_agent.state.manager import StateManager

    StateManager._board_versions.clear()  # 模拟进程重启，内存账本清空
    a = StateManager(str(tmp_path / "ws"))
    a.state_dict["marker"] = 1
    a.save()
    v = a.board_version
    assert v >= 1
    StateManager._board_versions.clear()  # 再次模拟重启
    b = StateManager(str(tmp_path / "ws"))
    assert b.board_version == v  # 从落盘状态继承，不断号


# ---------- A3：流程事件账本（进度事实可见，截断不得冒充完成） ----------

def test_flow_event_recorded_injected_and_cleared(tmp_path):
    from src.video_agent.state.manager import StateManager

    svc = StateManager(str(tmp_path / "ws"))
    svc.record_flow_event(
        "storyboard_shots_truncated",
        "上次分镜拆解输出被截断，只写入 4 个，疑似不完整",
    )
    ctx = svc.build_agent_context("all")
    assert "上次分镜拆解输出被截断" in ctx
    # 完整完成后消解
    svc.clear_flow_events("storyboard_shots_truncated")
    assert "上次分镜拆解输出被截断" not in svc.build_agent_context("all")


# test_is_truncated_detects_length_finish / test_split_truncation_marks_incomplete_and_records_event
# 已随任务#36 B5 执行器一步退役删除：被测对象（executors._is_truncated /
# StoryboardShotsTool 截断对账）不复存在。「截断不得冒充完成」的通用事实由
# test_flow_event_recorded_injected_and_cleared（StateManager 流程事件账本）承接钉死。


# ---------- B7：铁律文档保护（模型不得整篇重写） ----------

@pytest.mark.asyncio
async def test_model_cannot_rewrite_iron_rules_doc(monkeypatch, tmp_path):
    """888 现场：模型自作主张重写铁律，可能盖掉用户编辑。修复后写入被拒。"""
    from src.video_agent.state.manager import StateManager
    from src.video_agent.tools.document_tools import (
        DocumentWriteTool, WriteDocumentInput,
    )

    svc = StateManager(str(tmp_path / "ws"))
    monkeypatch.setattr(StateManager, "get_instance", classmethod(lambda cls: svc))
    result = await DocumentWriteTool().aexecute(WriteDocumentInput(
        name="执行铁律.md", content="# 模型自造的铁律\n",
    ))
    assert result.success is False
    assert "不得整篇重写" in str(result.error)


# ---------- A1：回话模板去矛盾（治理台账的可机检项） ----------

def test_feedback_template_no_contradiction():
    """888 病灶一：「请继续完成任务……不要再调用 Tool」自相矛盾逼推理模型
    万字思考反复裁决。模板措辞必须消除该矛盾。"""
    import inspect

    from src.video_agent.core import agent_loop

    src = inspect.getsource(agent_loop)
    assert "不要再调用 Tool" not in src
    assert "不要再输出 continue" not in src


# ---------- B8 豪华版：软参数模型出题 + 点选 + 机械回写 ----------
# test_collect_wizard_renders_skill_dim_candidates /
# test_parse_dim_selections_and_assemble_spec_doc /
# test_soft_not_added_on_confirm_intent 已随用户裁决 2026-08-31 退役删除（D-08 清偿）：
# 规格向导软参数收集链整体退役，规格交互归模型自主对话。


# test_action_alias_normalization_groupid_payload 已随 Q2 裁决 2026-09-01 退役删除：
# 文本轨驼峰 schema 宽容归一（type/groupId/payload）随执行器家族退役；
# FC 轨工具输入经 pydantic 严格校验（extra=forbid），错误结构化回喂模型纠正。


# test_script_analyze_generates_soft_candidates 已随任务#36 B5 执行器一步退役删除：
# 被测对象（executors.ScriptAnalyzeTool + exec_spec.run_collect_spec_node 候选落盘）
# 不复存在。平台不再机械出题，规格收集改由模型按 skill_runtime 用 workflow_pause
# 分组向导完成。
