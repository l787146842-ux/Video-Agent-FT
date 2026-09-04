"""Skill 章节映射回归测试（阶段一 1.6：消灭三拆重构遗留的注册断层）。

覆盖：
- 旧 tag <storyboard_designer> 一对多映射到三个拆解 stage
- 标题式「故事板设计」一对多 + 关键元素/分镜/音频层精确子标题映射
- 未知 tag/标题不报错不注册
- lint_skill_content 警告项（空章节/三拆部分缺失/坏 gate_rules）
"""
import pytest

import src.video_agent.web.skill_docs as sd
from src.video_agent.skill_runtime import registry
from src.video_agent.web.skill_docs import (
    lint_skill_content,
    split_skill_sections,
)

_SPLIT_TOOLS = ("storyboard_key_elements", "storyboard_shots", "storyboard_audio")


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    """每个测试独立 Skill 目录 + 清空运行时注册表。"""
    monkeypatch.setattr(sd, "SKILL_DOCS_DIR", tmp_path / "skills")
    registry.reset_registry()
    yield
    registry.reset_registry()


# ---------- 1. 旧 tag 一对多映射 ----------

def test_legacy_storyboard_designer_tag_maps_to_all_split_stages():
    content = (
        "skill_name: \"demo\"\n"
        "<storyboard_designer>\n故事板整节规范\n</storyboard_designer>\n"
    )
    secs = split_skill_sections(content)
    for stage in ("storyboard_ke", "storyboard_shot", "storyboard_audio"):
        assert "故事板整节规范" in secs.get(stage, "")


def test_new_split_tags_map_independently():
    content = (
        "<storyboard_key_elements>\n元素节\n</storyboard_key_elements>\n"
        "<storyboard_shots>\n分镜节\n</storyboard_shots>\n"
        "<storyboard_audio>\n音频节\n</storyboard_audio>\n"
    )
    secs = split_skill_sections(content)
    assert "元素节" in secs["storyboard_ke"] and "分镜节" not in secs["storyboard_ke"]
    assert "分镜节" in secs["storyboard_shot"] and "元素节" not in secs["storyboard_shot"]
    assert "音频节" in secs["storyboard_audio"]


# ---------- 2. 标题式映射 ----------

def test_heading_storyboard_design_maps_to_all_split_stages():
    content = (
        "# 标题式\n> 调用规则：测试\n\n"
        "## 流程规划\n流程正文\n\n"
        "## 故事板设计\n故事板正文\n\n"
        "## 提示词写法\n写法正文\n"
    )
    secs = split_skill_sections(content)
    for stage in ("storyboard_ke", "storyboard_shot", "storyboard_audio"):
        assert "故事板正文" in secs.get(stage, "")
    assert "流程正文" in secs.get("planning", "")
    assert "写法正文" in secs.get("prompt_draft", "")


def test_heading_exact_subheadings_map_precisely():
    content = (
        "# 精确子标题\n\n"
        "## 关键元素\n元素正文\n\n"
        "## 分镜\n分镜正文\n\n"
        "## 音频层\n音频正文\n"
    )
    secs = split_skill_sections(content)
    assert "元素正文" in secs["storyboard_ke"] and "分镜正文" not in secs["storyboard_ke"]
    assert "分镜正文" in secs["storyboard_shot"]
    assert "音频正文" in secs["storyboard_audio"]


def test_prompt_heading_wins_over_storyboard_keyword():
    """「分镜提示词写法」应归 prompt_draft 而非 storyboard_shot（提示词关键字优先）"""
    content = "# x\n\n## 分镜提示词写法\n提示词正文\n"
    secs = split_skill_sections(content)
    assert "提示词正文" in secs.get("prompt_draft", "")
    assert "提示词正文" not in secs.get("storyboard_shot", "")


# ---------- 3. 注册结果（available_tools 完整性） ----------

def test_legacy_tag_skill_registers_all_split_executors():
    sd.save_skill_doc(
        "legacy-demo",
        "---\nname: legacy-demo\ndescription: 测试桩\n---\n"
        "skill_name: \"旧标签演示\"\n"
        "<planner>\n流程\n</planner>\n"
        "<storyboard_designer>\n故事板整节\n</storyboard_designer>\n"
        "<write_the_prompt>\n写法\n</write_the_prompt>\n",
    )
    entry = registry.get_entry("legacy-demo")
    assert entry is not None
    for tool in _SPLIT_TOOLS:
        assert tool in entry.available_tools
    # 整节对三个执行器同等注入
    for tool in _SPLIT_TOOLS:
        assert "故事板整节" in registry.tool_sections("legacy-demo", tool)


def test_heading_skill_registers_all_split_executors():
    sd.save_skill_doc(
        "heading-demo",
        "---\nname: heading-demo\ndescription: 测试桩\n---\n"
        "# 标题式演示\n> 调用规则：测试\n\n## 故事板设计\n故事板正文\n",
    )
    entry = registry.get_entry("heading-demo")
    assert entry is not None
    for tool in _SPLIT_TOOLS:
        assert tool in entry.available_tools


def test_unknown_tag_or_heading_registers_nothing_without_error():
    content = "<unknown_tool>\n正文\n</unknown_tool>\n"
    assert split_skill_sections(content) == {}
    sd.save_skill_doc("unknown-demo", "---\nname: unknown-demo\ndescription: 测试桩\n---\n# 未知\n> 调用规则：测试\n<unknown_tool>\n正文\n</unknown_tool>\n")
    entry = registry.get_entry("unknown-demo")
    assert entry is not None and entry.available_tools == []


# ---------- 4. lint_skill_content ----------

def test_lint_empty_sections_warns():
    lint = lint_skill_content("# 空\n> 调用规则：无章节\n纯正文\n")
    assert lint["available_tools"] == []
    # 任务#36 B5 后新措辞：无管线能力章节 = 自由型（全文直注，无阶段裁剪）
    assert any("未识别到任何管线能力章节" in w for w in lint["warnings"])


def test_lint_partial_split_warns_missing_executors():
    content = (
        "<storyboard_key_elements>\n元素节\n</storyboard_key_elements>\n"
    )
    lint = lint_skill_content(content)
    assert "storyboard_key_elements" in lint["available_tools"]
    assert any(
        "storyboard_shots" in w and "storyboard_audio" in w
        for w in lint["warnings"]
    )


def test_lint_full_flova_skill_has_no_structural_warnings():
    content = (
        "<planner>\n流程\n**何时暂停**：每阶段后\n</planner>\n"
        "<storyboard_designer>\n故事板\n</storyboard_designer>\n"
        "<media_generator>\n生成设定图与分镜视频\n</media_generator>\n"
        "<write_the_prompt>\n提示词写法规范\n</write_the_prompt>\n"
    )
    lint = lint_skill_content(content)
    for tool in _SPLIT_TOOLS:
        assert tool in lint["available_tools"]
    assert lint["warnings"] == []


# ---------- 5. A1/M4 两级制分节（## 优先，无 ## 回落 ###） ----------

def test_two_level_split_keeps_subheadings_inside_section():
    """全文有 ## 时：###/#### 不再单独切分，归入前一 ## 节正文。"""
    content = (
        "## 分镜设计\n正文甲\n### 子标题\n正文乙\n#### 更细子标题\n正文丙\n"
        "## 提示词写法\n正文丁\n"
    )
    got = split_skill_sections(content)
    assert sorted(got.keys()) == ["prompt_draft", "storyboard_shot"]
    assert "正文乙" in got["storyboard_shot"] and "正文丙" in got["storyboard_shot"]
    assert "子标题" not in got.get("storyboard_shot", "").split("\n")[0]


def test_two_level_split_falls_back_to_triple_hash():
    """全文无 ## 时：回落 ### 切点（宽容兼容旧式纯 ### 文档）。"""
    content = "### 分镜设计\n正文甲\n### 提示词写法\n正文乙\n"
    got = split_skill_sections(content)
    assert "storyboard_shot" in got and "prompt_draft" in got


def test_list_skill_sections_matches_split_two_level():
    """前后端等价性：list_skill_sections 与 split_skill_sections 同口径。"""
    from src.video_agent.web.skill_docs import list_skill_sections

    content = (
        "## 分镜设计\n正文甲\n### 子标题\n正文乙\n"
        "## 提示词写法\n正文丁\n"
    )
    titles = [s["title"] for s in list_skill_sections(content)]
    assert titles == ["分镜设计", "提示词写法"]
    # 区间拼接还原正文（与 split 同口径）
    for sec in list_skill_sections(content):
        assert sec["end"] >= sec["start"]

