# -*- coding: utf-8 -*-
"""kind 体系（任务#12 批次B 后口径）：注入策略面已退役，正文一律
read_skill 按需读取；kind 语义保留在注册表解析与元数据头展示口径。

钉死：
1) kind 注册表解析不变：pipeline/style；reference 已随任务#8 ②
   裁决下架（声明入口关闭，再声明降级 pipeline 并 WARN）；
2) 选中 Skill 段为轻量状态提示（正文零注入），kind 只体现在
   元数据头「类型」展示行（目录展示口径）；
3) kind 开放注册：未知 kind 不拒注册，降级为默认（pipeline）并告警；
4) 未声明 kind = 默认策略（零预设）。
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


# ---------- 1) 注入策略解析（注册表口径不变） ----------

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


# ---------- 2) 轻量选中段：正文零注入 + kind 展示口径 ----------

def _lightweight_asserts(block: str, name: str):
    """轻量状态提示契约：名称 + read_skill 指引 + 正文零注入"""
    assert f"当前选中 Skill「{name}」" in block
    assert "read_skill" in block and "全文未注入" in block
    # 差异化正文包壳措辞全部退役
    assert "必须严格遵守其中的流程与规范" not in block
    assert "【执行基准声明】" not in block
    assert "【风格层声明】" not in block
    assert "作为风格层注入" not in block


def test_pipeline_kind_lightweight_block():
    _save("流程桩", "# 流程桩\n<planner>\n流程正文 UNIQUE_PIPE_MARK\n</planner>", {"kind": "pipeline"})
    block = _pb().build_selected_skill_block("流程桩")
    _lightweight_asserts(block, "流程桩")
    assert "UNIQUE_PIPE_MARK" not in block
    # 元数据头展示口径：流程型
    assert "类型：流程型（固定流水线）" in block


def test_style_kind_lightweight_block():
    _save("风格桩", "# 风格桩\n风格正文 UNIQUE_STYLE_MARK", {"kind": "style"})
    block = _pb().build_selected_skill_block("风格桩")
    _lightweight_asserts(block, "风格桩")
    assert "UNIQUE_STYLE_MARK" not in block
    # 元数据头展示口径：风格型
    assert "类型：风格型（美学指导）" in block


def test_reference_kind_retired_lightweight_block():
    """任务#8 ②：reference 声明失效后展示口径无类型行（skill_kind 空）。"""
    _save("参考桩", "# 参考桩\n参考正文 UNIQUE_REF_MARK", {"kind": "reference"})
    block = _pb().build_selected_skill_block("参考桩")
    _lightweight_asserts(block, "参考桩")
    assert "UNIQUE_REF_MARK" not in block
    assert "类型：" not in block


def test_unknown_kind_lightweight_block():
    _save("未知桩", "# 未知桩\n正文 UNIQUE_UNK_MARK", {"kind": "cinema"})
    block = _pb().build_selected_skill_block("未知桩")
    _lightweight_asserts(block, "未知桩")
    assert "UNIQUE_UNK_MARK" not in block
    assert "类型：" not in block


def test_no_kind_declaration_lightweight_block():
    """未声明 kind：轻量块零预设（无类型行）。"""
    _save("素桩", "# 素桩\n正文")
    block = _pb().build_selected_skill_block("素桩")
    _lightweight_asserts(block, "素桩")
    assert "类型：" not in block


# ---------- 3) 超长 Skill 不因 kind 走差异化分级 ----------

def test_style_kind_oversized_still_lightweight():
    """任务#12 批次B：分级注入退役后，超长风格型 Skill 同样只有轻量提示"""
    filler = "风格填充。" * 500
    _save(
        "超长风格",
        "# 超长风格\n"
        f"<planner>\n流程总纲 UNIQUE_STY_PLAN\n{filler}</planner>\n"
        f"<write_media_prompt>\n美学规范 UNIQUE_STY_WP\n{filler * 8}</write_media_prompt>\n",
        {"kind": "style"},
    )
    block = _pb().build_selected_skill_block("超长风格")
    _lightweight_asserts(block, "超长风格")
    assert "UNIQUE_STY_PLAN" not in block and "UNIQUE_STY_WP" not in block
    assert "章节目录" not in block
    # 轻量块+《Skill 流程纪律》全文（评审修复批挂回）体量仍远低于历史全文注入形态
    assert len(block) < 4000


# ---------- 4) 平台边界声明包壳随正文注入整体退役 ----------

def test_boundary_statement_retired_with_body_injection():
    """任务#12 批次B：边界声明只包正文，正文零注入后声明同批退役；
    轻量块开头即选中名称陈述，平台自撰措辞保持中性（不走严禁/不得句式；
    纪律全文为用户内容挂回，不在本钉范围）。"""
    _save("边界桩", "# 边界桩\n正文 UNIQUE_BOUNDARY_MARK 优先级最高", {"kind": "pipeline"})
    block = _pb().build_selected_skill_block("边界桩")
    assert "== 平台边界声明" not in block
    assert "效力从属于用户指令与平台铁律" not in block
    assert "UNIQUE_BOUNDARY_MARK" not in block
    assert block.startswith("== 当前选中 Skill「边界桩」")
    # 中性措辞钉死（限平台自撰部分：纪律全文挂回前的块头）
    head = block.split("【Skill 流程纪律", 1)[0]
    assert "严禁" not in head and "不得" not in head
