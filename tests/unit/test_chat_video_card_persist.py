"""对话流视频内联预览卡持久化回归（影响面审查修复批）：

videoCard 此前只存在于前端 finishStream 内存流，done 结算仅持久化
image_urls——刷新/SSE replay/重开项目时服务端快照全量替换消息列表，
视频卡永久消失（与 imageCard 刷新后仍在的契约不对称，违背「瞬态 SSE
不得作为唯一可见性」不变式）。本文件钉死修复后的三层契约：

1. StateManager.add_chat_message 的 videoCard 通道（结构/过滤语义）；
2. chat_service done 结算：final_payload["chat_inserts"] 中 kind=video
   项落盘为独立消息条目（同轮 turnId 聚合，与 imageCard 对称）；
3. 快照回放：get_full_snapshot 深拷贝携带 videoCard 可读回。
"""
from types import SimpleNamespace

import pytest

from src.video_agent.state.manager import StateManager


# ---------- 夹具 ----------

def _svc(tmp_path) -> StateManager:
    return StateManager(str(tmp_path / "ws"))


def _video_items():
    return [
        {"kind": "video", "url": "/media/v1.mp4", "name": "开场.mp4", "thumb": "/media/v1.jpg"},
        {"kind": "video", "url": "/media/v2.mp4"},
    ]


# ---------- 1. manager 通道 ----------

def test_add_chat_message_video_card_structure(tmp_path):
    """video_items → entry["videoCard"] = {"items": [...]}，字段保留 url/name/thumb。"""
    svc = _svc(tmp_path)
    svc.add_chat_message("agent", "", video_items=_video_items(), turn_id="turn-v")
    msg = svc.get_chat_messages()[-1]
    assert msg["videoCard"] == {"items": [
        {"url": "/media/v1.mp4", "name": "开场.mp4", "thumb": "/media/v1.jpg"},
        {"url": "/media/v2.mp4"},
    ]}
    assert msg["turnId"] == "turn-v"


def test_add_chat_message_video_card_drops_invalid_items(tmp_path):
    """url 为空的非法项丢弃；全部非法时不产生 videoCard 字段。"""
    svc = _svc(tmp_path)
    svc.add_chat_message("agent", "", video_items=[{"kind": "video", "url": ""}])
    assert "videoCard" not in svc.get_chat_messages()[-1]


def test_add_chat_message_video_card_coexists_with_image_card(tmp_path):
    """videoCard 与 imageCard 通道互不干扰（两通道对称独立）。"""
    svc = _svc(tmp_path)
    svc.add_chat_message(
        "agent", "", image_urls=["/media/i.png"], video_items=_video_items(),
    )
    msg = svc.get_chat_messages()[-1]
    assert msg["imageCard"] == {"image_urls": ["/media/i.png"]}
    assert msg["videoCard"]["items"][0]["url"] == "/media/v1.mp4"


# ---------- 2. done 结算落盘 ----------

class _Evt:
    """planner 流事件的鸭子替身（type/payload/text 三属性）。"""

    def __init__(self, type_: str, payload=None, text: str = ""):
        self.type = type_
        self.payload = payload
        self.text = text


def _body():
    return SimpleNamespace(
        request_id="req-video", message="生成视频", provider="prov-x",
        model="model-x", messages=[{"role": "user", "content": "生成视频"}],
        attachments=[], selected_draft_id="", selected_type="",
        skill_name="", skill_slug="", asset_mode="bound",
    )


@pytest.mark.asyncio
async def test_done_settlement_persists_video_card(tmp_path, monkeypatch):
    """done 结算：chat_inserts 中 kind=video 且 url 非空项落盘为独立
    videoCard 消息（同轮 turnId）；kind=image 与空 url 项不进入视频卡。"""
    import src.video_agent.web.chat_service as cs

    svc = _svc(tmp_path)
    events = []

    async def emit(ev):
        events.append(ev)

    monkeypatch.setattr(cs, "_create_chat_adapter", lambda p, m: object())
    monkeypatch.setattr(cs, "_resolve_summary_adapter", lambda body, cands: None)

    async def fake_stream(self, content, ctx):
        yield _Evt("done", {
            "text": "视频已生成",
            "chat_inserts": [
                {"kind": "video", "url": "/media/v1.mp4", "name": "开场.mp4", "thumb": "/media/v1.jpg"},
                {"kind": "image", "url": "/media/i.png", "name": "i.png"},
                {"kind": "video", "url": "", "name": ""},
            ],
        })

    monkeypatch.setattr(cs.Planner, "handle_message_stream", fake_stream)

    await cs._real_stream(
        svc, None, _body(), "生成视频", "生成视频", "生成视频",
        True, emit, 0.0,
    )

    msgs = svc.get_chat_messages()
    video_msgs = [m for m in msgs if m.get("videoCard")]
    assert len(video_msgs) == 1
    assert video_msgs[0]["videoCard"]["items"] == [
        {"url": "/media/v1.mp4", "name": "开场.mp4", "thumb": "/media/v1.jpg"},
    ]
    # 同轮 turnId 聚合（与正文消息共用）
    done_ev = next(e for e in events if e.get("type") == "done")
    turn_id = done_ev["payload"]["turn_id"]
    assert video_msgs[0]["turnId"] == turn_id
    body_msg = next(m for m in msgs if m.get("text") == "视频已生成")
    assert body_msg["turnId"] == turn_id


@pytest.mark.asyncio
async def test_done_settlement_video_only_turn_still_persisted(tmp_path, monkeypatch):
    """仅视频产出（无正文/确认/生图）的轮次同样落盘视频卡
    （持久化闸门条件包含 video_items，不因无正文而跳过）。"""
    import src.video_agent.web.chat_service as cs

    svc = _svc(tmp_path)

    async def emit(ev):
        pass

    monkeypatch.setattr(cs, "_create_chat_adapter", lambda p, m: object())
    monkeypatch.setattr(cs, "_resolve_summary_adapter", lambda body, cands: None)

    async def fake_stream(self, content, ctx):
        yield _Evt("done", {
            "text": "",
            "chat_inserts": [{"kind": "video", "url": "/media/v.mp4", "name": "v.mp4"}],
        })

    monkeypatch.setattr(cs.Planner, "handle_message_stream", fake_stream)

    await cs._real_stream(
        svc, None, _body(), "生成视频", "生成视频", "生成视频",
        True, emit, 0.0,
    )
    assert any(m.get("videoCard") for m in svc.get_chat_messages())


# ---------- 3. 快照回放 ----------

def test_snapshot_replay_carries_video_card(tmp_path):
    """刷新/SSE replay 契约：get_full_snapshot 深拷贝携带 videoCard，
    服务端快照全量替换消息列表后视频卡可读回。"""
    svc = _svc(tmp_path)
    svc.add_chat_message("agent", "", video_items=_video_items(), turn_id="turn-v")
    snap = svc.get_full_snapshot()
    msgs = snap["chatMessages"]
    card = next(m.get("videoCard") for m in msgs if m.get("videoCard"))
    assert card["items"][0]["url"] == "/media/v1.mp4"
    # 深拷贝隔离：改动快照不污染内部状态
    card["items"].clear()
    assert svc.get_chat_messages()[-1]["videoCard"]["items"]
