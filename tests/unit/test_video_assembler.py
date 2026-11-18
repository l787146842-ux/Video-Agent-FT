# -*- coding: utf-8 -*-
"""组装导出（video_assembler）回归钉。

契约：
- 只组装已有视频的镜头；任一目标镜头缺 videoUrl 即整体拒收（fail-closed）。
- 成片落 workspace/assets/，方案文档写 Final_Assembly_Plan.md（assembly 探针据此完成）。
- 成片作为 video 节点推画布；画布失败不推翻成片（如实告知）。
- 无 ffmpeg 时结构化失败，提示安装路径。
"""
import asyncio
import time
from pathlib import Path

import pytest

from src.video_agent.core import stage_probes
from src.video_agent.state.manager import StateManager
from src.video_agent.state.models import ASSEMBLY_PLAN_DOC_NAME
from src.video_agent.tools import assembly_tools as at
from src.video_agent.tools.assembly_tools import VideoAssemblerInput, VideoAssemblerTool


@pytest.fixture
def svc(tmp_path, monkeypatch):
    StateManager.reset_instance()
    instance = StateManager(str(tmp_path))
    StateManager._instance = instance
    monkeypatch.setattr(at, "ASSETS_DIR", tmp_path / "assets")
    yield instance
    StateManager.reset_instance()


def _seed(svc, n_video: int = 2, n_total: int = 2):
    drafts = [
        {"id": f"d{i}", "label": f"镜头{i}", "mediaType": "video",
         "videoUrl": (f"/workspace/assets/v{i}.mp4" if i < n_video else "")}
        for i in range(n_total)
    ]
    svc.state_dict["shots"] = [{"id": "g1", "title": "分镜组", "drafts": drafts}]


def _run(tool, params):
    return asyncio.run(tool.aexecute(params))


class TestCollectClips:
    def test_default_order_follows_groups_and_drafts(self, svc):
        _seed(svc, 2, 3)
        clips, missing = at._collect_clips(svc.state_dict, [])
        assert [c["draft_id"] for c in clips] == ["d0", "d1"]
        assert missing == ["镜头2"]

    def test_explicit_order_and_unknown_id(self, svc):
        _seed(svc, 2, 2)
        clips, missing = at._collect_clips(svc.state_dict, ["d1", "d0", "nope"])
        assert [c["draft_id"] for c in clips] == ["d1", "d0"]
        assert "nope（未找到该草稿）" in missing


class TestAssemblerTool:
    def test_missing_video_rejects_whole_run(self, svc):
        _seed(svc, 1, 2)
        res = _run(VideoAssemblerTool(), VideoAssemblerInput())
        assert res.success is False
        assert "还没有视频" in res.error
        # 未落任何方案文档
        assert svc.state_dict.get("documents") in (None, [])

    def test_no_ffmpeg_structured_error(self, svc, monkeypatch):
        _seed(svc, 2, 2)
        monkeypatch.setattr(at, "_ffmpeg_exe", lambda: "")
        res = _run(VideoAssemblerTool(), VideoAssemblerInput())
        assert res.success is False
        assert "ffmpeg" in res.error

    def test_success_writes_plan_and_chat_card(self, svc, monkeypatch, tmp_path):
        _seed(svc, 2, 2)
        src = tmp_path / "v0.mp4"
        src.write_bytes(b"x")

        async def _fake_resolve(url, tmpdir):
            return src

        def _fake_compose(exe, sources, output, bgm, volume):
            Path(output).parent.mkdir(parents=True, exist_ok=True)
            Path(output).write_bytes(b"fake-mp4")
            return 3.5

        async def _fake_push(canvas_id, video_url, filename):
            return "cv-1", "node-9", "成片已作为视频节点放到画布"

        monkeypatch.setattr(at, "_ffmpeg_exe", lambda: "ffmpeg")
        monkeypatch.setattr(at, "_resolve_source", _fake_resolve)
        monkeypatch.setattr(at, "_compose", _fake_compose)
        monkeypatch.setattr(at, "_push_to_canvas", _fake_push)

        res = _run(VideoAssemblerTool(), VideoAssemblerInput(filename="final.mp4"))
        assert res.success is True, res.error
        assert res.data["url"] == "/workspace/assets/final.mp4"
        assert res.data["duration_seconds"] == 3.5
        assert res.data["clips"] == 2
        assert res.data["canvas_node_id"] == "node-9"
        assert res.data["chat_inserts"][0]["kind"] == "video"
        assert (tmp_path / "assets" / "final.mp4").is_file()

        docs = [d for d in svc.state_dict["documents"] if d["name"] == ASSEMBLY_PLAN_DOC_NAME]
        assert docs and "时间轴" in docs[0]["content"]
        assert stage_probes.stage_done("assembly", svc.state_dict) is True

    def test_canvas_failure_keeps_film(self, svc, monkeypatch, tmp_path):
        _seed(svc, 1, 1)

        async def _fake_resolve(url, tmpdir):
            return tmp_path / "v.mp4"

        def _fake_compose(exe, sources, output, bgm, volume):
            Path(output).write_bytes(b"fake")
            return 1.0

        async def _fake_push(canvas_id, video_url, filename):
            return "", "", "画布推送失败（成片已落盘）：offline"

        monkeypatch.setattr(at, "_ffmpeg_exe", lambda: "ffmpeg")
        monkeypatch.setattr(at, "_resolve_source", _fake_resolve)
        monkeypatch.setattr(at, "_compose", _fake_compose)
        monkeypatch.setattr(at, "_push_to_canvas", _fake_push)

        res = _run(VideoAssemblerTool(), VideoAssemblerInput(push_to_canvas=True))
        assert res.success is True
        assert "画布推送失败" in res.data["detail"]


    def test_subset_assembly_reports_incomplete_stage(self, svc, monkeypatch, tmp_path):
        _seed(svc, 2, 2)

        async def _fake_resolve(url, tmpdir):
            return tmp_path / "v.mp4"

        def _fake_compose(exe, sources, output, bgm, volume):
            Path(output).write_bytes(b"x")
            return 1.0

        monkeypatch.setattr(at, "_ffmpeg_exe", lambda: "ffmpeg")
        monkeypatch.setattr(at, "_resolve_source", _fake_resolve)
        monkeypatch.setattr(at, "_compose", _fake_compose)

        res = _run(VideoAssemblerTool(), VideoAssemblerInput(
            shot_ids=["d0"], push_to_canvas=False))
        assert res.success is True
        assert "只组装 1/2 个镜头" in res.data["detail"]


class TestFilename:
    def test_rejects_traversal_and_forces_mp4(self):
        assert at._safe_filename("../../evil.mov") == "evil.mp4"
        assert at._safe_filename("") == "assembled.mp4"

    def test_default_has_timestamp(self, svc, monkeypatch, tmp_path):
        _seed(svc, 1, 1)

        async def _fake_resolve(url, tmpdir):
            return tmp_path / "v.mp4"

        def _fake_compose(exe, sources, output, bgm, volume):
            Path(output).write_bytes(b"x")
            return 1.0

        monkeypatch.setattr(at, "_ffmpeg_exe", lambda: "ffmpeg")
        monkeypatch.setattr(at, "_resolve_source", _fake_resolve)
        monkeypatch.setattr(at, "_compose", _fake_compose)
        res = _run(VideoAssemblerTool(), VideoAssemblerInput(push_to_canvas=False))
        assert res.success is True
        assert res.data["name"].startswith("assembled-")
        assert res.data["name"].endswith(".mp4")
