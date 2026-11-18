# -*- coding: utf-8 -*-
"""技能包 read_file/read_image 与路径 jail（2026-11-12）。"""
import asyncio
import base64

import pytest

import src.video_agent.web.skill_docs as sd
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


def _read(path: str, offset: int = 1, limit: int = 2000):
    return asyncio.run(ReadFileTool().aexecute(ReadFileInput(
        skill="pkg", file_path=path, offset=offset, limit=limit)))


def test_read_file_text_with_line_numbers(skills):
    res = _read("references/a.md", offset=2, limit=1)
    assert res.success is True
    data = res.data or {}
    assert "2: 第二行" in data["content"]
    assert "1: 第一行" not in data["content"]
    assert data["start_line"] == 2
    assert data["end_line"] == 2
    assert data["total_lines"] == 3


def test_read_file_allows_skill_md(skills):
    res = _read("SKILL.md")
    assert res.success is True
    assert "1: ---" in (res.data or {})["content"]


def test_read_file_path_jail(skills):
    for bad in ("../secret.md", "/etc/passwd", "C:/Windows/win.ini",
                "other/a.md", "references/../../secret.md"):
        res = _read(bad)
        assert res.success is False, f"路径 {bad} 应被拒绝"
        assert res.error_code == "validation"


def test_read_file_media_returns_descriptor(skills):
    res = _read("assets/pic.png")
    assert res.success is True
    data = res.data or {}
    assert data["media_kind"] == "image"
    assert data["size"] > 0
    assert data["url"].startswith("/api/skills/pkg/file?path=")
    assert "content" not in data


def test_read_image_returns_data_uri(skills):
    res = asyncio.run(ReadImageTool().aexecute(
        ReadImageInput(skill="pkg", file_path="assets/pic.png")))
    assert res.success is True
    images = (res.data or {}).get("images") or []
    assert images and images[0]["data_uri"].startswith("data:image/")


def test_read_image_rejects_non_image(skills):
    res = asyncio.run(ReadImageTool().aexecute(
        ReadImageInput(skill="pkg", file_path="references/a.md")))
    assert res.success is False
    assert res.error_code == "validation"
