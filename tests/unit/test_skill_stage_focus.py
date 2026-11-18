"""Skill 章节解析与选中 Skill 段（本文件覆盖章节解析与正文预算注入回归，指令性制作手册口径，
决策史见 git tag adr-archive-20260901；
遥测/预算观察项钉测试见 test_prompt_single_injection_p317.py）。
章节解析（split_skill_sections）随任务#12 裁决保留：供阶段裁剪闸、
音频闸、lint、scan_skills 等探针消费，也供预算切分按章节边界切齐。"""
from src.video_agent.core.prompt_builder import PromptBuilder
from src.video_agent.web import skill_docs


# ---------- 章节解析 ----------

def test_split_sections_heading_only():
    """通用口径：只认 Markdown 标题，标签文本按普通正文处理。"""
    content = (
        "# demo\n\n"
        "## 制作流程\n阶段逻辑与依赖关系\n\n"
        "## 分镜\n故事板结构规范\n\n"
        "## 提示词写法\n摄像机 → 主体 → 空间 → 音频\n\n"
        "## 媒体生成\n元素生成规范\n\n"
        "## 组装导出\n组装导出\n"
    )
    sections = skill_docs.split_skill_sections(content)
    assert "阶段逻辑" in sections["planning"]
    assert "故事板结构规范" in sections["storyboard_shot"]
    assert "摄像机" in sections["prompt_draft"]
    assert "元素生成规范" in sections["generation"]
    assert "组装导出" in sections["assembly"]
    # 旧标签不再触发任何映射
    assert skill_docs.split_skill_sections(
        "<planner>\n流程\n</planner>\n") == {}


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


# ---------- 选中 Skill 段（指令性制作手册口径：正文预算化注入） ----------

def _pb(raw_state):
    return PromptBuilder(
        lambda: skill_docs,
        lambda: "proj",
        lambda: raw_state,
    )


def test_selected_block_is_pointer_only_for_user_only_skill():
    """2026-11-12：现存 Skill 全部 user-only；选中块只给用户触发说明，
    不注入正文（正文只在用户消息带 /slug 时一次性注入）。"""
    from src.video_agent.skill_runtime import registry

    registry.reset_registry()
    state = {"keyElements": [], "shots": [], "audioItems": []}
    pb = _pb(state)
    block = pb.build_selected_skill_block("AI-短剧一站式生成")
    assert "当前主 Skill" in block
    assert "用户专用" in block
    assert "read_file" in block
    assert "依赖关系" not in block
    assert "references/媒体生成.md" not in block
    assert "<planner>" not in block
    assert "已注册独立执行器" not in block


def test_unsectioned_skill_block_is_empty():
    """无可识别章节的 Skill 返回空串（目录仍常驻，模型可 read_skill）"""
    pb = _pb({"keyElements": [], "shots": [], "audioItems": []})
    assert pb.build_selected_skill_block("不存在的 Skill") == ""
