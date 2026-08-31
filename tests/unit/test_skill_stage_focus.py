"""Skill 章节解析与选中 Skill 段（本文件覆盖章节解析与正文预算注入回归，批4/ADR-0007；
遥测/预算观察项钉测试见 test_prompt_single_injection_p317.py）。
章节解析（split_skill_sections）随任务#12 裁决保留：供阶段裁剪闸、
音频闸、lint、scan_skills 等探针消费，也供预算切分按章节边界切齐。"""
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


# ---------- 选中 Skill 段（批4/ADR-0007：正文预算化注入） ----------

def _pb(raw_state):
    return PromptBuilder(
        lambda: skill_docs,
        lambda: "proj",
        lambda: raw_state,
    )


def test_selected_block_planner_only_for_real_skill():
    """B1 裁决：真实存量 Skill 选中后默认只注入 <planner> 段全文 + 章节目录，
    其余章节正文经 read_skill 按需取读；执行器清单形态与全文硬直注形态措辞保持退役。"""
    from src.video_agent.skill_runtime import registry

    registry.reset_registry()  # 隔离：确保按真实 data/skills 目录重新注册
    state = {"keyElements": [], "shots": [], "audioItems": []}
    pb = _pb(state)
    block = pb.build_selected_skill_block("AI-短剧一站式生成")
    # 选中提示 + 取读指引在场（按需加载口径）
    assert "当前选中 Skill" in block and "read_skill" in block
    assert "正文头部到此为止" not in block  # 预算续读指引退役
    # planner 段探针在场；其余章节正文探针零注入（只进目录）
    assert "启动协议" in block
    assert "**导出基准**" not in block
    # 历史注入形态措辞保持退役（压制性包壳同批退役）
    assert "已注册独立执行器" not in block
    assert "== 当前 Skill 的流程基线" not in block


def test_unsectioned_skill_block_is_empty():
    """无可识别章节的 Skill 返回空串（目录仍常驻，模型可 read_skill）"""
    pb = _pb({"keyElements": [], "shots": [], "audioItems": []})
    assert pb.build_selected_skill_block("不存在的 Skill") == ""
