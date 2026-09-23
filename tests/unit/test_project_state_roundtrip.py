# -*- coding: utf-8 -*-
"""D-06 整板保存往返零静默丢字段回归（PUT /api/project/state）。

钉死硬不变量：前端提交的元素字段（含后端模型未声明的视图态额外字段）
经「保存 → 持久化 → 重载 → 回传」往返后必须逐字段完整保留，且不被注入
模型默认值污染落盘形态。

防回归面：
- 若元素模型丢掉 extra="allow" → 额外字段被静默丢弃 → 本测试 FAIL；
- 若落盘回转漏掉 exclude_unset → 注入默认值（如 DraftRecord.asset_id=None
  snake_case 污染）→ no-injection 断言 FAIL；
- 若回退裸 Dict 之外的有损模型 → 同上 FAIL。
"""
import copy

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.video_agent.state.manager import StateManager


# ---------- 代表性前端 payload（字段取自 src/web/types/index.ts 手写强类型，
#            刻意混入后端元素模型「未声明」的视图态额外字段） ----------

def _rich_draft(did: str) -> dict:
    """草稿：声明字段 + 前端独有额外字段（imageProviderId/videoModel/
    customRatioWidth/status 等后端 DraftRecord 未声明，靠 extra=allow 透传）。"""
    return {
        # 后端 DraftRecord 声明字段（alias 对齐前端 camelCase）
        "id": did, "label": "主角", "tag": "推荐", "mediaType": "image",
        "genType": "image", "prompt": "一个少年", "providerId": "p1",
        "model": "m1", "mode": "std", "aspectRatio": "16:9",
        "resolution": "1080p", "duration": "", "size": "1024x1024",
        "timbre": "", "imgUrl": "http://x/i.png", "videoUrl": "",
        "audioUrl": "", "refAssets": ["a1", "a2"],
        # 前端独有、后端未声明的额外字段（必须原样透传，不得静默丢弃）
        "imageProviderId": "img-p", "imageModel": "img-m",
        "videoProviderId": "vid-p", "videoModel": "vid-m",
        "videoAspectRatio": "21:9", "audioProviderId": "aud-p",
        "audioModel": "aud-m", "audioMode": "am",
        "imageResolution": "4K", "customRatioWidth": "1280",
        "customRatioHeight": "720", "status": "ready",
    }


def _payload() -> dict:
    return {
        "keyElements": [{
            "id": "ke-1", "title": "关键元素组", "desc": "描述",
            "badgeLabel": "已确认",  # 存量额外字段（类别标识已退役，只读透传不显示）
            "drafts": [_rich_draft("d-ke-1")],
        }],
        "shots": [{
            "id": "sh-1", "title": "分镜组", "duration": "3s",
            "roughDesc": "粗描述", "shotType": "特写",
            "cameraMovement": "pan", "shotRefs": ["s1"],
            "transition": "fade", "audioCue": "cue", "timeRange": "0-3",
            "generationConfig": {"steps": 20, "cfg": 7.5},
            "status": "ready", "linkedSceneId": "scene-9",
            "drafts": [_rich_draft("d-sh-1")],
        }],
        "audioItems": [{
            "id": "au-1", "title": "音频组", "timeRange": "0-10",
            "prompt": "配乐提示",
            "drafts": [_rich_draft("d-au-1")],
        }],
        "assets": [{
            "id": "as-1", "name": "素材", "type": "image",
            "isBound": True, "url": "http://x/a.png",
            # 前端独有额外字段（含嵌套 sourceDraft 快照，须整体透传）
            "sourceType": "shot", "sourceGroupId": "sh-1",
            "sourceDraft": _rich_draft("d-src-1"),
        }],
    }


@pytest.fixture
def svc(tmp_path):
    StateManager.reset_instance()
    instance = StateManager(str(tmp_path))
    StateManager._instance = instance
    yield instance
    StateManager.reset_instance()


@pytest.fixture
def client(svc):
    from src.video_agent.web.routes import project as project_routes
    from src.video_agent.web.app import video_agent_error_handler
    from src.video_agent.exceptions import VideoAgentError
    app = FastAPI()
    app.include_router(project_routes.router, prefix="/api")
    app.add_exception_handler(VideoAgentError, video_agent_error_handler)
    return TestClient(app)


def _reload_from_disk(tmp_path) -> StateManager:
    """强制从磁盘重载（新实例走 _load），验证真实持久化往返而非内存态。"""
    StateManager.reset_instance()
    reloaded = StateManager(str(tmp_path))
    StateManager._instance = reloaded
    return reloaded


# ---------- 核心：整板保存 → 落盘 → 重载 → 回传，四类别逐字段零丢失 ----------

def test_board_elements_survive_full_disk_roundtrip(client, svc, tmp_path):
    """PUT 富字段 payload → 落盘 → 新实例从磁盘重载 → 快照回传：
    四类别（含所有未声明额外字段）必须与提交逐字段完全一致。"""
    payload = _payload()
    sent = copy.deepcopy(payload)
    resp = client.put("/api/project/state", json=payload)
    assert resp.status_code == 200 and resp.json()["ok"] is True

    reloaded = _reload_from_disk(tmp_path)
    snap = reloaded.get_full_snapshot()
    for cat in ("keyElements", "shots", "audioItems", "assets"):
        assert snap[cat] == sent[cat], f"{cat} 往返丢字段/被改写"


def test_undeclared_extra_fields_preserved_verbatim(client, svc, tmp_path):
    """点名钉死此前「未建模」的额外字段：重载后仍在，值未被截断/改名。"""
    client.put("/api/project/state", json=_payload())
    snap = _reload_from_disk(tmp_path).get_full_snapshot()

    draft = snap["keyElements"][0]["drafts"][0]
    for extra_key in ("imageProviderId", "videoModel", "videoAspectRatio",
                      "imageResolution", "customRatioWidth", "customRatioHeight",
                      "status"):
        assert extra_key in draft, f"草稿额外字段 {extra_key} 被静默丢弃"
    assert draft["customRatioWidth"] == "1280"
    assert snap["keyElements"][0]["badgeLabel"] == "已确认"

    asset = snap["assets"][0]
    assert asset["sourceType"] == "shot" and asset["sourceGroupId"] == "sh-1"
    # 嵌套 sourceDraft 快照整体透传（含其自身的额外字段）
    assert asset["sourceDraft"]["videoModel"] == "vid-m"
    assert asset["sourceDraft"]["customRatioHeight"] == "720"


def test_minimal_payload_not_polluted_by_model_defaults(client, svc, tmp_path):
    """exclude_unset 边界：只提交 id 的退化元素，重载后必须仍只有 id，
    不得被注入 title=""/drafts=[]/asset_id=None 等模型默认值污染落盘形态。"""
    minimal = {
        "keyElements": [{"id": "ke-min"}],
        "shots": [{"id": "sh-min"}],
        "audioItems": [{"id": "au-min"}],
        "assets": [{"id": "as-min"}],
    }
    resp = client.put("/api/project/state", json=minimal)
    assert resp.status_code == 200
    snap = _reload_from_disk(tmp_path).get_full_snapshot()
    for cat in ("keyElements", "shots", "audioItems", "assets"):
        assert snap[cat] == [{"id": minimal[cat][0]["id"]}], \
            f"{cat} 被注入默认值（落盘回转漏 exclude_unset）"


def test_declared_field_equal_to_default_not_dropped(client, svc, tmp_path):
    """exclude_unset 只排除「未提交」字段；前端显式提交了与默认值相同的字段
    （如 isBound=false）仍属已设置，必须保留，不得被误当默认值剔除。"""
    payload = {"assets": [{"id": "as-x", "name": "", "isBound": False, "url": ""}]}
    client.put("/api/project/state", json=payload)
    snap = _reload_from_disk(tmp_path).get_full_snapshot()
    assert snap["assets"][0] == {"id": "as-x", "name": "", "isBound": False, "url": ""}


# ---------- chatMessages：handler 级模型回转保留额外字段（不注入默认值） ----------

def test_chat_message_extras_preserved_in_state_dict(client, svc):
    """消息模型（ChatMessage extra=allow）回转：前端富消息的未声明字段
    （imageCard/trace/pauseId/suggestedActions/ts 等）写入 state_dict 时
    逐字段保留、且不注入 timestamp="" 等默认值。

    注：断言落在 PUT 后的 state_dict（handler 回转身），不经重载——
    重载时 chatMessages 会被多对话不变式重绑到活跃对话 messages
    （既有行为，非 D-06 往返面；前端整板保存 payload 不含 chatMessages）。"""
    msg = {
        "sender": "agent", "text": "已完成",
        "modelName": "m", "thinkingMs": 1234,
        "imageCard": {"image_urls": ["http://x/1.png"], "provider": "p"},
        "videoCard": {"items": [{"url": "http://x/v.mp4", "thumb": "t"}]},
        "parts": [{"type": "text", "text": "hi"}, {"type": "image", "url": "u"}],
        "trace": {"trace_id": "t1", "steps": [{"step": 1}]},
        "confirmOptions": [{"label": "A", "value": "a"}],
        "suggestedActions": [{"kind": "continue", "label": "继续", "value": "go"}],
        "pauseId": "pz-1", "snapshotId": "sn-1", "kind": "confirm", "ts": 1700000000000,
    }
    resp = client.put("/api/project/state", json={"chatMessages": [msg]})
    assert resp.status_code == 200
    assert svc.state_dict["chatMessages"] == [msg]
