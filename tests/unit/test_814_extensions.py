"""814E1 钉死回归：通用章节执行器（0818 B4：依赖图调度通道退役）。"""
import json

import pytest

import src.video_agent.web.skill_docs as sd
from src.video_agent.skill_runtime import executors as ex_mod, registry
from src.video_agent.state.manager import StateManager
from src.video_agent.skill_runtime import exec_common
from src.video_agent.web import generation as gen_mod


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(sd, "SKILL_DOCS_DIR", tmp_path / "skills")
    registry.reset_registry()
    yield
    registry.reset_registry()


CUSTOM_SKILL = (
    "# 自定义章节 Skill\n> 调用规则：测试\n"
    "<planner>\n1. 读取并分析剧本 → **resource_prepare_and_analyze**\n"
    "2. 拆解分镜 → **storyboard_designer**\n依赖关系： 2→1\n</planner>\n"
    "<my_custom_tool>\n自定义章节规范：每个分组标题以 CUSTOM_ 开头。\n</my_custom_tool>\n"
)


class TestGenericSectionExecutor:
    def test_resolve_custom_tag_section(self):
        sd.save_skill_doc("custom", CUSTOM_SKILL)
        entry = registry.get_entry("custom")
        text = ex_mod._resolve_section_text(entry, "my_custom_tool")
        assert "CUSTOM_" in text, "白名单外自定义 tag 应能直取章节"
        # stage key 也能解析
        assert "依赖关系" in ex_mod._resolve_section_text(entry, "planning")
        # 不存在的章节返回空
        assert ex_mod._resolve_section_text(entry, "nope") == ""

    async def test_section_run_applies_actions(self, tmp_path, monkeypatch):
        sd.save_skill_doc("custom", CUSTOM_SKILL)
        svc = StateManager(str(tmp_path))
        monkeypatch.setattr(StateManager, "get_instance", classmethod(lambda cls: svc))
        monkeypatch.setattr(exec_common, "_resolve_chat_provider", lambda p="", m="": ("mockp", "mockm"))

        actions_json = json.dumps([
            {"action": "add_group", "group_type": "keyElement",
             "title": "CUSTOM_主角", "desc": "测试",
             "draft": {"label": "概念图", "mediaType": "image", "prompt": "x" * 90}},
        ], ensure_ascii=False)

        async def fake_chat(provider, model, messages, **kwargs):
            return f"```studio-actions\n{actions_json}\n```", "stop"

        monkeypatch.setattr(gen_mod, "call_chat_completion_stream", fake_chat)
        tool = ex_mod.SkillSectionRunTool()
        result = await tool.aexecute(ex_mod.SkillSectionRunInput(
            skill_name="自定义章节 Skill", section="my_custom_tool", task="拆关键元素",
        ))
        assert result.success is True
        assert result.data["applied"] >= 1
        titles = [g.get("title") for g in svc.state_dict.get("keyElements", [])]
        assert "CUSTOM_主角" in titles

    async def test_section_run_unknown_section_reports_available(self, tmp_path, monkeypatch):
        sd.save_skill_doc("custom", CUSTOM_SKILL)
        svc = StateManager(str(tmp_path))
        monkeypatch.setattr(StateManager, "get_instance", classmethod(lambda cls: svc))
        tool = ex_mod.SkillSectionRunTool()
        result = await tool.aexecute(ex_mod.SkillSectionRunInput(
            skill_name="自定义章节 Skill", section="nope", task="x",
        ))
        assert result.success is False
        assert "planning" in result.error
