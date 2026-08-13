"""
Studio Actions 执行器 — 从 actions.py 抽离。

职责：执行 studio-actions JSON 中的操作列表，操作 StateManager 共享状态并自动持久化。
解析逻辑在 action_parser.py，本文件仅负责执行。
"""
from datetime import datetime, timezone
import re
from typing import Any, Dict, List, Optional

from loguru import logger

from src.video_agent.config import settings
from src.video_agent.core import prompt_gates
from src.video_agent.state.models import CAT_KEY_ELEMENTS, CAT_SHOTS, ALL_CATEGORIES
from src.video_agent.state import storyboard_ops as ops
from src.video_agent.state.manager import StateManager
from src.video_agent.utils import gen_id
from src.video_agent.web.generation import submit_image_task, submit_video_task
from src.video_agent.web.provider_config import (
    resolve_provider_ref,
    spec_media_preference,
    stamp_draft_spec_preference,
)
from src.video_agent.web.prompt_refs import media_of_draft
from src.video_agent.web.action_descriptions import describe_action
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
        gate_enabled: bool = False,
    ):
        self.svc = state_service or StateManager.get_instance()
        # 前端当前选中的草稿——"current" 的唯一正确解释
        self.selected_draft_id = selected_draft_id
        self.selected_type = selected_type
        # 提示词结构闸机开关（Skill 流程激活时由 Planner 打开，日常微调/mock 不拦截）
        self.gate_enabled = gate_enabled
        # 执行器/闸机规则（skill_runtime executors 注入 parse_gate_rules 结果；
        # None = 用平台默认规则，保证无 Skill 场景不炸）
        self.gate_rules: Optional[Dict[str, Any]] = None
        # 决策 D：用户坚持（user_override）时硬伤降为警告照常放行
        self.gate_override: bool = False
        # 本批次闸机警告（executors._apply_actions 读取后随结果回喂）
        self.gate_warnings: List[str] = []
        # 当前激活的 Skill 名称（执行器/agent_loop 注入；S1：平台行为按 Skill 声明驱动）
        self.skill_name: str = ""
        # 结构阶段开关：True = add_draft 内联详细提示词被剥离（默认，主模型直出结构路径）；
        # 执行器按阶段设置（write_media_prompt 等提示词阶段必须关闭）
        self.structure_phase: bool = True
        # 本执行器生命周期内写入的文档名（供前端渲染"已完成"卡片）
        self.documents_written: List[str] = []
        # 待插入前端对话输入框的媒体（insert_chat_media 产出，随 done payload 带回）
        # 每项：{"kind": image|video|audio, "url": str, "name": str, "thumb": str}
        self.chat_inserts: List[Dict[str, str]] = []
        # 已执行操作的中文描述清单（供前端「阶段完成」卡片展开查看具体操作，随消息持久化）
        self.action_log: List[str] = []
        # 本批次被流程闸机拦截的原因清单（每次 execute 重置）：
        # 供 agent_loop 回喂模型自愈（对齐 Tool 模式错误回传闭环），
        # 避免操作被拦后模型正文虚报「已写入/已创建」
        self.gate_rejections: List[str] = []
        # 本批次实际搭建的结构分组类别（keyElement/shot/audio，每次 execute 重置）：
        # 供 agent_loop 在结构首建时把确认卡片强制换成「审阅拆分方案」系统文案
        self.structure_kinds_created: set = set()
        # 本批次被结构纯净闸剥离的内联详细提示词条数（每次 execute 重置）：
        # 剥离后草稿无提示词，正文追加更正说明防虚报
        self.prompts_stripped: int = 0
        # 流式增量执行（边写边填）计数：由 planner 流式路径维护，
        # agent_loop 据此把已预执行的动作从重复执行中剔除
        self.stream_preapplied: int = 0
        self.stream_consumed: int = 0
        # 流式批次是否已压入 undo 快照（整批只压一次，随非累加批次复位）
        self._stream_undo_pushed: bool = False
        # 流式批次是否已开始（首拆判定整个流式轮只算一次，与普通批次语义对齐）
        self._stream_batch_started: bool = False

    def _reject(self, reason: str) -> None:
        """记录一条闸机拦截原因（去重）"""
        if reason and reason not in self.gate_rejections:
            self.gate_rejections.append(reason)
        if reason and reason not in self.gate_warnings:
            self.gate_warnings.append(reason)

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

    def execute(self, actions: List[Dict[str, Any]], accumulate: bool = False) -> int:
        """执行操作列表，返回成功执行的数量。执行后自动持久化。

        Agent 主路径统一在此 push_undo()，使 Agent 改动与手动 update 一样可撤销；
        纯信号操作（select/确认/continue）或全部失败时不污染 undo 栈。

        accumulate=True（流式边写边填批次）：不重置闸机拦截/结构搭建等
        批次记录（整个流式轮视为同一批），undo 快照整批只压一次。
        """
        mutating = [a for a in actions if self._is_mutating(a)]
        if not accumulate:
            if mutating:
                self.svc.push_undo()
            self.gate_rejections = []  # 每批次重置拦截原因记录
            self.gate_warnings = []
            self.structure_kinds_created = set()
            self.prompts_stripped = 0
            self._stream_undo_pushed = False
            self._stream_batch_started = False
            # 首次搭建批次判定：批开始时故事板完全为空，则本批只允许先拆关键元素
            self._first_structure_batch = (
                self.gate_enabled
                and prompt_gates.gate_mode() == "strict"
                and prompt_gates.storyboard_is_empty(self.state)
            )
        else:
            if mutating and not self._stream_undo_pushed:
                self.svc.push_undo()
                self._stream_undo_pushed = True
            if not self._stream_batch_started:
                # 流式轮首个变动动作时判定（与普通批次「批开始时刻」语义一致）
                self._stream_batch_started = True
                self._first_structure_batch = (
                    self.gate_enabled
                    and prompt_gates.gate_mode() == "strict"
                    and prompt_gates.storyboard_is_empty(self.state)
                )
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
        elif mutating and not accumulate:
            # 全部失败：丢弃预先压入的 undo 快照（累加批次的快照属整个流式批，不在此丢）
            self.svc.discard_last_undo()
        return applied

    # 文本动作轨的异步执行器动作（skill_runtime.executors 注册的工具）
    _ASYNC_EXECUTOR_ACTIONS = frozenset({
        "script_analyze",
        "storyboard_key_elements",
        "storyboard_shots",
        "storyboard_audio",
        "write_media_prompt",
        "audio_generate",
        "video_assembler",
    })

    @staticmethod
    def _is_async_action(action: Dict[str, Any]) -> bool:
        """判断是否为需要独立 LLM 调用的执行器动作（文本轨据此走 execute_async）。"""
        return str(action.get("action") or action.get("type") or "").strip() in \
            StudioActionExecutor._ASYNC_EXECUTOR_ACTIONS

    async def execute_async(
        self, actions: List[Dict[str, Any]], accumulate: bool = False
    ) -> int:
        """文本动作轨执行含异步执行器的操作列表。

        异步动作 → skill_runtime 执行器（独立 LLM 调用 + 结构化校验）；
        其余动作 → 同步 execute（同一闸机/undo/持久化语义）。
        返回成功执行的条数。
        """
        applied = 0
        sync_actions: List[Dict[str, Any]] = []
        for act in actions or []:
            if self._is_async_action(act):
                result = await self._dispatch_async_action(act)
                if result is not None and result.success:
                    applied += 1
                    detail = str((result.data or {}).get("detail") or "")
                    if detail:
                        self.action_log.append(detail)
            else:
                sync_actions.append(act)
        if sync_actions:
            applied += self.execute(sync_actions, accumulate=accumulate)
        if applied > 0:
            self.svc.save_debounced()
        return applied

    async def _dispatch_async_action(self, action: Dict[str, Any]):
        """按动作名构造执行器实例并执行；未注册/参数不合返回 None。"""
        from src.video_agent.skill_runtime.executors import build_executor_tool

        tool = build_executor_tool(str(action.get("action") or ""))
        if tool is None:
            return None
        payload = {k: v for k, v in action.items() if k not in ("action", "type")}
        try:
            params = tool.get_input_schema()(**payload)
        except Exception:
            logger.warning(f"[SkillExec] 执行器参数构造失败: {action.get('action')} {payload}")
            return None
        return await tool.aexecute(params)

    @staticmethod
    def _is_mutating(action: Dict[str, Any]) -> bool:
        """判断操作是否可能变更状态（流程信号类操作不入 undo 栈）"""
        name = str(action.get("action") or action.get("type") or "").strip()
        return name not in ("", "select_draft", "request_confirmation", "continue", "insert_chat_media")

    def _describe_action(self, action: Dict[str, Any]) -> str:
        """生成操作的中文简述（委托 web.action_descriptions）"""
        return describe_action(action, find_draft=self._find_draft)

    # ---------- 提示词结构闸机 ----------

    @staticmethod
    def _kind_of_group(group: Optional[Dict[str, Any]]) -> str:
        """按分组 ID 前缀推断类别：keyElement | shot | audio | ''"""
        gid = str((group or {}).get("id") or "")
        if gid.startswith("ke-"):
            return "keyElement"
        if gid.startswith("shot-"):
            return "shot"
        if gid.startswith("audio-"):
            return "audio"
        return ""

    @staticmethod
    def _sync_shot_duration(group: Dict[str, Any], draft: Dict[str, Any], patch: Optional[Dict] = None) -> bool:
        """时长参数同步：委托领域层唯一实现（与 FC 轨同规则）"""
        return ops.sync_shot_duration(group, draft, patch)

    def _gate_check(self, prompt: str, kind: str) -> bool:
        """写入前闸机。返回 True = 放行。闸机未启用 / 模式非 strict 时恒放行；
        strict 拦截的写入返回 False，模型下一轮看到状态缺失后自行补写（自愈）。"""
        if not self.gate_enabled or kind not in ("shot", "keyElement") or not str(prompt or "").strip():
            return True
        mode = prompt_gates.gate_mode()
        if mode == "off":
            return True
        # 流程时序硬闸（strict）：元素图像未就绪严禁写分镜提示词（Skill 分批确认前置）
        if kind == "shot" and mode == "strict" and prompt_gates.element_images_missing(self.state):
            logger.info("[PromptGate] 拦截分镜提示词写入（元素图像未就绪）")
            self._reject(prompt_gates.SHOT_SEQUENCE_GATE_ERROR)
            return False
        ok, hard, soft = prompt_gates.validate_prompt_write(
            str(prompt), kind, self.state, rules=self.gate_rules,
        )
        for w in soft:
            logger.warning(f"[PromptGate] 软提醒（{kind}）: {w}")
        if ok:
            return True
        if self.gate_override:
            # 决策 D：用户坚持时硬伤降为警告照常放行
            logger.warning(f"[PromptGate] 用户坚持放行（{kind}）: {hard}")
            return True
        if mode != "strict":
            logger.warning(f"[PromptGate] warn 模式放行（{kind}）: {hard}")
            return True
        logger.info(f"[PromptGate] 拦截不合格提示词写入（{kind}）: {hard}")
        self._reject(prompt_gates.format_gate_errors(hard))
        return False

    def _spec_gate_ok(self) -> bool:
        """规格前置警告（S1：只对显式声明 flow.spec_gate 的 Skill 生效）。

        声明了但规格文档未写入：不硬拦（用户指令优先），只追加
        「建议补写规格」警告随 gate_warnings 回喂；未声明的 Skill 完全静默。
        """
        if not self.gate_enabled or prompt_gates.gate_mode() != "strict":
            return True
        if prompt_gates.has_spec_document(self.state):
            return True
        skill_name = getattr(self, "skill_name", "") or ""
        declared = False
        if skill_name:
            try:
                from src.video_agent.skill_runtime.registry import skill_flow_enabled

                declared = skill_flow_enabled(skill_name, "spec_gate")
            except Exception:
                declared = False
        if not declared:
            return True
        logger.info("[FlowGate] 规格文档未写入（Skill 声明 spec_gate，追加建议补写警告）")
        self._reject(prompt_gates.SPEC_GATE_ERROR)
        return True

    def _record_presented(self, draft_id: str) -> None:
        """记录本轮写入过提示词的草稿：用户下一条消息到达时晋升为「已确认」（确认闭环）"""
        if not draft_id or not self.gate_enabled:
            return
        interaction = self.state.setdefault("interaction", {})
        presented = interaction.setdefault("drafts_presented", [])
        if draft_id not in presented:
            presented.append(draft_id)

    def _gen_confirm_gate(self, pairs: List[tuple]) -> List[tuple]:
        """生成确认闸：Skill 激活且 strict 时，只允许对已经用户确认（tag=已确认）的
        草稿触发生成；全部未确认时返回空列表（调用方拒绝执行），未确认项跳过。"""
        if not self.gate_enabled or prompt_gates.gate_mode() != "strict":
            return pairs
        confirmed = [(g, d) for g, d in pairs if str(d.get("tag") or "").strip() == "已确认"]
        skipped = len(pairs) - len(confirmed)
        if skipped:
            logger.info(f"[GenGate] 跳过 {skipped} 个未经用户确认的草稿（生成需先确认 Prompt Draft）")
        if not confirmed:
            logger.info("[GenGate] 拦截生成：目标草稿 Prompt Draft 均未经用户确认")
        return confirmed

    async def execute_locked(self, actions: List[Dict[str, Any]], accumulate: bool = False) -> int:
        """持 svc.lock 执行（与 FC Tool 路径的并发契约对齐）。

        调用方已持有 svc.lock 时（如 chat_service mock 路径）必须改用同步 execute()，
        asyncio.Lock 不可重入，嵌套获取会死锁。
        """
        async with self.svc.lock:
            return self.execute(actions, accumulate=accumulate)

    async def execute_async_locked(
        self, actions: List[Dict[str, Any]], accumulate: bool = False,
    ) -> int:
        """持 svc.lock 执行异步执行器动作（对齐 execute_locked 并发契约）。"""
        async with self.svc.lock:
            return await self.execute_async(actions, accumulate=accumulate)

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
        if name in ("generate_video", "batch_generate_video", "gen_video"):
            return self._apply_generate_video(action)
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
        group, draft = result
        # 闸机：strict 模式拒绝结构不合格的提示词写入（不含提示词的其它字段 patch 不受影响）
        if "prompt" in patch:
            # 故事板待确认窗口（步骤3→步骤4 分界）：用户确认结构前严禁写提示词
            if self.gate_enabled and prompt_gates.gate_mode() == "strict" \
                    and prompt_gates.storyboard_pending(self.state):
                logger.info("[FlowGate] 拦截提示词写入（故事板待用户确认）")
                self._reject(prompt_gates.STORYBOARD_PENDING_GATE_ERROR)
                return False
            if not self._gate_check(
                str(patch.get("prompt") or ""), self._kind_of_group(group)
            ):
                return False
        ok = ops.patch_draft(draft, patch)
        if ok and str(patch.get("prompt") or "").strip():
            self._record_presented(draft.get("id", ""))
        # 时长参数同步：写入分镜提示词时把分镜时长补印到草稿时长参数（客观兜底）
        if ok and self._kind_of_group(group) == "shot":
            self._sync_shot_duration(group, draft, patch)
        return ok

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
        if not self._spec_gate_ok():
            return False
        # 首拆只允许关键元素：首次搭建批次内创建 shot/audio 分组直接拒绝
        group_type = str(
            action.get("group_type") or action.get("draft_type")
            or action.get("kind") or action.get("target_type") or ""
        ).strip()
        if (
            getattr(self, "_first_structure_batch", False)
            and group_type
            and ops.category_for_group_type(group_type) != CAT_KEY_ELEMENTS
        ):
            logger.info("[FlowGate] 拦截首次搭建批次的分镜/音频分组创建（应先拆关键元素）")
            self._reject(prompt_gates.KEY_ELEMENT_FIRST_GATE_ERROR)
            return False
        return self._apply_add_group_inner(action)

    def _apply_add_group_inner(self, action: Dict) -> bool:
        ok = self._add_group_core(action)
        if ok:
            kind = prompt_gates.normalize_structure_kind(
                action.get("group_type") or action.get("draft_type")
                or action.get("kind") or action.get("target_type") or ""
            )
            if kind:
                self.structure_kinds_created.add(kind)
        # 结构首次建立 → 即时置位故事板待确认标记（阶段分界，随用户回应清除）
        if ok and self.gate_enabled and prompt_gates.gate_mode() == "strict":
            interaction = self.state.setdefault("interaction", {})
            interaction["storyboard_pending"] = True
        return ok

    def _add_group_core(self, action: Dict) -> bool:
        group_type = (
            action.get("group_type") or action.get("draft_type")
            or action.get("kind") or action.get("target_type") or ""
        ).lower().strip()

        # 映射到 state 中的 key（含中文别名，与 FC 轨同一映射）
        cat_key = ops.category_for_group_type(group_type)

        group_data = action.get("group") or action.get("data") or {}
        # 也允许 patch 字段携带 title/desc
        patch = action.get("patch") or {}
        # 标题兜底链（8888 事故）：title → name → element_id → element_name → group_title
        title = (
            action.get("title") or group_data.get("title") or patch.get("title")
            or action.get("name") or group_data.get("name")
            or action.get("element_id") or action.get("element_name")
            or action.get("group_title") or "Agent 新建分组"
        )
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
            rough = pick("roughDesc")
            new_group["roughDesc"] = rough
            if not desc and rough:
                desc = rough  # 只写 roughDesc 不写 desc 时自动同步，前端卡片不显示空白
            new_group["desc"] = desc
            # 全局设置：分镜默认时长（Agent 自拆按 max_shot_duration 控制）
            new_group["duration"] = pick("duration", f"{settings.max_shot_duration}s")
            new_group["timeRange"] = pick("timeRange")
            new_group["shotType"] = pick("shotType")
            refs = action.get("sceneRefs") or group_data.get("sceneRefs") or []
            new_group["sceneRefs"] = refs if isinstance(refs, list) else [refs]
        badge = pick("badgeLabel")
        if badge:
            new_group["badgeLabel"] = badge

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

    def _append_draft_to_group(self, group: Dict, draft_data: Dict) -> Optional[Dict]:
        """向指定 group 添加一个 draft，返回新建的 draft；闸机拒绝其提示词时不添加（返回 None）。

        结构纯净闸（步骤3）：Skill 激活且 strict 时，内联草稿的详细提示词
        （> STRUCTURE_INLINE_PROMPT_MAX 字）被剥离后照常建卡，详细提示词留到步骤4。"""
        data = draft_data
        if self.structure_phase and self.gate_enabled and prompt_gates.gate_mode() == "strict":
            inline_prompt = str(data.get("prompt") or "").strip()
            if len(inline_prompt) > prompt_gates.STRUCTURE_INLINE_PROMPT_MAX:
                data = {**data, "prompt": ""}
                self.prompts_stripped += 1
                logger.info(
                    f"[FlowGate] 剥离 add_draft 内联详细提示词（{len(inline_prompt)} 字，"
                    "结构阶段只建骨架）"
                )
        if not self._gate_check(str(data.get("prompt") or ""), self._kind_of_group(group)):
            return None
        draft = ops.append_draft(group, data)
        # 规格偏好补印：草稿未自带供应商时按规格文档设定填充，
        # 防前端默认首选供应商回填污染（参数栏与规格设定不一致）
        cat = ops.category_for_group_type(self._kind_of_group(group))
        if stamp_draft_spec_preference(self.state, draft, cat):
            logger.info(
                f"[StudioActions] 新建草稿按规格偏好补印供应商: "
                f"{draft.get('providerId')}/{draft.get('model') or ''}"
            )
        if str(data.get("prompt") or "").strip():
            self._record_presented(draft.get("id", ""))
        return draft

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
        if not self._spec_gate_ok():
            return False
        group_id = action.get("group_id") or "current"
        group_type = action.get("group_type") or action.get("draft_type") or action.get("kind") or ""
        # 首拆只允许关键元素：首次搭建批次内新建 shot/audio 草稿直接拒绝
        if (
            getattr(self, "_first_structure_batch", False)
            and str(group_type).strip()
            and ops.category_for_group_type(str(group_type)) != CAT_KEY_ELEMENTS
        ):
            logger.info("[FlowGate] 拦截首次搭建批次的分镜/音频草稿创建（应先拆关键元素）")
            self._reject(prompt_gates.KEY_ELEMENT_FIRST_GATE_ERROR)
            return False
        draft_data = action.get("draft") or {}
        if not draft_data and action.get("patch"):
            # 898 事故回归：模型把建卡字段放进 patch/fields 而非 draft 时
            # 不得静默落成空默认草稿，提示词必须写入
            draft_data = action.get("patch") or {}

        label = str(draft_data.get("label") or "").strip()
        group = None
        if str(group_id) in ("", "current") and label:
            # 未指定有效分组时按 label 名称智能匹配（proj-1786169643 事故），
            # 优先于「current → 第一个分组」的旧兜底
            group = self._match_group_by_label(label)
        if group is None:
            group = self._find_group(group_id, group_type)
        if group is None and label:
            group = self._match_group_by_label(label)
        if not group:
            for cat_key in ALL_CATEGORIES:
                groups = self.state.get(cat_key, [])
                if groups:
                    group = groups[0]
                    break
        # 如果仍然找不到分组，自动创建一个
        if not group:
            auto_action = {**action, "group_type": group_type, "title": draft_data.get("label", "Agent 新建分组")}
            self._apply_add_group_inner(auto_action)
            # 取刚创建的分组（与 _apply_add_group 同一类别映射）
            cat_key = ops.category_for_group_type(group_type)
            groups = self.state.get(cat_key, [])
            if groups:
                group = groups[-1]  # 刚添加的在末尾
            if not group:
                return False

        appended = self._append_draft_to_group(group, draft_data)
        if appended is not None:
            kind = prompt_gates.normalize_structure_kind(group_type) or self._kind_of_group(group)
            if kind:
                self.structure_kinds_created.add(kind)
            if kind == "shot":
                self._sync_shot_duration(group, appended)
        return appended is not None

    def _match_group_by_label(self, label: str) -> Optional[Dict[str, Any]]:
        """按草稿 label 名称模糊匹配目标分组（proj-1786169643 事故：
        add_draft 未携带有效 group_id 时盲捡第一个分组，导致提示词全进程心组）。

        取 label 第一段（按 - / — 切分，如「艾AA - 角色概念图」→「艾AA」），
        与分组标题（剥 [Element_X] 前缀后）双向包含匹配。
        """
        key = re.split(r"[-—–]", label or "")[0].strip()
        if not key or len(key) < 2:
            return None
        for cat_key in ALL_CATEGORIES:
            for g in self.state.get(cat_key, []):
                title = str(g.get("title") or "")
                core = re.sub(r"\[[^\]]*\]", "", title).strip()
                if key in title or key in core or (core and core in key):
                    return g
        return None

    def _apply_write_document(self, action: Dict[str, Any]) -> bool:
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
        # 聊天框出图开关：关 = Agent 在对话中不主动触发生图
        if not settings.chat_image_enabled:
            self._reject(
                "聊天框出图已在全局设置中关闭，如需生图请先在顶栏「全局设置」开启「聊天框出图」。"
            )
            return False
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

        # 生成确认闸（混合形态硬边界）：未经用户确认的 Prompt Draft 不得生成
        pairs = self._gen_confirm_gate(pairs)
        if not pairs:
            return False

        # 规格文档偏好（用户意志落盘）：LLM 未指定供应商时优先于草稿自动回填的默认值，
        # 防前端默认首选供应商（如 Grsai）覆盖规格中设定的生图渠道
        spec_pid, spec_model = ("", "")
        if not provider_id:
            spec_pid, spec_model = spec_media_preference(self.state)

        submitted = 0
        for group, draft in pairs:
            prompt = (draft.get("prompt") or "").strip()
            if not prompt:
                continue
            refs = self._resolve_scene_refs(group) if group else []
            # provider 回退链：LLM 指定 → 规格文档偏好 → 目标草稿自身（预览框已选参数）→ 中间面板选中草稿 → 全局设置
            eff_provider = provider_id or spec_pid or (draft.get("providerId") or "") or sel_provider or settings.default_image_provider_id
            # model 回退链：LLM 指定 → 规格偏好（仅当供应商来自规格）→ 目标草稿自身 → 全局设置（仅当供应商一致）→ 供应商默认模型（generation 层兖底）
            eff_model = model or (spec_model if eff_provider == spec_pid else "") or (draft.get("model") or "") or (settings.default_image_model if eff_provider == settings.default_image_provider_id else "")
            # 比例回退链：LLM 指定 → 目标草稿自身 → 中间面板选中草稿 → 16:9
            eff_ratio = act_ratio or (draft.get("aspectRatio") or "") or sel_ratio or "16:9"
            # 分辨率回退链：LLM 指定 → 目标草稿自身 → 中间面板选中草稿 → 全局设置 → 1K
            eff_resolution = act_resolution or (draft.get("imageResolution") or "") or sel_resolution or settings.default_image_resolution or "1K"
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

    # ---------- 分镜视频生成（仅用户明确触发） ----------

    def _apply_generate_video(self, action: Dict) -> bool:
        """Agent 触发分镜视频生成（仅当用户明确要求时）。支持批量。

        参考素材自动挂接（对齐 Skill 步骤6）：
        - sceneRefs 引用的关键元素概念图 → 多参考图（MultiModalToVideo）；
        - 草稿 refAssets/audioUrl 中的音色参考音频 → reference_audio；
        - 提示词 @引用 → 位置标记重写 + 对应素材随请求发送。
        供应商/模型/分辨率回退链与生图一致（LLM 指定 → 草稿自身参数）。
        """
        from src.video_agent.web.generation import collect_shot_video_refs

        target = str(action.get("target") or action.get("draft_id") or "all").strip()
        draft_type = str(action.get("draft_type") or "shot").strip().lower()
        provider_id = resolve_provider_ref(
            str(action.get("provider_id") or action.get("provider") or "")
        )
        model = action.get("model") or ""
        act_resolution = str(action.get("resolution") or "").strip().lower()
        try:
            act_duration = int(action.get("duration") or 0)
        except (TypeError, ValueError):
            act_duration = 0

        if target in ("all_shots", "all_shot"):
            draft_type = "shot"
            target = "all"

        pairs = self._collect_drafts(target, draft_type)
        if not pairs:
            return False

        # 生成确认闸（混合形态硬边界）：未经用户确认的 Prompt Draft 不得生成
        pairs = self._gen_confirm_gate(pairs)
        if not pairs:
            return False

        submitted = 0
        for group, draft in pairs:
            prompt = (draft.get("prompt") or "").strip()
            if not prompt:
                continue
            # 参数回退链：LLM 指定 → 目标草稿自身参数 → 全局设置默认
            eff_provider = provider_id or (draft.get("providerId") or "") or settings.default_video_provider_id
            eff_model = model or (draft.get("model") or "") or (settings.default_video_model if eff_provider == settings.default_video_provider_id else "")
            eff_ratio = (draft.get("aspectRatio") or "16:9")
            eff_resolution = act_resolution or (draft.get("resolution") or "") or settings.default_video_resolution or "720p"
            dur_raw = str(draft.get("duration") or "").strip().lower()
            try:
                eff_duration = act_duration or int(re.sub(r"[^0-9]", "", dur_raw) or settings.max_shot_duration)
            except ValueError:
                eff_duration = settings.max_shot_duration
            eff_duration = max(1, min(eff_duration, 15))  # 模型单镜头上限 15s

            # 参数回写草稿：预览框参数区同步跳转
            if eff_provider:
                draft["providerId"] = eff_provider
            if eff_model:
                draft["model"] = eff_model

            image_refs, audio_refs = collect_shot_video_refs(self.state, group, draft)
            submit_video_task(
                self.state, draft, "shot", eff_provider, eff_model,
                duration=eff_duration, resolution=eff_resolution, aspect_ratio=eff_ratio,
                image_refs=image_refs, audio_refs=audio_refs,
                source="agent", on_failure_save=self.svc.save_debounced,
            )
            submitted += 1
        if submitted:
            logger.info(f"[StudioActions] generate_video: 已提交 {submitted} 个视频生成任务")
        return submitted > 0

    def _submit_image_task(self, draft: Dict, provider_id: str, model: str, refs: List[Dict], aspect_ratio: str = "16:9", resolution: str = "1K") -> None:
        """提交异步生图任务（委托 generation 层的 submit_image_task，批次5 下沉）"""
        submit_image_task(
            self.state, draft, provider_id, model, refs,
            aspect_ratio=aspect_ratio, resolution=resolution,
            on_failure_save=self.svc.save_debounced,
        )
