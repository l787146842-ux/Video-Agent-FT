"""文档/媒体动作域。

承载：write_document（项目文档工件写入/更新）、bind_asset（素材绑定）、
clear_media（卡片媒体清空）、insert_chat_media（故事板媒体 → 前端对话
输入框，纯前端信号不改状态）。执行器以参数传入（ex），实例方法壳保留在
StateOperationExecutor（测试 patch 目标不变），与 action_gen.py /
action_drafts.py 同一委托范式。
"""
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, List

from loguru import logger

from src.video_agent.config import settings
from src.video_agent.core.prompt_refs import media_of_draft
from src.video_agent.state import storyboard_ops as ops
from src.video_agent.utils import gen_id

if TYPE_CHECKING:
    from src.video_agent.core.action_executor import StateOperationExecutor


def apply_write_document(ex: "StateOperationExecutor", action: Dict[str, Any]) -> bool:
    """写入/更新项目文档工件（如 Final_Video_Spec.md）"""
    name = str(action.get("name") or action.get("title") or "").strip()
    content = action.get("content") or action.get("text") or ""
    if not name or not str(content).strip():
        return False

    docs = ex.state.setdefault("documents", [])
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for d in docs:
        if d.get("name") == name:
            d["content"] = content
            d["updated_at"] = now
            break
    else:
        docs.append({
            "id": gen_id("doc"),
            "name": name,
            "content": content,
            "created_at": now,
            "updated_at": now,
        })
    if name not in ex.documents_written:
        ex.documents_written.append(name)
    return True


def apply_bind_asset(ex: "StateOperationExecutor", action: Dict) -> bool:
    assets = ex.state.setdefault("assets", [])
    asset_id = action.get("asset_id") or action.get("id") or ""
    url = action.get("url") or action.get("asset_url") or ""
    name = action.get("name") or action.get("asset_name") or url or "Agent 绑定素材"

    existing = None
    for a in assets:
        if (asset_id and a.get("id") == asset_id) or (url and a.get("url") == url):
            existing = a
            break

    if existing:
        existing["isBound"] = True
        if url and not existing.get("url"):
            existing["url"] = url
    else:
        assets.insert(0, {
            "id": asset_id or gen_id("ast"),
            "name": name,
            "type": action.get("asset_type") or action.get("kind") or "image",
            "isBound": True,
            "url": url,
        })
    return True


def apply_clear_media(ex: "StateOperationExecutor", action: Dict) -> bool:
    """清空卡片内的媒体内容（图片/视频/音频地址），保留提示词与参数。
    draft_id 支持真实 ID、"current" 或卡片编号（如 "1-2"）。"""
    draft_id = action.get("draft_id") or action.get("target_id") or action.get("id") or "current"
    draft_type = action.get("draft_type") or action.get("kind") or action.get("target_type") or ""
    result = ex._find_draft(str(draft_id), draft_type)
    if not result:
        return False
    _, draft = result
    return ops.clear_draft_media(draft)


# ---------- 故事板媒体 → 对话输入框（纯前端信号，不改状态） ----------

def apply_insert_chat_media(ex: "StateOperationExecutor", action: Dict) -> bool:
    """把故事板草稿卡片的媒体（图片/视频/音频）插入前端对话输入框。

    支持三种定位方式：
    - draft_ids: 明确的草稿 ID 数组（优先）
    - target: "current" / "all" / "all_keyElements" / "all_shots" / "all_audio"
    - media_type: image/video/audio 过滤（可选）
    单次最多 settings.max_chat_inserts 个，防止一次灌满输入框。
    """
    media_type = str(action.get("media_type") or action.get("kind") or "").lower().strip()
    if media_type not in ("", "image", "video", "audio"):
        media_type = ""
    limit = int(action.get("limit") or settings.max_chat_inserts)
    limit = min(limit, settings.max_chat_inserts)

    pairs: List[tuple] = []
    draft_ids = action.get("draft_ids") or action.get("ids") or []
    if isinstance(draft_ids, str):
        draft_ids = [draft_ids]
    if draft_ids:
        for did in draft_ids:
            found = ex._find_draft(str(did), "")
            if found:
                pairs.append(found)
    else:
        target = str(action.get("target") or "current").strip()
        if target == "current":
            found = ex._find_draft("current", "")
            if found:
                pairs.append(found)
        elif target in ("all", "all_keyelements", "all_keyElements", "all_shots", "all_shot", "all_audio"):
            t = target.lower()
            if t.startswith("all_key"):
                draft_type = "keyelement"
            elif t.startswith("all_shot"):
                draft_type = "shot"
            elif t.startswith("all_audio"):
                draft_type = "audio"
            else:
                draft_type = ""
            pairs = ex._collect_drafts("all", draft_type)

    added = 0
    existing_urls = {it.get("url") for it in ex.chat_inserts}
    for group, draft in pairs:
        if added >= limit:
            break
        url, kind = media_of_draft(draft)
        if not url or url in existing_urls:
            continue
        if media_type and kind != media_type:
            continue
        name = draft.get("label") or group.get("title") or draft.get("id", "")
        ex.chat_inserts.append({
            "kind": kind,
            "url": url,
            "name": name,
            # 视频用首帧/已有概念图作缩略图，前端无需额外拉取
            "thumb": draft.get("imgUrl") or "" if kind == "video" else "",
        })
        existing_urls.add(url)
        added += 1

    if added:
        logger.info(f"[StudioActions] insert_chat_media: {added} 个媒体待插入对话输入框")
    return added > 0
