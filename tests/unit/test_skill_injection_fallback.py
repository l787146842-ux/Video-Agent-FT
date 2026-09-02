"""选中 Skill 注入行为测试。

任务#12 批次B：选中 Skill 全文硬注入退役；B1 裁决 2026-08-31：选中段改按需加载注入（<planner> 段全文 + 章节目录，其余经 read_skill 取读）；
流程规范由模型执行前调 read_skill 续读/读取（read_skill 门禁短路已随批次A 解除）。

4-4 双轨退役（协议单轨，决策史见 git tag adr-archive-20260901）：原 TestNonFcChannelFallback（非 FC 通道附件
全文直注）已随通道删除移除，替换为 CLI 聊天拦截断言（见文末）。

注：代码内置 Skill（编剧/分镜师/制片）已按用户要求彻底移除，
本测试全部使用文档 Skill（测试中为临时目录）。
"""
import pytest

import src.video_agent.web.skill_docs as skill_docs_mod
from src.video_agent.core.planner import Planner, PlannerContext
from src.video_agent.skill_runtime import registry

SKILL_MARKER = "SKILL_FLOW_MARKER_888"


@pytest.fixture
def doc_skill(tmp_path, monkeypatch):
    """临时文档 Skill 目录 + 一个测试 Skill（M2 门户：放行须可加载，
    带 frontmatter 必填键可注册 + 隔离注册表防污染）"""
    skill_dir = tmp_path / "skills"
    skill_dir.mkdir()
    monkeypatch.setattr(skill_docs_mod, "SKILL_DOCS_DIR", skill_dir)
    registry.reset_registry()
    skill_docs_mod.save_skill_doc(
        "demo-flow",
        "---\nname: 测试流程 Skill\ndescription: 测试桩\n---\n"
        f"# 测试流程 Skill\n> 调用规则：测试用\n<planner>\n{SKILL_MARKER} 完整流程正文\n</planner>",
    )
    yield skill_dir
    registry.reset_registry()


class TestSelectedSkillLightweightHint:
    """用户选中的 Skill 按需加载注入进 system prompt（B1：<planner> 段全文 +
    章节目录，其余章节经 read_skill 取读）"""

    def test_selected_skill_lightweight_hint_only(self, doc_skill):
        planner = Planner()
        ctx = PlannerContext(use_studio_context=False, skill_name="测试流程 Skill")
        prompt = planner._build_system_prompt(ctx)
        assert "当前选中 Skill" in prompt
        # read_skill 按需加载指引在场（目录段渐进披露口径）
        assert "read_skill" in prompt
        # B1：<planner> 段全文注入（正文片段在场）
        assert SKILL_MARKER in prompt, "选中 Skill 的 planner 段应注入"
        # 历史全文直注形态措辞已退役；「全文」字面仅允许来自《Skill 流程纪律》
        # 挂回块（用户内容，第 10 条"定稿全文写入"）与目录口径白名单短语，
        # 不得出现直注形态陈述（如"全文直注"）。
        assert "全文直注" not in prompt

    def test_fuzzy_selected_name_lightweight_hint(self, doc_skill):
        planner = Planner()
        ctx = PlannerContext(use_studio_context=False, skill_name="测试流程Skill.md")
        prompt = planner._build_system_prompt(ctx)
        # 模糊名解析后仍产出选中段，<planner> 段全文注入（B1）
        assert "当前选中 Skill" in prompt
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

