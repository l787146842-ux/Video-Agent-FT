"""选中 Skill 硬注入测试。

背景（888 项目事故）：若 Skill 与剧本只给目录/预览，模型等于看不到
流程规范与原文，产出质量直接劣化——选中 Skill 必须全文硬注入。

4-4 双轨退役（ADR-0001）：原 TestNonFcChannelFallback（非 FC 通道附件
全文直注）已随通道删除移除，替换为 CLI 聊天拦截断言（见文末）。

注：代码内置 Skill（编剧/分镜师/制片）已按用户要求彻底移除，
本测试全部使用文档 Skill（测试中为临时目录）。
"""
import pytest

import src.video_agent.web.skill_docs as skill_docs_mod
from src.video_agent.core.planner import Planner, PlannerContext

SKILL_MARKER = "SKILL_FLOW_MARKER_888"


@pytest.fixture
def doc_skill(tmp_path, monkeypatch):
    """临时文档 Skill 目录 + 一个测试 Skill"""
    skill_dir = tmp_path / "skills"
    skill_dir.mkdir()
    monkeypatch.setattr(skill_docs_mod, "SKILL_DOCS_DIR", skill_dir)
    skill_docs_mod.save_skill_doc(
        "demo-flow", f"# 测试流程 Skill\n> 调用规则：测试用\n{SKILL_MARKER} 完整流程正文",
    )
    return skill_dir


class TestSelectedSkillHardInjection:
    """用户选中的 Skill 必须全文进 system prompt（不依赖模型自觉调 read_skill）"""

    def test_selected_skill_full_text_injected(self, doc_skill):
        planner = Planner()
        ctx = PlannerContext(use_studio_context=False, skill_name="测试流程 Skill")
        prompt = planner._build_system_prompt(ctx)
        assert "当前选中 Skill" in prompt
        assert SKILL_MARKER in prompt, "选中 Skill 全文未注入 system prompt"
        # 流程纪律强化段：针对 888 项目事故（模型读到了 Skill 却一口气做完全部阶段）
        assert "Skill 流程纪律" in prompt
        assert "workflow_pause" in prompt
        # 纪律条款必须来自外置文件（宪法 Rule 6 单一事实源），而不是代码硬编码
        assert "不默认" in prompt

    def test_fuzzy_selected_name_still_injected(self, doc_skill):
        planner = Planner()
        ctx = PlannerContext(use_studio_context=False, skill_name="测试流程Skill.md")
        prompt = planner._build_system_prompt(ctx)
        assert SKILL_MARKER in prompt

    def test_no_selection_only_catalog(self, doc_skill):
        planner = Planner()
        ctx = PlannerContext(use_studio_context=False, skill_name="")
        prompt = planner._build_system_prompt(ctx)
        assert "当前选中 Skill" not in prompt
        assert "Skill 目录" in prompt
        # 目录里只列名称与摘要，不含全文
        assert SKILL_MARKER not in prompt

    def test_unknown_skill_falls_back_to_catalog(self, doc_skill):
        planner = Planner()
        ctx = PlannerContext(use_studio_context=False, skill_name="不存在的技能")
        prompt = planner._build_system_prompt(ctx)
        assert "当前选中 Skill" not in prompt

    def test_catalog_contains_no_code_skills(self, doc_skill):
        """代码内置 Skill（编剧/分镜师/制片）已彻底移除，不得出现在 Skill 目录"""
        planner = Planner()
        ctx = PlannerContext(use_studio_context=False, skill_name="")
        prompt = planner._build_system_prompt(ctx)
        for banned in ("编剧 Agent", "分镜师 Agent", "制片 Agent"):
            assert banned not in prompt, f"{banned} 不应再出现在 Skill 目录"


class TestCliChatRejected:
    """4-4 双轨退役：CLI 供应商不再承载聊天，选中即报人话错误。"""

    def test_cli_provider_chat_raises_friendly_error(self, monkeypatch):
        from src.video_agent.exceptions import AdapterError
        from src.video_agent.web import chat_opening as co

        monkeypatch.setattr(
            co, "get_provider_config",
            lambda pid: {"protocol": "gemini-cli"} if pid == "agy-x" else {"protocol": "openai"},
        )
        with pytest.raises(AdapterError, match="不支持聊天"):
            co._create_chat_adapter("agy-x", "auto")

