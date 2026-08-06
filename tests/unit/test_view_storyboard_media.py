"""view_storyboard_media 按需调图工具与多模态回喂治理（逐条看图写提示词机制）"""
import pytest

import src.video_agent.web.multimodal_builder as mb
from src.video_agent.core.fc_tool_runner import (
    FEEDBACK_MARKER,
    compress_prior_feedback,
    format_tool_results,
    strip_prior_feedback_images,
)
from src.video_agent.state.manager import StateManager
from src.video_agent.tools.storyboard_tools import (
    ViewStoryboardMediaInput,
    ViewStoryboardMediaTool,
)


@pytest.fixture
def svc(tmp_path):
    StateManager.reset_instance()
    instance = StateManager(str(tmp_path))
    StateManager._instance = instance
    yield instance
    StateManager.reset_instance()


@pytest.fixture
def fake_resolve(monkeypatch):
    """模拟图片解析成功：任何 URL 都转成伪 data URI"""
    async def _resolve(url: str) -> str:
        return f"data:image/png;base64,{abs(hash(url)) % 100000}" if url else ""
    monkeypatch.setattr(mb, "_resolve_injectable_url", _resolve)
    return _resolve


def _first_draft(svc):
    group = svc.state_dict["keyElements"][0]
    return group, group["drafts"][0]


@pytest.mark.asyncio
async def test_view_by_real_id(svc, fake_resolve):
    """按真实 draft_id 加载图片进上下文"""
    _, draft = _first_draft(svc)
    draft["imgUrl"] = "https://cdn/概念图.png"
    tool = ViewStoryboardMediaTool()
    result = await tool.aexecute(ViewStoryboardMediaInput(draft_ids=[draft["id"]]))
    assert result.success
    imgs = result.data["images"]
    assert len(imgs) == 1
    assert imgs[0]["data_uri"].startswith("data:image/png;base64,")
    assert imgs[0]["draft_id"] == draft["id"]


@pytest.mark.asyncio
async def test_view_by_index_number(svc, fake_resolve):
    """支持「组号-卡序号」编号定位（与 read_draft 一致）"""
    _, draft = _first_draft(svc)
    draft["imgUrl"] = "/workspace/assets/a.png"
    tool = ViewStoryboardMediaTool()
    result = await tool.aexecute(ViewStoryboardMediaInput(draft_ids=["1-1"], target="", limit=0))
    # 1-1 在 keyElements/shots/audio 各类别独立计数，至少命中关键元素第一张
    assert result.success
    assert any(im["draft_id"] == draft["id"] for im in result.data["images"])


@pytest.mark.asyncio
async def test_view_missing_draft_fails(svc, fake_resolve):
    tool = ViewStoryboardMediaTool()
    result = await tool.aexecute(ViewStoryboardMediaInput(draft_ids=["不存在-999"]))
    assert not result.success


@pytest.mark.asyncio
async def test_view_draft_without_image_noted(svc, fake_resolve):
    """目标草稿无图片时给出说明而非静默"""
    _, draft = _first_draft(svc)
    draft["imgUrl"] = ""
    tool = ViewStoryboardMediaTool()
    result = await tool.aexecute(ViewStoryboardMediaInput(draft_ids=[draft["id"]]))
    assert not result.success
    assert "没有可加载的图片" in (result.error or "")


@pytest.mark.asyncio
async def test_view_limit_truncates(svc, fake_resolve):
    """单次加载数量受 limit 约束，超限草稿进 notes 提示下轮再调"""
    drafts = []
    for g in svc.state_dict["keyElements"]:
        for d in g.get("drafts", []):
            d["imgUrl"] = f"/workspace/assets/{d['id']}.png"
            drafts.append(d)
    if len(drafts) < 2:
        pytest.skip("demo 状态草稿不足")
    tool = ViewStoryboardMediaTool()
    result = await tool.aexecute(ViewStoryboardMediaInput(target="all_keyElements", limit=1))
    assert result.success
    assert len(result.data["images"]) == 1
    assert any("上限" in n for n in result.data["notes"])


def test_format_tool_results_multimodal():
    """view_storyboard_media 结果回喂为多模态 parts（文本 + image_url）"""
    tool_results = [{
        "name": "view_storyboard_media", "ok": True,
        "data": {"images": [{"label": "概念图", "draft_id": "d-1", "data_uri": "data:image/png;base64,AA"}], "notes": []},
    }]
    feedback = format_tool_results(tool_results)
    assert isinstance(feedback, list)
    assert feedback[0]["type"] == "text"
    assert feedback[0]["text"].startswith(FEEDBACK_MARKER)
    assert any(p.get("type") == "image_url" and p["image_url"]["url"] == "data:image/png;base64,AA" for p in feedback)
    assert any(p.get("type") == "text" and "[图片：概念图]" in p.get("text", "") for p in feedback)


def test_format_tool_results_still_text_for_others():
    """普通工具回喂保持纯文本不变"""
    feedback = format_tool_results([{"name": "storyboard_patch_draft", "ok": True, "data": {}}])
    assert isinstance(feedback, str)
    assert "storyboard_patch_draft：执行成功" in feedback


def test_strip_prior_feedback_images():
    """新回喂带图时旧轮图片被剥离，文本保留并附说明"""
    msgs = [
        {"role": "user", "content": [
            {"type": "text", "text": FEEDBACK_MARKER + "已加载 2 张"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,OLD"}},
        ]},
    ]
    strip_prior_feedback_images(msgs)
    content = msgs[0]["content"]
    assert not any(p.get("type") == "image_url" for p in content)
    assert any("已从上下文移除" in p.get("text", "") for p in content)


def test_compress_prior_feedback_handles_list_content():
    """惰性压缩同样覆盖多模态回喂（list content）"""
    msgs = [
        {"role": "user", "content": [
            {"type": "text", "text": FEEDBACK_MARKER + "全文……"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,X"}},
        ]},
    ]
    compress_prior_feedback(msgs)
    assert isinstance(msgs[0]["content"], str)
