"""
Studio Actions 执行器 — 从 actions.py 抽离。

职责：执行 studio-actions JSON 中的操作列表，操作 StateManager 共享状态并自动持久化。
解析逻辑在 action_parser.py，本文件仅负责执行。
"""
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from loguru import logger

from src.video_agent.config import settings
from src.video_agent.state.models import CAT_SHOTS, ALL_CATEGORIES
from src.video_agent.state import storyboard_ops as ops
from src.video_agent.state.manager import StateManager
from src.video_agent.utils import gen_id
from src.video_agent.web.generation import generate_image_via_provider, image_size_for
from src.video_agent.web.provider_config import resolve_provider_ref
from src.video_agent.web.prompt_refs import (
    build_storyboard_media_map, media_of_draft, resolve_prompt_mentions,
)
from src.video_agent.web.task_manager import get_task_manager, writeback_if_complete
from src.video_agent.web.action_parser import (
    strip_action_blocks,
    has_action_block as _has_action_block,
    parse_actions_from_reply as _parse_actions,
)


class StudioActionExecutor:
    """
    执行 studio-actions JSON 中的操作列表。
    操作 StudioStateService 共享状态，执行后自动持久化。
    """

    def __init__(
        self,
        state_service: Optional[StateManager] = None,
        selected_draft_id: str = "",
        selected_type: str = "",
    ):
        self.svc = state_service or StateManager.get_instance()
        # 前端当前选中的草稿——"current" 的唯一正确解释
        self.selected_draft_id = selected_draft_id
        self.selected_type = selected_type
        # 本执行器生命周期内写入的文档名（供前端渲染"已完成"卡片）
        self.documents_written: List[str] = []
        # 待插入前端对话输入框的媒体（insert_chat_media 产出，随 done payload 带回）
        # 每项：{"kind": image|video|audio, "url": str, "name": str, "thumb": str}
        self.chat_inserts: List[Dict[str, str]] = []
        # 已执行操作的中文描述清单（供前端「阶段完成」卡片展开查看具体操作，随消息持久化）
        self.action_log: List[str] = []

    @property
    def state(self) -> Dict[str, Any]:
        return self.svc.state_dict

    def parse_actions_from_reply(self, reply: str) -> List[Dict[str, Any]]:
        """从 Agent 回复文本中提取 studio-actions JSON 块"""
        return _parse_actions(reply)

    def has_action_block(self, reply: str) -> bool:
        """回复中是否存在 studio-actions 块"""
        return _has_action_block(reply)

    def strip_action_blocks(self, reply: str) -> str:
        """移除回复中的 studio-actions 块，返回纯文本"""
        return strip_action_blocks(reply)

    def execute(self, actions: List[Dict[str, Any]]) -> int:
        """执行操作列表，返回成功执行的数量。执行后自动持久化。

        Agent 主路径统一在此 push_undo()，使 Agent 改动与手动 update 一样可撤销；
        纯信号操作（select/确认/continue）或全部失败时不污染 undo 栈。
        """
        mutating = [a for a in actions if self._is_mutating(a)]
        if mutating:
            self.svc.push_undo()
        applied = 0
        for action in actions:
            try:
                if self._apply(action):
                    applied += 1
                    self.action_log.append(self._describe_action(action))
            except Exception as e:
                logger.warning(f"Studio action failed: {action} -> {e}")
        if applied > 0:
            # 防抖落盘：多步循环中合并连续变更，避免每轮全量双写阻塞事件循环
            self.svc.save_debounced()
            logger.info(f"[StudioActions] Applied {applied} action(s), state persisted")
        elif mutating:
            # 全部失败：丢弃预先压入的 undo 快照
            self.svc.discard_last_undo()
        return applied

    @staticmethod
    def _is_mutating(action: Dict[str, Any]) -> bool:
        """判断操作是否可能变更状态（流程信号类操作不入 undo 栈）"""
        name = str(action.get("action") or action.get("type") or "").strip()
        return name not in ("", "select_draft", "request_confirmation", "continue", "insert_chat_media")

    def _describe_action(self, action: Dict[str, Any]) -> str:
        """生成操作的中文简述（供前端展示具体做了什么，尽量解析出真实名称）"""
        name = str(action.get("action") or action.get("type") or "").strip()
        title = str(action.get("title") or "").strip()
        label = str(action.get("label") or "").strip()
        doc = str(action.get("name") or action.get("doc_name") or action.get("key") or "").strip()
        patch = action.get("patch") if isinstance(action.get("patch"), dict) else {}
        # 更新类操作：优先从状态里解析出草稿真实 label
        draft_id = str(action.get("draft_id") or "")
        if draft_id and not label:
            found = self._find_draft(draft_id, str(action.get("draft_type") or ""))
            if found:
                label = str(found[1].get("label") or "")
        if name in ("add_group", "add_keyElement", "add_shot", "add_audio"):
            kind = {"keyElement": "关键元素", "shot": "分镜", "audio": "音频"}.get(
                str(action.get("group_type") or action.get("type_hint") or ""), "分组"
            )
            return f"新建{kind}分组「{title or '未命名'}」"
        if name in ("update_draft", "patch_draft", "update_current_draft", "set_prompt", "confirm_draft", "confirm_current_draft"):
            target = label or draft_id or "当前草稿"
            fields = list(patch.keys()) if patch else []
            if "prompt" in fields or name == "set_prompt":
                return f"更新草稿「{target}」的提示词"
            if fields:
                return f"更新草稿「{target}」（{'/'.join(fields[:3])}）"
            return f"确认草稿「{target}」"
        if name in ("update_group", "patch_group"):
            return f"更新分组「{title or action.get('group_id', '')}」"
        if name == "add_draft":
            return f"新增草稿「{label or '未命名'}」"
        if name in ("delete_draft", "remove_draft"):
            return f"删除草稿 {action.get('draft_id', '')}"
        if name in ("clear_media", "delete_media", "remove_media"):
            target = str(action.get("draft_id") or "").strip()
            found = self._find_draft(target, str(action.get("draft_type") or "")) if target else None
            t_label = str(found[1].get("label") or "") if found else target
            return f"清空草稿「{t_label or '当前草稿'}」内的媒体"
        if name in ("delete_group", "remove_group"):
            return f"删除分组 {action.get('group_id', '')}"
        if name in ("write_document", "write_doc", "save_document"):
            return f"写入文档「{doc or '未命名'}」"
        if name == "bind_asset":
            return f"绑定素材「{str(action.get('name') or action.get('url', ''))[:24]}」"
        if name in ("insert_chat_media", "send_to_chat", "add_to_chat_input"):
            return "插入故事板媒体到对话输入框"
        if name in ("generate_image", "batch_generate_image", "gen_image"):
            return f"发起生图（{str(action.get('target', ''))}）"
        if name == "select_draft":
            return "选中草稿"
        return f"执行操作 {name}"

    async def execute_locked(self, actions: List[Dict[str, Any]]) -> int:
        """持 svc.lock 执行（与 FC Tool 路径的并发契约对齐）。

        调用方已持有 svc.lock 时（如 chat_service mock 路径）必须改用同步 execute()，
        asyncio.Lock 不可重入，嵌套获取会死锁。
        """
        async with self.svc.lock:
            return self.execute(actions)

    # ---------- 内部方法 ----------

    def _resolve_index_ref(self, ref: str, draft_type: str = ""):
        """解析卡片编号（如 "1-2"）→ (group, draft)；委托领域层唯一实现"""
        return ops.resolve_index_ref(self.state, ref, draft_type)

    def _apply(self, action: Dict[str, Any]) -> bool:
        name = str(action.get("action") or action.get("type") or "").strip()
        if not name:
            return False

        if name in ("update_draft", "patch_draft", "update_current_draft", "set_prompt"):
            return self._apply_draft_patch(action)
        if name in ("clear_media", "delete_media", "remove_media"):
            return self._apply_clear_media(action)
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
        if name in ("write_document", "write_doc", "save_document"):
            return self._apply_write_document(action)
        if name == "bind_asset":
            return self._apply_bind_asset(action)
        if name in ("insert_chat_media", "send_to_chat", "add_to_chat_input"):
            return self._apply_insert_chat_media(action)
        if name in ("generate_image", "batch_generate_image", "gen_image"):
            return self._apply_generate_image(action)
        if name == "select_draft":
            return True  # 选中操作仅影响前端 UI，后端无需持久化
        # request_confirmation / continue 是流程信号，由 agent_loop 处理，不算状态变更
        return False

    def _find_draft(self, draft_id: str, draft_type: str = ""):
        """在 state 中查找 draft（真实 ID / "current" / 卡片编号）；委托领域层唯一实现"""
        return ops.find_draft(
            self.state, draft_id, draft_type,
            selected_draft_id=self.selected_draft_id, selected_type=self.selected_type,
        )

    def _find_group(self, group_id: str, group_type: str = ""):
        """在 state 中查找 group；委托领域层唯一实现"""
        return ops.find_group(
            self.state, group_id, group_type,
            selected_draft_id=self.selected_draft_id, selected_type=self.selected_type,
        )

    def _categories_for_type(self, draft_type: str, strict: bool = False) -> List[str]:
        """draft_type → 状态类别键；委托领域层唯一实现"""
        return ops.categories_for_type(draft_type, strict=strict)

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
        return ops.patch_draft(draft, patch)

    def _apply_group_patch(self, action: Dict) -> bool:
        group_id = action.get("group_id") or action.get("target_id") or action.get("id") or "current"
        group_type = action.get("group_type") or action.get("kind") or action.get("target_type") or ""
        patch = action.get("patch") or action.get("fields") or action.get("updates") or {}

        group = self._find_group(group_id, group_type)
        if not group:
            return False
        return ops.patch_group(group, patch)

    def _apply_delete_draft(self, action: Dict) -> bool:
        draft_id = action.get("draft_id") or action.get("id") or ""
        draft_type = action.get("draft_type") or action.get("kind") or ""
        if not draft_id or draft_id == "current":
            draft_id = self.selected_draft_id
        return ops.delete_draft(self.state, draft_id, draft_type)

    def _apply_delete_group(self, action: Dict) -> bool:
        group_id = action.get("group_id") or action.get("id") or ""
        group_type = action.get("group_type") or action.get("kind") or ""
        return ops.delete_group(self.state, group_id, group_type)

    def _apply_add_group(self, action: Dict) -> bool:
        """创建新的故事板分组（关键元素 / 分镜 / 音频）"""
        group_type = (
            action.get("group_type") or action.get("draft_type")
            or action.get("kind") or action.get("target_type") or ""
        ).lower().strip()

        # 映射到 state 中的 key（含中文别名，与 FC 轨同一映射）
        cat_key = ops.category_for_group_type(group_type)

        group_data = action.get("group") or action.get("data") or {}
        # 也允许 patch 字段携带 title/desc
        patch = action.get("patch") or {}
        title = action.get("title") or group_data.get("title") or patch.get("title") or "Agent 新建分组"
        desc = action.get("desc") or group_data.get("desc") or patch.get("desc") or ""

        new_id = group_data.get("id") or gen_id('shot' if cat_key == 'shots' else 'ke' if cat_key == 'keyElements' else 'audio')

        new_group: Dict[str, Any] = {
            "id": new_id,
            "title": title,
            "desc": desc,
            "drafts": [],
        }
        # 分镜特有字段（允许放在 action 顶层或 group 子对象里）
        def pick(field, default=""):
            return action.get(field) or group_data.get(field) or patch.get(field) or default

        if cat_key == CAT_SHOTS:
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
        return ops.append_draft(group, draft_data)

    def _apply_clear_media(self, action: Dict) -> bool:
        """清空卡片内的媒体内容（图片/视频/音频地址），保留提示词与参数。
        draft_id 支持真实 ID、"current" 或卡片编号（如 "1-2"）。"""
        draft_id = action.get("draft_id") or action.get("target_id") or action.get("id") or "current"
        draft_type = action.get("draft_type") or action.get("kind") or action.get("target_type") or ""
        result = self._find_draft(str(draft_id), draft_type)
        if not result:
            return False
        _, draft = result
        return ops.clear_draft_media(draft)

    def _apply_add_draft(self, action: Dict) -> bool:
        group_id = action.get("group_id") or "current"
        group_type = action.get("group_type") or action.get("draft_type") or action.get("kind") or ""
        draft_data = action.get("draft") or {}

        group = self._find_group(group_id, group_type)
        if not group:
            for cat_key in ALL_CATEGORIES:
                groups = self.state.get(cat_key, [])
                if groups:
                    group = groups[0]
                    break
        # 如果仍然找不到分组，自动创建一个
        if not group:
            auto_action = {**action, "group_type": group_type, "title": draft_data.get("label", "Agent 新建分组")}
            self._apply_add_group(auto_action)
            # 取刚创建的分组（与 _apply_add_group 同一类别映射）
            cat_key = ops.category_for_group_type(group_type)
            groups = self.state.get(cat_key, [])
            if groups:
                group = groups[-1]  # 刚添加的在末尾
            if not group:
                return False

        self._append_draft_to_group(group, draft_data)
        return True

    def _apply_write_document(self, action: Dict) -> bool:
        """写入/更新项目文档工件（如 Final_Video_Spec.md）"""
        name = str(action.get("name") or action.get("title") or "").strip()
        content = action.get("content") or action.get("text") or ""
        if not name or not str(content).strip():
            return False

        docs = self.state.setdefault("documents", [])
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
        if name not in self.documents_written:
            self.documents_written.append(name)
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
                "id": asset_id or gen_id("ast"),
                "name": name,
                "type": action.get("asset_type") or action.get("kind") or "image",
                "isBound": True,
                "url": url,
            })
        return True

    # ---------- 故事板媒体 → 对话输入框（纯前端信号，不改状态） ----------

    def _apply_insert_chat_media(self, action: Dict) -> bool:
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
                found = self._find_draft(str(did), "")
                if found:
                    pairs.append(found)
        else:
            target = str(action.get("target") or "current").strip()
            if target == "current":
                found = self._find_draft("current", "")
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
                pairs = self._collect_drafts("all", draft_type)

        added = 0
        existing_urls = {it.get("url") for it in self.chat_inserts}
        for group, draft in pairs:
            if added >= limit:
                break
            url, kind = media_of_draft(draft)
            if not url or url in existing_urls:
                continue
            if media_type and kind != media_type:
                continue
            name = draft.get("label") or group.get("title") or draft.get("id", "")
            self.chat_inserts.append({
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

    # ---------- 图片生成（仅用户明确触发） ----------

    def _selected_draft_media_config(self) -> tuple:
        """解析中间预览面板选中草稿的 (providerId, aspectRatio, imageResolution)，作为生图缺省配置。"""
        return ops.selected_draft_media_config(self.state, self.selected_draft_id, self.selected_type)

    def _apply_generate_image(self, action: Dict) -> bool:
        """Agent 触发生图（仅当用户明确要求时）。支持批量。

        LLM 指定的供应商/模型/比例/分辨率会同步回写到目标草稿，
        使中间预览框底部的参数选择跳转到对应配置。
        """
        target = str(action.get("target") or action.get("draft_id") or "all").strip()
        draft_type = str(action.get("draft_type") or "").strip().lower()
        # 供应商兼容显示名（LLM 常传界面上的名称如 Grsai）→ 内部 id
        provider_id = resolve_provider_ref(
            str(action.get("provider_id") or action.get("provider") or "")
        )
        model = action.get("model") or ""
        # LLM 显式指定的比例/分辨率（可选）：命中时回写草稿并优先使用
        act_ratio = str(action.get("aspect_ratio") or action.get("ratio") or "").strip()
        act_resolution = str(
            action.get("image_resolution") or action.get("resolution") or ""
        ).strip().upper()
        if act_resolution not in ("1K", "2K", "4K"):
            act_resolution = ""

        # 中间面板选中草稿的生图配置（provider/比例/分辨率回退链的最后一级）
        sel_provider, sel_ratio, sel_resolution = self._selected_draft_media_config()

        # 根据 target 确定类型
        if target in ("all_keyelements", "all_keyElements"):
            draft_type = "keyelement"
            target = "all"
        elif target in ("all_shots", "all_shot"):
            draft_type = "shot"
            target = "all"

        pairs = self._collect_drafts(target, draft_type)
        if not pairs:
            return False

        submitted = 0
        for group, draft in pairs:
            prompt = (draft.get("prompt") or "").strip()
            if not prompt:
                continue
            refs = self._resolve_scene_refs(group) if group else []
            # provider 回退链：LLM 指定 → 目标草稿自身（预览框已选参数）→ 中间面板选中草稿
            eff_provider = provider_id or (draft.get("providerId") or "") or sel_provider
            # model 回退链：LLM 指定 → 目标草稿自身（预览框已选参数）→ 供应商默认模型（generation 层兑底）
            eff_model = model or (draft.get("model") or "")
            # 比例回退链：LLM 指定 → 目标草稿自身 → 中间面板选中草稿 → 16:9
            eff_ratio = act_ratio or (draft.get("aspectRatio") or "") or sel_ratio or "16:9"
            # 分辨率回退链：LLM 指定 → 目标草稿自身 → 中间面板选中草稿 → 1K
            eff_resolution = act_resolution or (draft.get("imageResolution") or "") or sel_resolution or "1K"
            # 参数回写草稿：中间预览框底部参数选择跳转到对应供应商/模型/比例/分辨率
            draft["providerId"] = eff_provider
            if eff_model:
                draft["model"] = eff_model
            draft["aspectRatio"] = eff_ratio
            draft["imageResolution"] = eff_resolution
            self._submit_image_task(
                draft, eff_provider, eff_model, refs,
                aspect_ratio=eff_ratio, resolution=eff_resolution,
            )
            submitted += 1
        if submitted:
            logger.info(f"[StudioActions] generate_image: 已提交 {submitted} 个生图任务")
        return submitted > 0

    def _collect_drafts(self, target: str, draft_type: str) -> List[tuple]:
        """收集目标 (group, draft) 对；委托领域层唯一实现"""
        return ops.collect_drafts(self.state, target, draft_type)

    def _resolve_scene_refs(self, group: Dict) -> List[Dict[str, str]]:
        """解析分镜的 sceneRefs → 对应关键元素的概念图 URL 作为参考图"""
        return ops.resolve_scene_refs(self.state, group)

    def _submit_image_task(self, draft: Dict, provider_id: str, model: str, refs: List[Dict], aspect_ratio: str = "16:9", resolution: str = "1K") -> None:
        """提交异步生图任务（通过 GenerationTaskManager 统一管理）。

        尺寸由 比例 + 分辨率档位（1K/2K/4K）计算，确保生图模型感知分辨率。
        提示词中的 @引用会被解析为位置标记，被引用的素材（refAssets +
        sceneRefs 参考图）随请求发送给多模态生图模型。
        """
        tm = get_task_manager()
        task_id = f"{gen_id('img')}-{draft.get('id', 'x')[-4:]}"
        size = image_size_for(aspect_ratio, resolution)
        size_note = f"{size} ({aspect_ratio}, {resolution})"

        # --- 解析 @引用：重写提示词 + 汇总参考图（草稿自身 refAssets 优先，sceneRefs 其次）---
        base_ref_urls: List[str] = [u for u in (draft.get("refAssets") or []) if u]
        for r in refs:
            u = r.get("url") if isinstance(r, dict) else ""
            if u and u not in base_ref_urls:
                base_ref_urls.append(u)
        media_map = build_storyboard_media_map(self.state)
        eff_prompt, final_refs = resolve_prompt_mentions(
            draft.get("prompt", ""), base_ref_urls, media_map, max_refs=5
        )

        tm.create_task(
            task_id,
            status="processing",
            draft_id=draft.get("id", ""),
            draft_type="keyElement",
            prompt=eff_prompt,
            model=model,
            result=None,
        )
        prev_tag = draft.get("tag") or ""
        draft["tag"] = "生成中"
        # 生成日志：提交即记录 started；前端据此立即点亮卡片转圈（改进2）
        tm.record_gen_log(
            media_type="image", status="started", provider=provider_id, model=model,
            prompt=eff_prompt, draft_id=draft.get("id", ""), requested_size=size_note,
            source="agent", task_id=task_id,
        )
        tm.notify({
            "task_id": task_id, "status": "started", "kind": "image",
            "draft_id": draft.get("id", ""),
        })

        async def _run():
            t0 = time.time()
            task = tm.get_task(task_id)
            try:
                url = await generate_image_via_provider(
                    provider_id, model, eff_prompt,
                    size=size, aspect_ratio=aspect_ratio, resolution=resolution,
                    reference_images=final_refs,
                )
                if task:
                    elapsed = round(time.time() - t0, 1)
                    tm.update_task(task_id, status="succeeded", result={"images": [url]}, elapsed=elapsed)
                    tm.notify({
                        "task_id": task_id, "status": "succeeded", "kind": "image",
                        "draft_id": draft.get("id", ""),
                        "result": {"images": [url]}, "elapsed": elapsed,
                    })
                    tm.record_gen_log(
                        media_type="image", status="succeeded", provider=provider_id, model=model,
                        prompt=eff_prompt, draft_id=draft.get("id", ""), result_url=url,
                        elapsed=elapsed, requested_size=size_note, source="agent",
                        task_id=task_id,
                    )
                    writeback_if_complete(task_id)
            except Exception as e:  # GenerationError 是 Exception 子类，此处统一兜底保证任务状态闭环
                draft["tag"] = prev_tag  # 失败时恢复原标签，避免卡片永远卡在"生成中"
                self.svc.save_debounced()
                elapsed = round(time.time() - t0, 1)
                tm.update_task(task_id, status="failed", error=str(e), elapsed=elapsed)
                tm.notify({
                    "task_id": task_id, "status": "failed", "kind": "image",
                    "draft_id": draft.get("id", ""), "error": str(e), "elapsed": elapsed,
                })
                tm.record_gen_log(
                    media_type="image", status="failed", provider=provider_id, model=model,
                    prompt=eff_prompt, draft_id=draft.get("id", ""), error=str(e),
                    elapsed=elapsed, requested_size=size_note, source="agent",
                    task_id=task_id,
                )
                logger.warning(f"[StudioActions] 生图失败 {draft.get('id')}: {e}")

        try:
            tm.track(_run())
        except RuntimeError:
            pass  # 无事件循环时跳过（单元测试场景）
