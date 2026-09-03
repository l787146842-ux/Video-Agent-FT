"""暂停态消费域：暂停回应结构化回携/轮次计账/轮始自愈/等待确认三态消费。

从 chat_consume.py 按关注点切分后的本体（2026-09-03 拆分批）：
会话 compaction 域已切出至 web/history_compact.py（两个关注点调用图
零交）；规格向导消费管线已随用户裁决 2026-08-31 退役删除。
"""
from typing import Any, Dict, Optional

from loguru import logger

from src.video_agent.core import prompt_gates
from src.video_agent.core import workflow_runtime
from src.video_agent.core.tracer import AgentTracer
from src.video_agent.state.models import ALL_CATEGORIES_TUPLE


def consume_pause_response(svc, pause_response) -> Optional[Dict[str, str]]:
    """消费暂停回应结构化回携（对标 AskUserQuestion 范式，三态消费；
    决策史见 git tag adr-archive-20260901）。

    用户点选暂停卡选项时请求携带 {"pause_id", "value", "label"[, "decision"]}；
    与 interaction.active_pause 登记匹配即清除登记并返回持久化标记
    {"pause_id", "value", "label", "decision"}（decision 缺省 accept，
    卡片拒绝/取消选项为 decline）；不匹配（旧卡/自由打字）返回 None。
    决策经 reduce_interaction 落盘并进控制流 trace。
    LLM 语义不变：消息正文仍照常入 history，本函数只产出展示层标记。
    调用方需持有 svc.lock。
    """
    pid = str((pause_response or {}).get("pause_id") or "").strip()
    if not pid:
        return None
    interaction = svc.state_dict.get("interaction") or {}
    active = interaction.get("active_pause") or {}
    if str(active.get("pause_id") or "") != pid:
        return None
    decision = (
        "decline"
        if str((pause_response or {}).get("decision") or "").strip() == "decline"
        else "accept"
    )
    workflow_runtime.reduce_interaction(
        svc, set_flags={"last_pause_decision": decision},
        pop_flags=("active_pause",), flush=True)
    # review decision 解析（审阅卡确认即解除 review_spec 挂起）
    try:
        _used = svc.state_dict.get("usedSkills") or []
        _sk = str(_used[-1] or "") if _used else ""
        _tok = str(((svc.state_dict.get("workflow_run") or {})
                    .get("pending_decision") or {}).get("token") or "")
        if _sk and _tok.startswith("review:"):
            workflow_runtime.WorkflowRuntime(svc, _sk).resolve_decision(
                _tok, str((pause_response or {}).get("value") or "confirm"))
    except Exception as _e:
        logger.debug("[WorkflowRuntime] review decision 解析跳过: {}", _e)
    try:
        AgentTracer.get_instance().record_control_flow(
            "pause_consumed",
            f"暂停卡结构化回应消费：decision={decision} pause_id={pid}")
    except Exception as _e:
        logger.debug("[ConfirmFlow] 控制流留痕跳过: {}", _e)
    return {
        "pause_id": pid,
        "value": str((pause_response or {}).get("value") or ""),
        "label": str((pause_response or {}).get("label") or ""),
        "decision": decision,
    }


def advance_turn_seq(svc) -> int:
    """轮次序号递增（批 C：轮始计账）。

    turn_seq 是项目态的轮次计数（顶层键，不走 update 免入 undo 栈），
    供暂停卡戳发行轮次与轮始自愈对账计算卡龄。
    调用方需持有 svc.lock。"""
    seq = int(svc.state_dict.get("turn_seq") or 0) + 1
    svc.state_dict["turn_seq"] = seq
    svc.save_debounced()
    return seq


# 自愈退役阈值：暂停卡发行后超过该轮次仍未被消费即视为失效残留。
# 轮始递增后口径：发行轮 N 的卡在 N+3 轮轮始被退役（中间两轮容错）。
PAUSE_STALE_AFTER_TURNS = 3


def reconcile_stale_active_pause(
    svc, pause_response: Optional[Dict[str, Any]] = None,
) -> bool:
    """轮始自愈对账（批 C）：退役过期残留的 active_pause。

    失效探针（成立任一即退役）：
    - 无发行轮次戳（存量死态，如 666 残留）；
    - 卡龄（当前 turn_seq - issued_turn_seq）≥ PAUSE_STALE_AFTER_TURNS。
    本轮请求正是在回应该卡（pause_id 匹配）时不自愈，让正常消费链处理。
    退役 = reduce_interaction pop active_pause + 控制流 trace 留痕。
    调用方需持有 svc.lock；返回是否发生了退役。"""
    interaction = svc.state_dict.get("interaction") or {}
    active = interaction.get("active_pause")
    if not isinstance(active, dict):
        return False
    pid = str(active.get("pause_id") or "").strip()
    if not pid:
        return False
    _pr_pid = str((pause_response or {}).get("pause_id") or "").strip()
    if _pr_pid and _pr_pid == pid:
        return False
    turn_seq = int(svc.state_dict.get("turn_seq") or 0)
    issued = active.get("issued_turn_seq")
    if issued is None:
        reason = "缺发行轮次戳（存量残留）"
    else:
        age = turn_seq - int(issued)
        if age < PAUSE_STALE_AFTER_TURNS:
            return False
        reason = f"发行后 {age} 轮未消费（阈值 {PAUSE_STALE_AFTER_TURNS}）"
    workflow_runtime.reduce_interaction(
        svc, pop_flags=("active_pause",), flush=True)
    try:
        AgentTracer.get_instance().record_control_flow(
            "pause_self_heal",
            f"自愈退役：active_pause 过期残留（pause_id={pid}）—{reason}")
    except Exception as _e:
        logger.debug("[PauseSelfHeal] trace 留痕失败（不影响退役）: {}", _e)
    logger.info(f"[PauseSelfHeal] 退役过期暂停卡 pause_id={pid}，{reason}")
    return True


def _consume_pending_confirmation(
    svc, user_text: str = "", pause_value: str = "",
    pause_response: Optional[Dict[str, Any]] = None,
) -> str:
    """消费「等待确认」暂停态：用户的新消息即是对先前轮次暂停的回应。

    三态消费（问即停）：accept = 点选选项（结构化回携）；
    decline = 卡片拒绝/取消选项；cancel-supersede = 自由打字新指令取代
    悬挂暂停（用户消息文本即回应）。三种回应全部经 reduce_interaction 落盘
    last_pause_decision 并进控制流 trace；supersede 同步清除 active_pause。

    暂停态只写不清会让模型永远停在上一阶段；只清不带则模型看不到
    「用户已确认」的信号，两者都会导致从头重复同一套操作（读同一文档→
    写同一文档→再次请求确认）。此处同时完成：清除状态 + 把暂停说明
    以系统提示形式附在本轮用户消息后，返回附加提示（无暂停时返回空串）。
    调用方需持有 svc.lock。
    """
    interaction = svc.state_dict.get("interaction") or {}
    # 三态分类：结构化回携在场且匹配（或未登记时宽容受理）= accept/decline；
    # 否则有悬挂暂停且带新文本 = cancel-supersede（新指令取代暂停）
    _pr = pause_response or {}
    _pr_pid = str(_pr.get("pause_id") or "").strip()
    _active = interaction.get("active_pause") or {}
    _active_pid = str(_active.get("pause_id") or "")
    _decision = ""
    if _pr_pid and (not _active_pid or _pr_pid == _active_pid):
        _decision = (
            "decline"
            if str(_pr.get("decision") or "").strip() == "decline" else "accept"
        )
    elif (interaction.get("awaiting_confirmation") or _active_pid) \
            and str(user_text or "").strip():
        _decision = "cancel-supersede"
    if _decision:
        # supersede：悬挂暂停被新指令取代，同步清除 active_pause；
        # accept/decline 的登记清除归 consume_pause_response（持久化标记同源）
        _pop = ("active_pause",) if (
            _decision == "cancel-supersede" and _active_pid) else ()
        workflow_runtime.reduce_interaction(
            svc, set_flags={"last_pause_decision": _decision},
            pop_flags=_pop, flush=True)
        try:
            AgentTracer.get_instance().record_control_flow(
                "pause_consumed",
                f"暂停态随新消息消费：decision={_decision}"
                + (f" pause_id={_active_pid}" if _active_pid else ""))
        except Exception as _e:
            logger.debug("[ConfirmFlow] 控制流留痕跳过: {}", _e)
    # 暂停语义标记（summary/spec 等）随回应消费清除，避免残留影响后续轮次
    # （规格收集向导已随用户裁决 2026-08-31 退役，collect 标记无发行/消费方）
    workflow_runtime.reduce_interaction(svc, pop_flags=("pending_pause_kind",))
    # 故事板待确认窗口（步骤3→步骤4 分界）：不依赖 awaiting_confirmation，
    # 用户任何新消息到达即视为已审阅故事板，解除提示词写入封锁
    if interaction.get("storyboard_pending"):
        workflow_runtime.reduce_interaction(
            svc, set_flags={"storyboard_pending": False}, flush=True)
    # 确认闭环：先前轮次展示过提示词草案（drafts_presented）且用户新消息到达，
    # 将未被重写过的草稿晋升为「已确认」（生成闸的前置条件）；
    # 期间被重写的草稿 tag 已在写入时重置，不会被误晋升
    presented = [d for d in (interaction.get("drafts_presented") or []) if d]
    if presented:
        promoted = 0
        presented_set = set(presented)
        for cat in ALL_CATEGORIES_TUPLE:
            for group in svc.state_dict.get(cat, []) or []:
                for draft in group.get("drafts", []) or []:
                    tag = str(draft.get("tag") or "").strip()
                    if draft.get("id") in presented_set and tag in ("", "Agent", "草稿", "推荐"):
                        draft["tag"] = "已确认"
                        promoted += 1
        workflow_runtime.reduce_drafts_presented(svc, clear=True, flush=True)
        if promoted:
            logger.info(f"[ConfirmFlow] 用户回应到达：{promoted} 个已展示的 Prompt Draft 晋升为「已确认」")
    # 晋升兜底：处于暂停态但 presented 记录缺失（记录链路异常或
    # 草稿经未记录路径写入）时，用户对暂停的回应即视为对当前带提示词草稿的确认，
    # 否则 tag 永远停在 Agent，生成闸反复拦截造成「确认了也出不了图」
    if not presented and interaction.get("awaiting_confirmation"):
        fallback_promoted = 0
        for cat in ALL_CATEGORIES_TUPLE:
            for group in svc.state_dict.get(cat, []) or []:
                for draft in group.get("drafts", []) or []:
                    tag = str(draft.get("tag") or "").strip()
                    if (draft.get("prompt") or "").strip() and tag in ("", "Agent", "草稿", "推荐"):
                        draft["tag"] = "已确认"
                        fallback_promoted += 1
        if fallback_promoted:
            svc.save()
            logger.info(f"[ConfirmFlow] presented 缺失兜底：{fallback_promoted} 个带提示词草稿晋升为「已确认」")
    if not interaction.get("awaiting_confirmation"):
        return ""
    paused_msg = str(interaction.get("confirmation_message") or "")[:300]
    workflow_runtime.reduce_interaction(svc, set_flags={
        "awaiting_confirmation": False, "confirmation_message": "",}, flush=True)
    # 提示按客观状态机械生成（去 prose 越权）：
    # 规格已存在就如实告知，绝不固定发「先写入规格文档」指令；
    # 暂停点归 Skill 阶段边界，平台不 prose 指定
    spec_note = (
        "规格文档已写入，不必重写；"
        if prompt_gates.has_spec_document(svc.state_dict) else ""
    )
    # 三通道分离 C：用户点选系统派生继续选项时，
    # 下一步指令机械生成（frontmatter 声明流程唯一源），模型不再自行猜测；
    # 向导多组拼装 value 为逐行文本，走行格式判定
    flow_note = ""
    if prompt_gates.is_flow_continue_value(pause_value):
        _used = svc.state_dict.get("usedSkills") or []
        _skill = str(_used[-1] or "") if _used else ""
        flow_note = prompt_gates.flow_continue_note(svc.state_dict, _skill)
    # decline（卡片拒绝/取消选项）：告知模型原方案作废，按新消息处置；
    # accept/cancel-supersede 维持既有客观提示口径（测试钉死关键字样不变）
    if _decision == "decline":
        return (
            "\n\n（系统提示：先前轮次通过 workflow_pause 发起的暂停已被用户拒绝/取消"
            f"（暂停内容：{paused_msg}）。该暂停对应的方案不再生效；"
            "请按用户本条消息的内容处置，不要继续当时等待确认的流程。）"
        )
    return (
        "\n\n（系统提示：先前轮次已通过 workflow_pause 暂停等待确认，"
        f"暂停内容：{paused_msg}。本条消息即对该暂停的回应：表示确认时，按当前 Skill 流程"
        f"把当前阶段产出物做完；{spec_note}{flow_note}暂停点以 Skill 阶段边界为准；"
        "已完成的步骤（已读文档/已写规格）不必重复；"
        "提出修改意见时按新要求执行，完成后重新请求确认。）"
    )
