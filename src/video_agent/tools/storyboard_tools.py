"""
故事板操作 Tool 集 — 将 studio-actions 映射为标准 Tool（Rule2: 统一接口）。

每个 Tool 对应一个前端故事板操作，内部通过 StudioStateService 修改状态。
"""
from typing import Any, Dict, List, Literal, Optional, Type, Union

from pydantic import BaseModel, Field
from loguru import logger

import json

from src.video_agent.tools.base import BaseTool, StrictToolInput, ToolResult
from src.video_agent.config import settings
from src.video_agent.state.manager import StateManager
from src.video_agent.state.models import CAT_KEY_ELEMENTS, CAT_SHOTS, CAT_AUDIO_ITEMS, ALL_CATEGORIES_TUPLE
from src.video_agent.state import storyboard_ops as ops
from src.video_agent.state import conversation_ops
from src.video_agent.core import ports
from src.video_agent.core.prompt_refs import media_of_draft
from src.video_agent.core.provider_config import stamp_draft_spec_preference
from src.video_agent.storage.media_urls import resolve_injectable_url


# ---------- Input Schemas ----------

# 写类 Input 统一继承 StrictToolInput（extra="forbid"，批 4b 单一事实源）；
# 只读/交互控制面 Input 保持 BaseModel 原样，不扩大拒收面。

class CreateGroupInput(StrictToolInput):
    group_type: Literal["keyElement", "shot", "audio"] = Field(..., description="分组类型（闭集枚举）: keyElement | shot | audio")
    title: str = Field(..., description="分组标题")
    desc: str = Field("", description="分组描述")
    duration: str = Field("", description="时长（shot 类型用）")
    rough_desc: str = Field("", description="粗略描述（shot 类型用）")
    shot_type: str = Field("", description="镜头语言（shot 类型用）")
    scene_refs: List[str] = Field(default_factory=list, description="引用的关键元素标题数组；留空时系统自动从分组描述里的 [元素名] 令牌解析")
    draft: Optional[Union[Dict[str, Any], str]] = Field(None, description="附带草稿（可选；传 JSON 对象，字符串会自动解析一次）")
    idempotency_key: str = Field("", description="幂等键：重复提交去重用，可留空")


class PatchDraftInput(StrictToolInput):
    draft_id: str = Field(..., description="草稿 ID 或 'current'")
    draft_type: str = Field("", description="草稿类型: keyElement | shot | audio")
    patch: Dict[str, Any] = Field(..., description="要更新的字段字典")
    idempotency_key: str = Field("", description="幂等键：重复提交去重用，可留空")


class AddDraftInput(StrictToolInput):
    group_id: str = Field("current", description="目标分组 ID 或 'current'")
    group_type: str = Field("", description="分组类型")
    draft: Union[Dict[str, Any], str] = Field(..., description="新草稿数据（JSON 对象；字符串会自动解析一次）")
    idempotency_key: str = Field("", description="幂等键：重复提交去重用，可留空")


class DeleteGroupInput(StrictToolInput):
    group_id: str = Field(..., description="要删除的分组 ID")
    group_type: str = Field("", description="分组类型")
    idempotency_key: str = Field("", description="幂等键：重复提交去重用，可留空")


class ConfirmDraftInput(StrictToolInput):
    draft_id: str = Field("current", description="草稿 ID 或 'current'")
    draft_type: str = Field("", description="草稿类型")
    idempotency_key: str = Field("", description="幂等键：重复提交去重用，可留空")


class MediaToChatInput(BaseModel):
    draft_ids: List[str] = Field(default_factory=list, description="要插入的草稿 ID 数组（与 target 二选一，优先）")
    target: str = Field("", description="批量目标: all | all_keyElements | all_shots | all_audio（与 draft_ids 二选一）")
    media_type: str = Field("", description="媒体类型过滤: image | video | audio（可选）")
    limit: int = Field(0, description="插入数量上限（0 = 系统默认）")


class ReadDraftInput(BaseModel):
    draft_id: str = Field(..., description="草稿编号（如 '1-2' 表示第 1 组第 2 张卡）或草稿 ID")
    draft_type: str = Field("", description="草稿类型: keyElement | shot | audio（编号在各类别独立计数，建议指定以消除歧义）")


class ViewStoryboardMediaInput(BaseModel):
    draft_ids: List[str] = Field(default_factory=list, description="要查看的草稿 ID 或「组号-卡序号」编号数组（与 target 二选一，优先）")
    target: str = Field("", description="批量目标: all | all_keyElements | all_shots | all_audio（与 draft_ids 二选一）")
    limit: int = Field(0, description="本次加载图片数量上限（0 = 系统默认上限）")


class ReadStateGroupInput(BaseModel):
    category: Literal["keyElement", "shot", "audio"] = Field(..., description="分组类别（闭集枚举）: keyElement | shot | audio")
    group_id: str = Field("", description="分组 ID 或组号（如 '2'）或标题；留空返回该类别的分组目录（非全文）")


# ---------- Tool 实现 ----------

class StoryboardCreateGroupTool(BaseTool):
    name = "storyboard_create_group"
    risk = "medium"  # §2.7：写内部状态（可删除撤销）
    detail_tier = "expand"  # 产出类：建组展开可见输入
    description = (
        "创建新的故事板分组（关键元素/分镜/音频），可附带草稿。"
        "建组规范（Flova 形态）：关键元素——每个元素单独一组，组名=元素名，"
        "元素设定全文写在分组描述 desc 上；分镜——每个镜头单独一组，组名=镜头名，"
        "完整镜头描述写在 desc/roughDesc 上，引用到的元素用 [元素名] 令牌写在描述里"
        "（系统会自动解析为引用并挂参考），也可用 scene_refs 显式指定。"
    )

    def get_input_schema(self) -> Type[BaseModel]:
        return CreateGroupInput

    async def aexecute(self, params: CreateGroupInput) -> ToolResult:
        svc = StateManager.get_instance()
        cat_key = ops.category_for_group_type(params.group_type)

        # 批 6 · A3：draft 宽容解析——模型高频把 draft 传成 JSON 字符串，
        # 收到字符串自动 json.loads 拆包一次；拆不了按三要素原子拒收。
        draft_payload, coerce_err = ops.coerce_draft_payload(params.draft)
        if coerce_err:
            return ToolResult(
                success=False, error=coerce_err,
                error_code="validation", retryable=False,
            )

        # 批 1 · A2 + 批 3 · B5：附带草稿白名单外字段原子拒收（不建组不写卡，
        # 与 storyboard_patch_draft 同一先例）；报错三要素 = 原因 + 状态保留声明
        # + 缺什么才能继续。desc 承载卡片描述，不再静默丢弃。
        if draft_payload:
            dropped = ops.dropped_patch_fields(draft_payload, ops.ALLOWED_NEW_DRAFT_FIELDS)
            if dropped:
                return ToolResult(
                    success=False,
                    error=(f"Validation Error: draft 含白名单外字段: {', '.join(dropped)}。"
                           "本次调用已拒收、未创建分组，现有故事板与全部草稿保持原样。"
                           f"请只用合法字段（{', '.join(ops.ALLOWED_NEW_DRAFT_FIELDS)}）重新提交；"
                           "卡片描述统一放 desc 字段（角色：年龄/外貌/服装；场景：空间/材质/光源/氛围）。"),
                    error_code="validation", retryable=False,
                )
            # 批 3 · B6 原子性：显式草稿 id 查重（写入前拦截，防重复卡假成功）
            _explicit_id = str(draft_payload.get("id") or "").strip()
            if _explicit_id and ops.draft_id_exists(svc.state_dict, _explicit_id):
                return ToolResult(
                    success=False,
                    error=(f"Validation Error: 显式草稿 id '{_explicit_id}' 已存在（ID 重复）。"
                           "本次调用已拒收、未创建分组，现有故事板与全部草稿保持原样。"
                           "请省略 id 由系统分配，或改用 storyboard_patch_draft 修改已有卡片。"),
                    error_code="validation", retryable=False,
                )

        new_id = ops.new_group_id(cat_key)
        # 标题确定性归一（与文本轨同一 ops 实现）
        _raw_title = str(params.title or "")
        _title = ops.normalize_group_title(_raw_title)
        new_group: Dict[str, Any] = {"id": new_id, "title": _title, "desc": params.desc, "drafts": []}

        if cat_key == CAT_SHOTS:
            new_group["roughDesc"] = params.rough_desc or params.desc
            new_group["duration"] = params.duration or "5s"
            new_group["shotType"] = params.shot_type
            # 批 6 · A3：分镜描述里的 [元素名] 令牌自动解析为元素引用
            # （显式传 scene_refs 则以显式为准；匹配不到的令牌丢弃不拒收）
            if params.scene_refs:
                new_group["sceneRefs"] = params.scene_refs
            else:
                tokens = ops.parse_element_tokens(f"{params.desc or ''}\n{params.rough_desc or ''}")
                new_group["sceneRefs"] = ops.match_element_titles(svc.state_dict, tokens)

        async with svc.lock:
            svc.state_dict.setdefault(cat_key, []).append(new_group)

            # 附带草稿
            if draft_payload:
                ops.append_draft(new_group, draft_payload)

            svc.save()
        return ToolResult(success=True, data={"group_id": new_id})


class StoryboardPatchDraftTool(BaseTool):
    name = "storyboard_patch_draft"
    risk = "medium"  # §2.7：写内部状态（可重写撤销）
    detail_tier = "expand"  # 产出类
    description = "修改指定草稿的字段（提示词、标签、模型等）"

    def get_input_schema(self) -> Type[BaseModel]:
        return PatchDraftInput

    async def aexecute(self, params: PatchDraftInput) -> ToolResult:
        svc = StateManager.get_instance()

        # T2 第一步「错误可见」：白名单外字段原子拒收（不写入任何字段，
        # 避免部分写入后报错）；批 3 · B5 报错三要素 = 原因 + 状态保留
        # 声明 + 缺什么才能继续。差集只引用 ALLOWED_DRAFT_FIELDS，不复制名单（P1）
        dropped = ops.dropped_patch_fields(params.patch, ops.ALLOWED_DRAFT_FIELDS)
        if dropped:
            return ToolResult(
                success=False,
                error=(f"Validation Error: patch 含白名单外字段: {', '.join(dropped)}。"
                       "本次调用已拒收、未写入草稿，现有故事板与该卡片保持原样。"
                       f"请只用合法字段（{', '.join(ops.ALLOWED_DRAFT_FIELDS)}）重新提交。"),
                error_code="validation", retryable=False,
            )

        async with svc.lock:
            found = ops.find_draft(svc.state_dict, params.draft_id, params.draft_type)
            if found:
                group, draft = found
                # 统一白名单（含 imageResolution/genType，与文本轨一致）
                changed, _ = ops.patch_draft(draft, params.patch)
                if changed:
                    # 时长参数同步：分镜提示词写入时把分镜时长补印到草稿时长参数
                    ops.sync_shot_duration(group, draft, params.patch)
                    # 全局设置补印（与文本轨一致，草稿缺分辨率/时长时
                    # 按顶部「全局设置」填充，硬参数不依赖规格文档）
                    cat = ops.category_for_group_type(str(group.get("group_type") or ""))
                    stamp_draft_spec_preference(svc.state_dict, draft, cat)
                    svc.save()
                    return ToolResult(success=True, data={"draft_id": draft.get("id", params.draft_id)})
        return ToolResult(
            success=False,
            error=(f"Draft '{params.draft_id}' not found（未做任何改动，"
                   "现有故事板保持原样）。请先用 read_draft 核对草稿编号"
                   "（组号-卡序号或草稿 ID）后重试。"))


class StoryboardAddDraftTool(BaseTool):
    name = "storyboard_add_draft"
    risk = "medium"  # §2.7：写内部状态（可删除撤销）
    detail_tier = "expand"  # 产出类
    description = "给指定分组新增一个草稿卡片"

    def get_input_schema(self) -> Type[BaseModel]:
        return AddDraftInput

    async def aexecute(self, params: AddDraftInput) -> ToolResult:
        svc = StateManager.get_instance()

        # 批 6 · A3：draft 宽容解析（字符串自动 json.loads 拆包一次）
        draft_payload, coerce_err = ops.coerce_draft_payload(params.draft)
        if coerce_err:
            return ToolResult(
                success=False, error=coerce_err,
                error_code="validation", retryable=False,
            )

        # 批 1 · A2 + 批 3 · B5：白名单外字段原子拒收；报错三要素 =
        # 原因 + 状态保留声明 + 缺什么才能继续。
        dropped = ops.dropped_patch_fields(draft_payload or {}, ops.ALLOWED_NEW_DRAFT_FIELDS)
        if dropped:
            return ToolResult(
                success=False,
                error=(f"Validation Error: draft 含白名单外字段: {', '.join(dropped)}。"
                       "本次调用已拒收、未写入任何字段，现有故事板与全部草稿保持原样。"
                       f"请只用合法字段（{', '.join(ops.ALLOWED_NEW_DRAFT_FIELDS)}）重新提交；"
                       "卡片描述统一放 desc 字段（角色：年龄/外貌/服装；场景：空间/材质/光源/氛围）。"),
                error_code="validation", retryable=False,
            )
        # 批 3 · B6 原子性：显式草稿 id 查重（写入前拦截，防重复卡假成功）
        _explicit_id = str((draft_payload or {}).get("id") or "").strip()
        if _explicit_id and ops.draft_id_exists(svc.state_dict, _explicit_id):
            return ToolResult(
                success=False,
                error=(f"Validation Error: 显式草稿 id '{_explicit_id}' 已存在（ID 重复）。"
                       "本次调用已拒收、未写入任何字段，现有故事板与全部草稿保持原样。"
                       "请省略 id 由系统分配，或改用 storyboard_patch_draft 修改已有卡片。"),
                error_code="validation", retryable=False,
            )

        async with svc.lock:
            target_group = ops.find_group(svc.state_dict, params.group_id, params.group_type)
            if not target_group:
                return ToolResult(
                    success=False,
                    error=(f"Group '{params.group_id}' not found（未做任何改动，"
                           "现有故事板保持原样）。请先用 read_state_group 核对分组 ID "
                           "与 group_type 后重试。"))

            draft = ops.append_draft(target_group, draft_payload)
            # 时长参数同步：分镜草稿的时长参数与分镜结构对齐（客观兜底）
            ops.sync_shot_duration(target_group, draft)
            # 全局设置补印（唯一权威源）：草稿未自带供应商时按全局设置填充，
            # 防前端默认首选供应商回填污染（参数栏与全局设置不一致）
            cat = ops.category_for_group_type(str(params.group_type or ""))
            stamp_draft_spec_preference(svc.state_dict, draft, cat)
            svc.save()
        return ToolResult(success=True, data={"draft_id": draft["id"]})


class StoryboardDeleteGroupTool(BaseTool):
    name = "storyboard_delete_group"
    risk = "medium"  # §2.7 裁决：写内部状态（可重建撤销），定 medium
    detail_tier = "output"  # 删除类：仅输出留痕
    description = "删除整个故事板分组（含其全部草稿）"

    def get_input_schema(self) -> Type[BaseModel]:
        return DeleteGroupInput

    async def aexecute(self, params: DeleteGroupInput) -> ToolResult:
        svc = StateManager.get_instance()

        async with svc.lock:
            removed_draft_ids, hit = ops.delete_group(
                svc.state_dict, params.group_id, params.group_type)
            if hit:
                # 对象删除级联（二期子对话批 1）：先掐绑定在途微调任务再硬删
                # 对应隐藏线程，防 target_chat_messages 静默回落污染主对话；
                # 删除与级联同帧，撤销快照栈含 conversations 可原子恢复。
                # 掐停实现走 core/ports 端口（tools 层禁 import web，D-01 先例）。
                # 命中位与草稿列表分离（评审修补批）：空分组命中无草稿可级联，
                # 仍须落盘报成功，不得误报 not found 造成内存/磁盘漂移。
                if removed_draft_ids:
                    conversation_ops.cleanup_scoped_threads_for_removed(
                        svc, removed_draft_ids, save=False,
                        stop_tasks=lambda ids: ports.task_stop_port().stop_bound_tasks(ids))
                svc.save()
                return ToolResult(success=True, data={"deleted": params.group_id})
        return ToolResult(
            success=False,
            error=(f"Group '{params.group_id}' not found（未删除任何分组，"
                   "现有故事板保持原样）。请先用 read_state_group 核对分组 ID "
                   "与 group_type 后重试。"))


class StoryboardConfirmDraftTool(BaseTool):
    name = "storyboard_confirm_draft"
    risk = "medium"  # §2.7：写草稿标记（可再改撤销）
    detail_tier = "output"  # 标记类：仅输出留痕
    description = "将指定草稿标记为「已确认」"

    def get_input_schema(self) -> Type[BaseModel]:
        return ConfirmDraftInput

    async def aexecute(self, params: ConfirmDraftInput) -> ToolResult:
        svc = StateManager.get_instance()

        async with svc.lock:
            found = ops.find_draft(svc.state_dict, params.draft_id, params.draft_type)
            if found:
                _, draft = found
                ops.patch_draft(draft, {"tag": "已确认"})
                svc.save()
                return ToolResult(success=True, data={"draft_id": draft.get("id", params.draft_id), "tag": "已确认"})
        return ToolResult(
            success=False,
            error=(f"Draft '{params.draft_id}' not found（未做任何改动，"
                   "现有故事板保持原样）。请先用 read_draft 核对草稿编号后重试。"))


class StoryboardMediaToChatTool(BaseTool):
    name = "storyboard_media_to_chat"
    risk = "low"  # §2.7：只读（不改故事板状态，仅填充输入框）
    detail_tier = "output"  # 读取类：仅输出留痕
    description = (
        "把故事板草稿卡片里的媒体（图片/视频/音频）自动添加到右侧 Agent 对话输入框，"
        "供用户确认后发送。不修改故事板状态。"
    )

    def get_input_schema(self) -> Type[BaseModel]:
        return MediaToChatInput

    async def aexecute(self, params: MediaToChatInput) -> ToolResult:
        svc = StateManager.get_instance()
        media_type = params.media_type.lower().strip()
        if media_type not in ("", "image", "video", "audio"):
            media_type = ""
        limit = params.limit or settings.max_chat_inserts
        limit = min(limit, settings.max_chat_inserts)

        state = svc.state_dict
        pairs: List[tuple] = []
        if params.draft_ids:
            # D1 收拢：草稿查找经 StateManager.find_draft 唯一入口（三层循环抄写消灭）
            for did in params.draft_ids:
                found = svc.find_draft(did)
                if found is not None:
                    _cat, group, draft = found
                    pairs.append((group, draft))
        else:
            target = (params.target or "").lower()
            cat_keys = {
                "all_keyelements": (CAT_KEY_ELEMENTS,),
                "all_shots": (CAT_SHOTS,),
                "all_audio": (CAT_AUDIO_ITEMS,),
                "all": ALL_CATEGORIES_TUPLE,
            }.get(target, ())
            # target 结构化校验（与同族 view_storyboard_media 同口径）：
            # draft_ids/target 均未命中合法取值时结构化报错，附合法取值清单，
            # 不落入「没找到带媒体的目标草稿」误导回喂（如传 current 等不支持值）
            if not cat_keys:
                return ToolResult(
                    success=False,
                    error="参数无效：请传 draft_ids（草稿 ID 数组）或 "
                          "target（all | all_keyElements | all_shots | all_audio）",
                    error_code="validation", retryable=False,
                )
            for cat_key in cat_keys:
                for group in state.get(cat_key, []):
                    for draft in group.get("drafts", []):
                        pairs.append((group, draft))

        inserts: List[Dict[str, Any]] = []
        seen = set()
        for group, draft in pairs:
            if len(inserts) >= limit:
                break
            url, kind = media_of_draft(draft)
            if not url or url in seen:
                continue
            if media_type and kind != media_type:
                continue
            seen.add(url)
            inserts.append({
                "kind": kind,
                "url": url,
                "name": draft.get("label") or group.get("title") or draft.get("id", ""),
                "thumb": (draft.get("imgUrl") or "") if kind == "video" else "",
            })

        if not inserts:
            return ToolResult(success=False, error="没有找到带媒体的目标草稿")
        return ToolResult(success=True, data={"chat_inserts": inserts})


class StoryboardReadDraftTool(BaseTool):
    name = "read_draft"
    risk = "low"  # §2.7：只读
    # 五项修法批 3：模型惯于并行连发的只读工具，可进有界并行池
    parallel_safe = True
    detail_tier = "output"  # 读取类：仅输出留痕
    description = (
        "按需读取指定故事板草稿卡的提示词全文。上下文里草稿只有目录信息（编号/label/字数），"
        "审阅、修改或参考其写法时才需要调用本工具读取全文；触发生成时系统会自动取提示词，无需先读。"
        "draft_id 支持「组号-卡序号」编号（如 '1-2'），编号在关键元素/分镜/音频各类别独立从 1 计数，"
        "调用时建议同时带上 draft_type（keyElement/shot/audio）。"
    )

    def get_input_schema(self) -> Type[BaseModel]:
        return ReadDraftInput

    async def aexecute(self, params: ReadDraftInput) -> ToolResult:
        svc = StateManager.get_instance()
        wanted = (params.draft_id or "").strip()
        matches = ops.find_draft_matches(svc.state_dict, wanted, params.draft_type)
        if not matches:
            return ToolResult(
                success=False,
                error=f"未找到草稿「{wanted}」。编号格式为「组号-卡序号」（如 '1-2'），"
                      f"各类别（关键元素/分镜/音频）独立从 1 计数，可传 draft_type 消除歧义",
            )
        # 全文上限截断（与其他 read_* 工具一致，防单次返回撑爆上下文）
        max_chars = settings.max_doc_chars
        for m in matches:
            if len(m["prompt"]) > max_chars:
                m["prompt"] = m["prompt"][:max_chars] + f"\n……（提示词超长，已截断为前 {max_chars} 字）"
        # 同编号在多类别重复时全部返回，由模型确认具体目标
        return ToolResult(success=True, data={"drafts": matches})


class StoryboardReadStateGroupTool(BaseTool):
    name = "read_state_group"
    risk = "low"  # §2.7：只读
    detail_tier = "output"  # 读取类：仅输出留痕
    description = (
        "按需读回工作台状态中某个分组的全文（完整描述/粗描述/引用与草稿目录；"
        "草稿提示词全文仍用 read_draft）。状态 JSON 以摘要或截断形态注入时"
        "（带 read_state_group 指针提示），用本工具读回目标分组全文。"
    )

    def get_input_schema(self) -> Type[BaseModel]:
        return ReadStateGroupInput

    async def aexecute(self, params: ReadStateGroupInput) -> ToolResult:
        svc = StateManager.get_instance()
        cat_key = ops.category_for_group_type(params.category)
        groups = svc.state_dict.get(cat_key, []) or []
        wanted = (params.group_id or "").strip()
        if not wanted:
            listing = [
                {"id": g.get("id", ""), "index": i + 1,
                 "title": g.get("title", ""),
                 "draft_count": len(g.get("drafts", []) or [])}
                for i, g in enumerate(groups)
            ]
            return ToolResult(success=True, data={
                "name": f"{params.category} 分组目录",
                "content": json.dumps(listing, ensure_ascii=False),
            })
        target = None
        for i, g in enumerate(groups):
            if wanted in (str(g.get("id") or ""), str(i + 1)) \
                    or str(g.get("title", "")).strip() == wanted:
                target = g
                break
        if target is None:
            available = "、".join(
                f"{i + 1}:{g.get('title', '')}" for i, g in enumerate(groups[:10])
            ) or "无"
            return ToolResult(
                success=False,
                error=f"未找到分组「{wanted}」。已有分组：{available}",
            )
        # 深拷贝后剥离草稿提示词全文（渐进式披露：全文归 read_draft 通道）
        full = json.loads(json.dumps(target, ensure_ascii=False))
        for d in full.get("drafts", []) or []:
            if isinstance(d, dict) and "prompt" in d:
                d["prompt_chars"] = len(str(d.get("prompt") or ""))
                del d["prompt"]
        return ToolResult(success=True, data={
            "name": f"{params.category} 分组「{target.get('title', '')}」全文",
            "content": json.dumps(full, ensure_ascii=False),
        })


class ViewStoryboardMediaTool(BaseTool):
    name = "view_storyboard_media"
    risk = "low"  # §2.7：只读
    detail_tier = "output"  # 读取类：仅输出留痕
    description = (
        "按需把故事板草稿卡的图片加载进你的上下文（服务端转 base64 内联，你能直接看到画面）。"
        "编写/修改某条提示词草案前，先调用本工具加载对应草稿的图片再动笔；"
        "每轮只加载当前正在处理的那几张，不要一次拉全部（单次数量有上限，超限报错）。"
        "draft_ids 支持真实 ID 与「组号-卡序号」编号（如 '1-2'）。"
    )

    def get_input_schema(self) -> Type[BaseModel]:
        return ViewStoryboardMediaInput

    async def aexecute(self, params: ViewStoryboardMediaInput) -> ToolResult:
        svc = StateManager.get_instance()
        state = svc.state_dict
        limit = params.limit or settings.max_llm_images
        limit = min(limit, settings.max_llm_images)

        # --- 解析目标草稿（去重，保留顺序） ---
        pairs: List[tuple] = []
        seen_ids = set()

        def _collect(group: Dict[str, Any], draft: Dict[str, Any]) -> None:
            did = draft.get("id", "")
            if did and did not in seen_ids:
                seen_ids.add(did)
                pairs.append((group, draft))

        if params.draft_ids:
            for wanted in params.draft_ids:
                w = (wanted or "").strip()
                if not w:
                    continue
                hit = False
                for cat_key in ALL_CATEGORIES_TUPLE:
                    for gi, group in enumerate(state.get(cat_key, []) or []):
                        for di, draft in enumerate(group.get("drafts", []) or []):
                            if draft.get("id") == w or w == f"{gi + 1}-{di + 1}":
                                _collect(group, draft)
                                hit = True
                if not hit:
                    logger.warning(f"[Tools] view_storyboard_media 未找到草稿: {w}")
        else:
            cat_keys = {
                "all_keyelements": (CAT_KEY_ELEMENTS,),
                "all_shots": (CAT_SHOTS,),
                "all_audio": (CAT_AUDIO_ITEMS,),
                "all": ALL_CATEGORIES_TUPLE,
            }.get((params.target or "").lower(), ())
            if not cat_keys:
                return ToolResult(
                    success=False,
                    error="参数无效：请传 draft_ids（草稿 ID 或 '组号-卡序号' 编号）或 "
                          "target（all | all_keyElements | all_shots | all_audio）",
                )
            for cat_key in cat_keys:
                for group in state.get(cat_key, []) or []:
                    for draft in group.get("drafts", []) or []:
                        _collect(group, draft)

        if not pairs:
            return ToolResult(success=False, error="没有找到目标草稿")

        # --- 逐张解析图片（本地读盘 / 远程代下载 → data URI） ---
        images: List[Dict[str, str]] = []
        notes: List[str] = []
        for group, draft in pairs:
            if len(images) >= limit:
                notes.append(f"已达单次加载上限（{limit} 张），草稿「{draft.get('label') or draft.get('id')}」未加载，可下轮再调")
                break
            url = draft.get("imgUrl") or ""
            label = draft.get("label") or group.get("title") or draft.get("id", "")
            did = draft.get("id", "")
            if not url:
                notes.append(f"草稿「{label}」（draft_id={did}）没有图片媒体")
                continue
            data_uri = await resolve_injectable_url(url)
            if not data_uri:
                notes.append(f"草稿「{label}」（draft_id={did}）的图片无法加载（文件缺失或外链已失效），URL: {url}")
                continue
            images.append({"label": label, "draft_id": did, "data_uri": data_uri})

        if not images:
            detail = "；".join(notes[:3]) if notes else "目标草稿均无图片"
            return ToolResult(success=False, error=f"没有可加载的图片：{detail}")
        logger.info(f"[Tools] view_storyboard_media 加载 {len(images)} 张图片进上下文")
        return ToolResult(success=True, data={"images": images, "notes": notes})


# ---------- 注册 ----------

def register_storyboard_tools():
    """注册所有故事板 Tool 到 ToolManager"""
    from src.video_agent.tools.manager import ToolManager
    ToolManager.register(StoryboardCreateGroupTool())
    ToolManager.register(StoryboardPatchDraftTool())
    ToolManager.register(StoryboardAddDraftTool())
    ToolManager.register(StoryboardDeleteGroupTool())
    ToolManager.register(StoryboardConfirmDraftTool())
    ToolManager.register(StoryboardMediaToChatTool())
    ToolManager.register(StoryboardReadDraftTool())
    ToolManager.register(StoryboardReadStateGroupTool())
    ToolManager.register(ViewStoryboardMediaTool())
    logger.info("[Tools] 9 storyboard tools registered")
