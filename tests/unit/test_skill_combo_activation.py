# -*- coding: utf-8 -*-
"""任务 #11：Skill 组合激活（1 pipeline 可选 + N style 层）。

钉死：
1) style_skills_from_state 清洗：非空/去重保序/上限截断（非法结构空读）；
2) StateManager.set_style_skills 唯一写入点落盘项目态 styleSkills；
3) /api/skills/active-styles 端点：全量替换式清单——非存在 404、
   非 style 拒绝 400、与主流程同 slug 摘除、去重保序、上限截断、空清单全摘；
4) 主流程激活时若已在风格层清单内则摘除（同一 Skill 不得双占两层）；
5) 任务#12 批次B：组合注入（build_style_combo）退役——风格层只在
   Skill 目录段可见（名称提示 + read_skill 按需读取指引），正文零注入。
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
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    monkeypatch.setattr(sd, "SKILL_DOCS_DIR", skills_dir)
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
    content = content or f"# {name}\n正文"
    if manifest is None:
        # 批3：name/description 注册期必填，零预设仍带最小声明头
        sd.save_skill_doc(
            name, f"---\nname: {name}\ndescription: 测试桩\n---\n" + content)
    else:
        sd.save_skill_doc(name, content)
        frontmatter.write_manifest(
            name, {"name": name, "description": "测试桩", **manifest})
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


# ---------- 4) 组合注入退役：风格层只在目录段可见（任务#12 批次B） ----------

def test_combo_injection_api_retired():
    """build_style_combo/_build_one_style_block/STYLE_COMBO_SOFT_LIMIT
    已随任务#12 批次B 退役，模块不再暴露这些符号。"""
    assert not hasattr(pb_mod, "build_style_combo")
    assert not hasattr(PromptBuilder, "build_style_combo")
    assert not hasattr(PromptBuilder, "_build_one_style_block")
    assert not hasattr(pb_mod, "STYLE_COMBO_SOFT_LIMIT")


def test_catalog_notes_style_layers_without_body():
    """风格层叠加时目录段同步告知（名称在场 + 正文零注入指引）。"""
    _seed_combo_skills()
    raw = {"styleSkills": ["风格甲", "风格乙"]}
    ctx = _ctx("")
    block = _pb(raw).build_skill_catalog(ctx)
    assert "另有风格层叠加生效" in block
    assert "风格甲" in block and "风格乙" in block
    assert "read_skill" in block
    # 风格层正文零注入
    assert "MARK_STYLE_A" not in block and "MARK_STYLE_B" not in block


def test_catalog_style_note_absent_without_style_skills():
    _save("垫底", "# 垫底\n正文")  # 避免空目录触发默认文档生成探针
    block = _pb({}).build_skill_catalog(_ctx(""))
    assert "另有风格层叠加生效" not in block
    block2 = _pb({"styleSkills": []}).build_skill_catalog(_ctx(""))
    assert "另有风格层叠加生效" not in block2


def test_catalog_style_note_survives_bad_state():
    """raw state 读取异常 → 目录段照常产出（风格层注记静默省略）。"""
    _save("垫底", "# 垫底\n正文")
    def boom():
        raise RuntimeError("state unavailable")
    block = PromptBuilder(lambda: sd, lambda: "proj", boom).build_skill_catalog(_ctx(""))
    assert "Skill 目录" in block
    assert "另有风格层叠加生效" not in block


def test_catalog_style_note_skips_missing_layers():
    """不存在的风格层：目录段仍标注清单内名称，坏层不阻断。"""
    _seed_combo_skills()
    block = _pb({"styleSkills": ["不存在", "风格甲"]}).build_skill_catalog(_ctx(""))
    assert "风格甲" in block


# ---------- 5) build_system_prompt 组合链路 ----------

def _ctx(skill_name: str):
    from src.video_agent.core.planner import PlannerContext
    ctx = PlannerContext()
    ctx.use_studio_context = True
    ctx.skill_name = skill_name
    return ctx


def test_system_prompt_combo_body_zero_injection():
    """任务#12 批次B：1 pipeline + N style 层组合激活后，主流程与风格层
    正文都不进 system prompt；风格层只在目录段以名称可见。"""
    _seed_combo_skills()
    raw = {
        "keyElements": [], "shots": [], "audioItems": [],
        "activeSkill": {"slug": "流程甲", "source": "user"},
        "styleSkills": ["风格甲"],
    }
    text = _pb(raw).build_system_prompt(_ctx("流程甲"))
    # 正文零注入（主流程与风格层都不例外）
    assert "MARK_PIPELINE_A" not in text
    assert "MARK_STYLE_A" not in text
    # 目录段：主流程选中提示 + 风格层名称都在，配 read_skill 指引
    assert "当前选中 Skill" in text and "read_skill" in text
    assert "另有风格层叠加生效" in text and "风格甲" in text


def test_system_prompt_styles_only_without_primary():
    """1 pipeline 可选：无主流程时风格层单独生效（同样只在目录可见）。"""
    _seed_combo_skills()
    raw = {
        "keyElements": [], "shots": [], "audioItems": [],
        "styleSkills": ["风格甲"],
    }
    text = _pb(raw).build_system_prompt(_ctx(""))
    assert "MARK_STYLE_A" not in text
    assert "另有风格层叠加生效" in text and "风格甲" in text
