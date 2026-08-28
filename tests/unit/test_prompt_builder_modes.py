"""PromptBuilder 选中 Skill 段（任务#12 批次B：L2 注入路径退役后口径）。

钉死：选中 Skill 段只产出轻量状态提示（选中名称 + read_skill 按需加载
指引 + 元数据头），无论 Skill 长短，正文一律不进 system prompt；
全文直注/分级注入/回落截断三形态已整体退役。"""
import pytest

import src.video_agent.web.skill_docs as sd
from src.video_agent.core.prompt_builder import PromptBuilder


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


def test_selected_skill_block_is_lightweight_for_short_skill(skills_dir):
    """短 Skill：轻量状态提示，章节正文零注入"""
    sd.save_skill_doc(
        "演示4",
        "# 演示4\n> 调用规则：测试\n"
        "<script_analyze>\n分析\n</script_analyze>\n"
        "<storyboard_key_elements>\n关键元素\n</storyboard_key_elements>\n"
        "<write_media_prompt>\n提示词\n</write_media_prompt>\n",
    )
    block = _pb().build_selected_skill_block("演示4")
    assert "当前选中 Skill「演示4」" in block
    # read_skill 按需加载指引在场
    assert "read_skill" in block and "全文未注入" in block
    # 章节正文零注入
    assert "关键元素" not in block and "提示词" not in block
    # 历史注入形态措辞全部退役
    assert "已注册独立执行器" not in block
    assert "== 当前选中 Skill「演示4」全文" not in block


def test_selected_skill_block_is_lightweight_for_oversized_skill(skills_dir):
    """超长 Skill 同样只产出轻量状态提示（分级注入形态已退役）"""
    filler = "正文填充内容。" * 100
    sd.save_skill_doc(
        "超长流程",
        "# 超长流程\n> 调用规则：测试\n"
        f"<planner>\n流程总纲 UNIQUE_PLANNER_MARK\n{filler}</planner>\n"
        f"<storyboard_key_elements>\n关键元素规范 UNIQUE_KE_MARK\n{filler * 20}</storyboard_key_elements>\n"
        f"<write_media_prompt>\n提示词规范 UNIQUE_WP_MARK\n{filler * 20}</write_media_prompt>\n",
    )
    block = _pb().build_selected_skill_block("超长流程")
    assert "read_skill" in block and "全文未注入" in block
    # 分级注入三件套（章节全文/章节目录/首段回落）全部退役
    assert "UNIQUE_PLANNER_MARK" not in block
    assert "章节目录" not in block
    assert "正文首段" not in block
    # 任何章节正文都不进块
    assert "UNIQUE_KE_MARK" not in block and "UNIQUE_WP_MARK" not in block
    # 轻量块体量收敛（远低于历史全文/分级注入形态）
    assert len(block) < 800


def test_selected_skill_block_empty_for_unknown_skill(skills_dir):
    """不存在的 Skill：返空串（降级为仅目录）"""
    assert _pb().build_selected_skill_block("不存在") == ""


def test_selected_skill_block_empty_when_resolve_raises(skills_dir, monkeypatch):
    """解析异常不阻断对话：返空串（降级遥测可见）"""
    sd.save_skill_doc("炸桩", "# 炸桩\n正文")

    def boom(_name):
        raise RuntimeError("docs unavailable")

    monkeypatch.setattr(sd, "resolve_skill_content", boom)
    assert _pb().build_selected_skill_block("炸桩") == ""
