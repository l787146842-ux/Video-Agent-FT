# -*- coding: utf-8 -*-
"""M2 修复批 1（2026-08-30 用户裁决：停用=真停用）：可加载性门户全链路语义。

钉死（门户唯一源 = skill_runtime.registry）：
- 门户三件套：disabled_slugs 活读 / loadable_entries 排序剔除停用 /
  resolve_loadable_entry 先注册维再开关维；
- 停用 → match_skill_name_from_text 不解析出该项；
- 停用 → 注入支路（选中名/消息 slug）被拒并滑落下一支路；
- 停用 → fallback_skill_from_state 跳过停用项取启用项、全停用返回空，
  且不改项目态（重新启用后自动恢复）；
- 停用 → read_skill 三形态（全文/章节/资源）拒绝且报错含「停用」语义；
- 停用 → 风格层不进目录段；
- 动态切换：停用即盲、清 skills_disabled 即恢复（活读，不起新进程）；
- 存量行为保持：skills_disabled=[] 时目录段与 list_skills 与现状一致。
"""
import src.video_agent.web.skill_docs as sd
from src.video_agent.core.planner import PlannerContext
from src.video_agent.core.prompt_builder import PromptBuilder
from src.video_agent.skill_runtime import registry
from src.video_agent.tools.document_tools import (
    ListSkillsInput,
    ListSkillsTool,
    ReadSkillInput,
    ReadSkillTool,
)
from src.video_agent.web.chat_opening import _resolve_skill_name_for_injection


def _ctx() -> PlannerContext:
    ctx = PlannerContext()
    ctx.use_studio_context = True
    ctx.skill_name = ""
    return ctx


def _pb(raw_state) -> PromptBuilder:
    return PromptBuilder(lambda: sd, lambda: "proj", lambda: raw_state)


def _base_state(**extra):
    raw = {"keyElements": [], "shots": [], "audioItems": []}
    raw.update(extra)
    return raw


def _lonely_entry():
    """取一个名称/标识与其他条目互不包含的条目（文本匹配断言不被重叠项干扰）。"""
    entries = registry.loadable_entries()
    for e in entries:
        others = [x for o in entries if o is not e for x in (o.name, o.slug) if x]
        idents = [i for i in (e.name, e.slug) if i]
        if idents and all(
            not any(i in o or o in i for o in others) for i in idents
        ):
            return e
    return entries[0]


# ---------- 门户三件套 ----------


def test_disabled_slugs_live_read(set_global_setting):
    """开关活读：每次调用现读 settings，无缓存。"""
    assert registry.disabled_slugs() == frozenset()
    set_global_setting("skills_disabled", ["x-skill"])
    assert registry.disabled_slugs() == frozenset({"x-skill"})
    set_global_setting("skills_disabled", [])
    assert registry.disabled_slugs() == frozenset()


def test_loadable_entries_sorted_excluding_disabled(set_global_setting):
    """已注册 ∧ 未停用，按 slug 显式排序（防目录顺序漂移）。"""
    entries = registry.loadable_entries()
    assert entries
    assert [e.slug for e in entries] == sorted(e.slug for e in entries)
    victim = entries[0]
    set_global_setting("skills_disabled", [victim.slug])
    after = registry.loadable_entries()
    assert victim.slug not in {e.slug for e in after}
    assert len(after) == len(entries) - 1
    assert [e.slug for e in after] == sorted(e.slug for e in after)


def test_resolve_loadable_entry_registry_then_switch(set_global_setting):
    """先注册维、再开关维：未注册 → None；停用 → None（注册维仍可查）。"""
    victim = registry.loadable_entries()[0]
    assert registry.resolve_loadable_entry(victim.slug) is not None
    assert registry.resolve_loadable_entry("不存在的技能") is None
    set_global_setting("skills_disabled", [victim.slug])
    assert registry.resolve_loadable_entry(victim.slug) is None
    assert registry.resolve_loadable_entry(victim.name) is None
    # 注册维不受开关影响（供报错区分「已停用」与「不存在」）
    assert registry.resolve_entry(victim.slug) is not None


# ---------- 消费面：文本匹配 / 注入支路 / 兜底 ----------


def test_match_text_blind_when_disabled(set_global_setting):
    """停用 → AI 自动挑选不再考虑该项（文本匹配返回空）。"""
    victim = _lonely_entry()
    assert registry.match_skill_name_from_text(f"请跑{victim.name}") == victim.name
    set_global_setting("skills_disabled", [victim.slug])
    assert registry.match_skill_name_from_text(f"请跑{victim.name}") == ""
    assert registry.match_skill_name_from_text(f"请跑{victim.slug}") == ""


def test_injection_branch_rejects_disabled_and_slips(set_global_setting):
    """停用 → 选中名/消息 slug 支路不解析出该项，滑落兜底取启用项。"""
    entries = registry.loadable_entries()
    victim, other = entries[0], entries[1]
    assert _resolve_skill_name_for_injection(victim.name, "", {}) == victim.name
    assert _resolve_skill_name_for_injection("", victim.slug, {}) == victim.name

    set_global_setting("skills_disabled", [victim.slug])
    # 无可用候选：两分支都被拒且无兜底 → 空
    assert _resolve_skill_name_for_injection("", victim.slug, {}) == ""
    # 项目态有启用项：滑落到兜底取启用项（不取停用项）
    state = {"usedSkills": [victim.slug, other.slug]}
    assert _resolve_skill_name_for_injection("", victim.slug, state) == other.slug
    assert _resolve_skill_name_for_injection(victim.name, "", state) == other.slug
    # 未注册选中名维持现状：原样返回（不拦存量项目）
    assert _resolve_skill_name_for_injection("未登记的名字", "", {}) == "未登记的名字"


def test_fallback_skips_disabled_and_all_blind(set_global_setting):
    """兜底候选序列跳过停用项取启用项；全停用返回空；不改项目态。"""
    entries = registry.loadable_entries()
    a, b = entries[0], entries[1]
    set_global_setting("skills_disabled", [a.slug])
    # usedSkills 倒序候选：停用项被跳过
    assert registry.fallback_skill_from_state({"usedSkills": [a.slug, b.slug]}) == b.slug
    # activeSkill 停用 → 滑落 usedSkills 取启用项
    state = {"activeSkill": {"slug": a.slug, "source": "user"}, "usedSkills": [b.slug]}
    assert registry.fallback_skill_from_state(state) == b.slug
    # 全停用 → 空；项目态不被清空（重新启用后自动恢复）
    set_global_setting("skills_disabled", [a.slug, b.slug])
    assert registry.fallback_skill_from_state(state) == ""
    assert state["activeSkill"] == {"slug": a.slug, "source": "user"}
    assert state["usedSkills"] == [b.slug]
    set_global_setting("skills_disabled", [])
    assert registry.fallback_skill_from_state(state) == a.slug
    # 显式自由对话（批 C 口径）不受门户改写：空绑定仍是空
    free = {"activeSkill": {"slug": "", "source": "user"}, "usedSkills": [a.slug]}
    assert registry.fallback_skill_from_state(free) == ""


# ---------- 消费面：read_skill 三形态 / 目录段 / 风格层 ----------


async def test_read_skill_three_forms_reject_disabled(set_global_setting):
    """停用 → 全文/章节/资源三形态统一拒绝，报错区分「已停用」与「不存在」。"""
    victim = registry.loadable_entries()[0]
    tool = ReadSkillTool()
    # 启用时全文可读（存量行为）
    ok = await tool.aexecute(ReadSkillInput(name=victim.name))
    assert ok.success
    set_global_setting("skills_disabled", [victim.slug])
    full = await tool.aexecute(ReadSkillInput(name=victim.name))
    sec = await tool.aexecute(ReadSkillInput(name=victim.name, section="任意章节"))
    res = await tool.aexecute(ReadSkillInput(name=victim.name, resource="references/x.md"))
    for r in (full, sec, res):
        assert not r.success
        assert "已停用" in (r.error or "")
    # 资源通道门户同口径（含「停用」语义，非「未找到」）
    path, err = registry.resolve_skill_resource(victim.slug, "references/x.md")
    assert path is None and "已停用" in err
    # 不存在项仍是「未找到」语义，可用清单只含启用项（停用者不在列）
    miss = await tool.aexecute(ReadSkillInput(name="不存在的技能"))
    assert not miss.success and "未找到" in miss.error
    assert victim.name not in miss.error
    # 重新启用后可用清单恢复（活读）
    set_global_setting("skills_disabled", [])
    miss2 = await tool.aexecute(ReadSkillInput(name="不存在的技能"))
    assert victim.name in miss2.error


def test_catalog_and_style_layer_exclude_disabled(set_global_setting):
    """停用 → 不进目录段；风格层叠加里的停用项同样不进目录段。"""
    entries = registry.loadable_entries()
    victim, other = entries[0], entries[1]
    raw = _base_state(styleSkills=[victim.slug, other.slug])
    block_on = _pb(raw).build_skill_catalog(_ctx())
    assert victim.name in block_on and other.name in block_on
    assert "风格层叠加" in block_on  # 启用时风格层段在场

    set_global_setting("skills_disabled", [victim.slug])
    block_off = _pb(raw).build_skill_catalog(_ctx())
    assert victim.name not in block_off      # 目录条目与风格层均剔除
    assert other.name in block_off           # 启用项不受影响
    assert "风格层叠加" in block_off          # 仍有启用风格层，段保留
    assert other.name in block_off.split("风格层叠加", 1)[1]

    # 风格层全停用 → 风格层段消失
    set_global_setting("skills_disabled", [victim.slug, other.slug])
    block_none = _pb(raw).build_skill_catalog(_ctx())
    assert "风格层叠加" not in block_none


# ---------- 动态切换与存量行为 ----------


def test_hot_switch_blind_and_recover(set_global_setting):
    """活读热切换：停用即盲、清 skills_disabled 即恢复（不起新进程）。"""
    victim = registry.loadable_entries()[0]
    assert registry.resolve_loadable_entry(victim.slug) is not None
    set_global_setting("skills_disabled", [victim.slug])
    assert registry.resolve_loadable_entry(victim.slug) is None
    assert registry.match_skill_name_from_text(victim.name) != victim.name
    set_global_setting("skills_disabled", [])
    assert registry.resolve_loadable_entry(victim.slug) is not None
    assert registry.match_skill_name_from_text(victim.name) == victim.name


def test_stock_behavior_all_enabled_catalog():
    """存量保持：默认空开关时目录段含全部文档 Skill（与现状一致）。"""
    docs = sd.list_skill_docs()
    block = _pb(_base_state()).build_skill_catalog(_ctx())
    for d in docs:
        assert (d.get("name") or d.get("slug")) in block


async def test_stock_behavior_all_enabled_list_skills():
    """存量保持：默认空开关时 list_skills 名单与计数同文档目录一致。"""
    docs = sd.list_skill_docs()
    res = await ListSkillsTool().aexecute(ListSkillsInput())
    assert res.success and res.error is None
    assert res.data["count"] == len(docs)
    assert {s["slug"] for s in res.data["skills"]} == {d["slug"] for d in docs}
    for s in res.data["skills"]:
        assert s["name"] and "description" in s
