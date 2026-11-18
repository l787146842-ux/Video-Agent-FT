# -*- coding: utf-8 -*-
"""dsh 四组合 + 用户 `/slug` 一次性注入契约（2026-11-12）。"""
import asyncio

import pytest

import src.video_agent.web.skill_docs as sd
from src.video_agent.core.planner import Planner, PlannerContext
from src.video_agent.core.prompt_builder import PromptBuilder
from src.video_agent.skill_runtime import invocation, registry
from src.video_agent.tools.document_tools import ReadSkillInput, ReadSkillTool


BODY_MARKER = "BODY_MARKER_XYZ"


def _doc(name: str, extra: str = "") -> str:
    return (
        f"---\nname: {name}\ndescription: {name} 测试桩\n{extra}---\n"
        f"# {name}\n\n## 一、目标\n\n{BODY_MARKER}\n"
    )


@pytest.fixture
def skills(tmp_path, monkeypatch):
    d = tmp_path / "skills"
    d.mkdir()
    monkeypatch.setattr(sd, "SKILL_DOCS_DIR", d)
    registry.reset_registry()
    sd.save_skill_doc("both-skill", _doc("双向技能"))
    sd.save_skill_doc(
        "user-only", _doc("用户专用", "disable-model-invocation: true\n"))
    sd.save_skill_doc(
        "model-only", _doc("模型专用", "user-invocable: false\n"))
    registry.sync_all(force=True)
    try:
        yield d
    finally:
        registry.reset_registry()


def test_four_combination_catalogs(skills):
    model = {e.slug for e in registry.model_catalog_entries()}
    user = {e.slug for e in registry.user_catalog_entries()}
    assert model == {"both-skill", "model-only"}
    assert user == {"both-skill", "user-only"}
    assert registry.resolve_entry("user-only").model_invocable is False
    assert registry.resolve_entry("model-only").user_invocable is False


def test_slug_injection_is_one_shot_and_deduped(skills):
    entries, content = invocation.render_user_skills(
        "请用 /user-only 开始，再用一次 /user-only 和 /model-only")
    assert [e.slug for e in entries] == ["user-only"]
    assert content.count("<skill_content") == 1
    assert BODY_MARKER in content
    assert "用户已直接调用此 Skill" in content
    assert "Skill package: user-only" in content
    # 模型专用 / 未知 token 不注入
    assert "/model-only" not in [f"/{e.slug}" for e in entries]
    assert invocation.render_user_skills("请用 /不存在 开始") == ([], "")


def test_user_only_skill_is_hidden_from_system_prompt_body(skills):
    pb = PromptBuilder(lambda: sd, lambda: "proj", lambda: {})
    ctx = PlannerContext(use_studio_context=False, skill_name="用户专用")
    text = pb.build_system_prompt(ctx)
    assert "用户专用" in text
    assert "SELECTED_NOTE" not in text
    assert "用户专用" in text and "read_skill" in text
    assert BODY_MARKER not in text


def test_user_only_skill_rejected_by_read_skill(skills):
    tool = ReadSkillTool()
    res = asyncio.run(tool.aexecute(ReadSkillInput(name="用户专用")))
    assert res.success is False
    assert "not available for model invocation" in (res.error or "")


def test_model_only_skill_can_be_loaded(skills):
    tool = ReadSkillTool()
    res = asyncio.run(tool.aexecute(ReadSkillInput(name="模型专用")))
    assert res.success is True
    assert BODY_MARKER in str((res.data or {}).get("content") or "")


def test_planner_builds_skill_event_from_raw_text(skills):
    planner = Planner()
    ctx = PlannerContext(
        use_studio_context=False, raw_user_text="请用 /user-only 开始")
    content = planner._build_and_log_skill_event(ctx)
    assert BODY_MARKER in content
    assert ctx.skill_name == "用户专用"


# ---------- severity-① 绕过回归（2026-11-13）：歧义短名不得漏放 user-only 正文 ----------
#
# 病灶：门禁只对**输入 token** 做一次 resolve_entry，而 resolve_entry 在
# 歧义名（包含匹配多命中）下按设计返回 None；正文随后由 skill_docs 端口的
# 双向包含匹配补上 ⇒ read_skill(name="短剧") 能读走 user-only 技能全文。
# 以下用例自建夹具（不依赖 data/skills 具体包名），钉死三条边界：
# a) 歧义短名对 user-only 技能必须被拒且不返回任何正文；
# b) 歧义短名对 model-invocable 技能仍须正常工作（不误拒）；
# c) 精确名拒绝语义与文案不变。

AMBIG_BODY_MARKER = "AMBIG_BODY_MARKER_XYZ"
MODEL_BODY_MARKER = "MODEL_BODY_MARKER_XYZ"


def _ambig_doc(name: str, marker: str, extra: str = "") -> str:
    return (
        f"---\nname: {name}\ndescription: {name} 歧义门禁测试桩\n{extra}---\n"
        f"# {name}\n\n## 一、目标\n\n{marker}\n"
    )


@pytest.fixture
def ambiguous_skills(tmp_path, monkeypatch):
    """歧义短名场景（全部为「短剧」二字的包含匹配候选）：

    - 古风甜宠短剧（user-only；slug 排序在前）：与「古风短剧」同为「短剧」
      候选，两者并存使 resolve_entry("短剧") 多命中返回 None（绕过入口）；
      排序在前保证 skill_docs 的包含匹配确实落到**这条 user-only 条目**上
      ——这正是 severity-① 的实测泄漏形态（2026-11-13 实测三个短名全中）。
    - 古风短剧（model-invocable）：同候选，验证歧义名对可读技能不误伤；
    - 模型演示（model-invocable）：无歧义名的正常读取基线。
    """
    d = tmp_path / "skills"
    d.mkdir()
    monkeypatch.setattr(sd, "SKILL_DOCS_DIR", d)
    registry.reset_registry()
    sd.save_skill_doc(
        "ambig-a-user-only",
        _ambig_doc("古风甜宠短剧", AMBIG_BODY_MARKER,
                   "disable-model-invocation: true\n"))
    sd.save_skill_doc(
        "ambig-b-model-ok", _ambig_doc("古风短剧", MODEL_BODY_MARKER))
    sd.save_skill_doc(
        "plain-model", _ambig_doc("模型演示", MODEL_BODY_MARKER))
    registry.sync_all(force=True)
    try:
        yield d
    finally:
        registry.reset_registry()


def test_ambiguous_short_name_does_not_bypass_user_only_gate(ambiguous_skills):
    """severity-①：歧义短名「短剧」不得漏放 user-only 正文。

    缺陷实录（修复前）：resolve_entry("短剧") 因「古风甜宠短剧」与「古风短剧」
    双命中返回 None → pre-gate 整条失效 → 正文由 resolve_skill_content 的
    包含匹配给出（实测 6281 字 user-only 全文）。修复后 post-gate 以真实
    matched 名反查条目，user-only 一律拒绝且不带任何正文。
    """
    # 前置事实：该输入确实歧义（门禁旧写法在此拿到 None）
    assert registry.resolve_entry("短剧") is None
    # 而端口仍能解析出正文归属（正是旧实现的漏放通道）
    display, content = sd.resolve_skill_content("短剧")
    assert display == "古风甜宠短剧" and AMBIG_BODY_MARKER in content

    res = asyncio.run(ReadSkillTool().aexecute(ReadSkillInput(name="短剧")))
    assert res.success is False
    assert "not available for model invocation" in (res.error or "")
    # 关键断言：不返回任何正文（data 为空，而非「成功但内容被清空」）
    assert not (res.data or {}).get("content")
    assert AMBIG_BODY_MARKER not in str(res.data or "")


def test_ambiguous_name_section_and_resource_paths_also_blocked(ambiguous_skills):
    """歧义名经 section/resource 通道同样不得泄漏 user-only 正文。"""
    tool = ReadSkillTool()
    for params in (
        ReadSkillInput(name="短剧", section="一、目标"),
        ReadSkillInput(name="短剧", resource="references/无此文件.md"),
        ReadSkillInput(name="短剧", start=100),
    ):
        res = asyncio.run(tool.aexecute(params))
        assert res.success is False
        assert "not available for model invocation" in (res.error or "")
        assert AMBIG_BODY_MARKER not in str(res.data or "")


def test_ambiguous_name_still_works_for_model_invocable_skill(ambiguous_skills):
    """歧义名对 model-invocable 技能仍可读：门禁只加严可见面，不误伤正常加载。"""
    display, content = sd.resolve_skill_content("短剧")
    assert display == "古风甜宠短剧"  # 端口口径：包含匹配先命中者
    # 说明「短剧」当前解析到 user-only 项 → 被拒是正确行为；
    # 真正可读的 model-invocable 技能须以其**可唯一解析的身份**调用。
    res = asyncio.run(
        ReadSkillTool().aexecute(ReadSkillInput(name="古风短剧")))
    assert res.success is True
    assert MODEL_BODY_MARKER in str((res.data or {}).get("content") or "")


def test_exact_user_only_name_still_rejected_verbatim(ambiguous_skills):
    """精确名拒绝语义逐字不变（文案 `skill "<name>" is not available for model invocation`）。"""
    res = asyncio.run(
        ReadSkillTool().aexecute(ReadSkillInput(name="古风甜宠短剧")))
    assert res.success is False
    assert res.error == (
        'skill "古风甜宠短剧" is not available for model invocation')
    assert not res.data


def test_model_only_skill_readable_under_ambiguity_fixture(ambiguous_skills):
    """model-invocable 技能在歧义夹具下仍可正常读取（回归不误拒）。"""
    res = asyncio.run(
        ReadSkillTool().aexecute(ReadSkillInput(name="模型演示")))
    assert res.success is True
    assert MODEL_BODY_MARKER in str((res.data or {}).get("content") or "")


def test_unknown_name_keeps_not_found_semantics(ambiguous_skills):
    """不存在/未注册的既有三类拒载文案不被新门禁改写（不误报 not available）。"""
    res = asyncio.run(ReadSkillTool().aexecute(ReadSkillInput(name="从未存在的技能")))
    assert res.success is False
    assert "未找到" in (res.error or "")
    assert "not available for model invocation" not in (res.error or "")

