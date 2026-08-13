"""PromptBuilder 注入模式：executors（有章节）vs legacy（纯叙述文档）。"""
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


def test_executor_mode_injects_tools_not_full_text(skills_dir):
    sd.save_skill_doc(
        "演示4",
        "# 演示4\n> 调用规则：测试\n"
        "<script_analyze>\n分析\n</script_analyze>\n"
        "<storyboard_key_elements>\n关键元素\n</storyboard_key_elements>\n"
        "<write_media_prompt>\n提示词\n</write_media_prompt>\n",
    )
    block = _pb().build_selected_skill_block("演示4")
    assert "已注册独立执行器" in block
    assert "script_analyze" in block and "storyboard_key_elements" in block
    assert "write_media_prompt" in block
    # 章节全文不再注入主模型 system prompt
    assert "关键元素" not in block


def test_legacy_mode_injects_full_text_for_narrative_skill(skills_dir):
    sd.save_skill_doc(
        "叙述流程",
        "# 叙述流程\n> 调用规则：测试\nUNIQUE_MARKER_LEGACY 完整流程正文",
    )
    block = _pb().build_selected_skill_block("叙述流程")
    assert "当前选中 Skill" in block
    assert "UNIQUE_MARKER_LEGACY" in block
    assert "Skill 流程纪律" in block  # 外置纪律条款（prompts/planner/skill_discipline.md）


def test_planner_flow_baseline_injected(skills_dir):
    sd.save_skill_doc(
        "流程",
        "# 流程\n> 调用规则：测试\n"
        "<planner>\n阶段逻辑：先 script_analyze → document_write → storyboard_key_elements\n</planner>\n"
        "<script_analyze>\n分析\n</script_analyze>\n",
    )
    block = _pb().build_selected_skill_block("流程")
    assert "流程基线" in block
    assert "阶段逻辑" in block
