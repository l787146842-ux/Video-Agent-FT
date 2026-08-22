"""回归测试 0818-1111b：空参读文档自动归位 + 空输出引导续写 + 阶段同批声明翻译。

事故：1111 实测——模型空参试探 read_uploaded_doc 烧一轮；盲目重试翻倍成本；
旧调度工具只回步骤号，「step3=三拆解同阶段」分组不可见，
模型拆完关键元素就暂停且把下一步说成编写提示词。
"""
import asyncio

import pytest


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


# ---------- D2：坏输出引导续写 ----------


class TestBadOutputNudge:
    def test_nudge_requires_visible_output(self):
        from src.video_agent.core.agent_loop import _bad_output_nudge

        text = _bad_output_nudge(1)
        assert "工具调用" in text and "思考" in text


# ---------- D3：阶段同批声明翻译（P3 单一事实源） ----------


# STAGE_MANIFEST（stage_executors 声明样例）的消费用例已退役，
# 声明数据本身仍由 sidecar schema 层测试钉死（test_sidecar_schema_v3）。


class TestStageExecutorsDeclaration:
    # test_registry_parses_stage_executors / test_registry_undeclared_returns_empty /
    # test_stage_done_requires_all_executors 已随任务#36 B5 执行器一步退役删除：
    # registry.skill_stage_executors 与 exec_tools._stage_done_by_executors 不复存在，
    # 阶段完成度改由 pipeline_orchestrator.stage_done 客观探针判定（下方用例钉死）。

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
        """0818 B4：spec 阶段完成度走客观探针（spec 文档存在=完成）。"""
        from src.video_agent.core import pipeline_orchestrator as po

        with_spec = {"documents": [{"name": "Final_Video_Spec.md", "content": "画幅 16:9"}]}
        assert po.stage_done("spec", with_spec) is True
        assert po.stage_done("spec", {"documents": []}) is False


# ---------- D3-G4：平台不再给暂停时机出主意——该措辞防复活已迁
# check_legacy_orchestration 门禁（P2d 结构性测试减负） ----------


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
