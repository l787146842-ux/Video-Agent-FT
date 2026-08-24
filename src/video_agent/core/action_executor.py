"""
Studio 状态操作执行器 — 从 actions.py 抽离；D-01 清偿下沉 core（定义源）。

职责：执行结构化动作 dict 列表，操作 StateManager 共享状态并自动持久化。
动作来源 = FC 工具调用 / mock 结构化动作（动作通道唯一 = FC，ADR-0001；
文本块解析已随文本轨退役删除，任务#27）。

对 web 层（生成管线/供应商配置）的依赖经 core/ports.py 端口倒置，
web 层装配点注入实现（分层铁律：core 不 import web）；
web 层 re-export 壳已清退，消费方均直接导入本模块（任务#13 F-4）。

动作域拆分（任务 24 P7-3）：本文件为承重门面（分派入口 + 闸机判定 +
批次状态），域实现体切出三件——生成域 core/action_gen.py（先例）、
草稿/分组域 core/action_drafts.py、文档/媒体域 core/action_media.py；
实例方法壳保留（测试 patch 目标不变）。
"""
import time
from typing import Any, Dict, List, Optional

from loguru import logger

from src.video_agent.core import guard_pipeline, prompt_gates
from src.video_agent.core.ports import generation_port
from src.video_agent.state import storyboard_ops as ops
from src.video_agent.state.manager import StateManager
# 生成动作域切入 core/action_gen.py（实例方法壳保留，patch 目标不变）
from src.video_agent.core.action_gen import apply_generate_image, apply_generate_video
# 草稿/分组域与文档/媒体域实现体（任务 24 P7-3 切出；实例方法壳保留）
from src.video_agent.core.action_drafts import (
    add_group_core,
    append_draft_to_group,
    apply_add_draft,
    apply_add_group,
    apply_add_group_inner,
    apply_delete_draft,
    apply_delete_group,
    apply_draft_patch,
    apply_flow_directive,
    apply_group_patch,
    match_group_by_label,
    stamp_spec_resolution,
)
from src.video_agent.core.action_media import (
    apply_bind_asset,
    apply_clear_media,
    apply_insert_chat_media,
    apply_write_document,
)
from src.video_agent.core.action_descriptions import describe_action


class StateOperationExecutor:
    """
    执行结构化动作 dict 列表（FC 轨工具 / mock 结构化动作直达，不经文本解析）。
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
        # 闸机规则（Skill 激活时注入 parse_gate_rules 结果；
        # None = 用平台默认规则，保证无 Skill 场景不炸）
        # （原 skill_runtime executors 注入通道已随任务#36 B5 执行器退役删除）
        self.gate_rules: Optional[Dict[str, Any]] = None
        # 决策 D：用户坚持（user_override）时硬伤降为警告照常放行
        self.gate_override: bool = False
        # 本批次闸机警告（eval 回归读取核验闸机判定；每次 execute 重置）
        self.gate_warnings: List[str] = []
        # 当前激活的 Skill 名称（执行器/agent_loop 注入；：平台行为按 Skill 声明驱动）
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
        # 成功动作的逐动作实测耗时（ms），与 action_log 下标对齐；
        # agent_loop 用其替换时间线均摊耗时（文本轨此前均摊是白谎）
        self.last_action_durations: List[float] = []
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
        # 4-4 双轨退役：流式「边写边填」计数器（stream_preapplied/stream_consumed）
        # 与累加批次状态已删（流式预执行为文本轨基础设施）

    def _reject(self, reason: str) -> None:
        """记录一条闸机拦截原因（去重）"""
        if reason and reason not in self.gate_rejections:
            self.gate_rejections.append(reason)
        if reason and reason not in self.gate_warnings:
            self.gate_warnings.append(reason)

    @property
    def state(self) -> Dict[str, Any]:
        return self.svc.state_dict

    def execute(self, actions: List[Dict[str, Any]]) -> int:
        """执行操作列表，返回成功执行的数量。执行后自动持久化。

        Agent 主路径统一在此 push_undo，使 Agent 改动与手动 update 一样可撤销；
        纯信号操作（select/确认/continue）或全部失败时不污染 undo 栈。
        """
        mutating = [a for a in actions if self._is_mutating(a)]
        if mutating:
            self.svc.push_undo()
        self.gate_rejections = []  # 每批次重置拦截原因记录
        self.gate_warnings = []
        self.last_action_durations = []  # 每批次重置逐动作耗时
        self.structure_kinds_created = set()
        self.prompts_stripped = 0
        # 批前故事板是否为空快照（轮末阶段审阅卡只在「本批把空板推进到阶段完成」时注入）
        self._storyboard_empty_before = prompt_gates.storyboard_is_empty(self.state)
        applied = 0
        for action in actions:
            try:
                _t0 = time.monotonic()
                if self._apply(action):
                    applied += 1
                    self.action_log.append(self._describe_action(action))
                    self.last_action_durations.append((time.monotonic() - _t0) * 1000)
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

    # 文本动作轨的异步执行器动作（execute_async/_dispatch_async_action/
    # _ASYNC_EXECUTOR_ACTIONS）已随任务#36 B5 执行器一步退役删除：
    # 管线阶段改由通用主路径直走平台工具，无外部调用方。

    @staticmethod
    def _is_mutating(action: Dict[str, Any]) -> bool:
        """判断操作是否可能变更状态（流程信号类操作不入 undo 栈）"""
        name = str(action.get("action") or action.get("type") or "").strip()
        return name not in ("", "select_draft", "continue", "insert_chat_media")

    def _describe_action(self, action: Dict[str, Any]) -> str:
        """生成操作的中文简述（委托 core.action_descriptions）"""
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

    def _gate_check(self, prompt: str, kind: str, group: Optional[Dict[str, Any]] = None) -> bool:
        """写入前闸机（委托统一闸机管线，宪法 §2.0； 恢复接线，与 FC 轨同源判定）。

        返回 True = 放行。闸机未启用 / 模式非 strict 时恒放行；
        strict 拦截的写入返回 False，模型下一轮看到状态缺失后自行补写（自愈）。"""
        if not self.gate_enabled or kind not in ("shot", "keyElement") or not str(prompt or "").strip():
            return True
        if prompt_gates.gate_mode() == "off":
            return True
        # 元素概念图前置判定（引用感知，与 FC 轨的全量判定各自算好传入统一管线）
        element_missing = (
            kind == "shot"
            and prompt_gates.shot_references_missing_element_images(self.state, group=group)
        )
        outcome = guard_pipeline.evaluate_prompt_write(
            str(prompt), kind, self.state,
            gate_rules=self.gate_rules,
            gate_override=self.gate_override,
            element_image_missing=element_missing,
        )
        self.gate_warnings.extend(outcome.warnings)
        guard_pipeline.audit_verdicts(
            outcome.verdicts,
            skill_name=str(getattr(self, "skill_name", "") or ""),
            overridden=outcome.overridden,
        )
        # 元素概念图前置被用户覆盖：落盘铁律覆盖声明（有规格文档时）
        if outcome.element_image_override_hit:
            try:
                from src.video_agent.core.spec_rules import apply_element_image_override

                apply_element_image_override(self.state)
            except Exception as _e:
                logger.debug("[action_executor] 忽略异常: {}", _e)
        if outcome.ok:
            return True
        logger.info(f"[PromptGate] 拦截不合格提示词写入（{kind}）: {outcome.hard_errors}")
        self._reject(outcome.reject_message)
        return False

    def _record_presented(self, draft_id: str) -> None:
        """记录本轮写入过提示词的草稿：用户下一条消息到达时晋升为「已确认」（确认闭环）"""
        if not draft_id or not self.gate_enabled:
            return
        interaction = self.state.setdefault("interaction", {})
        presented = interaction.setdefault("drafts_presented", [])
        if draft_id not in presented:
            presented.append(draft_id)

    def _gen_confirm_gate(self, pairs: List[tuple]) -> List[tuple]:
        """生成确认闸（文本轨， 双轨收敛一期）：判定唯一实现 =
        guard_pipeline.evaluate_gen_confirm（与 FC 轨逐字节一致）。

        目标草稿存在未确认即整批硬拒（语义：模型跳确认非用户意志；
        override/未激活放行）；不再各自手写「跳过未确认项」镜像判定。"""
        # 一条龙：用户本条消息的显式指令作为本批生成同意（留痕）
        _svc = getattr(self, "svc", None)
        if _svc is not None and prompt_gates.flow_auto_continue(_svc.state_dict):
            logger.info("[FlowDirective] 一条龙指令作为本批生成同意（留痕）")
            return pairs
        drafts = [d for _, d in pairs]
        err, warns = guard_pipeline.evaluate_gen_confirm(
            drafts,
            active=self.gate_enabled and prompt_gates.gate_mode() == "strict",
            override=self.gate_override,
            action="generate(text-track)",
        )
        for w in warns:
            if w not in self.gate_warnings:
                self.gate_warnings.append(w)
        if err:
            logger.info("[GenGate] 拦截生成：目标草稿 Prompt Draft 未全部经用户确认")
            return []
        return pairs

    def _gen_asset_binding_gate(self, pairs: List[tuple]) -> List[tuple]:
        """生成前资产绑定检查（文本轨，任务#12 E-6 禁令下沉）：判定唯一实现 =
        guard_pipeline.evaluate_gen_asset_binding。

        目标分镜的 sceneRefs 引用了无概念图的关键元素即整批硬拒
        （先补图再生成为客观恢复路径）；override/未激活放行。"""
        groups = [
            g for g, d in pairs
            if isinstance(g, dict) and (d.get("prompt") or "").strip()
        ]
        err, warns = guard_pipeline.evaluate_gen_asset_binding(
            self.state, groups,
            active=self.gate_enabled and prompt_gates.gate_mode() == "strict",
            override=self.gate_override,
            action="generate_video(text-track)",
        )
        for w in warns:
            if w not in self.gate_warnings:
                self.gate_warnings.append(w)
        if err:
            logger.info("[AssetGate] 拦截视频生成：目标分镜引用了无概念图的关键元素")
            self._reject(err)
            return []
        return pairs

    async def execute_locked(self, actions: List[Dict[str, Any]]) -> int:
        """持 svc.lock 执行（与 FC Tool 路径的并发契约对齐）。

        调用方已持有 svc.lock 时（如 chat_service mock 路径）必须改用同步 execute，
        asyncio.Lock 不可重入，嵌套获取会死锁。
        """
        async with self.svc.lock:
            return self.execute(actions)

    # （execute_async_locked 已随任务#36 B5 执行器退役删除，异步执行器动作不再存在）

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
        if name == "flow_directive":
            return self._apply_flow_directive(action)
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
        # workflow_pause / continue 是流程信号（暂停经 FC 工具上抛），不算状态变更
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

    # ---------- 草稿/分组域承重壳（实现体 core/action_drafts.py，任务 24 P7-3） ----------

    def _apply_draft_patch(self, action: Dict) -> bool:
        """草稿 patch（含 confirm 复用路径）；定义源 = core/action_drafts.py"""
        return apply_draft_patch(self, action)

    def _stamp_spec_resolution(self, group: Dict[str, Any], draft: Dict[str, Any]) -> None:
        """分辨率补印；定义源 = core/action_drafts.py"""
        stamp_spec_resolution(self, group, draft)

    def _apply_group_patch(self, action: Dict) -> bool:
        """分组 patch；定义源 = core/action_drafts.py"""
        return apply_group_patch(self, action)

    def _apply_delete_draft(self, action: Dict) -> bool:
        """删除草稿；定义源 = core/action_drafts.py"""
        return apply_delete_draft(self, action)

    def _apply_delete_group(self, action: Dict) -> bool:
        """删除分组；定义源 = core/action_drafts.py"""
        return apply_delete_group(self, action)

    def _apply_add_group(self, action: Dict) -> bool:
        """创建故事板分组；定义源 = core/action_drafts.py"""
        return apply_add_group(self, action)

    def _apply_add_group_inner(self, action: Dict) -> bool:
        """创建分组（内部入口，含结构类别登记/待确认标记）；定义源 = core/action_drafts.py"""
        return apply_add_group_inner(self, action)

    def _add_group_core(self, action: Dict) -> bool:
        """创建分组核心组装；定义源 = core/action_drafts.py"""
        return add_group_core(self, action)

    def _append_draft_to_group(self, group: Dict, draft_data: Dict) -> Optional[Dict]:
        """向分组追加草稿（含结构纯净闸/客观补印）；定义源 = core/action_drafts.py"""
        return append_draft_to_group(self, group, draft_data)

    def _apply_add_draft(self, action: Dict) -> bool:
        """新建草稿（分组定位兜底链）；定义源 = core/action_drafts.py"""
        return apply_add_draft(self, action)

    def _match_group_by_label(self, label: str) -> Optional[Dict[str, Any]]:
        """按草稿 label 模糊匹配分组；定义源 = core/action_drafts.py"""
        return match_group_by_label(self, label)

    def _apply_flow_directive(self, action: Dict) -> bool:
        """一条龙指令机械登记；定义源 = core/action_drafts.py"""
        return apply_flow_directive(self, action)

    # ---------- 文档/媒体域承重壳（实现体 core/action_media.py，任务 24 P7-3） ----------

    def _apply_write_document(self, action: Dict[str, Any]) -> bool:
        """写入/更新项目文档工件；定义源 = core/action_media.py"""
        return apply_write_document(self, action)

    def _apply_bind_asset(self, action: Dict) -> bool:
        """素材绑定；定义源 = core/action_media.py"""
        return apply_bind_asset(self, action)

    def _apply_clear_media(self, action: Dict) -> bool:
        """清空卡片媒体；定义源 = core/action_media.py"""
        return apply_clear_media(self, action)

    def _apply_insert_chat_media(self, action: Dict) -> bool:
        """故事板媒体插入对话输入框；定义源 = core/action_media.py"""
        return apply_insert_chat_media(self, action)

    # ---------- 图片生成（仅用户明确触发） ----------

    def _selected_draft_media_config(self) -> tuple:
        """解析中间预览面板选中草稿的 (providerId, aspectRatio, imageResolution)，作为生图缺省配置。"""
        return ops.selected_draft_media_config(self.state, self.selected_draft_id, self.selected_type)

    def _apply_generate_image(self, action: Dict) -> bool:
        """Agent 触发生图（仅当用户明确要求时）；定义源 = core/action_gen.py。"""
        return apply_generate_image(self, action)

    def _collect_drafts(self, target: str, draft_type: str) -> List[tuple]:
        """收集目标 (group, draft) 对；委托领域层唯一实现"""
        return ops.collect_drafts(self.state, target, draft_type)

    def _resolve_scene_refs(self, group: Dict) -> List[Dict[str, str]]:
        """解析分镜的 sceneRefs → 对应关键元素的概念图 URL 作为参考图"""
        return ops.resolve_scene_refs(self.state, group)

    # ---------- 分镜视频生成（仅用户明确触发） ----------

    def _apply_generate_video(self, action: Dict) -> bool:
        """Agent 触发分镜视频生成（仅当用户明确要求时）；定义源 = core/action_gen.py。"""
        return apply_generate_video(self, action)

    def _submit_image_task(self, draft: Dict, provider_id: str, model: str, refs: List[Dict], aspect_ratio: str = "16:9", resolution: str = "1K") -> None:
        """提交异步生图任务（经生成端口委托 generation 层的 submit_image_task）"""
        generation_port().submit_image_task(
            self.state, draft, provider_id, model, refs,
            aspect_ratio=aspect_ratio, resolution=resolution,
            on_failure_save=self.svc.save_debounced,
        )
