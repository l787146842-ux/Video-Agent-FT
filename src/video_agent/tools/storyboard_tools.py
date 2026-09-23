"""
故事板操作 Tool 集 — 将 studio-actions 映射为标准 Tool（Rule2: 统一接口）。

每个 Tool 对应一个前端故事板操作，内部通过 StudioStateService 修改状态。
"""
from typing import Any, Dict, List, Literal, Optional, Type, Union

from pydantic import BaseModel, Field, model_validator
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

# draft 合法字段枚举（对齐 dsh schema 精确性：模型看得见字段就不用猜——
# 8888/3333 两次实测都把卡名写成 draft.title 被白名单拒收；白名单唯一源
# = ops.ALLOWED_NEW_DRAFT_FIELDS，此处动态拼接防漂移）
_DRAFT_FIELDS_HINT = (
    f"合法字段（白名单外字段整单拒收）：{', '.join(ops.ALLOWED_NEW_DRAFT_FIELDS)}。"
    "卡片名用 label（不是 title）；提示词放 prompt；卡片描述放 desc。"
    # 2026-09-23 批5（用户 D-1/D-2/D-3 裁决）：归属语义落成模型可见字段。
    # 平台此前只在注释里写了归属（可执行代码 0 命中），模型没有字段可用，
    # 只能自发用 tag/desc 表达而平台不消费 —— 本句即那条缺失的正面契约。
    f"音频卡用 audioType 声明种类（{'/'.join(ops.AUDIO_TYPES)}；"
    "voice = 角色音色卡，即 Skill 明文的 key_element_audio）。"
    # 2026-09-23 批10（事故 4444/P1-4）：**归属类目**这一级此前缺失——
    # 模型有 audioType 字段、也知道它是「角色音色卡」，却不知道**该挂进哪个类目**；
    # 4444 实跑 6 张 voice 卡全落 audioItems（独立 Audio_voice-* 组），
    # 而契约要求挂在角色自己的 keyElements 组内（或下游按引用取音色锚点会落空）。
    # 本句补齐「卡 → 宿主类目」的正面契约（与 CATEGORY_MEDIA_MATRIX 的
    # keyElement 行「可放音频」、前端 isVoiceCard 同口径；不新增拒收闸）。
    "角色的音色卡挂在该角色自己的 keyElement 组内"
    "（角色组用 elementType=character 声明；音色卡与该角色图像卡同组，"
    "分镜按 sceneRefs 引用该角色时自动取到音色锚点）。"
)

# group patch 合法字段枚举（2026-09-23 批10，事故 4444/P1-1）：
# 与 _DRAFT_FIELDS_HINT 同口径——模型看得见字段就不用猜（白名单唯一源
# = ops.ALLOWED_GROUP_FIELDS，动态拼接防漂移）。
_GROUP_FIELDS_HINT = (
    f"合法字段（白名单外字段整单拒收）：{', '.join(ops.ALLOWED_GROUP_FIELDS)}。"
    "分镜改引用用 sceneRefs（关键元素标题数组；裸名与 Element_ 前缀两种写法"
    "系统都认）；镜头内容改动用 desc；时长用 duration。"
)

class CreateGroupInput(StrictToolInput):
    group_type: Literal["keyElement", "shot", "audio"] = Field(..., description=(
        "分组类型（闭集枚举）: keyElement | shot | audio。"
        # 2026-09-23 批4（D-2=schema 层 / D-3=正面契约不加硬判）：
        # 矩阵单一事实源 = ops.CATEGORY_MEDIA_MATRIX，此处按行渲染正面契约。
        "类目能力矩阵："
        + "；".join(
            f"{k}{ops.matrix_contract_line(k)}"
            for k in ("keyElement", "shot", "audio"))
    ))
    title: str = Field(..., description="分组标题（裸名；平台按组类型幂等补类型前缀 Element_/Shot_/Audio_；shot 标题=一句话描述镜头内容，顺序由列表序号承担，标题中不带镜号/场号编号）")
    # 2026-09-23 批5（D-2=schema 层 / D-3=给字段+正面契约）：元素种类落成模型可见字段。
    element_type: str = Field("", description=(
        f"关键元素组的元素种类（{'/'.join(ops.ELEMENT_TYPES)}）；"
        "character=角色（其音色卡另建在该角色组内，标 mediaType=audio 且 "
        "audioType=voice）、scene=场景、prop=关键道具。"
        "其他组类型忽略此字段"))
    desc: str = Field("", description="分组描述（shot 类型：完整镜头设计写这里，唯一载体）")
    duration: str = Field("", description="时长（shot 类型用；整镜总时长）")
    summary: str = Field("", description="shot 类型必填：镜头结构摘要徽标（自由文本短句，须与 desc 镜头结构一致），如'含3个内切镜头（约18s）'/'带内部剪辑（约10s）'/'缓慢推近（约5s）'；缺失或空整单拒收；其他组类型忽略此字段")
    scene_refs: List[str] = Field(default_factory=list, description="引用的关键元素标题数组；留空时系统自动从分组描述里的 [元素名] 令牌与裸名提及解析合并")
    draft: Optional[Union[Dict[str, Any], str]] = Field(None, description="附带草稿（可选；传 JSON 对象，字符串会自动解析一次）。" + _DRAFT_FIELDS_HINT)
    idempotency_key: str = Field("", description="幂等键：重复提交去重用，可留空")

    @model_validator(mode="before")
    @classmethod
    def _desc_before_summary(cls, data):
        """批 E（2026-09-18）：shot 建组验原始入参键序——desc 必须先于 summary。

        意图：先写完整镜头设计 desc、再据其提炼 summary 徽标（flova：summary
        是 desc 的镜子），防「徽标吹内切、desc 里没有」。只查字段顺序、不看
        内容、不碰格式红线（与「summary 缺失整单拒收」同档写闸）。
        mode="before" 收到的 data = json.loads 保序 dict（manager.invoke_tool 原样传
        kwargs），故键序 = 模型原始入参 JSON 键序；倒序抛 ValueError →
        ValidationError → 整单拒收重填（retryable=False）。
        """
        if isinstance(data, dict) and data.get("group_type") == "shot":
            keys = list(data.keys())
            if ("desc" in keys and "summary" in keys
                    and keys.index("desc") > keys.index("summary")):
                raise ValueError(
                    "shot 建组入参键序错误：desc 必须先于 summary（先写完整镜头"
                    "设计 desc，再据其提炼 summary 徽标）；请调整字段顺序后整单重填。")
        return data


class PatchDraftInput(StrictToolInput):
    draft_id: str = Field(..., description="草稿 ID 或 'current'")
    draft_type: str = Field("", description="草稿类型: keyElement | shot | audio")
    patch: Dict[str, Any] = Field(..., description="要更新的字段字典。" + _DRAFT_FIELDS_HINT)
    idempotency_key: str = Field("", description="幂等键：重复提交去重用，可留空")


class AddDraftInput(StrictToolInput):
    group_id: str = Field("current", description="目标分组 ID 或 'current'")
    group_type: str = Field("", description="分组类型")
    draft: Union[Dict[str, Any], str] = Field(..., description="新草稿数据（JSON 对象；字符串会自动解析一次）。" + _DRAFT_FIELDS_HINT)
    idempotency_key: str = Field("", description="幂等键：重复提交去重用，可留空")


class DeleteGroupInput(StrictToolInput):
    group_id: str = Field(..., description="要删除的分组 ID")
    group_type: str = Field("", description="分组类型")
    idempotency_key: str = Field("", description="幂等键：重复提交去重用，可留空")


class PatchGroupInput(StrictToolInput):
    """2026-09-23 批10（事故 4444/P1-1）：改分组的入参。

    事故背景：`ops.patch_group` 与 `PATCH /storyboard/groups/{id}`（注释自称
    「用户直接编辑，不经 Planner，<10ms」）**都存在，却从未接线成模型工具**——
    模型要改一个分组的 `sceneRefs` 只能「删除整组 + 重建整组」。
    4444 实跑为此**删光 22 个 shot 组再重建 22 个**，耗时 261.6s，且重建产生
    全新 group id（中途任一批失败即留下残缺故事板）。
    本工具即那条缺失的接线（与 09-23 批2 补 `storyboard_delete_draft` 同类）。
    """
    group_id: str = Field(..., description="要修改的分组 ID（真实 ID；read_state_group 可查）")
    group_type: str = Field("", description="分组类型: keyElement | shot | audio")
    patch: Dict[str, Any] = Field(..., description="要更新的字段字典。" + _GROUP_FIELDS_HINT)
    idempotency_key: str = Field("", description="幂等键：重复提交去重用，可留空")


class DeleteDraftInput(StrictToolInput):
    """2026-09-23 批2（Q3）：删单卡工具入参。

    ops.delete_draft 早已存在，但**从未接线成工具**——模型建错卡后无撤销手段
    （3333 三张音色卡落错组时只能干看着）。本工具即那条缺失的接线。
    """
    draft_id: str = Field(..., description="要删除的草稿 ID，或「组号-卡序号」编号（如 '1-2'）")
    draft_type: str = Field("", description="草稿类型: keyElement | shot | audio（编号口径下建议指定以消除歧义）")
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
        # 2026-09-23 批2（Q1-B/Q2-A，用户裁决）：恢复建组正面契约。
        # 该引导句 2026-09-16 d75a374 被删且无闸机接管，直接导致：
        #   ①关键元素未一组一卡（2222 三个粗组）→ 前端候选源全是组标题；
        #   ②分镜引用候选源错位 → 26 镜 0 块引用。
        # 本次按「正面契约」写法恢复（避开 description lint 的禁令词表）。
        "建组规范：关键元素——每个元素单独一组，组名=元素名，"
        "元素设定全文写在分组描述 desc 上；分镜——每个镜头单独一组，组名=镜头名，"
        "完整镜头描述写在 desc 上，引用到的元素用 [元素名] 令牌写在描述里"
        "（系统会自动解析为引用并挂参考），也可用 scene_refs 显式指定。"
        "desc 中 [元素名] 令牌与裸名提及由系统自动解析为引用。"
        "shot 类型必填 summary（镜头结构摘要徽标），缺失整单拒收打回重填。"
    )

    def get_input_schema(self) -> Type[BaseModel]:
        return CreateGroupInput

    async def aexecute(self, params: CreateGroupInput) -> ToolResult:
        svc = StateManager.get_instance()
        cat_key = ops.category_for_group_type(params.group_type)

        # flova 对齐批（2026-09-17 裁决）：shot 建组写闸——summary 是写入侧承诺契约
        # （模型先承诺镜头结构摘要，desc 按其自洽展开；对齐 flova 落库摘要徽标字段）；
        # 缺失整单拒收打回重填，不建组不写卡（与 draft 白名单拒收同一先例）
        if params.group_type == "shot" and not str(params.summary or "").strip():
            return ToolResult(
                success=False,
                error=("Validation Error: shot 建组必填 summary（镜头结构摘要徽标）。"
                       "本次调用已拒收、未创建分组，现有故事板与全部草稿保持原样。"
                       "请为本次建组补填 summary 后重新提交：与 desc 镜头结构一致的自由文本短句，"
                       "如'含3个内切镜头（约18s）'/'带内部剪辑（约10s）'/'缓慢推近（约5s）'。"),
                error_code="validation", retryable=False,
            )

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
        # 标题确定性归一（2026-09-17 裁决：容器 ID 约定 = 类型前缀+裸名，与文本轨同一 ops 实现）
        _raw_title = str(params.title or "")
        _title = ops.normalize_group_title(_raw_title, cat_key)
        new_group: Dict[str, Any] = {"id": new_id, "title": _title, "desc": params.desc, "drafts": []}
        # 2026-09-23 批5（D-2/D-3）：元素种类落库（仅关键元素组有意义；
        # 空串=未声明，不强制不判错——给字段而非加闸）。
        _elem_type = str(getattr(params, "element_type", "") or "").strip().lower()
        if cat_key == CAT_KEY_ELEMENTS and _elem_type:
            new_group["elementType"] = _elem_type
        # badgeLabel 写口退役（2026-09-17 用户裁决：关键元素类别标识全链删除）：
        # 建组不再按 desc 锚点推导角标；存量数据只读透传（前端不显示不编辑）。

        # 分镜通道的未匹配元素令牌（非分镜恒空）
        unmatched_tokens: List[str] = []
        if cat_key == CAT_SHOTS:
            # roughDesc 写入通道退役（2026-09-15，6666 实证）：desc/roughDesc 双通道
            # 歧义致模型把完整分镜设计写进 roughDesc——前端展示唯一认 desc，
            # 内容落进盲区（用户看到 16 张空壳卡）。分镜正文唯一载体 = desc，
            # 存量 roughDesc 数据只读保留（context_builder 照常注入）。
            new_group["duration"] = params.duration or "5s"
            # flova 对齐批（2026-09-17 裁决）：summary 落库（标题旁徽标载体；
            # desc 编辑不重算——与 flova 行为对齐，承诺只在写入侧成立）
            new_group["summary"] = str(params.summary or "").strip()
            # shotType 已摘除（2026-09-14 裁决）：单值「镜头语言」字段与 Skill 声明的
            # 多内切镜格式抢方向盘，致分镜时出内切镜时不出——分镜格式唯一载体 = desc。
            # 批 6 · A3 + K4 批（2026-09-16 对齐 flova）：引用三源合并——
            # 显式 scene_refs ∪ [元素名] 令牌 ∪ 裸名提及（去重保序）；
            # 匹配不到的令牌丢弃不拒收，但必须回喂告知——3333 批裁决：
            # 静默丢弃=模型以为挂上了引用
            tokens = ops.parse_element_tokens(params.desc or "")
            matched_titles, unmatched_tokens = ops.match_element_titles_report(
                svc.state_dict, tokens)
            bare_hits = ops.scan_bare_name_mentions(
                params.desc or "", svc.state_dict.get(CAT_KEY_ELEMENTS, []))
            merged_refs: List[str] = []
            # flova 对齐批（2026-09-17）：canonical 去重——同一元素的裸名与 Element_ 前缀
            # 形态算同一引用（去重键=strip_type_prefix），去重保序留首；
            # 杜绝 K4 三源合并产同元素双份（场景 chips 行重复 chip）
            _seen_norm: set = set()
            for ref in list(params.scene_refs or []) + matched_titles + bare_hits:
                _k = ops.strip_type_prefix(str(ref))
                if _k in _seen_norm:
                    continue
                _seen_norm.add(_k)
                merged_refs.append(ref)
            new_group["sceneRefs"] = merged_refs

        async with svc.lock:
            svc.state_dict.setdefault(cat_key, []).append(new_group)

            # 附带草稿
            if draft_payload:
                ops.append_draft(new_group, draft_payload)

            svc.save()
        result_data: Dict[str, Any] = {"group_id": new_id}
        if unmatched_tokens:
            _miss = "、".join(unmatched_tokens[:5]) + ("…" if len(unmatched_tokens) > 5 else "")
            result_data["detail"] = (
                f"已建组，但描述中的 [元素名] 令牌未匹配到关键元素组（已丢弃、未挂引用）：{_miss}。"
                "元素名须与关键元素组标题一致（read_state_group 可查），必要时显式传 scene_refs。")
            result_data["warnings"] = [
                f"分镜「{_title[:12]}」的元素令牌未匹配：{_miss}（引用缺失，跨镜一致性可能断链）"]
        return ToolResult(success=True, data=result_data)


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


class StoryboardPatchGroupTool(BaseTool):
    """2026-09-23 批10（事故 4444/P1-1）：改分组工具（接线既有 ops.patch_group）。

    事故背景与取舍见 `PatchGroupInput` docstring。本工具**不做**三源合并
    （`[元素名]` 令牌 ∪ 裸名提及）：那是**建组**期的一次性解析语义，若在 patch
    上重做，「删掉某条引用」会立刻被 desc 里的裸名重新加回来（引用删不掉）。
    故 patch 一律**以模型显式传入的 sceneRefs 为准**（只做 canonical 去重）。
    """
    name = "storyboard_patch_group"
    risk = "medium"  # 写内部状态（可再改撤销）
    detail_tier = "expand"  # 产出类
    description = "修改指定分组的字段（标题、描述、时长、分镜的元素引用等）"

    def get_input_schema(self) -> Type[BaseModel]:
        return PatchGroupInput

    async def aexecute(self, params: PatchGroupInput) -> ToolResult:
        svc = StateManager.get_instance()

        # 白名单外字段原子拒收（不写入任何字段，避免部分写入后报错）；
        # 报错三要素 = 原因 + 状态保留声明 + 缺什么才能继续（与 patch_draft 同口径）
        dropped = ops.dropped_patch_fields(params.patch, ops.ALLOWED_GROUP_FIELDS)
        if dropped:
            return ToolResult(
                success=False,
                error=(f"Validation Error: patch 含白名单外字段: {', '.join(dropped)}。"
                       "本次调用已拒收、未写入分组，现有故事板与该分组保持原样。"
                       f"请只用合法字段（{', '.join(ops.ALLOWED_GROUP_FIELDS)}）重新提交。"),
                error_code="validation", retryable=False,
            )

        # 空 patch = 无效调用：不假装成功（无先例可循，取 fail-loud 口径，
        # 防「空提交返回 success」的假成功）
        if not params.patch:
            return ToolResult(
                success=False,
                error=("Validation Error: patch 为空，未指定任何要修改的字段。"
                       "本次调用已拒收、现有故事板保持原样。"
                       f"请在 patch 中给出至少一个合法字段"
                       f"（{', '.join(ops.ALLOWED_GROUP_FIELDS)}）后重新提交。"),
                error_code="validation", retryable=False,
            )

        async with svc.lock:
            group = ops.find_group(svc.state_dict, params.group_id, params.group_type)
            if group is not None:
                patch = dict(params.patch)
                # 标题写口归一：幂等补容器类型前缀（与建组同一个写口，
                # 防 patch 出「无前缀标题」破坏引用锚点口径）。
                # 类目由 group_type 归属推得（find_group 只回分组本身）
                if "title" in patch:
                    patch["title"] = ops.normalize_group_title(
                        str(patch.get("title") or ""),
                        ops.category_for_group_type(params.group_type))
                changed, _ = ops.patch_group(group, patch)
                if changed:
                    svc.save()
                    return ToolResult(success=True, data={
                        "group_id": group.get("id", params.group_id),
                        "changed": sorted(patch),
                        "detail": (f"已更新分组「{group.get('title') or ''}」的 "
                                   f"{', '.join(sorted(patch))} 字段"),
                    })
                return ToolResult(success=True, data={
                    "group_id": group.get("id", params.group_id),
                    "detail": "字段值与原值相同，分组未发生变化",
                })
        return ToolResult(
            success=False,
            error=(f"Group '{params.group_id}' not found（未做任何改动，"
                   "现有故事板保持原样）。请先用 read_state_group 核对分组 ID "
                   "与 group_type 后重试。"),
            error_code="not_found", retryable=False,
        )


class StoryboardDeleteDraftTool(BaseTool):
    """2026-09-23 批2（Q3）：删单卡工具（接线既有 ops.delete_draft）。

    事故背景：ops.delete_draft 早已存在却**从未接线成工具**——模型建错卡后
    没有任何撤销手段（3333 三张音色卡落错组时只能干看着，用户只能手工删）。
    本工具补齐这条缺失的接线；同时是存量数据处置（批6）的前置依赖。
    """
    name = "storyboard_delete_draft"
    risk = "medium"  # 写内部状态（可重建撤销）
    detail_tier = "output"  # 删除类：仅输出留痕
    description = "删除指定草稿（单张卡片）；删除整个分组请用 storyboard_delete_group"

    def get_input_schema(self) -> Type[BaseModel]:
        return DeleteDraftInput

    async def aexecute(self, params: DeleteDraftInput) -> ToolResult:
        svc = StateManager.get_instance()

        async with svc.lock:
            # 先经 find_draft 解析（支持真实 ID 与「组号-卡序号」编号两种口径），
            # 再以**真实 ID** 调 delete_draft（其契约明确要求真实 ID，不接受编号）
            found = ops.find_draft(
                svc.state_dict, params.draft_id, params.draft_type)
            if found:
                _, draft = found
                _real_id = str(draft.get("id") or params.draft_id)
                removed = ops.delete_draft(
                    svc.state_dict, _real_id, params.draft_type)
                if removed:
                    # 与 delete_group 同级联纪律（对象删除批 1）：先掐绑定在途微调
                    # 任务再硬删，防隐藏线程静默回落污染主对话
                    conversation_ops.cleanup_scoped_threads_for_removed(
                        svc, removed, save=False,
                        stop_tasks=lambda ids: ports.task_stop_port().stop_bound_tasks(ids))
                    svc.save()
                    return ToolResult(success=True, data={
                        "deleted": removed,
                        "detail": f"已删除 {len(removed)} 张卡片：{', '.join(removed)}",
                    })
        return ToolResult(
            success=False,
            error=(f"Draft '{params.draft_id}' not found（未删除任何卡片，"
                   "现有故事板保持原样）。请先用 read_state_group 或 "
                   "view_storyboard_media 核对草稿 ID/编号与 draft_type 后重试。"))


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
    parallel_safe = True  # 小步提速批 3 补充（用户裁决）：只读，可进有界并行池
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
        # 非法值显式拒收（3333 批裁决：静默归空=过滤失效，插入范围比模型
        # 请求的宽且 success 无说明）；合法值 = image | video | audio | 空
        if media_type not in ("", "image", "video", "audio"):
            return ToolResult(
                success=False,
                error=(f"参数无效：media_type='{params.media_type}'（合法取值："
                       "image | video | audio，留空=不过滤）。"
                       "本次调用已拒收、未做任何改动，输入框保持原样。"),
                error_code="validation", retryable=False,
            )
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
        "读取指定故事板草稿卡的提示词全文。"
        "draft_id 支持「组号-卡序号」编号（如 '1-2'），"
        "建议同时带 draft_type（keyElement/shot/audio）。"
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
    parallel_safe = True  # 小步提速批 3：只读，可进有界并行池
    detail_tier = "output"  # 读取类：仅输出留痕
    description = (
        "读回工作台状态中某个分组的全文（完整描述/粗描述/引用与草稿目录）。"
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
    parallel_safe = True  # 小步提速批 3：只读，可进有界并行池
    detail_tier = "output"  # 读取类：仅输出留痕
    description = (
        "把故事板草稿卡的图片加载进上下文（服务端转 base64 内联）。"
        "draft_ids 支持真实 ID 与「组号-卡序号」编号（如 '1-2'），单次数量有上限。"
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
    # 2026-09-23 批10（事故 4444/P1-1）：改分组工具（接线既有 ops.patch_group）
    ToolManager.register(StoryboardPatchGroupTool())
    ToolManager.register(StoryboardAddDraftTool())
    ToolManager.register(StoryboardDeleteGroupTool())
    ToolManager.register(StoryboardDeleteDraftTool())
    ToolManager.register(StoryboardConfirmDraftTool())
    ToolManager.register(StoryboardMediaToChatTool())
    ToolManager.register(StoryboardReadDraftTool())
    ToolManager.register(StoryboardReadStateGroupTool())
    ToolManager.register(ViewStoryboardMediaTool())
    logger.info("[Tools] 11 storyboard tools registered")
