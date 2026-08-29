# -*- coding: utf-8 -*-
"""M3 批2（2026-08-30 用户裁决：注册表=加载唯一门户）：被拒注册的坏包不能加载。

对齐业界「发现→注册→加载」：磁盘存在 ≠ 可加载，注册是加载的唯一门户。
钉死七件事：
① 坏包（缺 frontmatter name）在目录段/list_skills/文本匹配/slug 注入/
   resolve_skill_content/read_skill//api/skills 七面全盲（显式选择被拒不双滑落，空绑定）；
② 同夹具下好包四消费面行为与现状一致；
③ 注册后改坏 frontmatter → refresh_skill 拒注册摘除 → 消费面立即盲；
④ 磁盘直增未注册包不进目录，sync_all 后才可加载（发现→注册边界）；
⑤ 注册表空（全部失败）降级：目录空段跳过、read_skill 优雅报错、对话不阻断；
⑥ /api/skills 不返回被拒包；/api/skills/docs 仍磁盘全量（工作台供修复）；
⑦ 16 包字节级目录快照：空停用+全注册时与改造前磁盘口径基线逐字节相等。
"""
import json
import pathlib

import pytest

import src.video_agent.web.skill_docs as sd
from src.video_agent.core.planner import PlannerContext
from src.video_agent.core.prompt_builder import PromptBuilder
from src.video_agent.skill_runtime import frontmatter, registry
from src.video_agent.tools.document_tools import (
    ListSkillsInput, ListSkillsTool, ReadSkillInput, ReadSkillTool,
)
from src.video_agent.web.chat_opening import _resolve_skill_name_for_injection

GOLDEN = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "skill_catalog_golden.json"

GOOD_DOC = (
    "---\nname: 好包\ndescription: M3 好包测试桩\n---\n"
    "# 好包\n> 调用规则：测试\n<script_analyze>\n分析正文\n</script_analyze>\n"
)
BAD_DOC = "---\ndescription: 缺 name 必填键，注册被拒\n---\n# 坏包\n正文\n"


@pytest.fixture
def portal_env(tmp_path, monkeypatch):
    """隔离目录：一个好包（经保存接口注册）+ 一个坏包（直写磁盘，缺 name 拒注册）"""
    d = tmp_path / "skills"
    d.mkdir()
    monkeypatch.setattr(sd, "SKILL_DOCS_DIR", d)
    registry.reset_registry()
    sd.save_skill_doc("good-pack", GOOD_DOC)
    pkg = d / "bad-pack"
    pkg.mkdir()
    (pkg / frontmatter.SKILL_DOC_NAME).write_text(BAD_DOC, encoding="utf-8")
    registry.sync_all(force=True)
    yield d
    registry.reset_registry()


def _pb(raw):
    return PromptBuilder(lambda: sd, lambda: "proj", lambda: raw)


def _ctx(skill_name=""):
    ctx = PlannerContext()
    ctx.use_studio_context = True
    ctx.skill_name = skill_name
    return ctx


def _base_state(**extra):
    raw = {"keyElements": [], "shots": [], "audioItems": []}
    raw.update(extra)
    return raw


# ---------- ① 坏包七面全盲 ----------


def test_bad_package_blind_on_catalog_list_match_injection(portal_env):
    """坏包不进目录段/名单/文本匹配；slug 与选中名注入支路均被门户拒绝滑落"""
    assert registry.resolve_entry("bad-pack") is None  # 拒注册事实
    assert sd.get_skill_doc("bad-pack") is not None     # 磁盘存在（工作台可见）

    block = _pb(_base_state()).build_skill_catalog(_ctx())
    assert "坏包" not in block and "bad-pack" not in block
    assert "好包" in block  # 好包不受影响（目录面）

    assert registry.match_skill_name_from_text("请按坏包的流程执行") == ""
    # slug 注入支路：显式选择被拒 → 空绑定，不双滑落到文本匹配/兜底（M3 收紧）
    assert _resolve_skill_name_for_injection("", "bad-pack", _base_state(), "") == ""
    # 选中名支路（M3 收紧）：磁盘存在但被拒注册 → 空绑定，不得绑定也不双滑落
    assert _resolve_skill_name_for_injection("坏包", "", _base_state(), "") == ""
    # 磁盘根本不存在的名字：维持现状原样返回（不拦存量项目）
    assert _resolve_skill_name_for_injection("从未存在", "", _base_state(), "") == "从未存在"


async def test_bad_package_blind_on_list_skills_and_read(portal_env):
    """list_skills 名单不含坏包；read_skill 拒载且报错附工作台修复指引"""
    res = await ListSkillsTool().aexecute(ListSkillsInput())
    assert res.success and res.data["count"] == 1
    assert {s["slug"] for s in res.data["skills"]} == {"good-pack"}

    r = await ReadSkillTool().aexecute(ReadSkillInput(name="坏包"))
    assert not r.success
    assert "未通过注册" in r.error and "工作台" in r.error  # 拒注册语义≠停用≠未找到


def test_bad_package_blind_on_resolve_content(portal_env):
    """resolve_skill_content（read_skill 与选中段共用解析）不解析出坏包正文"""
    assert sd.resolve_skill_content("坏包") == ("", "")
    display, content = sd.resolve_skill_content("好包")
    assert display == "好包" and "分析正文" in content


# ---------- ② 好包四消费面现状一致 ----------


async def test_good_package_faces_intact(portal_env):
    block = _pb(_base_state()).build_skill_catalog(_ctx())
    assert "好包：M3 好包测试桩" in block
    assert registry.match_skill_name_from_text("按好包开工") == "好包"
    r = await ReadSkillTool().aexecute(ReadSkillInput(name="好包"))
    assert r.success and "分析正文" in r.data["content"]


# ---------- ③ 注册后改坏 → refresh 摘除 → 立即盲 ----------


async def test_break_frontmatter_then_refresh_blinds_faces(portal_env):
    assert registry.resolve_loadable_entry("good-pack") is not None
    # 改坏：删 name 必填键
    doc = portal_env / "good-pack" / frontmatter.SKILL_DOC_NAME
    doc.write_text("---\ndescription: 改坏后缺 name\n---\n# 好包\n正文\n", encoding="utf-8")
    assert registry.refresh_skill("good-pack") is None  # 拒注册摘除

    assert "好包" not in _pb(_base_state()).build_skill_catalog(_ctx())
    res = await ListSkillsTool().aexecute(ListSkillsInput())
    assert res.data["count"] == 0
    assert registry.match_skill_name_from_text("按好包开工") == ""
    r = await ReadSkillTool().aexecute(ReadSkillInput(name="好包"))
    assert not r.success and "未通过注册" in r.error


# ---------- ④ 磁盘直增未注册包：发现→注册边界 ----------


def test_direct_disk_addition_not_loadable_until_sync(portal_env):
    pkg = portal_env / "late-pack"
    pkg.mkdir()
    (pkg / frontmatter.SKILL_DOC_NAME).write_text(
        "---\nname: 迟到包\ndescription: 直增未注册\n---\n# 迟到包\n正文\n",
        encoding="utf-8")
    # 未注册：不进目录、不可解析（发现 ≠ 可加载）
    assert "迟到包" not in _pb(_base_state()).build_skill_catalog(_ctx())
    assert sd.resolve_skill_content("迟到包") == ("", "")
    # 注册后才可加载（下一次启动/接口保存等价路径）
    registry.sync_all(force=True)
    assert "迟到包" in _pb(_base_state()).build_skill_catalog(_ctx())
    assert sd.resolve_skill_content("迟到包")[0] == "迟到包"


# ---------- ⑤ 注册表空降级 ----------


async def test_registry_empty_degrades_gracefully(tmp_path, monkeypatch):
    """目录里只有坏包（全部注册失败）：目录空段跳过、read_skill 优雅报错、不阻断"""
    d = tmp_path / "skills"
    d.mkdir()
    monkeypatch.setattr(sd, "SKILL_DOCS_DIR", d)
    registry.reset_registry()
    pkg = d / "only-bad"
    pkg.mkdir()
    (pkg / frontmatter.SKILL_DOC_NAME).write_text(BAD_DOC, encoding="utf-8")
    registry.sync_all(force=True)
    try:
        assert registry.loadable_entries() == []
        assert _pb(_base_state()).build_skill_catalog(_ctx()) == ""
        res = await ListSkillsTool().aexecute(ListSkillsInput())
        assert res.success and res.data["count"] == 0
        r = await ReadSkillTool().aexecute(ReadSkillInput(name="任意"))
        assert not r.success and "未找到" in r.error and "无" in r.error
    finally:
        registry.reset_registry()


# ---------- ⑥ /api/skills 对齐 AI 可用性；/api/skills/docs 保磁盘全量 ----------


def test_api_skills_excludes_rejected_but_docs_keeps_full(portal_env):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from src.video_agent.web.routes import plugins as plugins_routes

    app = FastAPI()
    app.include_router(plugins_routes.router, prefix="/api")
    client = TestClient(app)

    resp = client.get("/api/plugins/ftdyb-agent/config")
    assert resp.status_code == 200, resp.text
    skills = resp.json()["skills"]
    slugs = {s["slug"] for s in skills}
    assert slugs == {"good-pack"}  # 对话栏不出现被拒包
    # 内容形状不变：system_prompt 仍为含 frontmatter 的磁盘全文（弹窗保存不抹声明头）
    for s in skills:
        assert s["system_prompt"].startswith("---") and "name:" in s["system_prompt"]

    resp2 = client.get("/api/skills/docs")
    assert resp2.status_code == 200, resp2.text
    doc_slugs = {d["slug"] for d in resp2.json()["docs"]}
    assert {"good-pack", "bad-pack"} <= doc_slugs  # 工作台仍可见坏包供修复


# ---------- ⑦ 16 包字节级目录快照 ----------


def test_sixteen_pack_catalog_byte_snapshot(tmp_path, monkeypatch):
    """空停用 + 全注册：build_skill_catalog 输出与改造前磁盘口径基线逐字节相等
    （基线固化 tests/fixtures/skill_catalog_golden.json，2026-08-30 探针验证）。
    数据面临时回挂真实 data/skills（16 包），避开测试镜像夹具桩。"""
    from src.video_agent.utils.paths import SKILL_DOCS_DIR as REAL_DIR

    monkeypatch.setattr(sd, "SKILL_DOCS_DIR", REAL_DIR)
    registry.reset_registry()
    registry.sync_all(force=True)
    try:
        assert len(registry.loadable_entries()) == 16, "存量 16 包须全注册（M1 口径）"
        golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
        actual = _pb(_base_state()).build_skill_catalog(_ctx())
        assert actual == golden["catalog"], "16 包目录段发生字节级漂移"
    finally:
        registry.reset_registry()
