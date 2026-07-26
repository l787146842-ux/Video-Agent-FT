"""
Studio Actions Executor
解析并执行 Agent 回复中的 studio-actions JSON 块。
操作 StudioStateService 共享状态并自动持久化。
"""
import json
import re
import time
import random
from typing import Any, Dict, List, Optional

from loguru import logger

from src.video_agent.web.state_service import StudioStateService


class StudioActionExecutor:
    """
    执行 studio-actions JSON 中的操作列表。
    操作 StudioStateService 共享状态，执行后自动持久化。
    """

    def __init__(
        self,
        state_service: Optional[StudioStateService] = None,
        selected_draft_id: str = "",
        selected_type: str = "",
    ):
        self.svc = state_service or StudioStateService.get_instance()
        # 前端当前选中的草稿——"current" 的唯一正确解释
        self.selected_draft_id = selected_draft_id
        self.selected_type = selected_type

    @property
    def state(self) -> Dict[str, Any]:
        return self.svc.state

    def parse_actions_from_reply(self, reply: str) -> List[Dict[str, Any]]:
        """从 Agent 回复文本中提取 studio-actions JSON 块"""
        actions: List[Dict[str, Any]] = []
        patterns = [
            r"```(?:studio-actions|studio_action|studioActions)\s*([\s\S]*?)```",
            r"<studio-actions>([\s\S]*?)</studio-actions>",
        ]
        for pattern in patterns:
            for match in re.finditer(pattern, reply, re.IGNORECASE):
                parsed = self._parse_json(match.group(1))
                if parsed:
                    actions.extend(self._normalize(parsed))
        return [a for a in actions if isinstance(a, dict)]

    def has_action_block(self, reply: str) -> bool:
        """回复中是否存在 studio-actions 块（无论能否解析成功）"""
        return bool(
            re.search(r"```(?:studio-actions|studio_action|studioActions)", reply, re.IGNORECASE)
            or re.search(r"<studio-actions>", reply, re.IGNORECASE)
        )

    def strip_action_blocks(self, reply: str) -> str:
        """移除回复中的 studio-actions 块，返回纯文本"""
        text = re.sub(
            r"```(?:studio-actions|studio_action|studioActions)\s*[\s\S]*?```",
            "",
            reply,
            flags=re.IGNORECASE,
        )
        text = re.sub(r"<studio-actions>[\s\S]*?</studio-actions>", "", text, flags=re.IGNORECASE)
        return text.strip()

    def execute(self, actions: List[Dict[str, Any]]) -> int:
        """执行操作列表，返回成功执行的数量。执行后自动持久化。"""
        applied = 0
        for action in actions:
            try:
                if self._apply(action):
                    applied += 1
            except Exception as e:
                logger.warning(f"Studio action failed: {action} -> {e}")
        if applied > 0:
            self.svc.save()
            logger.info(f"[StudioActions] Applied {applied} action(s), state persisted")
        return applied

    # ---------- 内部方法 ----------

    def _parse_json(self, raw: str) -> Any:
        try:
            return json.loads(raw.strip())
        except (json.JSONDecodeError, ValueError):
            return None

    def _normalize(self, parsed: Any) -> List[Dict]:
        if isinstance(parsed, list):
            return parsed
        if isinstance(parsed, dict):
            if isinstance(parsed.get("actions"), list):
                return parsed["actions"]
            if parsed.get("action"):
                return [parsed]
        return []

    def _apply(self, action: Dict[str, Any]) -> bool:
        name = str(action.get("action") or action.get("type") or "").strip()
        if not name:
            return False

        if name in ("update_draft", "patch_draft", "update_current_draft", "set_prompt"):
            return self._apply_draft_patch(action)
        if name in ("confirm_draft", "confirm_current_draft"):
            return self._apply_draft_patch({**action, "patch": {"tag": action.get("tag", "已确认")}})
        if name in ("update_group", "patch_group"):
            return self._apply_group_patch(action)
        if name == "add_draft":
            return self._apply_add_draft(action)
        if name in ("add_group", "add_keyElement", "add_shot", "add_audio"):
            return self._apply_add_group(action)
        if name in ("delete_draft", "remove_draft"):
            return self._apply_delete_draft(action)
        if name in ("delete_group", "remove_group"):
            return self._apply_delete_group(action)
        if name == "bind_asset":
            return self._apply_bind_asset(action)
        if name == "select_draft":
            return True  # 选中操作仅影响前端 UI，后端无需持久化
        # request_confirmation / continue 是流程信号，由 agent_loop 处理，不算状态变更
        return False

    def _find_draft(self, draft_id: str, draft_type: str = ""):
        """在 state 中查找 draft，返回 (group, draft) 或 None"""
        categories = self._categories_for_type(draft_type)
        for cat_key in categories:
            for group in self.state.get(cat_key, []):
                for draft in group.get("drafts", []):
                    if draft.get("id") == draft_id:
                        return group, draft
        if draft_id in ("current", ""):
            # 优先解析为前端当前选中的草稿
            if self.selected_draft_id:
                found = self._find_draft(self.selected_draft_id, self.selected_type or draft_type)
                if found:
                    return found
            # 兜底：第一个可用的 draft
            for cat_key in categories:
                for group in self.state.get(cat_key, []):
                    drafts = group.get("drafts", [])
                    if drafts:
                        return group, drafts[0]
        return None

    def _find_group(self, group_id: str, group_type: str = ""):
        categories = self._categories_for_type(group_type)
        for cat_key in categories:
            for group in self.state.get(cat_key, []):
                if group.get("id") == group_id:
                    return group
        if group_id in ("current", ""):
            # 优先返回包含前端选中草稿的分组
            if self.selected_draft_id:
                found = self._find_draft(self.selected_draft_id, self.selected_type or group_type)
                if found:
                    return found[0]
            # 兜底：第一个可用 group
            for cat_key in categories:
                groups = self.state.get(cat_key, [])
                if groups:
                    return groups[0]
        return None

    def _categories_for_type(self, draft_type: str) -> List[str]:
        t = (draft_type or "").lower().strip()
        if t in ("shot", "shots", "video"):
            return ["shots", "keyElements", "audioItems"]
        if t in ("audio", "audioitem"):
            return ["audioItems", "keyElements", "shots"]
        if t in ("keyelement", "key-element", "element", "image"):
            return ["keyElements", "shots", "audioItems"]
        return ["keyElements", "shots", "audioItems"]

    def _apply_draft_patch(self, action: Dict) -> bool:
        draft_id = action.get("draft_id") or action.get("target_id") or action.get("id") or "current"
        draft_type = action.get("draft_type") or action.get("kind") or action.get("target_type") or ""
        patch = action.get("patch") or action.get("fields") or action.get("updates") or {}
        if action.get("prompt") and "prompt" not in patch:
            patch["prompt"] = action["prompt"]

        result = self._find_draft(draft_id, draft_type)
        if not result:
            return False
        _, draft = result

        allowed = [
            "label", "tag", "mediaType", "imgUrl", "videoUrl", "prompt", "mode",
            "model", "providerId", "resolution", "duration", "aspectRatio",
            "size", "timbre", "refAssets",
        ]
        changed = False
        for field in allowed:
            if field in patch:
                draft[field] = patch[field]
                changed = True
        return changed

    def _apply_group_patch(self, action: Dict) -> bool:
        group_id = action.get("group_id") or action.get("target_id") or action.get("id") or "current"
        group_type = action.get("group_type") or action.get("kind") or action.get("target_type") or ""
        patch = action.get("patch") or action.get("fields") or action.get("updates") or {}

        group = self._find_group(group_id, group_type)
        if not group:
            return False

        allowed = ["title", "desc", "roughDesc", "duration", "timeRange", "prompt",
                   "shotType", "sceneRefs"]
        changed = False
        for field in allowed:
            if field in patch:
                group[field] = patch[field]
                changed = True
        return changed

    def _apply_delete_draft(self, action: Dict) -> bool:
        draft_id = action.get("draft_id") or action.get("id") or ""
        draft_type = action.get("draft_type") or action.get("kind") or ""
        if not draft_id or draft_id == "current":
            draft_id = self.selected_draft_id
        if not draft_id:
            return False
        for cat_key in self._categories_for_type(draft_type):
            for group in self.state.get(cat_key, []):
                drafts = group.get("drafts", [])
                for i, d in enumerate(drafts):
                    if d.get("id") == draft_id:
                        drafts.pop(i)
                        return True
        return False

    def _apply_delete_group(self, action: Dict) -> bool:
        group_id = action.get("group_id") or action.get("id") or ""
        group_type = action.get("group_type") or action.get("kind") or ""
        if not group_id:
            return False
        for cat_key in self._categories_for_type(group_type):
            groups = self.state.get(cat_key, [])
            for i, g in enumerate(groups):
                if g.get("id") == group_id:
                    groups.pop(i)
                    return True
        return False

    def _apply_add_group(self, action: Dict) -> bool:
        """创建新的故事板分组（关键元素 / 分镜 / 音频）"""
        group_type = (
            action.get("group_type") or action.get("draft_type")
            or action.get("kind") or action.get("target_type") or ""
        ).lower().strip()

        # 映射到 state 中的 key
        if group_type in ("shot", "shots", "video", "分镜"):
            cat_key = "shots"
        elif group_type in ("audio", "audioitem", "audioitems", "音频"):
            cat_key = "audioItems"
        else:
            cat_key = "keyElements"

        group_data = action.get("group") or action.get("data") or {}
        # 也允许 patch 字段携带 title/desc
        patch = action.get("patch") or {}
        title = action.get("title") or group_data.get("title") or patch.get("title") or "Agent 新建分组"
        desc = action.get("desc") or group_data.get("desc") or patch.get("desc") or ""

        new_id = group_data.get("id") or f"{'shot' if cat_key == 'shots' else 'ke' if cat_key == 'keyElements' else 'audio'}-{int(time.time())}-{random.randint(100,999)}"

        new_group: Dict[str, Any] = {
            "id": new_id,
            "title": title,
            "desc": desc,
            "drafts": [],
        }
        # 分镜特有字段（允许放在 action 顶层或 group 子对象里）
        def pick(field, default=""):
            return action.get(field) or group_data.get(field) or patch.get(field) or default

        if cat_key == "shots":
            new_group["roughDesc"] = pick("roughDesc", desc)
            new_group["duration"] = pick("duration", "5s")
            new_group["timeRange"] = pick("timeRange")
            new_group["shotType"] = pick("shotType")
            refs = action.get("sceneRefs") or group_data.get("sceneRefs") or []
            new_group["sceneRefs"] = refs if isinstance(refs, list) else [refs]

        self.state.setdefault(cat_key, []).append(new_group)

        # 如果 action 中携带了 drafts 列表，一并添加
        inline_drafts = group_data.get("drafts") or action.get("drafts") or []
        for d in inline_drafts:
            if isinstance(d, dict):
                self._append_draft_to_group(new_group, d)

        # 如果 action 中携带了单个 draft，也添加
        single_draft = action.get("draft")
        if single_draft and isinstance(single_draft, dict) and not inline_drafts:
            self._append_draft_to_group(new_group, single_draft)

        return True

    def _append_draft_to_group(self, group: Dict, draft_data: Dict) -> Dict:
        """向指定 group 添加一个 draft，返回新建的 draft"""
        draft = {
            "id": draft_data.get("id", f"draft-{int(time.time())}-{random.randint(100,999)}"),
            "label": draft_data.get("label", "Agent 草稿"),
            "tag": draft_data.get("tag", "Agent"),
            "mediaType": draft_data.get("mediaType", "image"),
            "imgUrl": draft_data.get("imgUrl", ""),
            "videoUrl": draft_data.get("videoUrl", ""),
            "prompt": draft_data.get("prompt", ""),
            "model": draft_data.get("model", ""),
            "mode": draft_data.get("mode", ""),
            "aspectRatio": draft_data.get("aspectRatio", "16:9"),
            "resolution": draft_data.get("resolution", "1080p"),
            "duration": draft_data.get("duration", "5s"),
            "timbre": draft_data.get("timbre", ""),
            "refAssets": draft_data.get("refAssets", []),
        }
        group.setdefault("drafts", []).append(draft)
        return draft

    def _apply_add_draft(self, action: Dict) -> bool:
        group_id = action.get("group_id") or "current"
        group_type = action.get("group_type") or action.get("draft_type") or action.get("kind") or ""
        draft_data = action.get("draft") or {}

        group = self._find_group(group_id, group_type)
        if not group:
            for cat_key in ["keyElements", "shots", "audioItems"]:
                groups = self.state.get(cat_key, [])
                if groups:
                    group = groups[0]
                    break
        # 如果仍然找不到分组，自动创建一个
        if not group:
            auto_action = {**action, "group_type": group_type, "title": draft_data.get("label", "Agent 新建分组")}
            self._apply_add_group(auto_action)
            # 取刚创建的分组
            t = (group_type or "").lower().strip()
            if t in ("shot", "shots", "video"):
                cat_key = "shots"
            elif t in ("audio", "audioitem"):
                cat_key = "audioItems"
            else:
                cat_key = "keyElements"
            groups = self.state.get(cat_key, [])
            if groups:
                group = groups[-1]  # 刚添加的在末尾
            if not group:
                return False

        self._append_draft_to_group(group, draft_data)
        return True

    def _apply_bind_asset(self, action: Dict) -> bool:
        assets = self.state.setdefault("assets", [])
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
                "id": asset_id or f"ast-{int(time.time())}-{random.randint(100,999)}",
                "name": name,
                "type": action.get("asset_type") or action.get("kind") or "image",
                "isBound": True,
                "url": url,
            })
        return True
