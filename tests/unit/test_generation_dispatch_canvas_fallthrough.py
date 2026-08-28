"""生图降级链单测（打桩在 CanvasBackend 适配器/协议层）。

覆盖三场景：
1. 在线成功 → 返回画布产物 URL（从画布状态回读），不走本地直连
2. 画布离线 → 静默降级本地直连（调用方无感）
3. 画布生图失败（AdapterError）→ 静默降级本地直连
另覆盖产物回读边界：图片仅存浏览器内地址（服务端不可回读）或
回读画布状态失败时仍静默降级。
"""
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest

from src.video_agent.exceptions import AdapterError
from src.video_agent.web import generation_dispatch


# ---------- 打桩：画布后端（满足 CanvasBackend 端口的最小子集） ----------

class StubCanvasBackend:
    """协议层打桩：只实现降级链用到的端口方法"""

    def __init__(
        self,
        *,
        online: bool = True,
        generate_result: Optional[Dict[str, Any]] = None,
        generate_error: Optional[Exception] = None,
        canvas_state: Optional[Dict[str, Any]] = None,
        state_error: Optional[Exception] = None,
    ):
        self.online = online
        self.generate_result = generate_result or {}
        self.generate_error = generate_error
        self.canvas_state = canvas_state or {}
        self.state_error = state_error
        self.payload: Optional[Dict[str, Any]] = None
        self.generate_calls = 0
        self.is_online_calls = 0
        self.get_canvas_calls = 0

    async def is_online(self) -> bool:
        self.is_online_calls += 1
        return self.online

    async def generate_image_online(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self.generate_calls += 1
        self.payload = payload
        if self.generate_error:
            raise self.generate_error
        return self.generate_result

    async def get_canvas(self, canvas_id: str = "") -> Dict[str, Any]:
        self.get_canvas_calls += 1
        if self.state_error:
            raise self.state_error
        return self.canvas_state


# ---------- 打桩：本地直连路径（fallthrough 目标） ----------

class FakeLocalImageAdapter:
    instances: List["FakeLocalImageAdapter"] = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.called = False
        FakeLocalImageAdapter.instances.append(self)

    async def generate_image(self, prompt, size=None, aspect_ratio=None, reference_images=None):
        self.called = True
        return SimpleNamespace(image_urls=["http://local/generated.png"])

    async def close(self):
        pass


@pytest.fixture(autouse=True)
def _patch_common(monkeypatch):
    """公共打桩：本地直连链路 + provider 解析（画布后端由各用例自行注入）"""
    FakeLocalImageAdapter.instances = []

    async def fake_resolve_ref(provider_id: str) -> str:
        return provider_id

    async def fake_provider_config(provider_id: str):
        return {"id": provider_id, "protocol": "openai", "image_models": ["m-1"]}

    async def fake_endpoint(provider_id: str, model: str):
        return ("http://endpoint/v1", "key", model or "m-1")

    monkeypatch.setattr(generation_dispatch, "resolve_provider_ref_async", fake_resolve_ref)
    monkeypatch.setattr(generation_dispatch, "get_provider_config_async", fake_provider_config)
    monkeypatch.setattr(generation_dispatch, "resolve_openai_endpoint_async", fake_endpoint)
    monkeypatch.setattr(generation_dispatch, "OpenAICompatImageAdapter", FakeLocalImageAdapter)
    yield


def _install(monkeypatch, backend: StubCanvasBackend) -> None:
    monkeypatch.setattr(generation_dispatch, "get_canvas_adapter", lambda: backend)


def _infinite_state_with_image(content: str) -> Dict[str, Any]:
    """config 节点 → 图片节点连线的画布状态（对端生成流程产物形态）"""
    return {
        "projectId": "p1",
        "nodes": [
            {"id": "config-1", "type": "config", "metadata": {"status": "success"}},
            {"id": "image-9", "type": "image", "metadata": {"content": content, "status": "success"}},
        ],
        "connections": [{"id": "c1", "fromNodeId": "config-1", "toNodeId": "image-9"}],
    }


async def _generate():
    return await generation_dispatch.generate_image_via_provider(
        "grsai", "m-1", "一只猫", size="1024x1024", aspect_ratio="1:1"
    )


# ---------- 场景一：在线成功 ----------

async def test_online_success_reads_url_from_state(monkeypatch):
    """产物从画布图片节点回读 URL；闸口判定交给 is_online"""
    backend = StubCanvasBackend(
        generate_result={
            "status": "succeeded",
            "tasks": [{"id": "config-1", "status": "succeeded", "source": "canvas"}],
        },
        canvas_state=_infinite_state_with_image("http://cdn/generated.png"),
    )
    _install(monkeypatch, backend)

    assert await _generate() == "http://cdn/generated.png"
    assert backend.generate_calls == 1
    assert backend.get_canvas_calls == 1
    assert backend.payload["provider_id"] == "grsai"
    assert backend.payload["model"] == "m-1"
    assert backend.payload["prompt"] == "一只猫"
    assert FakeLocalImageAdapter.instances == []  # 未走本地直连


# ---------- 场景二：画布离线静默降级 ----------

async def test_offline_silent_fallthrough(monkeypatch):
    """/health ok=false 或 hasCanvas=false 均体现为 is_online=False"""
    backend = StubCanvasBackend(online=False)
    _install(monkeypatch, backend)

    assert await _generate() == "http://local/generated.png"
    assert backend.generate_calls == 0  # 离线不发起画布生图
    assert len(FakeLocalImageAdapter.instances) == 1


# ---------- 场景三：画布生图失败静默降级 ----------

async def test_generation_failed_silent_fallthrough(monkeypatch):
    """轮询到 failed/超时（AdapterError）→ 调用方无感降级"""
    backend = StubCanvasBackend(
        generate_error=AdapterError("画布在线生图超时 (180s)", retryable=True)
    )
    _install(monkeypatch, backend)

    assert await _generate() == "http://local/generated.png"
    assert backend.generate_calls == 1
    assert len(FakeLocalImageAdapter.instances) == 1


# ---------- 产物回读边界 ----------

async def test_unreadable_image_falls_through(monkeypatch):
    """产物图片仅存浏览器内地址（blob:）→ 服务端不可取 → 静默降级本地"""
    backend = StubCanvasBackend(
        generate_result={
            "status": "succeeded",
            "tasks": [{"id": "config-1", "status": "succeeded", "source": "canvas"}],
        },
        canvas_state=_infinite_state_with_image("blob:http://localhost:3000/abc"),
    )
    _install(monkeypatch, backend)

    assert await _generate() == "http://local/generated.png"
    assert backend.generate_calls == 1
    assert len(FakeLocalImageAdapter.instances) == 1


async def test_state_read_error_falls_through(monkeypatch):
    """成功后回读画布状态失败 → 静默降级本地（不抛错）"""
    backend = StubCanvasBackend(
        generate_result={
            "status": "succeeded",
            "tasks": [{"id": "config-1", "status": "succeeded"}],
        },
        state_error=AdapterError("无法连接 canvas-agent"),
    )
    _install(monkeypatch, backend)

    assert await _generate() == "http://local/generated.png"
    assert len(FakeLocalImageAdapter.instances) == 1
