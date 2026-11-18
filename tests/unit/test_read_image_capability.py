# -*- coding: utf-8 -*-
"""read_image 模型图片能力闸 + read_file 媒体描述符契约（2026-11-13）。

覆盖：
1. 适配器**明确声明**不支持图片输入（False）→ read_image 明确报错，
   且**不产出** images/data_uri；
2. 能力未发布（None = 非对话路径/单测直连）→ 放行（不新增闸门）；
3. 明确支持（True）→ 正常返回 data_uri；
4. read_file 媒体描述符补 mime 字段（{media_kind, mime, size, url}）；
5. 硬链接拒绝（同 inode 第二个目录项可落在包外，resolve() 判不出来）；
6. offset/limit 的 pydantic 边界（ge=1 / le=2000）。

能力传递路径（为何不违层间门禁）：声明轴在 adapters/base_chat
.BaseChatAdapter.supports_image_input；发布经 core/chat_port 的 contextvar
（publish_model_image_support / current_model_supports_image_input），
工具层只 import core.chat_port —— check_layer_imports 只禁 core/tools→web，
故不越界。
"""
import asyncio
import base64
import os

import pytest
from pydantic import ValidationError

import src.video_agent.web.skill_docs as sd
from src.video_agent.adapters.base_chat import BaseChatAdapter, ChatResponse, StreamChunk
from src.video_agent.core import chat_port
from src.video_agent.skill_runtime import registry
from src.video_agent.tools.skill_file_tools import (
    ReadFileInput,
    ReadFileTool,
    ReadImageInput,
    ReadImageTool,
)

# 1x1 透明 PNG
PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"
    "YPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)


@pytest.fixture
def skills(tmp_path, monkeypatch):
    d = tmp_path / "skills"
    pkg = d / "pkg"
    (pkg / "references").mkdir(parents=True)
    (pkg / "assets").mkdir(parents=True)
    (pkg / "SKILL.md").write_text(
        "---\nname: 包测试\ndescription: 测试桩\n---\n# 包测试\n正文\n",
        encoding="utf-8",
    )
    (pkg / "references" / "a.md").write_text("第一行\n第二行\n第三行\n", encoding="utf-8")
    (pkg / "assets" / "pic.png").write_bytes(PNG_BYTES)
    (tmp_path / "secret.md").write_text("SECRET", encoding="utf-8")
    monkeypatch.setattr(sd, "SKILL_DOCS_DIR", d)
    registry.reset_registry()
    registry.sync_all(force=True)
    try:
        yield d
    finally:
        registry.reset_registry()
        chat_port.reset_model_image_support()


def _read_image(path: str = "assets/pic.png"):
    return asyncio.run(ReadImageTool().aexecute(
        ReadImageInput(skill="pkg", file_path=path)))


def _read_file(path: str = "assets/pic.png", offset: int = 1, limit: int = 2000):
    return asyncio.run(ReadFileTool().aexecute(ReadFileInput(
        skill="pkg", file_path=path, offset=offset, limit=limit)))


# ---------- ① 能力闸：明确不支持 → 明确报错且不产出图片 ----------

def test_read_image_rejected_when_adapter_declares_no_image_input(skills):
    """False = 适配器明确声明不支持 → 失败信封 + 零 data_uri/images。"""
    chat_port.publish_model_image_support(False)
    res = _read_image()
    assert res.success is False
    assert res.error_code == "validation"
    err = res.error or ""
    assert "图片输入能力" in err and "read_file" in err
    data = res.data or {}
    assert "images" not in data
    assert "data_uri" not in str(data)


def test_read_image_rejection_comes_before_reading_bytes(skills, monkeypatch):
    """闸门在产出 data URI 之前：即便图片本身可读也不做 base64 内联。"""
    chat_port.publish_model_image_support(False)
    scaled_calls = []

    def _boom(*args, **kwargs):
        scaled_calls.append(args)
        raise AssertionError("不应执行 downscale/base64 路径")

    import src.video_agent.tools.skill_file_tools as sft

    monkeypatch.setattr(sft, "downscale_image", _boom)
    res = _read_image()
    assert res.success is False
    assert scaled_calls == []


# ---------- ② 未发布（None）→ 放行：不新增闸门 ----------

def test_read_image_passes_when_capability_unpublished(skills):
    """None = 非对话路径（单测/CLI 直连）：维持改动前行为，正常出 data_uri。"""
    chat_port.reset_model_image_support()
    assert chat_port.current_model_supports_image_input() is None
    res = _read_image()
    assert res.success is True
    images = (res.data or {}).get("images") or []
    assert images and images[0]["data_uri"].startswith("data:image/")


# ---------- ③ 明确支持（True）→ 放行 ----------

def test_read_image_passes_when_adapter_supports_image_input(skills):
    chat_port.publish_model_image_support(True)
    res = _read_image()
    assert res.success is True
    images = (res.data or {}).get("images") or []
    assert images and images[0]["data_uri"].startswith("data:image/")


# ---------- ③-b 声明轴默认 fail-closed + 发布链（adapter 真值 → contextvar） ----------

class _NoVisionAdapter(BaseChatAdapter):
    """能力默认值（BaseChatAdapter.supports_image_input = False）。"""

    async def chat(self, messages, **kwargs):
        return ChatResponse(content="ok")

    async def chat_stream(self, messages, **kwargs):
        yield StreamChunk(type="done", finish_reason="stop")

    @property
    def supports_function_calling(self) -> bool:
        return True


class _VisionAdapter(_NoVisionAdapter):
    supports_image_input = True


def test_base_chat_adapter_defaults_to_no_image_input():
    """deny-by-default：未声明者 = False（fail-closed）。"""
    assert BaseChatAdapter.supports_image_input is False
    assert _NoVisionAdapter().supports_image_input is False
    assert _VisionAdapter().supports_image_input is True


def test_adapter_chat_call_publishes_capability_for_tools(skills):
    """能力从**真实 adapter 调用**传进工具层（无需 tools→adapters import）。

    注：属性发布是 contextvar 语义——只在**同一上下文**内可见（asyncio.run
    各建一个上下文），故断言必须在同一个协程里做，这也正是生产链路的形态
    （同一次模型调用的下游工具批）。
    """
    async def _scenario(adapter):
        await adapter.chat([{"role": "user", "content": "hi"}])
        published = chat_port.current_model_supports_image_input()
        res = await ReadImageTool().aexecute(
            ReadImageInput(skill="pkg", file_path="assets/pic.png"))
        return published, res

    published, res = asyncio.run(_scenario(_NoVisionAdapter()))
    assert published is False
    assert res.success is False

    published, res = asyncio.run(_scenario(_VisionAdapter()))
    assert published is True
    assert res.success is True


def test_adapter_stream_publishes_capability_for_tools(skills):
    """流式入口同样发布（agent_loop 主链路走 chat_stream）。"""

    async def _scenario(adapter):
        async for _chunk in adapter.chat_stream([{"role": "user", "content": "hi"}]):
            pass
        published = chat_port.current_model_supports_image_input()
        res = await ReadImageTool().aexecute(
            ReadImageInput(skill="pkg", file_path="assets/pic.png"))
        return published, res

    published, res = asyncio.run(_scenario(_NoVisionAdapter()))
    assert published is False
    assert res.success is False

    published, res = asyncio.run(_scenario(_VisionAdapter()))
    assert published is True
    assert res.success is True


# ---------- ④ read_file 媒体描述符：mime 字段 ----------

def test_read_file_media_descriptor_has_mime(skills):
    res = _read_file()
    assert res.success is True
    data = res.data or {}
    assert data["media_kind"] == "image"
    assert data["mime"] == "image/png"
    assert data["size"] > 0
    assert data["url"].startswith("/api/skills/pkg/file?path=")
    # 模型可见说明与实际能力一致：png 属 read_image 支持集 → 提示 read_image
    assert "read_image" in data["detail"]


def test_read_file_mime_for_non_image_media(skills):
    """非图片媒体的 mime 同样如实给出（registry 媒体后缀表来源）。"""
    (skills / "pkg" / "assets" / "clip.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42")
    res = _read_file("assets/clip.mp4")
    assert res.success is True
    data = res.data or {}
    assert data["media_kind"] == "video"
    assert data["mime"] == "video/mp4"


def test_read_file_bmp_does_not_hint_read_image(skills):
    """bmp 决策：仍在媒体描述符通道（registry 认 image），但 read_image 不支持，
    detail 不得提示 read_image（否则模型照做必被拒）。"""
    (skills / "pkg" / "assets" / "legacy.bmp").write_bytes(b"BM" + b"\x00" * 60)
    res = _read_file("assets/legacy.bmp")
    assert res.success is True
    data = res.data or {}
    assert data["media_kind"] == "image"
    assert data["mime"] == "image/bmp"
    assert "read_image" not in data["detail"]

    # 同一文件走 read_image → 明确「不是支持的图片类型」，不静默成功
    img = asyncio.run(ReadImageTool().aexecute(
        ReadImageInput(skill="pkg", file_path="assets/legacy.bmp")))
    assert img.success is False
    assert img.error_code == "validation"


def test_read_file_url_empty_when_route_cannot_serve(skills):
    """路由 jail 等价：不可路由的文件不给 URL（给了 URL 就要能取到）。"""
    # references/ 下 .pdf：read_file jail 允许读成元信息，但路由白名单
    # （resolve_skill_resource）只放行 references/ 的媒体后缀 → 不可路由
    (skills / "pkg" / "references" / "x.pdf").write_bytes(b"%PDF-1.4\n")
    res = _read_file("references/x.pdf")
    assert res.success is True
    data = res.data or {}
    assert data["media_kind"] == "document"
    assert data["url"] == ""
    assert "不提供 HTTP 访问" in data["detail"]


# ---------- ⑤ 硬链接拒绝 ----------

def test_read_file_rejects_hardlink(skills):
    """包内文件与包外文件同 inode 时拒绝（resolve()/字符串都判不出来）。"""
    outside = skills.parent / "outside_secret.md"
    outside.write_text("OUTSIDE-SECRET", encoding="utf-8")
    link = skills / "pkg" / "references" / "linked.md"
    try:
        os.link(outside, link)
    except (OSError, NotImplementedError) as e:  # pragma: no cover - 平台不支持
        pytest.skip(f"文件系统不支持硬链接: {e}")
    try:
        res = _read_file("references/linked.md")
        assert res.success is False
        assert res.error_code == "validation"
        assert "硬链接" in (res.error or "")
        assert "OUTSIDE-SECRET" not in str(res.data or {})
    finally:
        link.unlink(missing_ok=True)


def test_read_image_rejects_hardlink(skills):
    """read_image 与 read_file 共用同一 jail（硬链接同样拒绝，读不到包外字节）。"""
    outside = skills.parent / "outside_pic.png"
    outside.write_bytes(PNG_BYTES)
    link = skills / "pkg" / "assets" / "linked.png"
    try:
        os.link(outside, link)
    except (OSError, NotImplementedError) as e:  # pragma: no cover - 平台不支持
        pytest.skip(f"文件系统不支持硬链接: {e}")
    try:
        res = _read_image("assets/linked.png")
        assert res.success is False
        assert "硬链接" in (res.error or "")
    finally:
        link.unlink(missing_ok=True)


# ---------- ⑥ offset / limit 边界（pydantic 约束） ----------

@pytest.mark.parametrize("bad_offset", [0, -1, -100])
def test_read_file_offset_must_be_positive(bad_offset):
    with pytest.raises(ValidationError):
        ReadFileInput(skill="pkg", file_path="references/a.md", offset=bad_offset)


@pytest.mark.parametrize("bad_limit", [0, -1, 2001, 100000])
def test_read_file_limit_bounds(bad_limit):
    with pytest.raises(ValidationError):
        ReadFileInput(skill="pkg", file_path="references/a.md", limit=bad_limit)


def test_read_file_limit_upper_bound_accepted():
    """边界值 2000 合法（le=2000 不允许误伤上限本身）。"""
    assert ReadFileInput(
        skill="pkg", file_path="references/a.md", limit=2000).limit == 2000
    assert ReadFileInput(
        skill="pkg", file_path="references/a.md", offset=1).offset == 1


def test_read_file_offset_beyond_eof_clamps_to_last_line(skills):
    """offset 超过总行数 → 收敛到末行（不设上界的理由）。"""
    res = _read_file("references/a.md", offset=999)
    assert res.success is True
    data = res.data or {}
    assert data["start_line"] == 3
    assert "3: 第三行" in data["content"]
