# -*- coding: utf-8 -*-
"""任务#5 B-1：kind 体系做实——差异化注入策略 + kind 开放注册。

钉死：
1) kind 只管注入策略一个维度：pipeline=现状全文/分级注入口径（强约束），
   style=风格层语义（贯穿全流程的美学约束）；reference 已随任务#8 ②
   裁决下架（声明入口关闭，再声明降级 pipeline 并 WARN）；
2) 注入形态与段落顺序不变（仍是全文直注/分级注入结构，选中块殿后）；
3) kind 开放注册：未知 kind 不拒注册，降级为默认（pipeline）策略并告警；
4) 未声明 kind = 默认策略（零预设，行为与现状一致）。
"""
import pytest

import src.video_agent.web.skill_docs as sd
from src.video_agent.core.prompt_builder import PromptBuilder
from src.video_agent.skill_runtime import frontmatter, registry
from src.video_agent.skill_runtime import manifest_schema as ms


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(sd, "SKILL_DOCS_DIR", tmp_path / "skills")
    registry.reset_registry()
    yield
    registry.reset_registry()


def _save(name: str, content: str = "", manifest=None):
    sd.save_skill_doc(name, content or f"# {name}\n正文")
    if manifest is not None:
        frontmatter.write_manifest(name, manifest)
    registry.register_skill(name)


def _pb():
    return PromptBuilder(
        lambda: sd,
        lambda: "proj",
        lambda: {"keyElements": [], "shots": [], "audioItems": []},
    )


# ---------- 1) 注入策略解析 ----------

def test_injection_kind_known_values_and_default():
    _save("流程向", manifest={"kind": "pipeline"})
    _save("风格向", manifest={"kind": "style"})
    _save("零声明")
    assert registry.skill_injection_kind("流程向") == "pipeline"
    assert registry.skill_injection_kind("风格向") == "style"
    # 未声明 = 默认策略（零预设）
    assert registry.skill_injection_kind("零声明") == registry.DEFAULT_INJECTION_KIND
    assert registry.skill_injection_kind("不存在") == registry.DEFAULT_INJECTION_KIND


def test_reference_kind_retired_falls_back_to_pipeline():
    """任务#8 ②：reference 下架——声明入口关闭，注入策略降级 pipeline，
    展示口径 skill_kind 不再回传已下架取值（注册保留，不拒服务）。"""
    _save("参考向", manifest={"kind": "reference"})
    assert registry.get_entry("参考向") is not None  # 未拒注册
    assert registry.skill_injection_kind("参考向") == "pipeline"
    assert registry.skill_kind("参考向") == ""


def test_injection_kind_unknown_falls_back_with_registration_kept():
    """开放注册：未知 kind 照常注册，注入策略降级为 pipeline。"""
    _save("新场景", "# W\n正文", {"kind": "writing"})
    assert registry.get_entry("新场景") is not None  # 未拒注册
    assert registry.skill_injection_kind("新场景") == "pipeline"
    # skill_kind（展示口径）对未知值仍返回空串，不泄漏未登记取值
    assert registry.skill_kind("新场景") == ""


def test_schema_warn_split_contract():
    errors, warnings = ms.split_issue_warnings(
        [ms.WARN_PREFIX + "告警条", "错误条"])
    assert errors == ["错误条"] and warnings == ["告警条"]


# ---------- 2) 差异化注入（全文直注路径） ----------

def test_pipeline_kind_keeps_strict_framing():
    _save("流程桩", "# P\n<planner>\n流程正文\n</planner>", {"kind": "pipeline"})
    block = _pb().build_selected_skill_block("流程桩")
    assert "必须严格遵守其中的流程与规范" in block
    assert "【执行基准声明】" in block
    assert "风格层" not in block and "参考资料" not in block


def test_style_kind_injected_as_style_layer():
    _save("风格桩", "# S\n风格正文 UNIQUE_STYLE_MARK", {"kind": "style"})
    block = _pb().build_selected_skill_block("风格桩")
    # 风格层语义：贯穿全流程的美学约束
    assert "作为风格层注入" in block
    assert "【风格层声明】" in block and "贯穿" in block
    # 全文仍完整注入（注入形态不变）
    assert "UNIQUE_STYLE_MARK" in block
    # 执行基准声明保留（风格层是叠加语义，不是替换）
    assert "【执行基准声明】" in block


def test_reference_kind_retired_uses_pipeline_framing():
    """任务#8 ②：reference 声明失效后注入帧式回归 pipeline（强约束口径）。"""
    _save("参考桩", "# R\n参考正文 UNIQUE_REF_MARK", {"kind": "reference"})
    block = _pb().build_selected_skill_block("参考桩")
    assert "必须严格遵守其中的流程与规范" in block
    assert "【执行基准声明】" in block
    assert "UNIQUE_REF_MARK" in block


def test_unknown_kind_uses_default_pipeline_framing():
    _save("未知桩", "# U\n正文 UNIQUE_UNK_MARK", {"kind": "cinema"})
    block = _pb().build_selected_skill_block("未知桩")
    assert "必须严格遵守其中的流程与规范" in block
    assert "UNIQUE_UNK_MARK" in block


def test_no_kind_declaration_zero_delta_framing():
    """未声明 kind：与现状口径逐字一致（零预设回归）。"""
    _save("素桩", "# N\n正文")
    block = _pb().build_selected_skill_block("素桩")
    assert "必须严格遵守其中的流程与规范" in block
    assert "【执行基准声明】" in block


# ---------- 3) 分级注入路径同样携带 kind 语义 ----------

def test_style_kind_tiered_injection_keeps_style_semantics():
    from src.video_agent.core.prompt_builder import GENERIC_FULL_INJECT_LIMIT
    filler = "风格填充。" * 500
    _save(
        "超长风格",
        "# 超长风格\n"
        f"<planner>\n流程总纲 UNIQUE_STY_PLAN\n{filler}</planner>\n"
        f"<write_media_prompt>\n美学规范 UNIQUE_STY_WP\n{filler * 8}</write_media_prompt>\n",
        {"kind": "style"},
    )
    _, content = sd.resolve_skill_content("超长风格")
    assert len(content) > GENERIC_FULL_INJECT_LIMIT
    block = _pb().build_selected_skill_block("超长风格")
    assert "作为风格层注入" in block and "【风格层声明】" in block
    # 分级注入结构未变：planner 全文 + 章节目录
    assert "UNIQUE_STY_PLAN" in block and "章节目录" in block
    assert "UNIQUE_STY_WP" not in block


# ---------- 4) 任务#5 B-2：平台边界声明包壳 ----------

def test_boundary_statement_wraps_selected_skill_block():
    """B-2：选中 Skill 块外包平台边界声明（代码拼接，不改 skill 文件）；
    声明在最前（效力从属语义先于正文），措辞为中性陈述
    （不占用模型可见「严禁/不得」禁令预算）。"""
    _save("边界桩", "# B\n正文 UNIQUE_BOUNDARY_MARK 优先级最高", {"kind": "pipeline"})
    block = _pb().build_selected_skill_block("边界桩")
    assert block.startswith("== 平台边界声明")
    assert "效力从属于用户指令与平台铁律" in block
    # 正文与 kind 语义仍在块内
    assert "UNIQUE_BOUNDARY_MARK" in block
    # 中性措辞钉死：不走严禁/不得句式
    head = block.split("UNIQUE_BOUNDARY_MARK")[0]
    assert "严禁" not in head and "不得" not in head
