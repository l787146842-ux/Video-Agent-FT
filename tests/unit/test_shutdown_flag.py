"""评审返修批：Warn 关停标志复位出口（agent_task_manager._SHUTTING_DOWN）。

根因：_SHUTTING_DOWN 是模块级全局，无复位出口且只在 main() 包装的 handle_exit
置位（CLI/TestClient 启动不触发）→ 一次关停置位会永久残留：同进程内重启/
TestClient 复用进程时，后续在途 SSE gen 轮询 is_shutting_down() 一律立即收
终态帧（假关停）。

修复：
- 补 reset_shutting_down() 并在 lifespan startup 调用（复位出口）；
- mark_shutting_down() 同时接进 lifespan.shutdown 起点，使 CLI（handle_exit 置位）
  与 TestClient（不走 handle_exit）两种启动方式状态一致、可重入。

测试（规格原文）：置位→SSE 收终态帧→复位→SSE 恢复。
"""
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.video_agent.web import agent_task_manager as atm
from src.video_agent.web.agent_task_manager import (
    is_shutting_down,
    mark_shutting_down,
    reset_shutting_down,
    shutdown_terminal_frame,
)


@pytest.fixture(autouse=True)
def _restore_flag():
    """逐测试复位关停标志（模块级全局，防跨用例残留导致假关停）。"""
    reset_shutting_down()
    yield
    reset_shutting_down()


class _StubTM:
    """最小任务管理器桩：subscribe 回放 replay + done 终态帧（不触磁盘/不建 worker）。

    SSE 端点在函数内 `from ... import get_agent_task_manager` 运行时解析模块属性，
    故 monkeypatch atm.get_agent_task_manager 即可注入（同 test_session_parallel_b6）。

    队列同时投递 replay 与 done：Starlette TestClient 的 stream() 会同步跑完整个
    ASGI gen 才返回响应，故 gen 必须能自然收尾——done 是终态事件（gen 收到即 break），
    避免「running 任务无终态帧 → gen 永挂」。关停置位分支在 q.get() 之前命中，
    队列内容不被消费（首帧仍是关停终态帧），两种情况都能正常结束。"""

    def __init__(self, task_id: str):
        self.task_id = task_id

    def subscribe(self, task_id):
        import asyncio
        if task_id != self.task_id:
            return None
        q: asyncio.Queue = asyncio.Queue(maxsize=10)
        q.put_nowait({
            "type": "replay", "event_seq": 0,
            "payload": {"task_id": task_id, "status": "done"},
        })
        # 终态帧：使 SSE gen 在复位（非关停）路径下能自然 break 收尾
        q.put_nowait({
            "type": "done", "event_seq": 1,
            "payload": {"text": "完成", "applied_actions": 0},
        })
        return q

    def unsubscribe(self, task_id, q):  # noqa: ARG002
        pass


@pytest.fixture
def sse_env(monkeypatch):
    """挂载 agent 路由 + 注入桩 TM，返回 (client, task_id)。"""
    from src.video_agent.web.routes import agent as agent_routes
    from src.video_agent.web.app import video_agent_error_handler
    from src.video_agent.exceptions import VideoAgentError

    task_id = "agt-shutdown-test"
    monkeypatch.setattr(atm, "get_agent_task_manager", lambda: _StubTM(task_id))

    app = FastAPI()
    app.include_router(agent_routes.router, prefix="/api")
    app.add_exception_handler(VideoAgentError, video_agent_error_handler)
    return TestClient(app), task_id


def _first_sse_frame(client, task_id) -> dict:
    """订阅 SSE 并只读第一个 data 帧（读完即关流，避免 running 任务长挂阻塞）。"""
    with client.stream("GET", f"/api/agent/tasks/{task_id}/events") as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        for line in resp.iter_lines():
            if line.startswith("data: "):
                return json.loads(line[len("data: "):])
    raise AssertionError("SSE 未下发任何 data 帧")


# ===================== 标志生命周期（复位出口存在且可重入） =====================

def test_shutdown_flag_lifecycle_resettable():
    """核心修复：reset_shutting_down 复位出口存在——mark→True，reset→False，可重入。"""
    reset_shutting_down()
    assert is_shutting_down() is False
    mark_shutting_down()
    assert is_shutting_down() is True
    # 复位出口：一次关停置位不再永久残留
    reset_shutting_down()
    assert is_shutting_down() is False
    # 可重入：再次置位/复位仍正确（同进程重启场景）
    mark_shutting_down()
    assert is_shutting_down() is True
    reset_shutting_down()
    assert is_shutting_down() is False


def test_shutdown_terminal_frame_shape():
    """终态帧契约：type=error（与自然终止分支一致 break）+ code/kind 供前端映射。"""
    frame = shutdown_terminal_frame()
    assert frame["type"] == "error"
    assert frame["code"] == "SERVER_SHUTDOWN"
    assert frame["kind"] == "server_shutdown"
    assert frame["message"]


# ===================== SSE：置位→收终态帧→复位→恢复 =====================

def test_sse_yields_terminal_frame_when_shutting_down(sse_env):
    """置位：在途 SSE gen 轮询 is_shutting_down() → 首帧即关停终态帧后收尾。"""
    client, task_id = sse_env
    mark_shutting_down()
    frame = _first_sse_frame(client, task_id)
    assert frame["type"] == "error"
    assert frame["code"] == "SERVER_SHUTDOWN", f"关停中未下发终态帧: {frame}"


def test_sse_recovers_after_reset(sse_env):
    """复位：reset_shutting_down 后 SSE 恢复——首帧回到 replay（非假关停终态帧）。

    钉死根因回归：无复位出口时，前一次关停置位永久残留，此处会误收终态帧。"""
    client, task_id = sse_env
    # 先模拟一次关停置位（残留态）
    mark_shutting_down()
    assert is_shutting_down() is True
    # 复位（lifespan startup 出口）后恢复
    reset_shutting_down()
    frame = _first_sse_frame(client, task_id)
    assert frame["type"] == "replay", f"复位后仍收终态帧（假关停残留）: {frame}"
    assert frame["payload"]["task_id"] == task_id


def test_sse_full_shutdown_then_reset_cycle(sse_env):
    """完整时序（规格原文）：置位→SSE 收终态帧→复位→SSE 恢复，同一进程内连贯。"""
    client, task_id = sse_env

    # ① 置位 → SSE 收终态帧
    mark_shutting_down()
    f1 = _first_sse_frame(client, task_id)
    assert f1["type"] == "error" and f1["code"] == "SERVER_SHUTDOWN"

    # ② 复位 → SSE 恢复（首帧 replay）
    reset_shutting_down()
    f2 = _first_sse_frame(client, task_id)
    assert f2["type"] == "replay"

    # ③ 再置位 → 再次收终态帧（可重入，两种启动方式状态一致）
    mark_shutting_down()
    f3 = _first_sse_frame(client, task_id)
    assert f3["type"] == "error" and f3["code"] == "SERVER_SHUTDOWN"
