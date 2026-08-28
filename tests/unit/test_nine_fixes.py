# -*- coding: utf-8 -*-
"""九项修复回归测试（7777 复盘批次）：
- D2：整板保存乐观锁（board_version 校验 + 快照携带版本）
- C3：视频参考三桶拆分（视频参考项不再被静默丢弃）+ 新上限默认值
- A：任务管理器累计 model_fallback 事件（replay 补跳选择器用）
- 超时重试可视化（stream_notify）
（B：write_media_prompt 执行器批次用例与 write_media_prompt 重写模式用例
已随任务#36 B5 执行器一步退役删除：被测对象 executors._write_prompt_batch /
WriteMediaPromptTool / _pending_prompt_groups 不复存在。）
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
    from src.video_agent.web.app import video_agent_error_handler
    from src.video_agent.exceptions import VideoAgentError
    app = FastAPI()
    app.include_router(project_routes.router, prefix="/api")
    # P9：standalone 应用需注册统一转译 handler（与生产 app.py 同源，
    # 否则 VideoAgentError 无 handler 会被 TestClient 直接抛出）
    app.add_exception_handler(VideoAgentError, video_agent_error_handler)
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
# test_write_prompt_batch_shot_injects_at_rule / test_write_prompt_batch_keyelement_no_at_rule
# 已随任务#36 B5 执行器一步退役删除：被测对象（executors._write_prompt_batch）
# 不复存在；@ 引用补印机制（autofill_at_refs）已随 require_at_ref 闸机
# 退役一并删除。


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
# test_pending_prompt_groups_overwrite_and_scope / test_write_media_prompt_overwrite_full_replaces_all /
# test_write_media_prompt_overwrite_interrupt_keeps_old_and_resumes /
# test_write_media_prompt_overwrite_single_shot_scope 及其 fixture（wmp_env/_make_fake_stream/
# _SHOTS_WITH_PROMPTS）已随任务#36 B5 执行器一步退役删除：被测对象
# （executors._pending_prompt_groups / WriteMediaPromptTool）不复存在，
# 提示词编写改由模型按通用主路径直接调用平台工具完成。
