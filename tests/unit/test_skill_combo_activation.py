# -*- coding: utf-8 -*-
"""任务 #11：Skill 组合激活（1 pipeline 可选 + N style 层）。

钉死：
1) style_skills_from_state 清洗：非空/去重保序/上限截断（非法结构空读）；
2) StateManager.set_style_skills 唯一写入点落盘项目态 styleSkills；
3) /api/skills/active-styles 端点：全量替换式清单——非存在 404、
   非 style 拒绝 400、与主流程同 slug 摘除、去重保序、上限截断、空清单全摘；
4) 主流程激活时若已在风格层清单内则摘除（同一 Skill 不得双占两层）；
5) build_style_combo 注入拼装：组合头文案（外置模板）+ 各风格层块、
   与主流程同 slug 兜底去重、无风格层空串（存量行为零变化）；
6) 组合超预算口径：先强制既有分级注入，仍超按清单顺序截断并留
   模型可见注记（不静默）。
"""
import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

import src.video_agent.web.skill_docs as sd
from src.video_agent.core import prompt_builder as pb_mod
from src.video_agent.core.prompt_builder import PromptBuilder
from src.video_agent.exceptions import VideoAgentError
from src.video_agent.skill_runtime import frontmatter, registry
from src.video_agent.state.manager import StateManager
from src.video_agent.web.routes import plugins


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(sd, "SKILL_DOCS_DIR", tmp_path / "skills")
    registry.reset_registry()
    yield
    registry.reset_registry()


@pytest.fixture
def svc(tmp_path):
    StateManager.reset_instance()
    instance = StateManager(str(tmp_path))
    StateManager._instance = instance
    yield instance
    StateManager.reset_instance()


def _save(name: str, content: str = "", manifest=None):
    sd.save_skill_doc(name, content or f"# {name}\n正文")
    if manifest is not None:
        frontmatter.write_manifest(name, manifest)
    registry.register_skill(name)


def _pb(raw_state):
    return PromptBuilder(lambda: sd, lambda: "proj", lambda: raw_state)


def _seed_combo_skills():
    # H1 与 slug 同口径（真实 Skill 同此），保证 entry.name 与清单 slug 一致
    _save("风格甲", "# 风格甲\n风格正文 MARK_STYLE_A", {"kind": "style"})
    _save("风格乙", "# 风格乙\n风格正文 MARK_STYLE_B", {"kind": "style"})
    _save("流程甲", "# 流程甲\n流程正文 MARK_PIPELINE_A", {"kind": "pipeline"})


# ---------- 1) style_skills_from_state 清洗 ----------

def test_style_skills_from_state_cleans():
    assert registry.style_skills_from_state(None) == []
    assert registry.style_skills_from_state({}) == []
    assert registry.style_skills_from_state({"styleSkills": "not-list"}) == []
    # 非空/去重保序
    out = registry.style_skills_from_state(
        {"styleSkills": [" a ", "", "b", "a", None, "c"]})
    assert out == ["a", "b", "c"]


def test_style_skills_from_state_caps_at_max():
    slugs = [f"s{i}" for i in range(registry.MAX_STYLE_LAYERS + 5)]
    out = registry.style_skills_from_state({"styleSkills": slugs})
    assert len(out) == registry.MAX_STYLE_LAYERS
    assert out == slugs[:registry.MAX_STYLE_LAYERS]


# ---------- 2) StateManager 唯一写入点 ----------

def test_set_style_skills_writes_project_state(svc):
    svc.set_style_skills(["a", "b"])
    assert svc.state_dict["styleSkills"] == ["a", "b"]
    svc.set_style_skills([])  # 空清单 = 摘除全部
    assert svc.state_dict["styleSkills"] == []
    svc.set_style_skills(None)
    assert svc.state_dict["styleSkills"] == []


# ---------- 3) /api/skills/active-styles 端点 ----------

class TestActiveStyleLayersEndpoint:
    @pytest.fixture
    def client(self, svc):
        app = FastAPI()
        app.include_router(plugins.router, prefix="/api")

        @app.exception_handler(VideoAgentError)
        async def _vae_handler(request, exc):  # noqa: ARG001
            return JSONResponse(status_code=exc.status_code, content={"message": str(exc)})

        return TestClient(app)

    def test_full_replace_writes_state(self, client, svc):
        _seed_combo_skills()
        r = client.post("/api/skills/active-styles",
                        json={"slugs": ["风格甲", "风格乙"]})
        assert r.status_code == 200
        assert r.json()["style_skills"] == ["风格甲", "风格乙"]
        assert svc.state_dict["styleSkills"] == ["风格甲", "风格乙"]
        used = svc.state_dict.get("usedSkills") or []
        assert "风格甲" in used and "风格乙" in used

    def test_unknown_slug_404(self, client, svc):
        _seed_combo_skills()
        r = client.post("/api/skills/active-styles", json={"slugs": ["不存在"]})
        assert r.status_code == 404
        assert "styleSkills" not in svc.state_dict

    def test_pipeline_slug_rejected_400(self, client, svc):
        _seed_combo_skills()
        r = client.post("/api/skills/active-styles", json={"slugs": ["流程甲"]})
        assert r.status_code == 400
        assert "styleSkills" not in svc.state_dict

    def test_primary_slug_skipped(self, client, svc):
        _seed_combo_skills()
        client.post("/api/skills/active", json={"slug": "风格甲"})
        r = client.post("/api/skills/active-styles",
                        json={"slugs": ["风格甲", "风格乙"]})
        assert r.status_code == 200
        assert r.json()["style_skills"] == ["风格乙"]

    def test_dedup_and_order_kept(self, client, svc):
        _seed_combo_skills()
        r = client.post("/api/skills/active-styles",
                        json={"slugs": ["风格乙", "风格乙", "风格甲"]})
        assert r.json()["style_skills"] == ["风格乙", "风格甲"]

    def test_cap_at_max_style_layers(self, client, svc):
        for i in range(registry.MAX_STYLE_LAYERS + 2):
            _save(f"层{i}", f"# 层{i}\n正文", {"kind": "style"})
        r = client.post("/api/skills/active-styles",
                        json={"slugs": [f"层{i}" for i in range(registry.MAX_STYLE_LAYERS + 2)]})
        assert r.status_code == 200
        assert len(r.json()["style_skills"]) == registry.MAX_STYLE_LAYERS

    def test_empty_list_clears_all(self, client, svc):
        _seed_combo_skills()
        client.post("/api/skills/active-styles", json={"slugs": ["风格甲"]})
        r = client.post("/api/skills/active-styles", json={"slugs": []})
        assert r.status_code == 200
        assert svc.state_dict["styleSkills"] == []

    def test_primary_activation_removes_style_layer(self, client, svc):
        """同一 Skill 不得双占两层：升为主流程时自风格层清单摘除。"""
        _seed_combo_skills()
        client.post("/api/skills/active-styles", json={"slugs": ["风格甲"]})
        r = client.post("/api/skills/active", json={"slug": "风格甲"})
        assert r.status_code == 200
        assert svc.state_dict["activeSkill"]["slug"] == "风格甲"
        assert svc.state_dict["styleSkills"] == []


# ---------- 4) build_style_combo 注入拼装 ----------

def test_combo_empty_when_no_style_skills():
    assert _pb({}).build_style_combo() == ""
    assert _pb({"styleSkills": []}).build_style_combo() == ""


def test_combo_assembles_header_and_blocks():
    _seed_combo_skills()
    raw = {"styleSkills": ["风格甲", "风格乙"]}
    block = _pb(raw).build_style_combo()
    # 外置模板头（计数与名单）
    assert "叠加风格层（2 个）" in block
    assert "风格甲" in block and "风格乙" in block
    # 各风格层正文都在（组合注入）
    assert "MARK_STYLE_A" in block and "MARK_STYLE_B" in block
    # 风格层语义（kind 差异化注入）
    assert "风格层" in block


def test_combo_dedup_against_primary():
    _seed_combo_skills()
    raw = {
        "activeSkill": {"slug": "风格甲", "source": "user"},
        "styleSkills": ["风格甲", "风格乙"],
    }
    block = _pb(raw).build_style_combo()
    assert "MARK_STYLE_B" in block
    assert block.count("MARK_STYLE_A") == 0


def test_combo_forced_tiered_when_over_budget(monkeypatch):
    """超观察线第一级兜底：全部风格层强制既有分级注入（不新造裁剪通道）。"""
    filler = "填充。" * 400
    _save(
        "大风格甲",
        f"# 大风格甲\n<planner>\n总纲 MARK_BIG_A_PLAN\n</planner>\n"
        f"<write_media_prompt>\n美学 MARK_BIG_A_WP\n{filler}</write_media_prompt>\n",
        {"kind": "style"},
    )
    monkeypatch.setattr(pb_mod, "STYLE_COMBO_SOFT_LIMIT", 1500)
    block = _pb({"styleSkills": ["大风格甲"]}).build_style_combo()
    # 分级注入形态：planner 章节全文 + 章节目录，其余章节不直注
    assert "章节目录" in block and "MARK_BIG_A_PLAN" in block
    assert "MARK_BIG_A_WP" not in block


def test_combo_truncates_with_model_visible_note(monkeypatch):
    """超观察线第二级兜底：按清单顺序截断，被截风格层留模型可见注记。"""
    _seed_combo_skills()
    monkeypatch.setattr(pb_mod, "STYLE_COMBO_SOFT_LIMIT", 400)
    block = _pb({"styleSkills": ["风格甲", "风格乙"]}).build_style_combo()
    assert "MARK_STYLE_A" in block
    assert "MARK_STYLE_B" not in block
    assert "暂缓注入" in block and "风格乙" in block
    assert "read_skill" in block


# ---------- 4.5) 组合空/异常路径（坏层不阻断、兜底返空） ----------

def test_combo_empty_when_raw_state_raises():
    """raw state 读取异常 → 返空串（存量行为零变化，不抛给调用方）。"""
    def boom():
        raise RuntimeError("state unavailable")
    assert PromptBuilder(lambda: sd, lambda: "proj", boom).build_style_combo() == ""


def test_combo_empty_when_only_primary_in_styles():
    """风格层清单仅含主流程同 slug → 兜底去重后返空串（不双注入）。"""
    _seed_combo_skills()
    raw = {
        "activeSkill": {"slug": "流程甲", "source": "user"},
        "styleSkills": ["流程甲"],
    }
    assert _pb(raw).build_style_combo() == ""


def test_combo_skips_missing_style_layers():
    """不存在/解析失败的风格层静默跳过，不阻断其余注入；全坏返空串。"""
    _seed_combo_skills()
    block = _pb({"styleSkills": ["不存在", "风格甲"]}).build_style_combo()
    assert "MARK_STYLE_A" in block and "不存在" not in block
    assert _pb({"styleSkills": ["不存在"]}).build_style_combo() == ""


def test_combo_kind_lookup_failure_falls_back_to_style(monkeypatch):
    """kind 查询抛异常 → 降级 style 口径，注入不中断。"""
    _seed_combo_skills()

    def boom(_slug):
        raise RuntimeError("registry broken")

    monkeypatch.setattr(registry, "skill_injection_kind", boom)
    block = _pb({"styleSkills": ["风格甲"]}).build_style_combo()
    assert "MARK_STYLE_A" in block


def test_combo_empty_when_forced_tiered_yields_nothing(monkeypatch):
    """超观察线强制分级后若全部块为空 → 返空串（不产出残壳）。"""
    _seed_combo_skills()
    monkeypatch.setattr(pb_mod, "STYLE_COMBO_SOFT_LIMIT", 5)
    builder = _pb({"styleSkills": ["风格甲"]})
    builder._build_one_style_block = (
        lambda slug, force_tiered=False: "" if force_tiered else "块内容")
    assert builder.build_style_combo() == ""


# ---------- 5) build_system_prompt 组合链路 ----------

def _ctx(skill_name: str):
    from src.video_agent.core.planner import PlannerContext
    ctx = PlannerContext()
    ctx.use_studio_context = True
    ctx.skill_name = skill_name
    return ctx


def test_system_prompt_combines_primary_and_styles():
    _seed_combo_skills()
    raw = {
        "keyElements": [], "shots": [], "audioItems": [],
        "activeSkill": {"slug": "流程甲", "source": "user"},
        "styleSkills": ["风格甲"],
    }
    text = _pb(raw).build_system_prompt(_ctx("流程甲"))
    assert "MARK_PIPELINE_A" in text and "MARK_STYLE_A" in text
    # 组合块拼在选中主流程块之后（同近生成端，风格层更靠后）
    assert text.index("MARK_PIPELINE_A") < text.index("MARK_STYLE_A")


def test_system_prompt_styles_only_without_primary():
    """1 pipeline 可选：无主流程时风格层单独生效。"""
    _seed_combo_skills()
    raw = {
        "keyElements": [], "shots": [], "audioItems": [],
        "styleSkills": ["风格甲"],
    }
    text = _pb(raw).build_system_prompt(_ctx(""))
    assert "MARK_STYLE_A" in text
