"""回归测试 0818-1111b：空参读文档自动归位 + 空输出引导续写 + 阶段同批声明翻译。

事故：1111 实测——模型空参试探 read_uploaded_doc 烧一轮；auto_retry 盲重跑
翻倍成本；skill_pipeline_plan 只回步骤号，「step3=三拆解同阶段」分组不可见，
模型拆完关键元素就暂停且把下一步说成编写提示词。
"""
import asyncio
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


# ---------- D1：read_uploaded_doc 单文档自动归位 ----------


class TestUploadedDocAutoResolve:
    def test_single_doc_empty_name_auto_resolves(self):
        from src.video_agent.tools.document_tools import _resolve_uploaded_doc

        docs = [{"id": "d1", "name": "三体简短版.md", "content": "正文"}]
        target, note = _resolve_uploaded_doc(docs, "", "")
        assert target and target["name"] == "三体简短版.md"
        assert "自动归位" in note

    def test_multi_doc_empty_name_still_errors(self):
        from src.video_agent.tools.document_tools import _resolve_uploaded_doc

        docs = [{"id": "d1", "name": "a.md"}, {"id": "d2", "name": "b.md"}]
        target, note = _resolve_uploaded_doc(docs, "", "")
        assert target is None and note == ""

    def test_aexecute_empty_name_single_doc_succeeds(self, monkeypatch):
        from src.video_agent.tools import document_tools as dt

        class FakeSvc:
            state_dict = {"uploadedDocs": [{"id": "d1", "name": "三体简短版.md", "content": "剧本正文"}]}

        monkeypatch.setattr(dt.StateManager, "get_instance", lambda: FakeSvc)
        tool = dt.ReadUploadedDocTool()
        res = asyncio.run(tool.aexecute(dt.ReadUploadedDocInput(name="")))
        assert res.success
        assert "自动归位" in res.data["content"]


# ---------- D2：auto_retry 引导续写 ----------


class TestBadOutputNudge:
    def test_nudge_requires_visible_output(self):
        from src.video_agent.core.agent_loop import _bad_output_nudge

        text = _bad_output_nudge(1)
        assert "工具调用" in text and "思考" in text


# ---------- D3：阶段同批声明翻译（P3 单一事实源） ----------


STAGE_MANIFEST = {"flow": {"stage_executors": {
    "1": ["script_analyze"],
    "3": ["storyboard_key_elements", "storyboard_shots", "storyboard_audio"],
}}}


class TestStageExecutorsDeclaration:
    def test_registry_parses_stage_executors(self, monkeypatch):
        from src.video_agent.skill_runtime import registry

        monkeypatch.setattr(registry, "skill_manifest_of", lambda name: STAGE_MANIFEST)
        stages = registry.skill_stage_executors("任意Skill")
        assert stages["3"] == ["storyboard_key_elements", "storyboard_shots", "storyboard_audio"]

    def test_registry_undeclared_returns_empty(self, monkeypatch):
        from src.video_agent.skill_runtime import registry

        monkeypatch.setattr(registry, "skill_manifest_of", lambda name: None)
        assert registry.skill_stage_executors("任意Skill") == {}

    def test_stage_done_requires_all_executors(self):
        from src.video_agent.skill_runtime.exec_tools import _stage_done_by_executors

        exs = ["storyboard_key_elements", "storyboard_shots", "storyboard_audio"]
        full = {"keyElements": [1], "shots": [1], "audioItems": [1]}
        partial = {"keyElements": [1], "shots": [], "audioItems": []}
        assert _stage_done_by_executors(exs, full) is True
        assert _stage_done_by_executors(exs, partial) is False
        assert _stage_done_by_executors(["unknown_tool"], full) is None

    def test_detail_surfaces_same_batch_grouping(self):
        from src.video_agent.skill_runtime.exec_tools import render_pipeline_detail

        status = [{
            "step": 3, "title": "设计 Storyboard", "done": False, "ready": True,
            "executors": ["storyboard_key_elements", "storyboard_shots", "storyboard_audio"],
        }]
        detail = render_pipeline_detail(status, status)
        assert "同批" in detail and "暂停点在阶段边界" in detail

    def test_pipeline_plan_attaches_executors_and_done(self, monkeypatch):
        """声明同批的阶段：status 带 executors，且完成度按全批客观判定。"""
        from src.video_agent.skill_runtime import exec_tools, dag, guard, registry

        status = [
            {"step": 1, "title": "分析", "done": True, "ready": False},
            {"step": 3, "title": "设计 Storyboard", "done": False, "ready": True},
        ]
        monkeypatch.setattr(guard, "skill_planner_flow", lambda name: "flow")
        monkeypatch.setattr(dag, "pipeline_status", lambda flow, state, cond=None: status)
        monkeypatch.setattr(dag, "parse_steps", lambda flow: {1: "分析", 3: "设计 Storyboard"})
        monkeypatch.setattr(dag, "parse_dependencies", lambda flow: {})
        monkeypatch.setattr(dag, "topo_batches", lambda steps, deps: [[1], [3]])
        monkeypatch.setattr(registry, "resolve_entry", lambda name: None)
        monkeypatch.setattr(registry, "skill_manifest_of", lambda name: STAGE_MANIFEST)

        class FakeSvc:
            state_dict = {"keyElements": [1], "shots": [], "audioItems": []}

        monkeypatch.setattr(exec_tools.StateManager, "get_instance", lambda: FakeSvc)
        from src.video_agent.skill_runtime.exec_common import SkillToolInput

        res = asyncio.run(exec_tools.SkillPipelinePlanTool().aexecute(SkillToolInput(skill_name="X")))
        step3 = next(s for s in res.data["steps"] if s["step"] == 3)
        assert step3["executors"] == STAGE_MANIFEST["flow"]["stage_executors"]["3"]
        assert step3["done"] is False  # 只拆完关键元素 ≠ 阶段完成
        assert "同批" in res.data["detail"]

    def test_ai_skill_manifest_declares_stage3_batch(self):
        """单一事实源：AI-一站式 Skill 自己声明 step3 三拆解同批
        （0818 B0：声明家迁 sidecar，经 registry 统一入口读）。"""
        from src.video_agent.skill_runtime import registry

        manifest = registry.skill_manifest_of("AI-短剧一站式生成")
        stages = (manifest.get("flow") or {}).get("stage_executors") or {}
        assert stages.get("3") == ["storyboard_key_elements", "storyboard_shots", "storyboard_audio"]

    def test_ai_skill_manifest_declares_step2_spec_done(self):
        """step2 完成度走客观声明（spec 文档存在=完成），掐掉冗余写规格轮。"""
        from src.video_agent.skill_runtime import registry

        manifest = registry.skill_manifest_of("AI-短剧一站式生成")
        assert ((manifest.get("flow") or {}).get("step_done_conditions") or {}).get("2") == "spec"

    def test_step_done_spec_condition_objective(self):
        """dag.step_done 按声明评估：spec 在=完成，不在=未完成。"""
        from src.video_agent.skill_runtime import dag

        with_spec = {"documents": [{"name": "Final_Video_Spec.md", "content": "画幅 16:9"}]}
        assert dag.step_done(2, "写入规格", with_spec, {"2": "spec"}) is True
        assert dag.step_done(2, "写入规格", {"documents": []}, {"2": "spec"}) is False


# ---------- D3-G4：平台不再给暂停时机出主意 ----------


class TestProgressNoteNoPauseOpinion:
    def test_no_same_batch_pause_suggestion(self):
        src = (ROOT / "src" / "video_agent" / "core" / "prompt_builder.py").read_text(encoding="utf-8")
        assert "同批发出" not in src, "平台不得建议暂停时机（暂停点归 Skill 单一事实源）"


# ---------- 落盘加固：Windows 锁文件竞态重试 ----------


class TestAtomicWriteRetry:
    def test_replace_retries_on_permission_error(self, monkeypatch, tmp_path):
        """os.replace 首次 WinError 5 时退避重试，二次成功即落盘。"""
        from src.video_agent.utils import fileio

        calls = {"n": 0}
        real_replace = fileio.os.replace

        def flaky_replace(src, dst):
            calls["n"] += 1
            if calls["n"] == 1:
                raise PermissionError(13, "access denied")
            return real_replace(src, dst)

        monkeypatch.setattr(fileio.os, "replace", flaky_replace)
        monkeypatch.setattr(fileio.time, "sleep", lambda s: None)
        target = tmp_path / "state.json"
        fileio.atomic_write_text(target, '{"ok": true}')
        assert calls["n"] == 2
        assert target.read_text(encoding="utf-8") == '{"ok": true}'

    def test_replace_exhausted_raises(self, monkeypatch, tmp_path):
        from src.video_agent.utils import fileio
        import pytest as _pt

        def always_denied(src, dst):
            raise PermissionError(13, "access denied")

        monkeypatch.setattr(fileio.os, "replace", always_denied)
        monkeypatch.setattr(fileio.time, "sleep", lambda s: None)
        with _pt.raises(PermissionError):
            fileio.atomic_write_text(tmp_path / "x.json", "{}")
