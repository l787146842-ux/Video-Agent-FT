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


