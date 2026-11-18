# -*- coding: utf-8 -*-
"""再生隔离回归钉（2026-10-26 用户裁决：已有媒体不得被覆盖）。

裁决原文要点：关键元素 / 分镜 / 音频**已经生成**时，在 Agent 聊天框里要求重新
生成，默认不能覆盖原有媒体文件，只能再建一张卡生成。三条口径（用户三问三答）：
  ① 判据 = 该卡**已有同种媒体**（imgUrl / videoUrl / audioUrl 各自独立）；
  ② 范围 = 仅 Agent 聊天框（前端手点生成按钮不走本机制）；
  ③ 批量再生遇已有媒体的卡 = **逐张新建卡再生成**（不跳过、不整批拒收）。

钉死五条：
  ① `ops.media_overwrite_kind` / `ops.regen_carrier` 判定语义（同种媒体才算冲突、
     同值重写不算、无媒体卡原地写）；
  ② `storyboard_patch_draft`（视频/音频落卡通道）写媒体时切卡并回执新 draft_id；
  ③ `image_generate` 批量轨提交前逐张切卡（原卡与旧图保持原样）；
  ④ 承载卡继承原卡提示词/渠道并清空媒体与绑定；
  ⑤ 无冲突路径零行为变化（存量回归）。
"""
import asyncio

import pytest

from src.video_agent.state import storyboard_ops as ops
from src.video_agent.state.manager import StateManager
from src.video_agent.tools.storyboard_tools import (
    PatchDraftInput,
    StoryboardPatchDraftTool,
)


@pytest.fixture
def svc(tmp_path):
    StateManager.reset_instance()
    instance = StateManager(str(tmp_path))
    StateManager._instance = instance
    yield instance
    StateManager.reset_instance()


def _seed(svc, drafts):
    svc.state_dict["keyElements"] = []
    svc.state_dict["shots"] = [{"id": "sh-1", "title": "Shot_舱内醒来", "drafts": drafts}]
    svc.state_dict["audioItems"] = []


# ---------- ① 判定语义 ----------


class TestMediaOverwriteKind:
    def test_same_kind_with_different_value_conflicts(self):
        draft = {"videoUrl": "/old.mp4"}
        assert ops.media_overwrite_kind(draft, {"videoUrl": "/new.mp4"}) == "video"

    def test_same_value_rewrite_is_not_a_conflict(self):
        """幂等回写（同值）不丢任何东西，不算覆盖。"""
        draft = {"videoUrl": "/v.mp4"}
        assert ops.media_overwrite_kind(draft, {"videoUrl": "/v.mp4"}) == ""

    def test_other_kind_is_independent(self):
        """图片卡上写视频 = 换媒体种类，不是覆盖同种媒体（用户口径：看同种媒体）。"""
        draft = {"imgUrl": "/a.png"}
        assert ops.media_overwrite_kind(draft, {"videoUrl": "/v.mp4"}) == ""

    def test_card_without_media_never_conflicts(self):
        assert ops.media_overwrite_kind({}, {"imgUrl": "/a.png"}) == ""

    def test_prompt_only_patch_never_conflicts(self):
        draft = {"videoUrl": "/v.mp4"}
        assert ops.media_overwrite_kind(draft, {"prompt": "新提示词"}) == ""

    def test_empty_new_value_never_conflicts(self):
        """显式清空（传空串）不算覆盖写。"""
        draft = {"videoUrl": "/v.mp4"}
        assert ops.media_overwrite_kind(draft, {"videoUrl": ""}) == ""

    def test_audio_track_is_judged_separately(self):
        draft = {"audioUrl": "/old.mp3"}
        assert ops.media_overwrite_kind(draft, {"audioUrl": "/new.mp3"}) == "audio"

    def test_regen_carrier_creates_sibling_and_keeps_origin(self):
        state = {"shots": [{"id": "sh-1", "drafts": [
            {"id": "d1", "videoUrl": "/old.mp4", "prompt": "p", "bound": True}]}]}
        group = state["shots"][0]
        origin = group["drafts"][0]
        carrier, created = ops.regen_carrier(state, group, origin, "video")
        assert created is True
        assert carrier["id"] != "d1"
        assert carrier["videoUrl"] == "", "承载卡初始无媒体"
        assert origin["videoUrl"] == "/old.mp4", "原卡与旧片保持原样"
        assert origin["bound"] is True, "原卡绑定态不动"
        assert carrier["bound"] is False
        assert [d["id"] for d in group["drafts"]] == ["d1", carrier["id"]], "同组追加"

    def test_regen_carrier_reuses_card_without_media(self):
        state = {"shots": [{"id": "sh-1", "drafts": [
            {"id": "d1", "videoUrl": "", "prompt": "p"}]}]}
        group = state["shots"][0]
        origin = group["drafts"][0]
        carrier, created = ops.regen_carrier(state, group, origin, "video")
        assert created is False and carrier is origin
        assert len(group["drafts"]) == 1


class TestDuplicateDraftForRegen:
    def test_inherits_inputs_and_clears_media(self):
        state = {"keyElements": []}
        group = {"id": "ke-1", "drafts": []}
        origin = {
            "id": "d1", "label": "设定图", "mediaType": "image", "imgUrl": "/a.png",
            "videoUrl": "/v.mp4", "audioUrl": "/a.mp3", "prompt": "三视图提示词",
            "desc": "角色描述", "imageProviderId": "prov-x", "imageModel": "m-x",
            "imageResolution": "2K", "aspectRatio": "9:16", "refAssets": ["/ref.png"],
            "bound": True,
        }
        group["drafts"].append(origin)
        new = ops.duplicate_draft_for_regen(state, group, origin)
        assert new["id"] != "d1"
        # 继承生成意图的同一套输入
        assert new["prompt"] == "三视图提示词"
        assert new["desc"] == "角色描述"
        assert new["imageProviderId"] == "prov-x", "逐卡渠道必须继承（否则换渠道）"
        assert new["imageModel"] == "m-x"
        assert new["imageResolution"] == "2K"
        assert new["aspectRatio"] == "9:16"
        assert new["refAssets"] == ["/ref.png"]
        assert new["mediaType"] == "image"
        # 媒体与绑定由本次生成重新成立
        assert new["imgUrl"] == "" and new["videoUrl"] == "" and new["audioUrl"] == ""
        assert new["bound"] is False
        # 卡名可分辨（左栏卡面零文字，用户靠 title 认卡）
        assert new["label"] == "设定图（再生）"
        # 原卡零改动
        assert origin["imgUrl"] == "/a.png" and origin["bound"] is True
        assert origin["label"] == "设定图"

    def test_failed_tag_not_inherited(self):
        state = {"keyElements": []}
        group = {"id": "ke-1", "drafts": []}
        origin = {"id": "d1", "label": "图", "imgUrl": "/a.png", "tag": "生成失败"}
        group["drafts"].append(origin)
        assert ops.duplicate_draft_for_regen(state, group, origin)["tag"] == "Agent"


# ---------- ② patch 落卡通道（视频 / 音频） ----------


class TestPatchDraftRegenCarrier:
    async def test_existing_video_moves_to_new_card(self, svc):
        _seed(svc, [{"id": "s-vid", "label": "分镜视频", "mediaType": "video",
                     "videoUrl": "/old.mp4", "prompt": "p"}])
        group = svc.state_dict["shots"][0]
        r = await StoryboardPatchDraftTool().aexecute(PatchDraftInput(
            draft_id="s-vid", draft_type="shot",
            patch={"videoUrl": "/new.mp4", "tag": "已生成"},
        ))
        assert r.success is True
        new_id = r.data["draft_id"]
        assert new_id != "s-vid", "已有视频不得被覆盖，必须落到新卡"
        assert r.data["regen_of"] == "s-vid"
        assert "保持原样" in r.data["detail"], "平台改写必须模型可见（§2.5）"
        origin = next(d for d in group["drafts"] if d["id"] == "s-vid")
        carrier = next(d for d in group["drafts"] if d["id"] == new_id)
        assert origin["videoUrl"] == "/old.mp4", "原卡旧片保持原样"
        assert carrier["videoUrl"] == "/new.mp4"
        assert carrier["prompt"] == "p", "承载卡继承原卡提示词"
        assert carrier["bound"] is True, "新卡出片即绑定（同组同类型唯一）"
        assert origin.get("bound") in (False, None)

    async def test_existing_audio_moves_to_new_card(self, svc):
        svc.state_dict["keyElements"] = []
        svc.state_dict["shots"] = []
        svc.state_dict["audioItems"] = [{"id": "au-1", "title": "Audio_末日序曲", "drafts": [
            {"id": "a1", "label": "BGM", "mediaType": "audio", "audioType": "bgm",
             "audioUrl": "/old.mp3"}]}]
        group = svc.state_dict["audioItems"][0]
        r = await StoryboardPatchDraftTool().aexecute(PatchDraftInput(
            draft_id="a1", draft_type="audio", patch={"audioUrl": "/new.mp3"},
        ))
        assert r.success is True and r.data["draft_id"] != "a1"
        origin = next(d for d in group["drafts"] if d["id"] == "a1")
        assert origin["audioUrl"] == "/old.mp3", "原卡旧音频保持原样"

    async def test_card_without_media_writes_in_place(self, svc):
        """存量回归：卡上还没有视频时，patch 照常写在原卡（不建新卡）。"""
        _seed(svc, [{"id": "s-vid", "label": "分镜视频", "mediaType": "video",
                     "videoUrl": "", "prompt": "p"}])
        group = svc.state_dict["shots"][0]
        r = await StoryboardPatchDraftTool().aexecute(PatchDraftInput(
            draft_id="s-vid", draft_type="shot", patch={"videoUrl": "/first.mp4"},
        ))
        assert r.success is True
        assert r.data["draft_id"] == "s-vid"
        assert "regen_of" not in r.data
        assert len(group["drafts"]) == 1
        assert group["drafts"][0]["videoUrl"] == "/first.mp4"

    async def test_prompt_patch_on_generated_card_stays_in_place(self, svc):
        """提示词/参数类 patch 不受影响：只有写同种媒体才切卡。"""
        _seed(svc, [{"id": "s-vid", "label": "分镜视频", "mediaType": "video",
                     "videoUrl": "/v.mp4", "prompt": "旧"}])
        group = svc.state_dict["shots"][0]
        r = await StoryboardPatchDraftTool().aexecute(PatchDraftInput(
            draft_id="s-vid", draft_type="shot", patch={"prompt": "新提示词"},
        ))
        assert r.success is True and r.data["draft_id"] == "s-vid"
        assert len(group["drafts"]) == 1
        assert group["drafts"][0]["prompt"] == "新提示词"
        assert group["drafts"][0]["videoUrl"] == "/v.mp4"


# ---------- ③ 生图批量轨 ----------


def _stub_image_gen(monkeypatch):
    from src.video_agent.web import generation_dispatch

    captured = []

    async def fake_gen(provider_id, model, prompt, **kwargs):
        captured.append((provider_id, model, prompt))
        return "http://fake/new.png"

    monkeypatch.setattr(generation_dispatch, "generate_image_via_provider", fake_gen)
    return captured


class TestImageGenerateRegenCarrier:
    async def test_batch_regen_creates_card_per_generated_target(self, svc, monkeypatch):
        """批量再生：已有图的卡逐张新建承载卡，原卡旧图保持原样（用户口径③）。"""
        from src.video_agent.tools.document_tools import GenerateImageInput, ImageGenerateTool

        monkeypatch.setattr(StateManager, "_instance", svc)
        svc.state_dict["shots"] = []
        svc.state_dict["audioItems"] = []
        svc.state_dict["keyElements"] = [{
            "id": "ke-1", "title": "Element_程心", "drafts": [
                {"id": "d-has", "label": "设定图", "mediaType": "image", "tag": "已确认",
                 "imgUrl": "/old.png", "prompt": "角色三视图提示词"},
                {"id": "d-empty", "label": "空白卡", "mediaType": "image", "tag": "已确认",
                 "imgUrl": "", "prompt": "另一段提示词"},
            ]}]
        group = svc.state_dict["keyElements"][0]
        _stub_image_gen(monkeypatch)

        r = await ImageGenerateTool().aexecute(
            GenerateImageInput(target="all_keyElements"))
        assert r.success is True
        await asyncio.sleep(0.3)

        assert len(group["drafts"]) == 3, "只有已出图的卡才新建承载卡（逐张）"
        origin = next(d for d in group["drafts"] if d["id"] == "d-has")
        empty = next(d for d in group["drafts"] if d["id"] == "d-empty")
        carrier = next(d for d in group["drafts"] if d["id"] not in ("d-has", "d-empty"))
        assert origin["imgUrl"] == "/old.png", "原卡旧图保持原样"
        assert empty["imgUrl"] == "http://fake/new.png", "无媒体卡原地写（存量行为）"
        assert carrier["imgUrl"] == "http://fake/new.png", "承载卡承载本次结果"
        assert carrier["prompt"] == "角色三视图提示词", "承载卡继承原卡提示词"
        # §2.5：平台改写必须模型可见
        assert r.data["regen_draft_ids"] == [carrier["id"]]
        assert "保持原样" in r.data["detail"]

    async def test_no_regen_when_targets_have_no_media(self, svc, monkeypatch):
        """存量回归：全部目标都没出过图时，卡数不变、回执无 regen 段。"""
        from src.video_agent.tools.document_tools import GenerateImageInput, ImageGenerateTool

        monkeypatch.setattr(StateManager, "_instance", svc)
        svc.state_dict["shots"] = []
        svc.state_dict["audioItems"] = []
        svc.state_dict["keyElements"] = [{
            "id": "ke-1", "title": "Element_程心", "drafts": [
                {"id": "d1", "label": "设定图", "mediaType": "image", "tag": "已确认",
                 "imgUrl": "", "prompt": "提示词"}]}]
        group = svc.state_dict["keyElements"][0]
        _stub_image_gen(monkeypatch)

        r = await ImageGenerateTool().aexecute(
            GenerateImageInput(target="all_keyElements"))
        assert r.success is True
        await asyncio.sleep(0.3)
        assert len(group["drafts"]) == 1
        assert "regen_draft_ids" not in r.data
        assert group["drafts"][0]["imgUrl"] == "http://fake/new.png"
