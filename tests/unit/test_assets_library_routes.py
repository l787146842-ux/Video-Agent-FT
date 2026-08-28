"""阶段 3 素材库迁移契约测试：/api 素材库端点套件（routes/assets_library.py）。

钉死：
- /api/asset-picker 的 image/local 形状对齐前端 fetchAssetPicker（{items, canvas_online}），
  canvas_online 恒 True（本地后端，前端离线态不得误触发）；
- 本地扫描：类型白名单、隐藏/下划线目录排除、分类/关键字/文件夹过滤；
- 元数据（data/asset_library.json）分类/标签/展示名覆盖生效；
- 兼容路径 /api/canvas-assets 形状不变（{library, canvas_online}）；
- /api/local-assets 形状为 {items, tree}；
- 缩略图懒生成 + 缓存命中；流式端点内容一致 + 目录穿越 404。
"""
import json

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from PIL import Image

from src.video_agent.exceptions import VideoAgentError
from src.video_agent.web.routes import assets_library as al


@pytest.fixture()
def assets_env(tmp_path, monkeypatch):
    assets = tmp_path / "assets"
    assets.mkdir()
    meta = tmp_path / "asset_library.json"
    monkeypatch.setattr(al, "ASSETS_DIR", assets)
    monkeypatch.setattr(al, "ASSET_THUMBS_DIR", assets / "_thumbs")
    monkeypatch.setattr(al, "ASSET_LIBRARY_FILE", meta)
    return {"assets": assets, "meta": meta}


@pytest.fixture()
def client(assets_env):  # noqa: ARG001（assets_env 经 monkeypatch 生效于路由模块）
    app = FastAPI()
    app.include_router(al.router, prefix="/api")

    @app.exception_handler(VideoAgentError)
    async def _vae(request, exc):  # noqa: ARG001
        return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})

    return TestClient(app)


def _png(path, size=(400, 300), color=(200, 30, 30)):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path, "PNG")


def _seed(assets):
    """基础素材：根图 + 子目录图 + 视频 + 不支持类型 + 缩略图缓存目录内杂图"""
    _png(assets / "a.png")
    _png(assets / "sub" / "b.jpg", size=(16, 16))
    (assets / "clip.mp4").write_bytes(b"\x00\x00fake-video")
    (assets / "note.txt").write_text("不是素材", encoding="utf-8")
    _png(assets / "_thumbs" / "leak.png")
    return ["a.png", "sub/b.jpg", "clip.mp4"]


# ---------- asset-picker：列表与形状 ----------

def test_picker_local_shape_and_whitelist(client, assets_env):
    _seed(assets_env["assets"])
    resp = client.get("/api/asset-picker?type=local")
    assert resp.status_code == 200
    body = resp.json()
    assert body["canvas_online"] is True
    ids = [it["id"] for it in body["items"]]
    assert ids == ["a.png", "clip.mp4", "sub/b.jpg"]  # 按名排序；.txt/_thumbs 排除
    img = body["items"][0]
    # 前端 AssetPickerItem 契约字段
    assert img["url"] == "/workspace/assets/a.png"
    assert img["thumb"] == "/api/asset-thumb/a.png"
    assert img["name"] == "a"
    assert img["size"] > 0 and img["mtime"]
    assert img["source"] == "local"
    vid = next(it for it in body["items"] if it["id"] == "clip.mp4")
    assert vid["thumb"] == vid["url"]  # 非图片无缩略图端点，回原件


def test_picker_local_folder_default_category_and_filter(client, assets_env):
    _seed(assets_env["assets"])
    body = client.get("/api/asset-picker?type=local").json()
    sub = next(it for it in body["items"] if it["id"] == "sub/b.jpg")
    assert sub["category"] == "sub"  # 无元数据时分类回退文件夹名
    root = next(it for it in body["items"] if it["id"] == "a.png")
    assert root["category"] == "未分类"

    filtered = client.get("/api/asset-picker?type=local&category=sub").json()
    assert [it["id"] for it in filtered["items"]] == ["sub/b.jpg"]

    by_q = client.get("/api/asset-picker?type=local&q=CLIP").json()
    assert [it["id"] for it in by_q["items"]] == ["clip.mp4"]


def test_picker_image_uses_metadata(client, assets_env):
    _seed(assets_env["assets"])
    assets_env["meta"].write_text(json.dumps({
        "version": 1,
        "categories": [
            {"name": "角色", "paths": ["a.png"]},
            {"name": "空分类", "paths": []},
        ],
        "items": {"a.png": {"name": "主角立绘", "tags": ["女主", "立绘"]}},
    }), encoding="utf-8")

    body = client.get("/api/asset-picker?type=image").json()
    assert body["canvas_online"] is True
    hero = next(it for it in body["items"] if it["id"] == "a.png")
    assert hero["name"] == "主角立绘"
    assert hero["category"] == "角色"
    assert hero["tags"] == ["女主", "立绘"]

    by_tag = client.get("/api/asset-picker?type=image&q=立绘").json()
    assert [it["id"] for it in by_tag["items"]] == ["a.png"]
    by_cat = client.get("/api/asset-picker?type=image&category=未分类").json()
    assert "a.png" not in [it["id"] for it in by_cat["items"]]


def test_picker_canvas_and_unknown_return_empty(client, assets_env):
    _seed(assets_env["assets"])
    # 画布 tab 前端走 routes/canvas.py 画布空间接口，本端点不再代理画布
    body = client.get("/api/asset-picker?type=canvas").json()
    assert body == {"items": [], "canvas_online": True}
    assert client.get("/api/asset-picker?type=whatever").json()["items"] == []


# ---------- /canvas-assets 与 /asset-library ----------

def test_canvas_assets_keeps_legacy_shape(client, assets_env):
    _seed(assets_env["assets"])
    body = client.get("/api/canvas-assets").json()
    assert body["canvas_online"] is True
    lib = body["library"]
    assert lib["active_library_id"] == "local"
    cats = lib["libraries"][0]["categories"]
    names = [c["name"] for c in cats]
    assert "角色" not in names and "sub" in names and "未分类" in names
    flat = [it["id"] for c in cats for it in c["items"]]
    assert set(flat) == {"a.png", "clip.mp4", "sub/b.jpg"}


def test_asset_library_category_order_follows_meta(client, assets_env):
    _seed(assets_env["assets"])
    assets_env["meta"].write_text(json.dumps({
        "categories": [{"name": "场景", "paths": ["sub/b.jpg"]}],
    }), encoding="utf-8")
    lib = client.get("/api/asset-library").json()
    names = [c["name"] for c in lib["libraries"][0]["categories"]]
    assert names[0] == "场景"  # 元数据声明序在前
    assert set(names) == {"场景", "未分类"}


# ---------- /local-assets：形状 {items, tree} ----------

def test_local_assets_items_and_tree(client, assets_env):
    _seed(assets_env["assets"])
    body = client.get("/api/local-assets").json()
    assert {it["id"] for it in body["items"]} == {"a.png", "clip.mp4", "sub/b.jpg"}
    tree = body["tree"]
    assert tree["name"] == "全部素材" and tree["count"] == 3
    sub = next(ch for ch in tree["children"] if ch["name"] == "sub")
    assert sub["count"] == 1 and sub["items"][0]["id"] == "sub/b.jpg"

    folder = client.get("/api/local-assets?folder=sub").json()
    assert [it["id"] for it in folder["items"]] == ["sub/b.jpg"]


# ---------- 流式端点与路径安全 ----------

def test_asset_file_streams_content(client, assets_env):
    payload = b"\x89PNG-fake-bytes" * 64
    (assets_env["assets"] / "big.bin.mp4").write_bytes(payload)
    resp = client.get("/api/asset-file/big.bin.mp4")
    assert resp.status_code == 200
    assert resp.content == payload
    assert resp.headers["content-type"].startswith("video/mp4")


def test_path_traversal_rejected(client, assets_env):
    _png(assets_env["assets"] / "ok.png")
    with pytest.raises(VideoAgentError) as exc:
        al._safe_asset_path("../secrets.txt")
    assert exc.value.status_code == 404
    with pytest.raises(VideoAgentError):
        al._safe_asset_path("_thumbs/leak.png")  # 缓存目录不外发
    assert client.get("/api/asset-file/missing.png").status_code == 404


# ---------- 缩略图 ----------

def test_thumb_lazy_generate_and_cache(client, assets_env):
    _png(assets_env["assets"] / "a.png", size=(400, 300))
    thumb_file = assets_env["assets"] / "_thumbs" / "a.png.jpg"
    assert not thumb_file.exists()
    resp = client.get("/api/asset-thumb/a.png")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/jpeg"
    assert thumb_file.exists()
    with Image.open(thumb_file) as t:
        assert t.size[0] <= 288 and t.size[1] <= 288
    # 二次请求命中缓存（文件未被重写）
    before = thumb_file.stat().st_mtime_ns
    assert client.get("/api/asset-thumb/a.png").status_code == 200
    assert thumb_file.stat().st_mtime_ns == before


def test_thumb_falls_back_to_original_for_non_image(client, assets_env):
    payload = b"video-bytes"
    (assets_env["assets"] / "c.mp4").write_bytes(payload)
    resp = client.get("/api/asset-thumb/c.mp4")
    assert resp.status_code == 200
    assert resp.content == payload


def test_thumb_missing_returns_404(client, assets_env):
    assert client.get("/api/asset-thumb/nope.png").status_code == 404
