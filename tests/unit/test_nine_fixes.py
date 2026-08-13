# -*- coding: utf-8 -*-
"""九项修复回归测试（7777 复盘批次）：
- D2：整板保存乐观锁（board_version 校验 + 快照携带版本）
- B：write_media_prompt 执行器批次指令注入 @ 引用规则与出场元素清单
- C3：视频参考三桶拆分（视频参考项不再被静默丢弃）+ 新上限默认值
- A：任务管理器累计 model_fallback 事件（replay 补跳选择器用）
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.video_agent.state.manager import StateManager


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
    app = FastAPI()
    app.include_router(project_routes.router, prefix="/api")
    return TestClient(app)


# ---------- D2：乐观锁 ----------

def test_snapshot_carries_board_version(svc):
    snap = svc.get_full_snapshot()
    assert "board_version" in snap
    assert isinstance(snap["board_version"], int)


def test_put_state_accepts_matching_version_and_bumps(client, svc):
    current = svc.board_version
    r = client.put("/api/project/state", json={"base_version": current, "shots": []})
    assert r.status_code == 200
    assert r.json()["ok"] is True
    # 响应必须回传落盘后版本：前端据此跟进，否则下次 PUT 永远落后 1 被拒
    assert r.json()["board_version"] == current + 1
    assert svc.board_version == current + 1


def test_put_state_consecutive_edits_both_accepted(client, svc):
    """回归（用户实测事故）：前端每次 PUT 成功后采纳响应版本跟进，
    连续两次编辑的保存必须都成功，不得第二次因落后 1 被 409 拒。"""
    v = svc.board_version
    r1 = client.put("/api/project/state", json={"base_version": v, "shots": []})
    assert r1.status_code == 200
    v = r1.json()["board_version"]  # 前端跟进版本
    r2 = client.put("/api/project/state", json={"base_version": v, "shots": []})
    assert r2.status_code == 200
    assert r2.json()["board_version"] == v + 1


def test_put_state_rejects_stale_version(client, svc):
    # 模拟在途期间后端已写入（版本前进），前端陈旧 PUT 必须被拒
    client.put("/api/project/state", json={"base_version": svc.board_version, "shots": []})
    stale = svc.board_version - 1
    r = client.put("/api/project/state", json={"base_version": stale, "shots": []})
    assert r.status_code == 409
    assert "版本冲突" in r.json()["detail"]


def test_put_state_without_version_still_allowed(client, svc):
    # 旧客户端不带 base_version：保持兼容（不校验）
    r = client.put("/api/project/state", json={"shots": []})
    assert r.status_code == 200


# ---------- B：执行器 @ 引用规则移植 ----------

@pytest.mark.asyncio
async def test_write_prompt_batch_shot_injects_at_rule(monkeypatch, tmp_path):
    """7777 事故回归：分镜批次指令必须携带 @引用规则 + 本镜头出场元素清单。"""
    from src.video_agent.skill_runtime import executors as ex_mod

    svc = StateManager(str(tmp_path / "ws"))
    svc.state_dict["keyElements"] = [
        {"id": "ke-1", "title": "二向箔", "drafts": []},
        {"id": "ke-2", "title": "太阳系外缘", "drafts": []},
    ]
    shot = {
        "id": "shot-1", "title": "二向箔展开",
        "sceneRefs": ["ke-1", "ke-2"],
        "drafts": [{"id": "d1", "prompt": ""}],
    }
    captured = {}

    async def fake_stream(tool, skill, system, user, svc_, content, **kwargs):
        captured["system"] = system
        captured["user"] = user
        return (0, [], "", "stop")

    monkeypatch.setattr(ex_mod, "_stream_actions_progressive", fake_stream)
    await ex_mod._write_prompt_batch(
        "write_media_prompt", "测试技能", "", svc, "prov", "model",
        [("shots", shot)], "规格", "摘要",
    )
    assert "【@引用规则】" in captured["system"]
    assert "本镜头出场元素：二向箔、太阳系外缘" in captured["user"]


@pytest.mark.asyncio
async def test_write_prompt_batch_keyelement_no_at_rule(monkeypatch, tmp_path):
    """关键元素批次不注入分镜 @ 规则（避免干扰元素图提示词）。"""
    from src.video_agent.skill_runtime import executors as ex_mod

    svc = StateManager(str(tmp_path / "ws"))
    svc.state_dict["keyElements"] = [
        {"id": "ke-1", "title": "二向箔", "drafts": [{"id": "d1", "prompt": ""}]},
    ]
    captured = {}

    async def fake_stream(tool, skill, system, user, svc_, content, **kwargs):
        captured["system"] = system
        return (0, [], "", "stop")

    monkeypatch.setattr(ex_mod, "_stream_actions_progressive", fake_stream)
    await ex_mod._write_prompt_batch(
        "write_media_prompt", "测试技能", "", svc, "prov", "model",
        [("keyElements", svc.state_dict["keyElements"][0])], "规格", "摘要",
    )
    assert "【@引用规则】" not in captured["system"]


# ---------- C3：视频参考三桶 + 新上限 ----------

def test_settings_ref_limits_defaults():
    from src.video_agent.config import settings
    assert settings.video_ref_limit_image == 30
    assert settings.video_ref_limit_video == 10
    assert settings.video_ref_limit_audio == 10
    assert settings.video_ref_limit_total == 50
    assert settings.image_ref_limit == 10


def test_video_adapter_normalizes_video_ref():
    """视频参考项（role=reference_video 或 .mp4 扩展名）归一为 video 类，不再误判为图片。"""
    from src.video_agent.adapters.video_compat import OpenAICompatVideoAdapter
    refs = OpenAICompatVideoAdapter._normalize_media_refs(
        [
            {"url": "/workspace/assets/a.mp4", "role": "reference_video"},
            {"url": "https://cdn.example.com/b.mov"},
        ],
        "",
    )
    assert all(r["kind"] == "video" for r in refs)
    assert all(r["role"] == "reference_video" for r in refs)


def test_video_adapter_builds_video_url_content():
    """Seedance 媒体列表格式包含 video_url 内容项（C3：≤10 段视频参考）。"""
    from src.video_agent.adapters.video_compat import OpenAICompatVideoAdapter
    content = OpenAICompatVideoAdapter._build_media_content(
        "提示词",
        [{"url": "/workspace/assets/a.mp4", "kind": "video", "role": "reference_video"}],
    )
    assert content[0]["type"] == "text"
    assert content[1]["type"] == "video_url"
    assert content[1]["video_url"]["url"] == "/workspace/assets/a.mp4"


def test_resolve_scene_refs_limit_param(tmp_path):
    from src.video_agent.state import storyboard_ops as ops
    state = {
        "keyElements": [
            {"id": f"ke-{i}", "title": f"元素{i}",
             "drafts": [{"imgUrl": f"http://x/{i}.png"}]}
            for i in range(8)
        ],
    }
    group = {"sceneRefs": [f"ke-{i}" for i in range(8)]}
    assert len(ops.resolve_scene_refs(state, group)) == 5          # 默认保持旧上限
    assert len(ops.resolve_scene_refs(state, group, limit=30)) == 8


# ---------- A：任务管理器累计 model_fallback ----------

def test_agent_task_manager_records_model_fallback():
    """降级即时事件累计进任务记录，replay 携带供前端补跳选择器。"""
    from src.video_agent.web.agent_task_manager import AgentTaskManager
    tm = AgentTaskManager.__new__(AgentTaskManager)
    record = {"fallback": None, "status": "running"}
    tm._tasks = {"t1": record}
    tm._apply_event(record, {"type": "model_fallback", "provider": "p2", "model": "m2"})
    assert record["fallback"] == {"provider": "p2", "model": "m2"}


# ---------- 超时重试可视化（7777 挂死静默事故） ----------

@pytest.mark.asyncio
async def test_stream_notify_bind_and_emit():
    """通知通道：绑定后 notify_stream 送达，未绑定静默。"""
    from src.video_agent.utils.stream_notify import (
        bind_stream_notifier, unbind_stream_notifier, notify_stream,
    )
    got = []

    async def notifier(text):
        got.append(text)

    await notify_stream("未绑定，应被忽略")
    token = bind_stream_notifier(notifier)
    try:
        await notify_stream("等待中…")
    finally:
        unbind_stream_notifier(token)
    await notify_stream("已解绑，应被忽略")
    assert got == ["等待中…"]


@pytest.mark.asyncio
async def test_with_retry_notifies_on_transient_failure():
    """非流式重试：瞬时故障重试前向前端推送状态文案（不再静默）。"""
    import httpx
    from src.video_agent.adapters import retry as retry_mod
    from src.video_agent.utils.stream_notify import (
        bind_stream_notifier, unbind_stream_notifier,
    )
    got = []

    async def notifier(text):
        got.append(text)

    calls = {"n": 0}

    async def flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ReadTimeout("read timed out")
        return "ok"

    token = bind_stream_notifier(notifier)
    try:
        result = await retry_mod.with_retry(flaky, max_retries=2, base_delay=0.01, context="chat")
    finally:
        unbind_stream_notifier(token)
    assert result == "ok"
    assert any("重试" in t for t in got)


@pytest.mark.asyncio
async def test_chat_stream_retry_notifies_user():
    """流式重试：首块前瞬时故障 → 重试文案即时推送（7777 静默挂死修复）。"""
    from src.video_agent.adapters.base_chat import StreamChunk
    from src.video_agent.adapters.openai_compat import OpenAICompatChatAdapter
    from src.video_agent.exceptions import AdapterError
    from src.video_agent.utils.stream_notify import (
        bind_stream_notifier, unbind_stream_notifier,
    )
    got = []

    async def notifier(text):
        got.append(text)

    adapter = OpenAICompatChatAdapter(base_url="http://fake", api_key="k", model="m")
    calls = {"n": 0}

    async def fake_stream_once(payload, timeout):
        calls["n"] += 1
        if calls["n"] == 1:
            raise AdapterError("LLM 返回 HTTP 502: 繁忙", retryable=True, http_status=502)
        yield StreamChunk(type="text_delta", text="你好")
        yield StreamChunk(type="done", finish_reason="stop")

    adapter._stream_once = fake_stream_once
    token = bind_stream_notifier(notifier)
    try:
        chunks = [c async for c in adapter.chat_stream([{"role": "user", "content": "x"}])]
    finally:
        unbind_stream_notifier(token)
    assert [c.type for c in chunks] == ["text_delta", "done"]
    assert any("重试" in t for t in got)


# ---------- write_media_prompt 重写模式（7777 "重写全部"卡死事故） ----------

_SHOTS_WITH_PROMPTS = lambda: [
    {"id": "s1", "title": "镜头1", "drafts": [{"id": "d1", "prompt": "旧提示词1"}]},
    {"id": "s2", "title": "镜头2", "drafts": [{"id": "d2", "prompt": "旧提示词2"}]},
    {"id": "s3", "title": "镜头3", "drafts": [{"id": "d3", "prompt": ""}]},
]


def test_pending_prompt_groups_overwrite_and_scope():
    """选取语义：补写只挑空分组；重写纳入全部；具体 draft_id 收窄到单张。"""
    from src.video_agent.skill_runtime.executors import _pending_prompt_groups
    state = {"keyElements": [], "audioItems": [], "shots": _SHOTS_WITH_PROMPTS()}
    ids = lambda lst: [g["id"] for _, g in lst]
    # 补写（默认）：只有无提示词的 s3
    assert ids(_pending_prompt_groups(state, "all_shots")) == ["s3"]
    # 重写：三个分组全部纳入
    assert ids(_pending_prompt_groups(state, "all_shots", overwrite=True)) == ["s1", "s2", "s3"]
    # 单张重写：draft_id 收窄到所属分组，不误伤其他
    assert ids(_pending_prompt_groups(state, "d2", overwrite=True)) == ["s2"]
    # 具体 group_id 同样收窄
    assert ids(_pending_prompt_groups(state, "s1", overwrite=True)) == ["s1"]


@pytest.fixture
def wmp_env(tmp_path, monkeypatch):
    """隔离 Skill 目录 + 注册带 write_the_prompt 章节的测试技能 + 接管实例/供应商解析。"""
    import src.video_agent.web.skill_docs as sd
    from src.video_agent.skill_runtime import registry
    from src.video_agent.skill_runtime import executors as ex_mod

    monkeypatch.setattr(sd, "SKILL_DOCS_DIR", tmp_path / "skills")
    registry.reset_registry()
    sd.save_skill_doc(
        "重写技能",
        "# 重写技能\n> 调用规则：测试\n<write_the_prompt>\n写中文提示词\n</write_the_prompt>\n",
    )
    svc = StateManager(str(tmp_path / "ws"))
    svc.state_dict["keyElements"] = []
    svc.state_dict["audioItems"] = []
    svc.state_dict["shots"] = _SHOTS_WITH_PROMPTS()
    monkeypatch.setattr(StateManager, "get_instance", classmethod(lambda cls: svc))
    monkeypatch.setattr(ex_mod, "_resolve_chat_provider", lambda p="", m="": ("fake", "fake-model"))
    yield svc
    registry.reset_registry()


def _make_fake_stream(svc, write: bool):
    """伪造批次写入：按 user 指令里的 group_id 清单替换提示词（write=False 模拟中断零产出）"""
    import re

    async def fake_stream(tool, skill, system, user, svc_, content, **kwargs):
        if not write:
            return (0, [], "", "stop")
        gids = set(re.findall(r"group_id=(\S+?)（", user))
        applied = 0
        for g in svc_.state_dict.get("shots") or []:
            if g["id"] in gids:
                for d in g["drafts"]:
                    d["prompt"] = "重写后的提示词 @镜头元素"
                applied += 1
        return (applied, [], "", "stop")

    return fake_stream


@pytest.mark.asyncio
async def test_write_media_prompt_overwrite_full_replaces_all(monkeypatch, wmp_env):
    """全量重写：overwrite=true + all_shots → 旧提示词全部被覆盖，一张不漏。"""
    from src.video_agent.skill_runtime import executors as ex_mod
    from src.video_agent.skill_runtime.executors import WriteMediaPromptInput, WriteMediaPromptTool

    svc = wmp_env
    monkeypatch.setattr(ex_mod, "_stream_actions_progressive", _make_fake_stream(svc, write=True))
    result = await WriteMediaPromptTool().aexecute(
        WriteMediaPromptInput(skill_name="重写技能", target="all_shots", overwrite=True)
    )
    assert result.success, result.error
    prompts = [d["prompt"] for g in svc.state_dict["shots"] for d in g["drafts"]]
    assert all(p == "重写后的提示词 @镜头元素" for p in prompts)
    assert "重写" in result.data["detail"]


@pytest.mark.asyncio
async def test_write_media_prompt_overwrite_interrupt_keeps_old_and_resumes(monkeypatch, wmp_env):
    """中断无损失 + 续写：首次零产出（模拟超时/停止）判失败且旧提示词完整保留；
    再次带 overwrite 调用从断点续写补齐。"""
    from src.video_agent.skill_runtime import executors as ex_mod
    from src.video_agent.skill_runtime.executors import WriteMediaPromptInput, WriteMediaPromptTool

    svc = wmp_env
    # 第一次：全部批次零产出（模拟内层调用挂死/被停止）
    monkeypatch.setattr(ex_mod, "_stream_actions_progressive", _make_fake_stream(svc, write=False))
    result1 = await WriteMediaPromptTool().aexecute(
        WriteMediaPromptInput(skill_name="重写技能", target="all_shots", overwrite=True)
    )
    assert not result1.success
    assert "overwrite=true" in result1.error  # 续写指引必须提醒再带 overwrite
    # 旧提示词完整保留（未出现清空裸奔窗口）
    olds = [d["prompt"] for g in svc.state_dict["shots"] for d in g["drafts"]]
    assert olds == ["旧提示词1", "旧提示词2", ""]

    # 第二次：恢复正常写入，断点续写补齐全部
    monkeypatch.setattr(ex_mod, "_stream_actions_progressive", _make_fake_stream(svc, write=True))
    result2 = await WriteMediaPromptTool().aexecute(
        WriteMediaPromptInput(skill_name="重写技能", target="all_shots", overwrite=True)
    )
    assert result2.success, result2.error
    prompts = [d["prompt"] for g in svc.state_dict["shots"] for d in g["drafts"]]
    assert all(p == "重写后的提示词 @镜头元素" for p in prompts)


@pytest.mark.asyncio
async def test_write_media_prompt_overwrite_single_shot_scope(monkeypatch, wmp_env):
    """单张重写：target 指定 draft_id 只重写该分镜，其他分镜旧提示词不动。"""
    from src.video_agent.skill_runtime import executors as ex_mod
    from src.video_agent.skill_runtime.executors import WriteMediaPromptInput, WriteMediaPromptTool

    svc = wmp_env
    monkeypatch.setattr(ex_mod, "_stream_actions_progressive", _make_fake_stream(svc, write=True))
    result = await WriteMediaPromptTool().aexecute(
        WriteMediaPromptInput(skill_name="重写技能", target="d2", overwrite=True)
    )
    assert result.success, result.error
    prompts = {g["id"]: g["drafts"][0]["prompt"] for g in svc.state_dict["shots"]}
    assert prompts["s2"] == "重写后的提示词 @镜头元素"
    assert prompts["s1"] == "旧提示词1"  # 未被误伤
