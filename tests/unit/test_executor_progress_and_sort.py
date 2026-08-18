# -*- coding: utf-8 -*-
"""Q2/Q3/Q4 回归：执行器子步骤进时间线、首拆即显快照、补漏元素按类别归位"""
import pytest

from src.video_agent.skill_runtime import executors as ex_mod
from src.video_agent.skill_runtime.progress import (
    bind_progress_emitter,
    emit_state_refresh,
    emit_timeline_note,
    unbind_progress_emitter,
)
from src.video_agent.state.manager import StateManager
from src.video_agent.web import skill_docs as sd
from src.video_agent.skill_runtime import registry
from src.video_agent.skill_runtime import exec_common
from src.video_agent.web import generation as gen_mod


@pytest.fixture(autouse=True)
def _reset_registry():
    registry.reset_registry()
    yield
    registry.reset_registry()


@pytest.fixture(autouse=True)
def _isolate_skills(tmp_path, monkeypatch):
    """隔离 data/skills：防止测试 _write 污染真实 skill 目录（ke-prog 覆盖事故）。"""
    d = tmp_path / "skills"
    d.mkdir()
    monkeypatch.setattr(sd, "SKILL_DOCS_DIR", d)
    yield


@pytest.fixture(autouse=True)
def _bridge_stream_calls(monkeypatch):
    """流式拆解桥接：call_chat_completion_stream 转发到测试 patch 的
    call_chat_completion（整段一次性回放），适配 Q5 流式逐条落盘改造。"""

    async def fake_stream(provider, model, messages, *, max_tokens=8192,
                          temperature=0.7, timeout=180, on_delta=None, **_kw):
        content, finish = await gen_mod.call_chat_completion(
            provider, model, messages, max_tokens=max_tokens
        )
        if on_delta and content:
            await on_delta(content)
        return content, finish

    monkeypatch.setattr(gen_mod, "call_chat_completion_stream", fake_stream)


def _write(slug: str, content: str):
    sd.save_skill_doc(slug, content)


# ---------- Q4：补漏元素不垫底（按类别稳定排序） ----------

def test_sort_key_elements_by_badge_stable(tmp_path):
    svc = StateManager(str(tmp_path / "ws"))
    svc.state_dict["keyElements"] = [
        {"id": "1", "title": "二向箔", "badgeLabel": "道具", "drafts": []},
        {"id": "2", "title": "罗辑", "badgeLabel": "人物", "drafts": []},
        {"id": "3", "title": "冥王星", "badgeLabel": "场景", "drafts": []},
        {"id": "4", "title": "星环号", "badgeLabel": "载具", "drafts": []},
        {"id": "5", "title": "程心", "badgeLabel": "人物", "drafts": []},
    ]
    assert ex_mod._sort_key_elements_by_badge(svc) is True
    ids = [g["id"] for g in svc.state_dict["keyElements"]]
    # 人物（保持原先后）→ 场景 → 道具 → 载具
    assert ids == ["2", "5", "3", "1", "4"]
    # 已有序时不再改动状态
    assert ex_mod._sort_key_elements_by_badge(svc) is False


def test_sort_badge_unknown_labels_keep_relative_order(tmp_path):
    svc = StateManager(str(tmp_path / "ws"))
    svc.state_dict["keyElements"] = [
        {"id": "1", "title": "太阳系", "badgeLabel": "宏观天体", "drafts": []},
        {"id": "2", "title": "程心", "badgeLabel": "人物", "drafts": []},
        {"id": "3", "title": "二向箔", "badgeLabel": "", "drafts": []},
    ]
    ex_mod._sort_key_elements_by_badge(svc)
    ids = [g["id"] for g in svc.state_dict["keyElements"]]
    # 人物最前；未命中的两个保持原相对顺序
    assert ids == ["2", "1", "3"]


# ---------- Q2/Q3：子步骤时间线明细 + 首拆即显快照 ----------

@pytest.mark.asyncio
async def test_split_emits_notes_and_snapshots_and_sorts(monkeypatch, tmp_path):
    """完整 KE 拆解：首拆落盘即发快照+明细；验收定向补建后再发一次并按类别归位。"""
    from src.video_agent.skill_runtime.executors import (
        StoryboardKeyElementsTool, StoryboardSplitInput,
    )

    _write(
        "ke-prog",
        "# KE\n> 调用规则：测试\n<storyboard_key_elements>\n拆解规范\n</storyboard_key_elements>\n",
    )
    calls = {"n": 0}

    async def fake_chat(provider, model, messages, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            # 首拆：故意乱序（道具在前、人物在后），验证补建后归位
            return ('[{"action":"add_group","group_type":"keyElement",'
                    '"title":"二向箔","desc":"道具","badgeLabel":"道具"},'
                    '{"action":"add_group","group_type":"keyElement",'
                    '"title":"罗辑","desc":"角色","badgeLabel":"人物"}]', "stop")
        if calls["n"] == 2:
            # 定向补拆轮：补机器验收发现的缺失台词人程心
            return ('[{"action":"add_group","group_type":"keyElement",'
                    '"title":"程心","desc":"角色","badgeLabel":"人物"}]', "stop")
        return ("[]", "stop")  # 不应再发生（补拆只跑 1 轮）

    def fake_resolve(provider="", model=""):
        return ("fake-provider", "fake-model")

    svc = StateManager(str(tmp_path / "ws"))
    # 清空 demo 项目自带分组，构造干净故事板
    svc.state_dict["keyElements"] = []
    svc.state_dict["shots"] = []
    svc.state_dict["audioItems"] = []
    svc.state_dict["uploadedDocs"] = [
        {"id": "d1", "name": "剧本.md", "content": "剧本正文：\n罗辑：黑暗森林。\n程心：好的。"}
    ]
    monkeypatch.setattr(gen_mod, "call_chat_completion", fake_chat)
    monkeypatch.setattr(exec_common, "_resolve_chat_provider", fake_resolve)
    monkeypatch.setattr(StateManager, "get_instance", classmethod(lambda cls: svc))

    events = []

    async def collector(ev):
        events.append(ev)

    token = bind_progress_emitter(collector)
    try:
        tool = StoryboardKeyElementsTool()
        result = await tool.aexecute(StoryboardSplitInput(skill_name="KE-PROG"))
    finally:
        unbind_progress_emitter(token)

    assert result.success, result.error
    # Q3：首拆落盘 + 验收补建，各发一次状态快照（前端左栏增量点亮）
    applied_events = [e for e in events if e.get("type") == "actions_applied"]
    assert len(applied_events) >= 2
    # Q2：子步骤明细进时间线（首拆/补拆轮都有）
    notes = [
        e.get("result_summary", "")
        for e in events if e.get("type") == "tool_finished" and str(e.get("id", "")).startswith("sub-")
    ]
    assert any("首拆完成" in s for s in notes)
    assert any("验收" in s and "补建 1 个遗漏元素" in s for s in notes)
    # 只跑 1 轮补拆：不应出现第二轮明细
    assert not any("第 2 轮" in s for s in notes)
    # Q4：补建后按类别归位（人物保持原先后→道具），补建的人物不垫底
    titles = [g["title"] for g in svc.state_dict["keyElements"]]
    assert titles == ["罗辑", "程心", "二向箔"]


@pytest.mark.asyncio
async def test_emit_helpers_without_emitter_no_error():
    """未绑定事件通道（单测/CLI）：只记 trace、不抛异常。"""
    await emit_timeline_note("测试明细")
    await emit_state_refresh(3)


@pytest.mark.asyncio
async def test_emit_state_refresh_with_emitter():
    events = []

    async def collector(ev):
        events.append(ev)

    token = bind_progress_emitter(collector)
    try:
        await emit_state_refresh(5)
    finally:
        unbind_progress_emitter(token)
    assert events and events[0]["type"] == "actions_applied"
    assert events[0]["count"] == 5
