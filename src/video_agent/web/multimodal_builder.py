"""
多模态内容构建器（从 chat_service.py 拆分，修复计划书 P1-6）。

职责：
- /workspace/ 本地图片 → base64 data URI（云端 LLM 无法访问 127.0.0.1，必须内联）
- 素材超限策略：优先级排序（选中草稿相关优先）+ 未注入素材的文本清单降级
- 富文本 content_parts 的交错多模态构建（保持「文字 ↔ 媒体」排版对应关系）

纯构建逻辑，不涉及会话编排与 SSE。
"""
import asyncio
import base64
import mimetypes
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import httpx
from loguru import logger

from src.video_agent.config import settings
from src.video_agent.web.attachments import attachment_context, collect_image_urls
from src.video_agent.state.manager import StateManager
from src.video_agent.state.models import CAT_KEY_ELEMENTS, CAT_SHOTS, CAT_AUDIO_ITEMS
from src.video_agent.utils.paths import WORKSPACE_DIR

# 单张图片注入 LLM 的大小上限（base64 编码后体积膨胀约 4/3）
_MAX_IMAGE_BYTES = 10 * 1024 * 1024
# 文本清单里最多列出的未注入素材条数（防止素材极多时撑爆上下文）
_MANIFEST_MAX_ITEMS = 30
# 远程图片服务端代下载的超时（秒）
_REMOTE_FETCH_TIMEOUT = 20.0

# selected_type（前端 DraftType）→ 快照列表键
_TYPE_TO_CATEGORY = {"keyElement": CAT_KEY_ELEMENTS, "shot": CAT_SHOTS, "audio": CAT_AUDIO_ITEMS}


def _downscale_image(raw: bytes, suffix: str) -> tuple:
    """注入前把图片缩放到长边 ≤ settings.llm_image_max_edge。

    Vision 模型内部会重采样，内联原图纯属浪费 token（单张可达数千）。
    返回 (bytes, mime)；缩放失败/未装 Pillow/未超限时返回 (raw, "") 表示沿用原图。
    """
    max_edge = settings.llm_image_max_edge
    if max_edge <= 0:
        return raw, ""
    try:
        import io

        from PIL import Image
    except ImportError:
        return raw, ""
    try:
        img = Image.open(io.BytesIO(raw))
        w, h = img.size
        if max(w, h) <= max_edge:
            return raw, ""
        scale = max_edge / max(w, h)
        img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)
        # PNG（含透明通道）保持 PNG，其余统一 JPEG q85
        keep_png = suffix == ".png" or img.mode in ("RGBA", "LA", "P")
        buf = io.BytesIO()
        if keep_png:
            img.save(buf, format="PNG", optimize=True)
            return buf.getvalue(), "image/png"
        if img.mode != "RGB":
            img = img.convert("RGB")
        img.save(buf, format="JPEG", quality=85)
        out = buf.getvalue()
        logger.info(f"[Multimodal] 图片已缩放 {w}x{h} → {img.size[0]}x{img.size[1]} "
                    f"({len(raw) // 1024}KB → {len(out) // 1024}KB)")
        return out, "image/jpeg"
    except Exception as e:
        logger.warning(f"[Multimodal] 图片缩放失败，沿用原图: {e}")
        return raw, ""


def _read_image_data_uri(img_url: str) -> str:
    """读取 /workspace/ 本地图片并转为 base64 data URI（同步，供 to_thread 调用）。

    云端 LLM 无法访问 127.0.0.1，本地图片必须内联为 data URI 才能被供应商读取。
    路径越界 / 文件不存在 / 超过大小上限时返回空串（跳过该图片）。
    注入前按 llm_image_max_edge 缩放（vision token 优化）。
    """
    rel = img_url[len("/workspace/"):]
    path = (WORKSPACE_DIR / rel).resolve()
    try:
        path.relative_to(WORKSPACE_DIR.resolve())
    except ValueError:
        logger.warning(f"[Multimodal] 图片路径越界，已跳过: {img_url}")
        return ""
    if not path.is_file():
        logger.warning(f"[Multimodal] 图片不存在，已跳过: {img_url}")
        return ""
    if path.stat().st_size > _MAX_IMAGE_BYTES:
        logger.warning(f"[Multimodal] 图片超过 10MB，已跳过: {img_url}")
        return ""
    raw, mime_override = _downscale_image(path.read_bytes(), path.suffix.lower())
    mime = mime_override or mimetypes.guess_type(path.name)[0] or "image/png"
    b64 = base64.b64encode(raw).decode("ascii")
    return f"data:{mime};base64,{b64}"


async def fetch_remote_image_data_uri(url: str) -> str:
    """服务端代下载远程图片 → base64 data URI。

    云端 LLM 网关经常无法抓取外部临时托管链接（时效过期/防盗链/内网），
    把 URL 原样透传会导致整个请求被供应商 400 拒绝；统一改为服务端先
    下载内联。失败（404/超时/超限/非图片）返回空串，调用方降级为文本清单。
    """
    if not url.lower().startswith(("http://", "https://")):
        return ""
    try:
        async with httpx.AsyncClient(timeout=_REMOTE_FETCH_TIMEOUT, follow_redirects=True) as client:
            resp = await client.get(url)
        if resp.status_code != 200:
            logger.warning(f"[Multimodal] 远程图片拉取失败 HTTP {resp.status_code}，跳过注入: {url}")
            return ""
        raw = resp.content
    except Exception as e:
        logger.warning(f"[Multimodal] 远程图片拉取失败，跳过注入: {url} ({e})")
        return ""
    if len(raw) > _MAX_IMAGE_BYTES:
        logger.warning(f"[Multimodal] 远程图片超过 10MB，跳过注入: {url}")
        return ""
    suffix = Path(urlparse(url).path).suffix.lower() or ".png"
    raw, mime_override = _downscale_image(raw, suffix)
    ct = (resp.headers.get("content-type") or "").split(";")[0].strip()
    mime = mime_override or (ct if ct.startswith("image/") else "") or mimetypes.guess_type(url)[0] or "image/png"
    b64 = base64.b64encode(raw).decode("ascii")
    return f"data:{mime};base64,{b64}"


async def _resolve_injectable_url(url: str) -> str:
    """把待注入 LLM 的媒体 URL 统一转为可被供应商直读的形式：

    - /workspace/ 本地文件 → 读盘转 data URI（越界/不存在返回空）
    - http(s) 远程链接 → 服务端代下载转 data URI（失败返回空）
    - 其他（已是 data: URI 等）→ 原样透传
    返回空串表示该图片本次无法注入，调用方应跳过（素材清单仍会列出）。
    """
    if url.startswith("/workspace/"):
        return await asyncio.to_thread(_read_image_data_uri, url)
    if url.lower().startswith(("http://", "https://")):
        return await fetch_remote_image_data_uri(url)
    return url


async def build_multimodal_content(
    text: str,
    attachments: List[Dict[str, str]],
    images: List[str],
    content_parts: Optional[List[Dict[str, str]]] = None,
    selected_draft_id: str = "",
    selected_type: str = "",
    videos: Optional[List[str]] = None,
) -> Any:
    """构建多模态 LLM 输入（文本 + 图片 parts）。无图片时返回纯文本。

    /workspace/ 本地图片转 base64 data URI 注入；http(s) 远程图片由服务端
    代下载后同样内联（云端网关抓不到外部临时链接，透传 URL 会被供应商 400 拒绝）。

    content_parts（可选）：前端富文本输入框按用户排版顺序序列化的有序片段。
    存在时优先走交错构建路径，保证 LLM 精确识别「文字 ↔ 媒体」的对应关系。

    素材超限策略（多模态模型单次上传有数量限制）：
    - 最多注入 settings.max_llm_images 张图片，优先注入与当前选中草稿相关的素材；
    - 未注入的图片 + 全部视频/音频降级为文本清单，LLM 仍可知晓其存在
      并通过 insert_chat_media / URL 引用它们，而不是假装看不见。
    """
    if content_parts:
        note = attachment_context(attachments) if attachments else ""
        # 除用户排版的内联图片外，仍需注入「已绑定素材」图片（attachments 中的
        # 图片 + images 参数），追加到交错内容末尾，避免丢失原有素材注入能力。
        extra = collect_image_urls(attachments) if attachments else []
        for img_url in (images or []):
            if img_url and img_url not in extra:
                extra.append(img_url)
        part_urls = {p.get("url") for p in content_parts if p.get("type") == "image"}
        extra = [u for u in extra if u and u not in part_urls]
        extra = _prioritize_images(extra, selected_draft_id, selected_type)
        manifest = _build_asset_manifest_note(
            content_parts=content_parts, extra_images=extra, videos=videos or [],
            selected_draft_id=selected_draft_id, selected_type=selected_type,
        )
        trailing = "\n\n".join(x for x in (note, manifest) if x)
        return await _build_interleaved_content(content_parts, trailing, extra)

    image_urls = collect_image_urls(attachments) if attachments else []
    for img_url in (images or []):
        if img_url and img_url not in image_urls:
            image_urls.append(img_url)

    manifest = ""
    if image_urls or videos:
        manifest = _build_asset_manifest_note(
            injected_candidates=image_urls, videos=videos or [],
            selected_draft_id=selected_draft_id, selected_type=selected_type,
        )

    if not image_urls:
        return f"{text}\n\n{manifest}" if manifest else text

    # 优先级排序：与选中草稿相关的图片排前，截取模型可承受的数量
    image_urls = _prioritize_images(image_urls, selected_draft_id, selected_type)
    max_images = settings.max_llm_images

    content_parts_list: List[Dict[str, Any]] = [{"type": "text", "text": text}]
    injected_urls: List[str] = []
    for img_url in image_urls[:max_images]:
        url = await _resolve_injectable_url(img_url)
        if not url:
            continue
        content_parts_list.append({"type": "image_url", "image_url": {"url": url}})
        injected_urls.append(img_url)
    logger.info(f"[Multimodal] 多模态消息：{len(injected_urls)}/{len(image_urls)} 张图片已注入 LLM 上下文（上限 {max_images}）")
    if manifest:
        content_parts_list[0]["text"] = f"{text}\n\n{manifest}"
    return content_parts_list if injected_urls else (content_parts_list[0]["text"] if manifest else text)


# ---------- 素材超限策略：优先级排序 + 文本清单 ----------

def _selected_draft_related_urls(svc: StateManager, selected_draft_id: str, selected_type: str) -> List[str]:
    """收集与当前选中草稿强相关的媒体 URL（优先注入给 LLM）。

    包括：草稿自身媒体与 refAssets；分镜时额外含 sceneRefs 指向的
    关键元素概念图（它们就是该镜头画面的参考依据）。
    """
    related: List[str] = []
    if not selected_draft_id:
        return related
    category = _TYPE_TO_CATEGORY.get(selected_type, selected_type)
    raw_state = svc.state_dict
    scene_ref_titles: List[str] = []
    for group in (raw_state.get(category) or []):
        if not isinstance(group, dict):
            continue
        for draft in (group.get("drafts") or []):
            if not isinstance(draft, dict) or draft.get("id") != selected_draft_id:
                continue
            for u in (draft.get("refAssets") or []):
                if u and u not in related:
                    related.append(u)
            for field in ("imgUrl", "videoUrl", "audioUrl"):
                u = draft.get(field) or ""
                if u and u not in related:
                    related.append(u)
            if category == CAT_SHOTS:
                scene_ref_titles = [t for t in (group.get("sceneRefs") or []) if isinstance(t, str)]
    for title in scene_ref_titles:
        for ke_group in (raw_state.get(CAT_KEY_ELEMENTS) or []):
            if not isinstance(ke_group, dict) or ke_group.get("title") != title:
                continue
            for draft in (ke_group.get("drafts") or []):
                u = (draft.get("imgUrl") or "") if isinstance(draft, dict) else ""
                if u and u not in related:
                    related.append(u)
    return related


def _prioritize_images(image_urls: List[str], selected_draft_id: str, selected_type: str) -> List[str]:
    """图片注入优先级：与选中草稿相关的排前，其余保持原顺序（去重）。"""
    if not image_urls:
        return image_urls
    try:
        svc = StateManager.get_instance()
        related = set(_selected_draft_related_urls(svc, selected_draft_id, selected_type))
    except Exception:
        related = set()
    if not related:
        return image_urls
    head = [u for u in image_urls if u in related]
    tail = [u for u in image_urls if u not in related]
    return head + tail


def _storyboard_media_inventory(svc: StateManager) -> List[Dict[str, str]]:
    """枚举故事板全部草稿媒体（供文本清单使用）"""
    items: List[Dict[str, str]] = []
    kind_of_field = (("imgUrl", "image"), ("videoUrl", "video"), ("audioUrl", "audio"))
    cat_labels = {CAT_KEY_ELEMENTS: "关键元素", CAT_SHOTS: "分镜", CAT_AUDIO_ITEMS: "音频"}
    for cat, label in cat_labels.items():
        for group in (svc.state_dict.get(cat) or []):
            if not isinstance(group, dict):
                continue
            for draft in (group.get("drafts") or []):
                if not isinstance(draft, dict):
                    continue
                for field, kind in kind_of_field:
                    url = draft.get(field) or ""
                    if not url:
                        continue
                    items.append({
                        "name": draft.get("label") or group.get("title", ""),
                        "section": label,
                        "kind": kind,
                        "url": url,
                        "draft_id": draft.get("id", ""),
                    })
    return items


def _build_asset_manifest_note(
    *,
    content_parts: Optional[List[Dict[str, str]]] = None,
    extra_images: Optional[List[str]] = None,
    injected_candidates: Optional[List[str]] = None,
    videos: Optional[List[str]] = None,
    selected_draft_id: str = "",
    selected_type: str = "",
) -> str:
    """构建「未注入素材文本清单」。

    多模态模型单次请求可上传的媒体数量有限（超限直接报错），无法把所有
    素材都塞进上下文。清单让 LLM 明确知道：哪些素材真实存在但未被
    上传，需要时可用 insert_chat_media / storyboard_media_to_chat 把
    指定草稿插入对话输入框，或在提示词里用 URL 引用。
    """
    try:
        svc = StateManager.get_instance()
        related = set(_selected_draft_related_urls(svc, selected_draft_id, selected_type))
        inventory = _storyboard_media_inventory(svc)
    except Exception:
        return ""

    max_images = settings.max_llm_images
    # 本次实际会注入的图片（与构建逻辑保持一致的估算）
    injected: List[str] = []
    if content_parts:
        injected = [p.get("url", "") for p in content_parts if p.get("type") == "image" and p.get("url")]
        for u in (extra_images or [])[:max_images]:
            if u and u not in injected:
                injected.append(u)
    else:
        injected = list((injected_candidates or [])[:max_images])
    injected_set = set(injected)

    lines: List[str] = []
    listed = 0
    # 1) 故事板媒体中未被注入的（带 draft_id，供 view_storyboard_media 按需调图）
    for it in inventory:
        if it["url"] in injected_set:
            continue
        marker = "★" if it["url"] in related else ""
        lines.append(f"- [{it['section']}/{it['kind']}]{marker} {it['name']}: {it['url']} (draft_id={it['draft_id']})")
        listed += 1
        if listed >= _MANIFEST_MAX_ITEMS:
            break
    # 2) 本次消息携带但未注入的视频/音频（vision 模型无法直接读取）
    for v in (videos or []):
        if v and v not in injected_set and not any(v == it["url"] for it in inventory):
            lines.append(f"- [视频] {v}")
            listed += 1
            if listed >= _MANIFEST_MAX_ITEMS:
                break

    if not lines:
        return ""
    return (
        f"（系统说明：多模态模型单次请求可上传的图片数量有限，本次已注入 {len(injected_set)} 张，"
        f"优先注入了与当前选中草稿相关的素材（★标记）。以下素材真实存在但未上传，"
        f"编写某条提示词前若需要看到对应画面，调用 view_storyboard_media(draft_ids=[...]) "
        f"按条目加载图片（每轮只调当前需要的那几张，不要一次拉全部）；"
        f"也可用 insert_chat_media / storyboard_media_to_chat 把指定草稿的媒体插入用户对话输入框，"
        f"或在回复中引用它们的 URL，不要声称看不到它们：\n" + "\n".join(lines) + "）"
    )


async def _build_interleaved_content(
    content_parts: List[Dict[str, str]],
    trailing_note: str = "",
    extra_images: Optional[List[str]] = None,
) -> Any:
    """按有序 content_parts 构建交错多模态内容。

    - text  → 文本 part（相邻片段合并）
    - image → image_url part（/workspace/ 本地图转 data URI），插在文字之间
    - video/audio → 文本标记 [video: 名称]/[audio: 名称]（当前 vision LLM 无法
      直接读取视频/音频，用标记占位并保留交错位置，让模型知道「此处有个视频」）
    - extra_images → 已绑定素材图片，追加到末尾（保持原有素材注入能力）

    总量受 settings.max_llm_images 约束（多模态模型单次上传限制），
    超限部分降级为文本标记 [图片: 名称]（未上传），避免模型报错。
    最终无图片成功注入时降级为纯文本字符串。
    """
    result: List[Dict[str, Any]] = []
    text_buf: List[str] = []
    max_images = settings.max_llm_images

    def flush_text() -> None:
        if not text_buf:
            return
        merged = "".join(text_buf)
        if merged.strip():
            result.append({"type": "text", "text": merged})
        text_buf.clear()

    injected = 0
    for part in content_parts:
        ptype = part.get("type", "text")
        if ptype == "text":
            text_buf.append(part.get("text", ""))
            continue
        url = part.get("url", "")
        name = part.get("name", "") or url
        if ptype == "image":
            if not url:
                continue
            if injected >= max_images:
                # 超出模型单次上传上限：保留位置标记但不注入，避免请求报错
                text_buf.append(f"[图片: {name}]（超出单次上传上限，未发送给模型）")
                continue
            img = await _resolve_injectable_url(url)
            if not img:
                continue
            flush_text()
            result.append({"type": "image_url", "image_url": {"url": img}})
            injected += 1
        elif ptype in ("video", "audio"):
            # 视频/音频无法被 vision 模型直接读取：用文本标记占位保留交错位置。
            # 视频若带首帧海报图（thumb），额外注入 image_url，让模型「看到」画面。
            text_buf.append(f"[{ptype}: {name}]")
            thumb = part.get("thumb", "") if ptype == "video" else ""
            if thumb and injected < max_images:
                img = await _resolve_injectable_url(thumb)
                if img:
                    flush_text()
                    result.append({"type": "image_url", "image_url": {"url": img}})
                    injected += 1
    # 已绑定素材图片追加到末尾（在文档说明之前），同样受总上限约束
    for img_url in (extra_images or []):
        if injected >= max_images:
            break
        url = await _resolve_injectable_url(img_url)
        if not url:
            continue
        flush_text()
        result.append({"type": "image_url", "image_url": {"url": url}})
        injected += 1
    if trailing_note:
        text_buf.append(f"\n\n{trailing_note}")
    flush_text()

    if injected == 0:
        # 无图片注入（纯文字 / 仅视频音频标记）→ 降级纯文本
        return "".join(p["text"] for p in result if p.get("type") == "text")
    if len(result) == 1 and result[0].get("type") == "text":
        return result[0]["text"]
    logger.info(f"[Multimodal] 交错多模态消息：{injected} 张图片按排版顺序注入")
    return result
