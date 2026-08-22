"""PromptBuilder 注入模式（任务#36 B5 通用主路径）：
全文直注（≤阈值）/ 分级注入（超长）/ legacy 回退闸。"""
import pytest

import src.video_agent.web.skill_docs as sd
from src.video_agent.core.prompt_builder import PromptBuilder, GENERIC_FULL_INJECT_LIMIT


@pytest.fixture
def skills_dir(tmp_path, monkeypatch):
    d = tmp_path / "skills"
    d.mkdir()
    monkeypatch.setattr(sd, "SKILL_DOCS_DIR", d)
    return d


def _pb():
    return PromptBuilder(
        lambda: sd,
        lambda: "proj",
        lambda: {"keyElements": [], "shots": [], "audioItems": []},
    )


def test_generic_mode_injects_full_text_for_short_skill(skills_dir):
    """≤ 阈值：全文直注（含章节正文），不再有执行器清单形态"""
    sd.save_skill_doc(
        "演示4",
        "# 演示4\n> 调用规则：测试\n"
        "<script_analyze>\n分析\n</script_analyze>\n"
        "<storyboard_key_elements>\n关键元素\n</storyboard_key_elements>\n"
        "<write_media_prompt>\n提示词\n</write_media_prompt>\n",
    )
    block = _pb().build_selected_skill_block("演示4")
    assert "当前选中 Skill" in block
    # 全文直注：章节正文随全文在块内
    assert "关键元素" in block and "提示词" in block
    # 执行器清单形态已退役
    assert "已注册独立执行器" not in block


def test_generic_mode_tiered_injection_for_oversized_skill(skills_dir):
    """> 阈值：planner 章节全文 + 章节目录（标题+字符区间）+ 续读指令"""
    filler = "正文填充内容。" * 100  # 每章基础填充约 700 字
    sd.save_skill_doc(
        "超长流程",
        "# 超长流程\n> 调用规则：测试\n"
        f"<planner>\n流程总纲 UNIQUE_PLANNER_MARK\n{filler}</planner>\n"
        f"<storyboard_key_elements>\n关键元素规范 UNIQUE_KE_MARK\n{filler * 20}</storyboard_key_elements>\n"
        f"<write_media_prompt>\n提示词规范 UNIQUE_WP_MARK\n{filler * 20}</write_media_prompt>\n",
    )
    _, content = sd.resolve_skill_content("超长流程")
    assert len(content) > GENERIC_FULL_INJECT_LIMIT  # 前置：确实触发分级
    block = _pb().build_selected_skill_block("超长流程")
    # planner 章节全文注入
    assert "流程规划章节" in block and "UNIQUE_PLANNER_MARK" in block
    # 章节目录：标题 + 字符区间
    assert "章节目录" in block
    assert "storyboard_key_elements" in block and "write_media_prompt" in block
    assert "字）" in block
    # 续读指令
    assert "read_skill" in block
    # 非 planner 章节正文不整段注入（只出现在目录标题行）
    assert "UNIQUE_KE_MARK" not in block and "UNIQUE_WP_MARK" not in block


def test_generic_mode_tiered_fallback_without_planner(skills_dir):
    """超长且无 planner 章节：回落全文首段截断，保底不丢流程入口"""
    sd.save_skill_doc(
        "无章节超长",
        "# 无章节超长\n> 调用规则：测试\n" + "散文本。" * 8000,
    )
    _, content = sd.resolve_skill_content("无章节超长")
    assert len(content) > GENERIC_FULL_INJECT_LIMIT
    block = _pb().build_selected_skill_block("无章节超长")
    assert "正文首段" in block


def test_legacy_mode_injects_full_text_for_narrative_skill(skills_dir, set_global_setting):
    """legacy 回退闸：强制旧全文直注行为（事故回退保留）"""
    set_global_setting("skill_runtime", "legacy")
    sd.save_skill_doc(
        "叙述流程",
        "# 叙述流程\n> 调用规则：测试\nUNIQUE_MARKER_LEGACY 完整流程正文",
    )
    block = _pb().build_selected_skill_block("叙述流程")
    assert "当前选中 Skill" in block
    assert "UNIQUE_MARKER_LEGACY" in block
    assert "Skill 流程纪律" in block  # 外置纪律条款（prompts/planner/skill_discipline.md）


def test_executors_mode_deprecated_falls_back_to_generic(skills_dir, set_global_setting):
    """executors 值已弃用：按通用主路径执行（不返回空块）"""
    set_global_setting("skill_runtime", "executors")
    sd.save_skill_doc(
        "演示5",
        "# 演示5\n> 调用规则：测试\nUNIQUE_GENERIC_FALLBACK 正文",
    )
    block = _pb().build_selected_skill_block("演示5")
    assert "UNIQUE_GENERIC_FALLBACK" in block
    assert "已注册独立执行器" not in block


def test_stage_focus_block_legacy_only(skills_dir):
    """阶段聚焦块仅 legacy 路径保留（通用路径全文直注不叠加聚焦指针）"""
    sd.save_skill_doc(
        "流程",
        "# 流程\n> 调用规则：测试\n"
        "<planner>\n阶段逻辑：先分析 → document_write → 关键元素\n</planner>\n"
        "<script_analyze>\n分析\n</script_analyze>\n",
    )
    block = _pb().build_selected_skill_block("流程")
    assert "阶段逻辑" in block  # 随全文直注
    # 执行器形态专属段（已注册独立执行器/流程基线标题）已退役
    assert "已注册独立执行器" not in block
    assert "== 当前 Skill 的流程基线" not in block
