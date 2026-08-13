"""Skill 章节解析与执行器注入块（M5：legacy 全文注入/阶段聚焦已移除，
本文件只保留章节解析与 executors 注入块的回归测试）"""
from src.video_agent.core.prompt_builder import PromptBuilder
from src.video_agent.web import skill_docs


# ---------- 章节解析 ----------

def test_split_sections_flova_tag_format():
    """flova 原生 <tag> 章节按工具名映射到制作阶段"""
    content = (
        "skill_name: demo\n"
        "<planner>\n阶段逻辑与依赖关系\n</planner>\n"
        "<storyboard_shots>\n故事板结构规范\n</storyboard_shots>\n"
        "<write_the_prompt>\n摄像机 → 主体 → 空间 → 音频\n</write_the_prompt>\n"
        "<media_generator>\n元素生成规范\n</media_generator>\n"
        "<video_assembler>\n组装导出\n</video_assembler>\n"
    )
    sections = skill_docs.split_skill_sections(content)
    assert "阶段逻辑" in sections["planning"]
    assert "故事板结构规范" in sections["storyboard_shot"]
    assert "摄像机" in sections["prompt_draft"]
    assert "元素生成规范" in sections["generation"]
    assert "组装导出" in sections["assembly"]


def test_split_sections_heading_fallback():
    """本地改写的标题式 Skill 按标题关键字兜底映射；
    「故事板设计」一对多映射到三个拆解 stage（三拆注册断层修复）"""
    content = (
        "# 剧本生视频\n\n## 本系统动作约定\n动作清单\n\n"
        "## 流程规划（阶段逻辑与依赖关系）\n流程正文\n\n"
        "## 故事板设计规范\n分组规范\n\n## 生成规范\n生成正文\n\n"
        "## 提示词写法\n写法正文\n\n## 组装与导出\n组装正文\n"
    )
    sections = skill_docs.split_skill_sections(content)
    assert "流程正文" in sections["planning"]
    for stage in ("storyboard_ke", "storyboard_shot", "storyboard_audio"):
        assert "分组规范" in sections[stage]
    assert "写法正文" in sections["prompt_draft"]
    assert "生成正文" in sections["generation"]
    assert "组装正文" in sections["assembly"]


def test_split_sections_empty():
    assert skill_docs.split_skill_sections("") == {}


# ---------- 执行器注入块（executors 唯一形态） ----------

def _pb(raw_state):
    return PromptBuilder(
        lambda: skill_docs,
        lambda: "proj",
        lambda: raw_state,
    )


def test_executor_runtime_block_instead_of_full_text():
    """只注入已注册执行器清单 + 流程基线，不注入 Skill 全文"""
    from src.video_agent.skill_runtime import registry

    registry.reset_registry()  # 隔离：确保按真实 data/skills 目录重新注册
    state = {"keyElements": [], "shots": [], "audioItems": []}
    pb = _pb(state)
    block = pb.build_selected_skill_block("AI-短剧一站式生成")
    assert "已注册独立执行器" in block
    for tool in ("script_analyze", "storyboard_key_elements", "storyboard_shots",
                 "storyboard_audio", "write_media_prompt", "audio_generate", "video_assembler"):
        assert tool in block
    # 全文不注入（章节在执行器调用时自动注入）
    assert "Seedance 顺序" not in block


def test_unsectioned_skill_block_is_empty():
    """无可识别章节的 Skill 返回空串（目录仍常驻，模型可 read_skill）"""
    pb = _pb({"keyElements": [], "shots": [], "audioItems": []})
    assert pb.build_selected_skill_block("不存在的 Skill") == ""
