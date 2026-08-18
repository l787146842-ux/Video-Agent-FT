"""回归测试 0818-3333：pipeline 调度回喂可见性 + 语言跟随契约。

事故：skill_pipeline_plan 返回值全是干货但回喂只给模型「执行成功」五字，
模型看不到批次信息连调 3 次空转（每轮白烧 8~20s 思考）；planner 模板缺
语言跟随契约（回复须跟随用户消息语言）。
"""
import asyncio
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


# ---------- C1：pipeline 调度回喂可见性 ----------


class TestPipelineDetailVisibility:
    def test_render_pipeline_detail_lists_done_and_ready(self):
        from src.video_agent.skill_runtime.exec_tools import render_pipeline_detail

        status = [
            {"step": 1, "title": "剧本分析", "done": True, "ready": False},
            {"step": 2, "title": "关键元素", "done": False, "ready": True},
            {"step": 3, "title": "分镜拆解", "done": False, "ready": False},
        ]
        detail = render_pipeline_detail(status, [status[1]])
        assert "剧本分析" in detail and "关键元素" in detail
        assert "下一可执行批次" in detail
        assert "分镜拆解" in detail

    def test_pipeline_plan_aexecute_attaches_detail(self, monkeypatch):
        """aexecute 必须带 detail（层 8 回喂可见性契约），掐掉盲重复调用。"""
        from src.video_agent.skill_runtime import exec_tools, dag, guard, registry

        status = [
            {"step": 1, "title": "剧本分析", "done": True, "ready": False},
            {"step": 2, "title": "关键元素", "done": False, "ready": True},
        ]
        monkeypatch.setattr(guard, "skill_planner_flow", lambda name: "1. 剧本分析\n2. 关键元素")
        monkeypatch.setattr(dag, "pipeline_status", lambda flow, state, cond=None: status)
        monkeypatch.setattr(dag, "parse_steps", lambda flow: {1: "剧本分析", 2: "关键元素"})
        monkeypatch.setattr(dag, "parse_dependencies", lambda flow: {})
        monkeypatch.setattr(dag, "topo_batches", lambda steps, deps: [[1], [2]])
        monkeypatch.setattr(registry, "resolve_entry", lambda name: None)

        class FakeSvc:
            state_dict = {}

        monkeypatch.setattr(exec_tools.StateManager, "get_instance", lambda: FakeSvc)

        from src.video_agent.skill_runtime.exec_common import SkillToolInput

        tool = exec_tools.SkillPipelinePlanTool()
        res = asyncio.run(tool.aexecute(SkillToolInput(skill_name="测试Skill")))
        assert res.success
        detail = res.data.get("detail", "")
        assert "下一可执行批次" in detail and "关键元素" in detail

    def test_feedback_carries_pipeline_detail(self):
        """层 8 回喂必须把 pipeline detail 原样带给模型（端到端钉契约）。"""
        from src.video_agent.core.fc_feedback import format_tool_results

        text = format_tool_results([{
            "name": "skill_pipeline_plan", "ok": True,
            "data": {"detail": "已完成：剧本分析; 未完成：关键元素; 下一可执行批次：关键元素"},
        }])
        assert "下一可执行批次：关键元素" in text


# ---------- C2：语言跟随契约（P3 单一事实源） ----------


class TestLanguageContract:
    def test_language_template_exists_with_rule(self):
        lang = (ROOT / "prompts" / "shared" / "language.md").read_text(encoding="utf-8")
        assert "跟随用户" in lang or "用户最新一条消息的语言" in lang

    @pytest.mark.parametrize("tpl", ["planner/system.md", "planner/system_fc.md"])
    def test_planner_templates_include_language(self, tpl):
        text = (ROOT / "prompts" / tpl).read_text(encoding="utf-8")
        assert "shared/language.md" in text, f"{tpl} 未 include 语言规则（P3 单一事实源）"
