"""assembly 阶段完成探针修复（整改计划批 6）。

问题：原探针与 shot_media 同构（shots 有 videoUrl 即判完成），「已生成未
组装」被误判完成，assembly 阶段被静默跳过。
修复（对标 Stop≠Done≠Verified：完成看产物证据，fail-closed）：
- sidecar flow.stages.assembly.done 声明优先（document:<文档名>）；
- 未声明回落「全部分镜有视频 + 组装方案文档在盘」；
- video_assembler 执行器落盘 Final_Assembly_Plan.md 客观产物（幂等）。
"""
import pytest

from src.video_agent.core import pipeline_orchestrator as po
from src.video_agent.state.manager import StateManager
from src.video_agent.state.models import ASSEMBLY_PLAN_DOC_NAME


@pytest.fixture
def svc(tmp_path):
    StateManager.reset_instance()
    instance = StateManager(str(tmp_path))
    StateManager._instance = instance
    yield instance
    StateManager.reset_instance()


def _state_with_shots(n_videos: int, n_total: int) -> dict:
    drafts = [
        {"id": f"d{i}", "label": f"镜头{i}",
         "videoUrl": (f"http://v/{i}.mp4" if i < n_videos else "")}
        for i in range(n_total)
    ]
    return {"shots": [{"id": "g1", "title": "分镜组", "drafts": drafts}]}


def _add_plan_doc(state: dict, name: str = ASSEMBLY_PLAN_DOC_NAME):
    state.setdefault("documents", []).append(
        {"id": "doc1", "name": name, "content": "方案"})


class TestAssemblyProbeFallback:
    """未声明时的平台客观探针（与 shot_media 解耦）"""

    def test_partial_videos_not_done(self):
        state = _state_with_shots(1, 3)
        _add_plan_doc(state)
        assert po.stage_done("assembly", state) is False

    def test_all_videos_but_no_plan_doc_not_done(self):
        """已生成未组装：不再被误判完成（原 bug 场景）"""
        state = _state_with_shots(3, 3)
        assert po.stage_done("assembly", state) is False

    def test_all_videos_and_plan_doc_done(self):
        state = _state_with_shots(3, 3)
        _add_plan_doc(state)
        assert po.stage_done("assembly", state) is True

    def test_shot_media_probe_unchanged(self):
        """shot_media 探针不受影响（任一视频即完成）"""
        state = _state_with_shots(1, 3)
        assert po.stage_done("shot_media", state) is True

    def test_empty_shots_not_done(self):
        assert po.stage_done("assembly", {"shots": []}) is False


class TestAssemblyProbeDeclaration:
    """sidecar flow.stages.assembly.done 声明优先"""

    def test_declared_document_name_overrides(self, monkeypatch):
        from src.video_agent.skill_runtime import registry

        monkeypatch.setattr(
            registry, "skill_manifest_of",
            lambda skill: {"flow": {"stages": {"assembly": {
                "done": "document:Custom_Assembly.md"}}}})
        state = _state_with_shots(0, 2)  # 无视频
        _add_plan_doc(state, name="Custom_Assembly.md")
        assert po.stage_done("assembly", state, skill="X") is True
        # 平台默认产物名在声明覆盖下不作数
        state2 = _state_with_shots(2, 2)
        _add_plan_doc(state2)  # 默认名
        assert po.stage_done("assembly", state2, skill="X") is False

    def test_no_declaration_uses_fallback(self, monkeypatch):
        from src.video_agent.skill_runtime import registry

        monkeypatch.setattr(registry, "skill_manifest_of", lambda skill: None)
        state = _state_with_shots(2, 2)
        _add_plan_doc(state)
        assert po.stage_done("assembly", state, skill="X") is True


class TestAssemblerPersistsArtifact:
    """video_assembler 执行器落盘客观产物（探针的供给侧闭环）"""

    async def test_assembler_writes_plan_doc(self, svc):
        from src.video_agent.skill_runtime.exec_media_gen import (
            VideoAssemblerTool, VideoAssemblerInput,
        )

        state = svc.state_dict
        state["shots"] = [{
            "id": "g1", "title": "分镜",
            "drafts": [{"id": "d1", "label": "镜头1",
                        "videoUrl": "http://v/1.mp4", "duration": "5"}],
        }]
        tool = VideoAssemblerTool()
        result = await tool.aexecute(VideoAssemblerInput(skill_name=""))
        assert result.success

        docs = svc.state_dict.get("documents") or []
        names = [d.get("name") for d in docs]
        assert ASSEMBLY_PLAN_DOC_NAME in names
        # 探针闭环：产物落盘后 assembly 阶段可判完成（分镜需全有视频）
        assert po.stage_done("assembly", svc.state_dict) is True

    async def test_assembler_upsert_idempotent(self, svc):
        from src.video_agent.skill_runtime.exec_media_gen import (
            VideoAssemblerTool, VideoAssemblerInput,
        )

        tool = VideoAssemblerTool()
        await tool.aexecute(VideoAssemblerInput(skill_name=""))
        await tool.aexecute(VideoAssemblerInput(skill_name=""))
        docs = [d for d in svc.state_dict.get("documents") or []
                if d.get("name") == ASSEMBLY_PLAN_DOC_NAME]
        assert len(docs) == 1, "重复执行必须幂等 upsert，不得重复插入"
