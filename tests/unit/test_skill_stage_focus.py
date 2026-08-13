"""Skill 分阶段聚焦注入：章节解析、阶段探测、聚焦块生成"""
from src.video_agent.core.prompt_builder import PromptBuilder
from src.video_agent.web import skill_docs


# ---------- 章节解析 ----------

def test_split_sections_flova_tag_format():
    """flova 原生 <tag> 章节按工具名映射到制作阶段"""
    content = (
        "skill_name: demo\n"
        "<planner>\n阶段逻辑与依赖关系\n</planner>\n"
        "<storyboard_designer>\n故事板结构规范\n</storyboard_designer>\n"
        "<write_the_prompt>\n摄像机 → 主体 → 空间 → 音频\n</write_the_prompt>\n"
        "<media_generator>\n元素生成规范\n</media_generator>\n"
        "<video_assembler>\n组装导出\n</video_assembler>\n"
    )
    sections = skill_docs.split_skill_sections(content)
    assert "阶段逻辑" in sections["planning"]
    assert "故事板结构规范" in sections["storyboard_ke"]
    assert "故事板结构规范" in sections["storyboard_shot"]
    assert "故事板结构规范" in sections["storyboard_audio"]
    assert "摄像机" in sections["prompt_draft"]
    assert "元素生成规范" in sections["generation"]
    assert "组装导出" in sections["assembly"]


def test_split_sections_heading_fallback():
    """本地改写的标题式 Skill 按标题关键字兜底映射"""
    content = (
        "# 剧本生视频\n\n## 本系统动作约定\n动作清单\n\n"
        "## 流程规划（阶段逻辑与依赖关系）\n流程正文\n\n"
        "## 故事板设计规范\n分组规范\n\n## 生成规范\n生成正文\n\n"
        "## 提示词写法\n写法正文\n\n## 组装与导出\n组装正文\n"
    )
    sections = skill_docs.split_skill_sections(content)
    assert "流程正文" in sections["planning"]
    assert "分组规范" in sections["storyboard_ke"]
    assert "分组规范" in sections["storyboard_shot"]
    assert "分组规范" in sections["storyboard_audio"]
    assert "写法正文" in sections["prompt_draft"]
    assert "生成正文" in sections["generation"]
    assert "组装正文" in sections["assembly"]


def test_split_sections_empty():
    assert skill_docs.split_skill_sections("") == {}


# ---------- 阶段探测 ----------

def _pb(raw_state):
    return PromptBuilder(
        lambda: skill_docs,
        lambda: "proj",
        lambda: raw_state,
    )


def test_detect_stage_transitions():
    # 无分组 → 规格规划
    assert _pb({"keyElements": [], "shots": [], "audioItems": []}).detect_stage() == "planning"
    # 有分组无草稿 → 故事板结构
    state = {"keyElements": [{"id": "k", "title": "t", "drafts": []}], "shots": [], "audioItems": []}
    assert _pb(state).detect_stage() == "storyboard"
    # 草稿缺提示词 → 提示词草案
    state["keyElements"][0]["drafts"] = [{"id": "d", "prompt": ""}]
    assert _pb(state).detect_stage() == "prompt_draft"
    # 全部就绪 → 素材生成
    state["keyElements"][0]["drafts"][0]["prompt"] = "完整提示词"
    assert _pb(state).detect_stage() == "generation"


def test_detect_stage_disabled_without_state_accessor():
    pb = PromptBuilder(lambda: skill_docs, lambda: "proj")
    assert pb.detect_stage() == ""
    assert pb.build_stage_focus_block("任意内容") == ""


# ---------- 聚焦块注入 ----------

def test_no_focus_block_for_unmapped_skill():
    """无法解析章节的 Skill 不产生聚焦块（行为不变）"""
    state = {"keyElements": [], "shots": [], "audioItems": []}
    pb = _pb(state)
    focus = pb.build_stage_focus_block("# 随便一个文档\n没有任何可识别章节")
    assert focus == ""
