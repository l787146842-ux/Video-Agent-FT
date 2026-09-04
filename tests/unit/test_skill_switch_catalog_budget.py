# -*- coding: utf-8 -*-
"""批5（对齐 Flova 卡片开关）防回归测试：
1) 开关过滤：settings.skills_disabled 里的 slug 不进目录段；默认空 = 全启用；
2) 条目预算：超 skill_catalog_max_entries 按最近使用序（项目 usedSkills）
   截断，尾部附「另有 N 个已启用 Skill 未列出」指针行；
3) list_skills：低危只读工具，返回启用名单（停用者不在列），无副作用。
"""
import src.video_agent.web.skill_docs as sd
from src.video_agent.core.planner import PlannerContext
from src.video_agent.core.prompt_builder import PromptBuilder
from src.video_agent.tools.document_tools import ListSkillsInput, ListSkillsTool
from src.video_agent.tools.manager import ToolManager


def _ctx(skill_name: str = "") -> PlannerContext:
    ctx = PlannerContext()
    ctx.use_studio_context = True
    ctx.skill_name = skill_name
    return ctx


def _pb(raw_state) -> PromptBuilder:
    return PromptBuilder(lambda: sd, lambda: "proj", lambda: raw_state)


def _base_state(**extra):
    raw = {"keyElements": [], "shots": [], "audioItems": []}
    raw.update(extra)
    return raw


def _all_docs():
    return sd.list_skill_docs()


def test_default_all_enabled_no_pointer_line(set_global_setting):
    """开关默认全启用（存量 15 skill 全在目录），无截断指针行。"""
    docs = _all_docs()
    assert len(docs) >= 15
    block = _pb(_base_state()).build_skill_catalog(_ctx(""))
    for d in docs:
        assert (d.get("name") or d.get("slug")) in block
    assert "未列出" not in block


def test_disabled_skill_filtered_from_catalog(set_global_setting):
    """skills_disabled 里的 slug 不进目录，其余不受影响。"""
    docs = _all_docs()
    victim, other = docs[0], docs[1]
    set_global_setting("skills_disabled", [victim["slug"]])
    block = _pb(_base_state()).build_skill_catalog(_ctx(""))
    assert (victim.get("name") or victim.get("slug")) not in block
    assert (other.get("name") or other.get("slug")) in block


def test_catalog_budget_truncation_by_recency_with_pointer(set_global_setting):
    """超预算按最近使用序截断：usedSkills 末位在前，截断数入指针行。"""
    docs = _all_docs()
    total = len(docs)
    # 取两个已用（较早 → 较近）与一个未用探针
    older, recent = docs[0]["slug"], docs[1]["slug"]
    unused = next(d for d in docs[2:] if d["slug"] not in (older, recent))
    set_global_setting("skill_catalog_max_entries", 2)
    raw = _base_state(usedSkills=[older, recent])
    block = _pb(raw).build_skill_catalog(_ctx(""))
    recent_name = recent if not docs[1].get("name") else docs[1]["name"]
    older_name = older if not docs[0].get("name") else docs[0]["name"]
    # 最近使用的在前（目录行序）
    idx_recent = block.find(f"- {recent_name}")
    idx_older = block.find(f"- {older_name}")
    assert idx_recent >= 0 and idx_older > idx_recent
    # 未使用者被截断，指针行给出实际截断数
    unused_name = unused.get("name") or unused.get("slug")
    assert f"- {unused_name}" not in block
    assert f"另有 {total - 2} 个已启用 Skill 未列出" in block


def test_catalog_budget_counts_after_switch_filter(set_global_setting):
    """指针行 N = 开关过滤后仍超预算的实际截断数（两杠杆同批叠加口径）。"""
    docs = _all_docs()
    set_global_setting("skills_disabled", [docs[0]["slug"]])
    set_global_setting("skill_catalog_max_entries", 2)
    block = _pb(_base_state()).build_skill_catalog(_ctx(""))
    assert f"另有 {len(docs) - 1 - 2} 个已启用 Skill 未列出" in block


async def test_list_skills_readonly_returns_enabled_only(set_global_setting):
    """list_skills 只读返回启用名单：停用者不在列、计数一致、不写任何状态。"""
    docs = _all_docs()
    victim = docs[0]
    set_global_setting("skills_disabled", [victim["slug"]])
    res = await ListSkillsTool().aexecute(ListSkillsInput())
    assert res.success and res.error is None
    slugs = {s["slug"] for s in res.data["skills"]}
    assert victim["slug"] not in slugs
    assert res.data["count"] == len(docs) - 1
    for s in res.data["skills"]:
        assert s["name"] and "description" in s
    # 开关恢复后名单回到全启用（只读探针随开关口径同源变化）
    set_global_setting("skills_disabled", [])
    res2 = await ListSkillsTool().aexecute(ListSkillsInput())
    assert res2.data["count"] == len(docs)


def test_list_skills_registered_low_risk():
    """工具注册表登记：低危只读（审批生效档推导为 none，不过确认闸）。
    自愈重注册：个别既有测试夹具会 reset 全局 ToolManager（跨文件污染先例），
    断言前重走接线点（register 幂等），不依赖全局残留态。"""
    from src.video_agent.tools import register_document_tools

    register_document_tools()
    assert "list_skills" in ToolManager._tools
    assert ToolManager.get_tool_risk("list_skills") == "low"
    assert ToolManager.get_tool_approval_tier("list_skills") == "none"


def test_skills_disabled_slug_list_sanitizer():
    """开关写入唯一规整口：非列表拒收；清洗去重去空、限长。"""
    from src.video_agent.web.routes.runtime_settings import _sanitize_slug_list

    assert _sanitize_slug_list("not-a-list") is None
    assert _sanitize_slug_list(["a", "", "  ", "a", "b"]) == ["a", "b"]
    assert _sanitize_slug_list([1, None]) == ["1"]
    assert len(_sanitize_slug_list([f"s{i}" for i in range(500)])) == 200
