# -*- coding: utf-8 -*-
"""阶段子代理执行器试点批（2026-09-15，对齐 Flova 章节隔离）契约单测。

钉死：①stage 归一化（试点枚举内原样、未知/空回落通用）；②stage 模式工具面
= 通用白名单去 read_skill（断跨阶段预读通道）；③任务文本带阶段标注行、
通用形态零变化；④_launch_subagent 带 stage 时精准注入该阶段章节全文
（不走 8000 截断）、章节缺失回落截断路径；⑤不带 stage 注入行为与现状
逐字一致（防回归钉）；⑥子会话 meta 记 stage 名（左栏子线程可辨阶段）。

不驱动真实模型循环（monkeypatch handle_message 断言装配契约，
同 test_subagent_run_subagent 口径）。
"""
import pytest

import src.video_agent.tools.document_tools  # noqa: F401  触发工具注册
from src.video_agent.core import planner as pmod
from src.video_agent.core.planner import Planner, PlannerContext
from src.video_agent.core.subagent import (
    PIPELINE_STAGE_KINDS, STAGE_TOOL_WHITELIST, SUBAGENT_TOOL_WHITELIST,
    build_subagent_task, resolve_stage, whitelist_for_kind,
)
from src.video_agent.state.manager import StateManager

SKILL = "演示阶段技能"
SHOTS_SECTION = "SECTION_SHOTS_BODY：分镜语法三件套探针"


@pytest.fixture
def svc(tmp_path):
    StateManager.reset_instance()
    instance = StateManager(str(tmp_path))
    StateManager._instance = instance
    yield instance
    StateManager.reset_instance()


@pytest.fixture(autouse=True)
def _ensure_platform_tools():
    from src.video_agent.tools.analysis_tools import register_analysis_tools
    from src.video_agent.tools.document_tools import register_document_tools
    from src.video_agent.tools.storyboard_tools import register_storyboard_tools
    register_storyboard_tools()
    register_document_tools()
    register_analysis_tools()


class _FakeSkillDocs:
    """记录 get_skill_doc 是否被调（精准注入时不应触发全文截断路径）。"""

    def __init__(self, content: str = ""):
        self.content = content
        self.calls = 0

    def get_skill_doc(self, slug):
        self.calls += 1
        return {"content": self.content} if self.content else None


def _fake_child(captured: dict):
    class _FakeResp:
        text = "ok"

    async def _fake_handle(self, user_message, context, **kw):
        captured["msg"] = user_message
        captured["ctx"] = context
        return _FakeResp()

    return _fake_handle


# ---------- 纯契约 ----------

def test_resolve_stage_enum_and_fallback():
    assert resolve_stage("script_analyze") == "script_analyze"
    assert resolve_stage("storyboard_shots") == "storyboard_shots"
    assert resolve_stage(" storyboard_shots ") == "storyboard_shots"  # 归一化
    # 未知/空/铺开批未开的阶段 → 回落通用（不阻断委派）
    assert resolve_stage("write_media_prompt") == ""
    assert resolve_stage("不存在") == ""
    assert resolve_stage("") == ""
    assert PIPELINE_STAGE_KINDS == frozenset({"script_analyze", "storyboard_shots"})


def test_stage_whitelist_drops_read_skill_only():
    """stage 面 = 通用面 − read_skill；硬约束（防递归/花钱/确认）两面均保留。"""
    assert STAGE_TOOL_WHITELIST == SUBAGENT_TOOL_WHITELIST - {"read_skill"}
    assert "storyboard_create_group" in STAGE_TOOL_WHITELIST  # 落账工具保留
    for wl in (SUBAGENT_TOOL_WHITELIST, STAGE_TOOL_WHITELIST):
        assert "run_subagent" not in wl
        assert "image_generate" not in wl and "generate_video" not in wl
        assert "workflow_pause" not in wl
    # 路由：带 stage → 收紧面；不带/未知 → 通用面
    assert whitelist_for_kind("general", "storyboard_shots") == STAGE_TOOL_WHITELIST
    assert whitelist_for_kind("general", "") == SUBAGENT_TOOL_WHITELIST
    assert whitelist_for_kind("general", "未知阶段") == SUBAGENT_TOOL_WHITELIST


def test_build_subagent_task_stage_header():
    msg = build_subagent_task("拆解剧本为分镜", stage="storyboard_shots")
    assert "本次委派阶段：分镜设计" in msg      # STAGE_LABELS 展示标签
    assert "章节即产出规范的全部依据" in msg
    assert msg.rstrip().endswith("拆解剧本为分镜")
    # 通用形态零变化：无阶段标注行
    plain = build_subagent_task("拆解剧本为分镜")
    assert "本次委派阶段" not in plain
    assert "被委派的子代理" in plain            # 固定范围声明仍在


# ---------- _launch_subagent 装配 ----------

async def test_launch_stage_injects_section_precisely(svc, monkeypatch):
    """带 stage：精准注入该阶段章节全文（不截断、不走 get_skill_doc 全文路径）。"""
    captured = {}
    monkeypatch.setattr(pmod.Planner, "handle_message", _fake_child(captured))
    seen = {}
    monkeypatch.setattr(
        pmod, "tool_sections",
        lambda skill, tool: seen.update(skill=skill, tool=tool) or SHOTS_SECTION)
    sd = _FakeSkillDocs(content="X" * 9000)  # 若走截断路径必出现 9000 字全文
    parent = Planner(state_manager=svc, llm_adapter=None, skill_docs=sd)
    await parent._launch_subagent(
        "拆解剧本为分镜", PlannerContext(subagent_depth=0, skill_name=SKILL),
        stage="storyboard_shots")

    assert seen == {"skill": SKILL, "tool": "storyboard_shots"}
    msg = captured["msg"]
    assert SHOTS_SECTION in msg                       # 章节全文在场
    assert f"注入 Skill 章节（{SKILL} · storyboard_shots）" in msg
    assert "本次委派阶段：分镜设计" in msg              # 阶段标注行
    assert sd.calls == 0                              # 未走全文截断回落
    assert "章节内容截断" not in msg
    # 工具面收紧 + 子会话 meta 记 stage
    assert captured["ctx"].subagent_whitelist == STAGE_TOOL_WHITELIST
    child_cid = captured["ctx"].session_conversation_id
    assert svc.get_conversation_scope(child_cid).get("subagent_kind") \
        == "stage:storyboard_shots"


async def test_launch_stage_missing_section_falls_back(svc, monkeypatch):
    """Skill 无该阶段章节：回落现行全文 8000 截断路径（委派不阻断）。"""
    captured = {}
    monkeypatch.setattr(pmod.Planner, "handle_message", _fake_child(captured))
    monkeypatch.setattr(pmod, "tool_sections", lambda skill, tool: "")
    sd = _FakeSkillDocs(content="Y" * 9000)
    parent = Planner(state_manager=svc, llm_adapter=None, skill_docs=sd)
    await parent._launch_subagent(
        "拆解", PlannerContext(subagent_depth=0, skill_name=SKILL),
        stage="storyboard_shots")
    assert sd.calls == 1
    assert "章节内容截断" in captured["msg"]


async def test_launch_without_stage_keeps_current_behavior(svc, monkeypatch):
    """防回归钉：不带 stage（含未知 stage）注入行为与现状逐字一致——
    全文前 8000 截断、通用白名单、无阶段标注、meta 记 general。"""
    captured = {}
    monkeypatch.setattr(pmod.Planner, "handle_message", _fake_child(captured))

    def _boom(skill, tool):
        raise AssertionError("通用委派不应触发阶段章节取读")

    monkeypatch.setattr(pmod, "tool_sections", _boom)
    sd = _FakeSkillDocs(content="Z" * 9000)
    parent = Planner(state_manager=svc, llm_adapter=None, skill_docs=sd)
    await parent._launch_subagent(
        "自由任务", PlannerContext(subagent_depth=0, skill_name=SKILL),
        stage="不存在的阶段")
    msg = captured["msg"]
    assert sd.calls == 1
    assert f"注入 Skill 章节（{SKILL}）" in msg       # 现状标注（无 · stage 后缀）
    assert "章节内容截断" in msg
    assert "本次委派阶段" not in msg
    assert captured["ctx"].subagent_whitelist == SUBAGENT_TOOL_WHITELIST
    child_cid = captured["ctx"].session_conversation_id
    assert svc.get_conversation_scope(child_cid).get("subagent_kind") == "general"
