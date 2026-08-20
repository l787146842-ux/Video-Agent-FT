"""规格向导消费：用户候选项机械落盘为规格文档（6666/1111 事故回归）。"""
import pytest

import src.video_agent.web.skill_docs as sd
from src.video_agent.core import prompt_gates
from src.video_agent.state.manager import StateManager
from src.video_agent.web.chat_service import _consume_spec_wizard


@pytest.fixture
def svc(tmp_path):
    return StateManager(str(tmp_path))


@pytest.fixture
def skills_dir(tmp_path, monkeypatch):
    d = tmp_path / "skills"
    d.mkdir()
    monkeypatch.setattr(sd, "SKILL_DOCS_DIR", d)
    sd.save_skill_doc(
        "向导技能",
        "# 向导技能\n> 调用规则：测试\n"
        "<script_analyze>\n分析\n</script_analyze>\n"
        "<storyboard_key_elements>\n关键元素\n</storyboard_key_elements>\n",
    )
    return d


def test_selections_write_spec_doc(svc, skills_dir, monkeypatch):
    """6666 二轮：向导只消费 Skill 软维度，规格文档不再写入硬参数。"""
    monkeypatch.setattr(
        prompt_gates, "skill_spec_dimensions",
        lambda skill: ["视频标题", "视觉风格"],
    )
    svc.state_dict["usedSkills"] = ["向导技能"]
    note, _name = _consume_spec_wizard(
        svc,
        "视觉风格：赛博朋克",
    )
    assert note and "Final_Video_Spec.md" in note
    docs = svc.state_dict.get("documents") or []
    assert any(prompt_gates.is_spec_doc_name(d.get("name") or "") for d in docs)
    content = next(d["content"] for d in docs if d.get("name") == "Final_Video_Spec.md")
    assert "- 视觉风格：赛博朋克" in content
    assert "- 视频标题：" + prompt_gates._PLACEHOLDER_DIM_VALUE in content  # 未选维度占位
    assert "图片分辨率" not in content
    assert "视频分辨率" not in content
    assert "分镜最大时长" not in content
    assert svc.state_dict["interaction"].get("spec_collected") is True


def test_plain_reply_without_selection_ignored(svc, skills_dir):
    svc.state_dict["usedSkills"] = ["向导技能"]
    assert _consume_spec_wizard(svc, "继续吧") == ("", "")
    assert not (svc.state_dict.get("documents") or [])
