"""
/api 素材库（本地化）

素材库事实源在本 Agent 后端：
- 事实源：workspace/assets/ 目录扫描（utils/paths.ASSETS_DIR）
- 元数据：data/asset_library.json（分类/标签/展示名覆盖，见文件头注释）
- 响应形状对齐前端 fetchAssetPicker / AssetLibraryModal 既有消费（前端零改动）。

端点清单（经 app.py 以 /api 前缀挂载）：
- GET /canvas-assets       → {library, canvas_online}（兼容路径，指本地素材库）
- GET /asset-library       → 库结构 {libraries:[{id,name,categories:[{name,items}]}], active_library_id}
- GET /asset-picker        → 统一选择器 {items, canvas_online}（type=image|canvas|local）
- GET /local-assets        → {items, tree}
- GET /asset-file/{rel}    → 大文件流式下载（StreamingResponse 分块，不整载内存）
- GET /asset-thumb/{rel}   → 图片缩略图（懒生成缓存 workspace/assets/_thumbs/；非图片流式回退原件）
"""
import json
import mimetypes
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

from fastapi import APIRouter, Query
from fastapi.responses import FileResponse, StreamingResponse
from loguru import logger
from PIL import Image, ImageOps

from src.video_agent.exceptions import VideoAgentError
from src.video_agent.utils.paths import ASSET_LIBRARY_FILE, ASSET_THUMBS_DIR, ASSETS_DIR
from src.video_agent.web.error_payload import LEGACY_NOT_FOUND

router = APIRouter()

# 素材类型白名单（doc/pdf 等不是素材库素材）
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
_VIDEO_EXTS = {".mp4", ".webm", ".mov", ".m4v", ".flv", ".avi"}
_AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"}

# 上传文件名形如 up_<hex12>_<原始名>，展示时去前缀还原
_UP_NAME_RE = re.compile(r"^up_[0-9a-f]{12}_(.+)$")

_STREAM_CHUNK = 1024 * 1024          # 流式分块 1MB
_THUMB_BOX = (288, 288)              # 缩略图包围盒（卡片网格 3-4 列足够）
_THUMB_QUALITY = 82
_PICKER_LIMIT = 500                  # 单次返回上限
_DEFAULT_CATEGORY = "未分类"


# ---------- 基础工具 ----------

def _asset_kind(name: str) -> Optional[str]:
    ext = Path(name).suffix.lower()
    if ext in _IMAGE_EXTS:
        return "image"
    if ext in _VIDEO_EXTS:
        return "video"
    if ext in _AUDIO_EXTS:
        return "audio"
    return None


def _display_name(rel: str) -> str:
    """展示名：去上传前缀 + 去扩展名"""
    base = os.path.basename(rel)
    m = _UP_NAME_RE.match(base)
    if m:
        base = m.group(1)
    return os.path.splitext(base)[0] or base


def _scan_rels() -> List[str]:
    """扫描素材目录 → 支持类型文件的相对路径列表（排除隐藏/下划线前缀目录，目录内按名排序）"""
    rels: List[str] = []
    if not ASSETS_DIR.is_dir():
        return rels
    for current, dirs, files in os.walk(ASSETS_DIR):
        dirs[:] = sorted((d for d in dirs if not d.startswith((".", "_"))), key=str.lower)
        cur = Path(current)
        for name in sorted(files, key=str.lower):
            if name.startswith((".", "_")) or _asset_kind(name) is None:
                continue
            rels.append((cur / name).relative_to(ASSETS_DIR).as_posix())
    return rels


def _load_meta() -> Dict[str, Any]:
    """读取 data/asset_library.json；缺失/损坏一律空元数据（扫描事实源不受影响）"""
    empty: Dict[str, Any] = {"categories": [], "items": {}}
    try:
        data = json.loads(ASSET_LIBRARY_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return empty
    except (OSError, json.JSONDecodeError) as e:
        logger.warning(f"[AssetsLibrary] 素材元数据读取失败（{ASSET_LIBRARY_FILE}）: {e}")
        return empty
    if not isinstance(data, dict):
        return empty
    cats = [c for c in (data.get("categories") or [])
            if isinstance(c, dict) and str(c.get("name") or "").strip()]
    items = data.get("items") or {}
    return {"categories": cats, "items": items if isinstance(items, dict) else {}}


def _category_maps(meta: Dict[str, Any]) -> Tuple[Dict[str, str], Dict[str, Dict[str, Any]]]:
    """元数据 → (相对路径→分类名, 相对路径→条目信息)"""
    path2cat: Dict[str, str] = {}
    for cat in meta["categories"]:
        name = str(cat.get("name")).strip()
        for p in cat.get("paths") or []:
            if isinstance(p, str) and p.strip():
                path2cat.setdefault(p.strip().replace("\\", "/").lstrip("/"), name)
    infos = {k: v for k, v in meta["items"].items()
             if isinstance(k, str) and isinstance(v, dict)}
    return path2cat, infos


def _category_of(rel: str, path2cat: Dict[str, str]) -> str:
    """分类优先级：元数据显式分类 > 所在文件夹名 > 未分类"""
    folder = os.path.dirname(rel)
    return path2cat.get(rel) or (folder or _DEFAULT_CATEGORY)


def _build_item(rel: str, info: Dict[str, Any], category: str) -> Dict[str, Any]:
    """单条素材（字段对齐前端 AssetPickerItem：id/name/url/thumb/category/size/mtime/source）"""
    path = ASSETS_DIR / rel
    try:
        st = path.stat()
        size, mtime = st.st_size, st.st_mtime
    except OSError:
        size, mtime = 0, 0.0
    kind = _asset_kind(rel) or "image"
    url = f"/workspace/assets/{quote(rel)}"
    return {
        "id": rel,
        "file": rel,
        "name": str(info.get("name") or "") or _display_name(rel),
        "url": url,
        "thumb": f"/api/asset-thumb/{quote(rel)}" if kind == "image" else url,
        "kind": kind,
        "size": size,
        "mtime": datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat() if mtime else "",
        "created_at": mtime,
        "folder": os.path.dirname(rel),
        "category": category,
        "tags": [t for t in (info.get("tags") or []) if isinstance(t, str)],
        "source": "local",
    }


def _match_filter(item: Dict[str, Any], category: str, q: str) -> bool:
    if category and item["category"] != category:
        return False
    if q:
        needle = q.lower()
        hay = [item["name"], item["category"], *item["tags"]]
        if not any(needle in str(x).lower() for x in hay):
            return False
    return True


def _iter_items(category: str, q: str) -> List[Dict[str, Any]]:
    """扫描 + 元数据合并 + 过滤 → 标准化条目列表"""
    meta = _load_meta()
    path2cat, infos = _category_maps(meta)
    out: List[Dict[str, Any]] = []
    for rel in _scan_rels():
        item = _build_item(rel, infos.get(rel) or {}, _category_of(rel, path2cat))
        if _match_filter(item, category, q):
            out.append(item)
    return out


# ---------- 库结构（/api/asset-library 形状） ----------

def _build_library(category: str = "", q: str = "") -> Dict[str, Any]:
    """装配 library 结构：元数据声明的分类按声明序在前，扫描新出现的分类按字典序补后"""
    meta = _load_meta()
    order = [str(c.get("name")).strip() for c in meta["categories"]]
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for item in _iter_items(category, q):
        grouped.setdefault(item["category"], []).append(item)
    cats = [{"name": n, "items": grouped[n]} for n in order if grouped.get(n)]
    cats.extend({"name": n, "items": grouped[n]} for n in sorted(grouped) if n not in order)
    return {
        "libraries": [{
            "id": "local",
            "name": "本地素材库",
            "categories": cats,
        }],
        "active_library_id": "local",
    }


def _flatten_library(library: Dict[str, Any]) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for lib in library.get("libraries") or []:
        for cat in lib.get("categories") or []:
            items.extend(cat.get("items") or [])
    return items[:_PICKER_LIMIT]


# ---------- 文件夹树（/api/local-assets 的 tree 段） ----------

def _build_tree(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    root: Dict[str, Any] = {"path": "", "name": "全部素材", "children": [], "items": [], "count": 0}
    nodes = {"": root}

    def ensure(rel_dir: str) -> Dict[str, Any]:
        if rel_dir in nodes:
            return nodes[rel_dir]
        parent = ensure(os.path.dirname(rel_dir))
        node: Dict[str, Any] = {
            "path": rel_dir, "name": os.path.basename(rel_dir),
            "children": [], "items": [], "count": 0,
        }
        parent["children"].append(node)
        nodes[rel_dir] = node
        return node

    for it in items:
        ensure(it["folder"])["items"].append(it)

    def fill(node: Dict[str, Any]) -> int:
        total = len(node["items"])
        for child in node["children"]:
            total += fill(child)
        node["count"] = total
        return total

    fill(root)
    return root


# ---------- 路径安全 + 流式/缩略图 ----------

def _safe_asset_path(rel: str) -> Path:
    """相对路径 → 素材绝对路径；目录穿越/隐藏目录/不存在一律 404"""
    cleaned = str(rel or "").replace("\\", "/").lstrip("/")
    miss = VideoAgentError("素材不存在", status_code=404, error_code=LEGACY_NOT_FOUND)
    if not cleaned or ".." in cleaned.split("/"):
        raise miss
    root = ASSETS_DIR.resolve()
    path = (root / cleaned).resolve()
    try:
        relp = path.relative_to(root)
    except ValueError:
        raise miss from None
    if not path.is_file() or any(part.startswith((".", "_")) for part in relp.parts):
        raise miss
    return path


def _stream_file(path: Path) -> StreamingResponse:
    """分块流式回文件（大文件不整载内存）"""
    def _iter():
        with open(path, "rb") as f:
            while chunk := f.read(_STREAM_CHUNK):
                yield chunk

    media = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return StreamingResponse(
        _iter(), media_type=media,
        headers={"Content-Length": str(path.stat().st_size)},
    )


# ---------- 端点 ----------

@router.get("/asset-library")
async def get_asset_library(
    category: str = Query("", description="按分类过滤"),
    q: str = Query("", description="名称/标签关键字"),
):
    """本地素材库结构（形状对齐旧平坦化来源）"""
    return _build_library(category, q)


@router.get("/canvas-assets")
async def get_canvas_assets():
    """兼容路径：指本地素材库（响应形状 {library, canvas_online} 不变）"""
    return {"library": _build_library(), "canvas_online": True}


@router.get("/asset-picker")
async def asset_picker(
    type: str = Query("image", description="image|canvas|local"),
    category: str = Query("", description="按分类过滤"),
    q: str = Query("", description="名称/标签关键字"),
):
    """统一素材选择器（前端 fetchAssetPicker 唯一数据源；形状钉死 {items, canvas_online}）。

    canvas 档：前端画布 tab 走 routes/canvas.py 画布空间接口，本端点不再代理画布，
    恒回空 items + canvas_online=True（本地后端恒在线，前端离线态不再误触发）。"""
    if type == "image":
        items = _flatten_library(_build_library(category, q))
    elif type == "local":
        items = _iter_items(category, q)[:_PICKER_LIMIT]
    else:
        items = []
    return {"items": items, "canvas_online": True}


@router.get("/local-assets")
async def list_local_assets(
    folder: str = Query("", description="按文件夹过滤（相对路径，空=全部）"),
):
    """本地素材列表：{items, tree}"""
    prefix = folder.replace("\\", "/").strip("/")
    items = [
        it for it in _iter_items("", "")
        if not prefix
        or it["folder"] == prefix
        or it["folder"].startswith(prefix + "/")
    ]
    return {"items": items, "tree": _build_tree(items)}


@router.get("/asset-file/{rel:path}")
async def asset_file(rel: str):
    """大文件流式下载端点（与 /workspace/assets 静态挂载并存，供需要分块流的消费方）"""
    return _stream_file(_safe_asset_path(rel))


@router.get("/asset-thumb/{rel:path}")
async def asset_thumb(rel: str):
    """图片缩略图：懒生成并缓存到 _thumbs/（源文件更新自动重生）；非图片流式回退原件"""
    path = _safe_asset_path(rel)
    relp = path.relative_to(ASSETS_DIR.resolve()).as_posix()
    if _asset_kind(relp) != "image":
        return _stream_file(path)
    thumb_path = ASSET_THUMBS_DIR / (relp + ".jpg")
    try:
        if not thumb_path.exists() or thumb_path.stat().st_mtime < path.stat().st_mtime:
            thumb_path.parent.mkdir(parents=True, exist_ok=True)
            with Image.open(path) as img:
                img = ImageOps.exif_transpose(img)
                img.thumbnail(_THUMB_BOX)
                if img.mode not in ("RGB", "L"):
                    img = img.convert("RGB")
                img.save(thumb_path, "JPEG", quality=_THUMB_QUALITY, optimize=True)
    except (OSError, ValueError) as e:
        logger.warning(f"[AssetsLibrary] 缩略图生成失败 {relp}: {e}")
        return _stream_file(path)
    return FileResponse(
        thumb_path, media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=86400"},
    )
