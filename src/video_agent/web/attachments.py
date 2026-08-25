"""
附件处理服务 — 从 routes/agent.py 抽离，保持路由层精简。

职责：
1. 将上传素材登记进服务端资产列表（bind）
2. 文本类附件文档（故事/剧本）正文存入 state.uploadedDocs，供 read_uploaded_doc 按需检索
3. 为 LLM 构建素材上下文说明（文档只注入清单+预览，其他类型能力说明）
4. 从附件中提取图片 URL（多模态 vision 注入）
"""
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from loguru import logger

from src.video_agent.config import settings
from src.video_agent.state.manager import StateManager
from src.video_agent.utils import gen_id
from src.video_agent.utils.paths import ASSETS_DIR

# 文本类素材：正文不再全量注入，改存 uploadedDocs 由模型按需检索
_TEXT_DOC_EXTS = {".md", ".txt"}
# PDF 素材：服务端抽取文本后与 .md/.txt 同等对待（read_uploaded_doc 按需检索）
_PDF_EXTS = {".pdf"}
# PDF 抽取页数上限：超长 PDF 只取前段，避免阻塞请求
_PDF_MAX_PAGES = 100
_MAX_DOC_CHARS = settings.max_doc_chars
_MAX_ATTACHMENTS = settings.max_attachments
# 清单预览长度：让模型能判断文档内容性质，全文靠 read_uploaded_doc
_DOC_PREVIEW_CHARS = 200

# PDF 抽取结果缓存：(mtime, text)，同一文件多轮对话不重复抽取
_PDF_CACHE: Dict[str, Any] = {}


def _extract_pdf_text(fpath: Path) -> str:
    """抽取 PDF 文本层内容（pdfplumber）；扫描件/解析失败返回空串。

    依赖可选：未安装 pdfplumber 时诚实降级为空（上层提示用户改用文本格式）。
    """
    try:
        stat = fpath.stat()
        cached = _PDF_CACHE.get(str(fpath))
        if cached and cached[0] == stat.st_mtime:
            return cached[1]
        import pdfplumber  # 延迟导入：依赖较重，仅真实上传 PDF 时加载
    except (ImportError, OSError) as e:
        if isinstance(e, ImportError):
            logger.warning("[Attachments] 未安装 pdfplumber，无法解析 PDF（pip install pdfplumber）")
        else:
            logger.warning(f"[Attachments] PDF 读取失败 {fpath.name}: {e}")
        return ""
    pages: List[str] = []
    try:
        with pdfplumber.open(fpath) as pdf:
            for page in pdf.pages[:_PDF_MAX_PAGES]:
                text = page.extract_text() or ""
                if text.strip():
                    pages.append(text.strip())
    except Exception as e:  # 加密/损坏 PDF 等，降级提示用户
        logger.warning(f"[Attachments] PDF 解析失败 {fpath.name}: {e}")
        return ""
    result = "\n\n".join(pages)
    _PDF_CACHE[str(fpath)] = (stat.st_mtime, result)
    return result


def _read_text_doc(url: str) -> str:
    """读取本地文本/PDF 附件正文（防目录穿越）；失败返回空串"""
    if not url.startswith("/workspace/assets/"):
        return ""
    fpath = ASSETS_DIR / Path(url).name
    ext = fpath.suffix.lower()
    if not fpath.exists():
        return ""
    if ext in _PDF_EXTS:
        return _extract_pdf_text(fpath)
    if ext not in _TEXT_DOC_EXTS:
        return ""
    try:
        return fpath.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        logger.warning(f"[Attachments] 附件文档读取失败 {url}: {e}")
        return ""


def store_uploaded_docs(svc: StateManager, attachments: List[Dict[str, str]]) -> None:
    """把本次消息携带的文本/PDF 附件正文存入 state.uploadedDocs（按需检索源）。

    同名文档覆盖更新；仅存 .md/.txt/.pdf（PDF 服务端抽取文本层），
    其他格式由 attachment_context 说明能力限制。
    必须在 svc.lock 内调用（与 bind_attachments 同一短锁段）。
    """
    if not attachments:
        return
    changed = False
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    docs = svc.state_dict.setdefault("uploadedDocs", [])
    for att in attachments[:_MAX_ATTACHMENTS]:
        url = att.get("url", "")
        name = att.get("name") or url or "文档"
        content = _read_text_doc(url)
        if not content:
            continue
        entry = next((d for d in docs if d.get("name") == name), None)
        if entry:
            entry["content"] = content
            entry["char_count"] = len(content)
            entry["uploaded_at"] = now
        else:
            docs.insert(0, {
                "id": att.get("id") or gen_id("udoc"),
                "name": name,
                "kind": att.get("kind") or "file",
                "content": content,
                "char_count": len(content),
                "uploaded_at": now,
            })
        changed = True
    if changed:
        svc.save()


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
    为 LLM 构建素材说明：文本类文档（.md/.txt）默认只注入清单（名称+字数+前 200 字预览），
    正文已存入 uploadedDocs，需要全文时调用 read_uploaded_doc 按需检索；
    其他类型给出明确的能力说明，避免 LLM 乱猜「我看不到素材」或假装看过。
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
        if ext in _TEXT_DOC_EXTS or ext in _PDF_EXTS:
            content = _read_text_doc(url)
            if not content:
                if ext in _PDF_EXTS:
                    parts.append(
                        f"（用户上传了 PDF 文档《{name}》，但未抽取出文本内容"
                        f"（可能是扫描件或未安装 pdfplumber）；"
                        f"请告知用户粘贴关键内容，或改用 .md/.txt）"
                    )
                else:
                    parts.append(f"（素材文档《{name}》未在服务器上找到，请让用户重新上传）")
                continue
            preview = content[:_DOC_PREVIEW_CHARS].replace("\n", " ")
            parts.append(
                f"（用户上传了素材文档《{name}》，共 {len(content)} 字，已存档。"
                f"开头预览：{preview}…"
                f"正文未自动注入上下文，需要全文时调用 read_uploaded_doc（name=\"{name}\"）读取，"
                f"不要声称看不到该文档。）"
            )
        elif ext == ".docx":
            parts.append(
                f"（用户上传了 {ext} 文档《{name}》，服务端暂不支持解析该格式正文；"
                f"请告知用户粘贴关键内容，或改用 .md/.txt/.pdf）"
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
