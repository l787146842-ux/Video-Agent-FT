"""外来 Skill 工具名自动映射回归测试（审计修复：888 项目事故）。

背景：第三方平台工作流直译的 Skill 引用本系统不存在的工具名
（write_media_prompt / media_generator / reply_to_user 等），模型只能
近似映射导致阶段纪律失真。修复：注入时检测已知外来词汇并追加对照表。

覆盖：
- build_foreign_tool_note 检测/不误判字段名
- 选中 Skill 硬注入块附带映射表
- read_skill 工具返回内容附带映射表
- 真实 Skill 文档：已恢复 flova 原版文字，标题行可解析、外来工具名自动映射
"""
import pytest

import src.video_agent.web.skill_docs as skill_docs_mod
from src.video_agent.core.planner import Planner, PlannerContext
from src.video_agent.tools.document_tools import ReadSkillInput, ReadSkillTool
from src.video_agent.web.skill_docs import build_foreign_tool_note


@pytest.fixture
def foreign_skill(tmp_path, monkeypatch):
    """临时 Skill 目录：一份引用外来工具名的文档"""
    skill_dir = tmp_path / "skills"
    skill_dir.mkdir()
    monkeypatch.setattr(skill_docs_mod, "SKILL_DOCS_DIR", skill_dir)
    skill_docs_mod.save_skill_doc(
        "foreign-flow",
        "# 外来回流测试\n> 调用规则：测试用\n"
        "步骤 3 调用 storyboard_designer 建故事板；步骤 4 用 write_media_prompt 写提示词；"
        "生成用 media_generator；暂停用 reply_to_user。字段如 element_id、shot_id 不是工具。",
    )
    return skill_dir


class TestForeignToolDetection:
    def test_known_foreign_names_detected(self):
        note = build_foreign_tool_note("先 write_media_prompt 再 media_generator")
        assert "外来工具名映射" in note
        assert "write_media_prompt" in note and "media_generator" in note
        # 映射目标必须是本系统真实动作
        assert "patch.prompt" in note
        assert "generate_image" in note

    def test_no_foreign_names_returns_empty(self):
        assert build_foreign_tool_note("用 storyboard_patch_draft 写入提示词，然后 workflow_pause") == ""
        assert build_foreign_tool_note("") == ""

    def test_field_names_not_misjudged(self):
        """element_id/shot_id/audio_id 等字段名不得被误判为外来工具"""
        note = build_foreign_tool_note("为每个 element_id 与 shot_id 编写提示词，audio_id 同理")
        assert note == ""


class TestSelectedSkillInjectionWithMapping:
    def test_hard_injection_appends_mapping_note(self, foreign_skill):
        planner = Planner()
        ctx = PlannerContext(use_studio_context=False, skill_name="外来回流测试")
        prompt = planner._build_system_prompt(ctx)
        assert "当前选中 Skill" in prompt
        assert "外来工具名映射" in prompt
        assert "reply_to_user" in prompt and "workflow_pause" in prompt

    def test_localized_skill_gets_no_note(self, tmp_path, monkeypatch):
        skill_dir = tmp_path / "skills"
        skill_dir.mkdir()
        monkeypatch.setattr(skill_docs_mod, "SKILL_DOCS_DIR", skill_dir)
        skill_docs_mod.save_skill_doc(
            "local-flow", "# 本地流程\n> 调用规则：测试用\n用 storyboard_patch_draft 写提示词。",
        )
        planner = Planner()
        ctx = PlannerContext(use_studio_context=False, skill_name="本地流程")
        prompt = planner._build_system_prompt(ctx)
        assert "外来工具名映射" not in prompt


class TestReadSkillToolWithMapping:
    async def test_read_skill_content_has_mapping_note(self, foreign_skill):
        tool = ReadSkillTool()
        result = await tool.aexecute(ReadSkillInput(name="外来回流测试"))
        assert result.success
        content = result.data["content"]
        assert "外来工具名映射" in content
        assert "media_generator" in content
