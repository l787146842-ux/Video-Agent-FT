"""
附件处理服务 — 从 routes/agent.py 抽离，保持路由层精简。

职责：
1. 将上传素材登记进服务端资产列表（bind）
2. 为 LLM 构建素材上下文说明（文本注入 / 能力说明）
3. 从附件中提取图片 URL（多模态 vision 注入）
"""
from pathlib import Path
from typing import Any, Dict, List

from loguru import logger

from src.video_agent.config import settings
from src.video_agent.state.manager import StateManager
from src.video_agent.utils import gen_id
from src.video_agent.utils.paths import ASSETS_DIR

# 文本类素材直接把正文注入给 LLM；单文档上限防止把上下文撑爆
_TEXT_DOC_EXTS = {".md", ".txt"}
_MAX_DOC_CHARS = settings.max_doc_chars
_MAX_ATTACHMENTS = settings.max_attachments


def bind_attachments(svc: StateManager, attachments: List[Dict[str, str]]) -> None:
    """把本次消息携带的上传素材登记进服务端资产列表（isBound=True）并持久化"""
    if not attachments:
        return
    assets = svc.state_dict.setdefault("assets", [])
    changed = False
    for att in attachments[:_MAX_ATTACHMENTS]:
        url = att.get("url", "")
        name = att.get("name") or url or "上传素材"
        if not url:
            continue
        existing = next((a for a in assets if a.get("url") == url), None)
        if existing:
            existing["isBound"] = True
        else:
            assets.insert(0, {
                "id": att.get("id") or gen_id("ast"),
                "name": name,
                "type": att.get("kind") or "file",
                "isBound": True,
                "url": url,
            })
        changed = True
    if changed:
        svc.save()


def attachment_context(attachments: List[Dict[str, str]]) -> str:
    """
    为 LLM 构建素材说明：文本类文档（.md/.txt）直接读出正文注入；
    其他类型给出明确的能力说明，避免 LLM 瘘猜「我看不到素材」或假装看过。
    """
    parts: List[str] = []
    for att in attachments[:_MAX_ATTACHMENTS]:
        url = att.get("url", "")
        name = att.get("name") or url or "素材"
        if not url.startswith("/workspace/assets/"):
            parts.append(f"（用户提供了外部素材《{name}》，URL: {url}）")
            continue
        # 只取 basename，防止路径穿越
        fpath = ASSETS_DIR / Path(url).name
        ext = fpath.suffix.lower()
        if ext in _TEXT_DOC_EXTS:
            if not fpath.exists():
                parts.append(f"（素材文档《{name}》未在服务器上找到，请让用户重新上传）")
                continue
            try:
                content = fpath.read_text(encoding="utf-8", errors="replace")
            except OSError as e:
                parts.append(f"（素材文档《{name}》读取失败：{e}）")
                continue
            truncated = ""
            if len(content) > _MAX_DOC_CHARS:
                content = content[:_MAX_DOC_CHARS]
                truncated = f"\n……（正文超长，已截断为前 {_MAX_DOC_CHARS} 字）"
            parts.append(f"=== 用户上传的素材文档《{name}》全文 ===\n{content}{truncated}\n=== 文档结束 ===")
        elif ext in (".pdf", ".docx"):
            parts.append(
                f"（用户上传了 {ext} 文档《{name}》，服务端暂不支持解析该格式正文；"
                f"请告知用户粘贴关键内容，或改用 .md/.txt）"
            )
        else:
            kind = att.get("kind") or "文件"
            parts.append(f"（用户上传并绑定了{kind}素材《{name}》，URL: {url}，可作为参考图/引用资产使用）")
    return "\n\n".join(parts)


def collect_image_urls(attachments: List[Dict[str, str]]) -> List[str]:
    """从附件中提取图片 URL（用于多模态 vision 注入）"""
    image_exts = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
    urls: List[str] = []
    for att in attachments[:_MAX_ATTACHMENTS]:
        kind = att.get("kind") or ""
        url = att.get("url") or ""
        if not url:
            continue
        if kind == "image":
            urls.append(url)
        elif kind in ("file", ""):
            ext = Path(url).suffix.lower()
            if ext in image_exts:
                urls.append(url)
    return urls
