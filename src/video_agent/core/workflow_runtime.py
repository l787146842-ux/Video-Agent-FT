# -*- coding: utf-8 -*-
"""Workflow Runtime — 账本 + 裁判数据层。

正向设计（业界基准：Anthropic workflows-vs-agents / Claude Code hooks 公理 /
Codex loop+approval / Temporal 持久化执行与 LangGraph 检查点恢复；
共识：确定性 = 把关模型发起的动作，不是系统代替模型发起动作）：
模型永远是唯一行动主体，运行时做持久状态、产物账本、投影与裁判数据，
不发起任何行动（stage_precondition 越阶硬闸已随 C1b 裁决 2026-08-31 退役）。

职责边界：
- Skill 激活不再编译 ``WorkflowDefinition``（16 节点 DAG 契约已随 2026-09-10
  阶段规则去代码化批退役，``compile_definition`` 恒 None）；账本按平铺节点
  清单（``_FLAT_NODES``）跑客观探针；
- 持久化 ``WorkflowRun``（current_node/completed_nodes/pending_gate/artifacts），
  **仅本模块 reducer 可改**（StateManager 仍唯一写入点，Rule3）；
  interaction 全域经 reducer 族（reduce_interaction / reduce_session_summary /
  reduce_gate_overrides / reduce_drafts_presented）单一写入；
- 完成度只认客观探针（stage_done，fail-closed）；账本产物只服务审计与
  机械停闸（_apply_stage_gate）判据，不接 UI、不判「流程完成」；
- 「不暂停连跑」语义归自主性档位。
"""
import copy
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from src.video_agent.config import settings
from src.video_agent.core import stage_probes as po
from src.video_agent.core import prompt_gates
from src.video_agent.skill_runtime import registry
from src.video_agent.skill_runtime import frontmatter
from src.video_agent.skill_runtime.manifest_schema import split_issue_warnings
from src.video_agent.core.workflow_contract import (
    DEFAULT_V2_REVIEW_NODES,
)
from src.video_agent.core.workflow_events import EventLedger
from src.video_agent.core.turn_commit import (
    TurnCommit, TurnResult, WorkflowCommitError, commit_turn,
)

# per-turn 编译缓存（轮始清理；同轮内 sync_run/排除计算共享）
_COMPILE_CACHE: Dict[str, Optional[Dict[str, Any]]] = {}


def clear_compile_cache() -> None:
    """轮始清理编译缓存（frontmatter 声明轮间可能被编辑，缓存仅限本轮）。"""
    _COMPILE_CACHE.clear()


def canonical_slug(name: str) -> str:
    """canonical 身份归一：小写 + 去空格/连字符/下划线/扩展名。

    「AI短剧一站式生成」与「AI-短剧一站式生成」归一到同一身份，
    模型逐字复制显示名的误差不再造成解析失败。"""
    return registry._norm_name(name).replace("-", "").replace("_", "")


def compile_definition(skill: str) -> Optional[Dict[str, Any]]:
    """DAG 编译函数已随 16 节点 workflow 契约退役，恒返回 None。
    流程调度靠 Skill 散文+模型自觉+6 步清单机械停（2026-09-10 阶段规则
    去代码化批）：平台不再编译节点拓扑/前置关系，账本按平铺节点清单
    （见 ``_FLAT_NODES``）跑客观探针，不判「流程完成」。"""
    return None


# 节点 → 客观探针键映射（账本无自报）：completed_nodes 全量由 stage_done
# 探针重算；turn_commit 的自报 completed_node 降级为非权威提示——下次
# sync 即被本重算覆盖，不再具有账本效力。
# - collect_spec 与 write_spec 同证同源：规格文档在场即证明收集已发生；
# - 媒体阶段挂同键阶段探针；
# - storyboard 三个结构节点用节点级探针（key_elements/shots_groups/
#   audio_groups，运行时内部键，不可声明覆盖）；
# - 审批节点（6 个）的「已评审」客观证据 = 账本 DecisionResolved 事件
#   （resolve_decision 提交），前置产物在场但未落账决议时不予完成
#   （fail-closed：不因文档存在而跳过评审暂停）。
_NODE_PROBE_KEYS = {
    "analyze_script": "analysis",
    "collect_spec": "spec",
    "write_spec": "spec",
    "ke_media": "ke_media",
    "shot_media": "shot_media",
    "audio_assets": "audio_assets",
    "assembly": "assembly",
}
_NODE_STRUCTURE_KEYS = {
    "storyboard_key_elements": "key_elements",
    "storyboard_shots": "shots_groups",
    "storyboard_audio": "audio_groups",
}
# 审批节点 → 前置产物探针键（全齐备才可能进入「待评审」态；
# review_storyboard 审的是分镜+音频层整张蓝图，前置取两设计节点）
_REVIEW_NODE_PREREQ = {
    "review_spec": ("spec",),
    "review_key_elements": ("key_elements",),
    "review_storyboard": ("shots_groups", "audio_groups"),
    "review_shot_media": ("shot_media",),
    "review_audio": ("audio_assets",),
    "review_assembly": ("assembly",),
}
_REVIEW_NODES = tuple(_REVIEW_NODE_PREREQ)

# 平铺节点清单（无 DAG）：16 节点 workflow 契约退役后不再编译节点拓扑，
# 本清单只提供**确定性的进度扫描顺序**（节点 id 词表与 6 步评审清单
# ``workflow_contract.DEFAULT_V2_REVIEW_NODES`` 断言对齐）。扫描顺序把
# 每个产出节点紧随其审批节点，使 current_node 在产物齐备时即指向待评审
# 里程碑（机械停闸 _apply_stage_gate 的「本轮翻转」判据来源）。
_FLAT_NODES: Tuple[str, ...] = (
    "analyze_script",
    "collect_spec",
    "write_spec",
    "review_spec",
    "storyboard_key_elements",
    "storyboard_shots",
    "storyboard_audio",
    "review_key_elements",
    "review_storyboard",
    "ke_media",
    "shot_media",
    "review_shot_media",
    "audio_assets",
    "review_audio",
    "assembly",
    "review_assembly",
)


def _node_objectively_done(node_id: str, run: Dict[str, Any],
                           state: Dict[str, Any], skill: str) -> bool:
    """workflow_contract 单节点完成度客观判定（默认 16 节点全覆盖）。"""
    if node_id in _NODE_PROBE_KEYS:
        return po.stage_done(_NODE_PROBE_KEYS[node_id], state, skill)
    if node_id in _NODE_STRUCTURE_KEYS:
        return po.stage_done(_NODE_STRUCTURE_KEYS[node_id], state, skill)
    if node_id in _REVIEW_NODE_PREREQ:
        if not all(po.stage_done(k, state, skill)
                   for k in _REVIEW_NODE_PREREQ[node_id]):
            return False
        rid = str(run.get("run_id") or "")
        return any(e.node_id == node_id and e.event_type == "DecisionResolved"
                   for e in EventLedger(state).by_run(rid))
    return False


def in_storyboard_window(state: Dict[str, Any], skill: str) -> bool:
    """A' 章节注入窗口只读判定（纯函数，不写状态；2026-09-18 批 B）。

    窗口 = 故事板设计已开始（KE 结构非空）且分镜评审未通过
    （review_storyboard 未完成）。避开探针粒度陷阱：建第一批 shot 后
    storyboard_shots 探针即判完成、current_node 翻向 audio，但模型仍在
    写后续 shot——只要 review_storyboard 未过，章节持续在场。
    """
    if not isinstance(state, dict):
        return False
    # 故事板设计已开始：KE 结构非空（客观探针，fail-closed）
    if not po.stage_done("key_elements", state, skill):
        return False
    # 分镜评审未通过：review_storyboard 未完成（需 DecisionResolved 事件）
    run = state.get("workflow_run") or {}
    if _node_objectively_done("review_storyboard", run, state, skill):
        return False
    return True


def sync_run(state: Dict[str, Any], skill: str) -> Dict[str, Any]:
    """同步 WorkflowRun（无 DAG 模式）：完成度按客观探针全量重算。

    2026-09-10 阶段规则去代码化批：16 节点 workflow 契约退役，
    ``compile_definition`` 恒 None ⇒ 平台不再编译节点拓扑/前置关系；
    账本改按平铺节点清单（``_FLAT_NODES``）逐个跑客观探针重算
    completed_nodes（账本无自报），current_node = 清单中首个未完成节点，
    供机械停闸（``_apply_stage_gate``）判「本轮是否发生里程碑翻转」。
    全部完成时 current_node 置空 ⇒ 闸不触发。
    不置 failure_state（「无 DAG」是常态不是失败）。
    run 块为 reducer 单一写入点。"""
    run = state.setdefault("workflow_run", {})
    now = datetime.now(timezone.utc).isoformat()
    if not run.get("run_id"):
        run.update({
            "run_id": f"run_{uuid.uuid4().hex}", "workflow_id": "",
            "definition_revision": "", "definition_hash": "",
            "slug": canonical_slug(skill), "name": str(skill or ""),
            "revision": "", "status": "ready", "current_node": "",
            "completed_nodes": [], "pending_decision": None, "artifacts": [],
            "run_version": 0, "event_sequence": 0, "failure_state": None,
            "created_at": now, "updated_at": now,
        })
    # 在途旧 run 一次性补齐字段（禁止 clear 式回滚：artifacts 等既有值不动）
    for key, value in (
        ("workflow_id", ""), ("definition_revision", ""), ("definition_hash", ""),
        ("slug", canonical_slug(skill)), ("name", str(skill or "")), ("revision", ""),
        ("status", "ready"), ("current_node", ""), ("completed_nodes", []),
        ("pending_decision", None), ("artifacts", []), ("run_version", 0),
        ("event_sequence", 0), ("failure_state", None), ("created_at", now),
    ):
        run.setdefault(key, copy.deepcopy(value))
    # 账本无自报：平铺清单全量探针重算，覆盖任何历史自报条目
    run["completed_nodes"] = [
        node_id for node_id in _FLAT_NODES
        if _node_objectively_done(node_id, run, state, skill)]
    run["current_node"] = ""
    for node_id in _FLAT_NODES:
        if node_id not in run["completed_nodes"]:
            run["current_node"] = node_id
            break
    run["failure_state"] = None
    if run.get("pending_decision"):
        run["status"] = "waiting_user"
    elif run.get("status") == "waiting_user":
        # 挂起决议已消费（resolve_decision 置 None）→ 恢复就绪态
        run["status"] = "ready"
    run["updated_at"] = now
    return run


def apply_interaction(
    state: Dict[str, Any],
    set_flags: Optional[Dict[str, Any]] = None,
    pop_flags: tuple = (),
) -> Dict[str, Any]:
    """interaction 旗标写入原语（不落盘）：reducer 族唯一写入原语。

    不经 StateManager 的持态调用点（轮末策略/执行器批内等）用本原语，
    落盘由调用方或 reduce_* 族承担；interaction 全域经 reducer 族写入。"""
    inter = state.setdefault("interaction", {})
    for key, val in (set_flags or {}).items():
        inter[key] = val
    for key in pop_flags:
        inter.pop(key, None)
    return inter


def reduce_interaction(
    svc: Any,
    set_flags: Optional[Dict[str, Any]] = None,
    pop_flags: tuple = (),
    flush: bool = False,
) -> Dict[str, Any]:
    """interaction 暂停旗标域写入点（reducer 语义）。

    职责：active_pause / storyboard_pending / last_pause_decision 等暂停流控旗标。
    session_summary / gate_overrides / drafts_presented 各有专属 reducer。
    flush=True 时即时落盘（暂停闭环等承重路径）。
    控制流可观测：写入经 [ControlFlow] 日志留痕。"""
    inter = apply_interaction(svc.state_dict, set_flags, pop_flags)
    if flush:
        svc.save()
    else:
        svc.save_debounced()
    if set_flags or pop_flags:
        logger.info(
            "[ControlFlow] reduce_interaction set={} pop={}",
            sorted((set_flags or {}).keys()), sorted(pop_flags),
        )
    return inter


def reduce_session_summary(
    svc: Any,
    fp: Optional[str] = None,
    text: Optional[str] = None,
    active: Optional[bool] = None,
    flush: bool = False,
) -> Dict[str, Any]:
    """interaction.session_summary 唯一写入点（compaction 摘要缓存 + 注入标记）。

    fp/text 非 None 时整体替换缓存字典（摘要重建）；active 非 None 时合并
    注入形态标记（无既有缓存且 active=False 时不新建键）。
    flush=True 即时落盘；控制流可观测：写入经 [ControlFlow] 日志留痕。"""
    inter = svc.state_dict.setdefault("interaction", {})
    changed = False
    if fp is not None or text is not None:
        inter["session_summary"] = {"fp": fp or "", "text": text or ""}
        changed = True
    if active is not None:
        cached = inter.get("session_summary")
        if not isinstance(cached, dict):
            if active:
                inter["session_summary"] = {"active": True}
                changed = True
        elif bool(cached.get("active")) != bool(active):
            cached["active"] = bool(active)
            changed = True
    if changed:
        if flush:
            svc.save()
        else:
            svc.save_debounced()
        logger.info(
            "[ControlFlow] reduce_session_summary fp={} text_len={} active={}",
            fp is not None, len(text) if text else 0, active,
        )
    return inter


def reduce_gate_overrides(
    svc: Any,
    rule_ids: List[str],
    flush: bool = False,
) -> Dict[str, Any]:
    """interaction.gate_overrides 唯一写入点（会话层一次性豁免登记/消费清除）。

    rule_ids 整体覆盖写入（消费即清除传 []）。
    flush=True 即时落盘（消费/登记闭环承重路径）。
    控制流可观测：写入经 [ControlFlow] 日志留痕。"""
    inter = apply_interaction(svc.state_dict, set_flags={"gate_overrides": list(rule_ids)})
    if flush:
        svc.save()
    else:
        svc.save_debounced()
    logger.info("[ControlFlow] reduce_gate_overrides count={}", len(rule_ids))
    return inter


def reduce_drafts_presented(
    svc: Any,
    draft_id: Optional[str] = None,
    clear: bool = False,
    flush: bool = False,
) -> Dict[str, Any]:
    """interaction.drafts_presented 唯一写入点（展示草稿登记/消费清除）。

    draft_id 非 None 时幂等追加；clear=True 时整体清空。
    flush=True 即时落盘；控制流可观测：写入经 [ControlFlow] 日志留痕。"""
    inter = svc.state_dict.setdefault("interaction", {})
    changed = False
    if clear:
        inter["drafts_presented"] = []
        changed = True
    elif draft_id:
        presented = inter.setdefault("drafts_presented", [])
        if draft_id not in presented:
            presented.append(draft_id)
            changed = True
    if changed:
        if flush:
            svc.save()
        else:
            svc.save_debounced()
        logger.info(
            "[ControlFlow] reduce_drafts_presented draft_id={} clear={}",
            draft_id, clear,
        )
    return inter


def record_node_event(
    state: Dict[str, Any], node_id: str, event_type: str,
    payload: Optional[Dict[str, Any]] = None,
) -> Optional[Any]:
    """后台/异步节点事件入账（v2 收尾）：独立事件独立耗时，
    幂等键稳定（同 run 同节点同类型不重复）。无 run 时跳过。"""
    run = state.get("workflow_run") or {}
    rid = str(run.get("run_id") or "")
    if not rid:
        return None
    ledger = EventLedger(state)
    return ledger.append(
        event_type, run_id=rid, node_id=node_id,
        idempotency_key=f"bg:{rid}:{node_id}:{event_type}",
        payload=dict(payload or {}))


def project(state: Dict[str, Any], turn_id: str = "") -> Dict[str, Any]:
    """workflow 投影（done 载荷/重连 replay 同源）。

    run 级快照 + 本轮事件序列（前端历史重载与实时 SSE 一致重建）。
    只读派生，不改状态。

    ``pending_decision_payload`` —— 布尔旗标之外附决策完整结构
    （token/node_id/message/schema/options，DecisionRequest 五元组透传），
    前端渲染层据此 schema→表单数据驱动（schema.fields = 多字段参数表单：
    每项 {key, label, type=text|number|select, options?, default?, required?}；
    产出侧写入 fields 即生效，投影层不做形态假设）；提交走既有
    暂停回应/消息通道，runtime 不因此发起任何行动（账本层不变式）。"""
    run = state.get("workflow_run") or {}
    proj = {
        "run_id": run.get("run_id") or "",
        "status": run.get("status") or "",
        "current_node": run.get("current_node") or "",
        "completed_nodes": list(run.get("completed_nodes") or []),
        "event_sequence": int(run.get("event_sequence") or 0),
        "pending_decision": bool(run.get("pending_decision")),
    }
    _pend = run.get("pending_decision") or {}
    if isinstance(_pend, dict) and _pend.get("token"):
        proj["pending_decision_payload"] = {
            "token": str(_pend.get("token") or ""),
            "node_id": str(_pend.get("node_id") or ""),
            "message": str(_pend.get("prompt") or _pend.get("message") or ""),
            "schema": copy.deepcopy(_pend.get("schema") or {}),
            "options": copy.deepcopy(_pend.get("options") or []),
        }
    if turn_id:
        ledger = EventLedger(state)
        proj["turn_events"] = [
            e.to_dict() for e in ledger.events if e.turn_id == str(turn_id)
        ]
    return proj


def record_artifact(state: Dict[str, Any], skill: str, name: str) -> None:
    """产物账本一等条目（ArtifactCommitted）：reducer 单一写入。

    独立事件入账 + run.artifacts 单一写入（幂等去重）。"""
    if not name:
        return
    run = state.get("workflow_run") or {}
    rid = str(run.get("run_id") or "")
    if not rid:
        return
    artifacts = run.setdefault("artifacts", [])
    if name not in artifacts:
        artifacts.append(name)
    all_artifacts = state.setdefault("workflow_artifacts", [])
    if not any(isinstance(x, dict) and x.get("name") == name for x in all_artifacts):
        all_artifacts.append({"name": name, "kind": "artifact"})
    ledger = EventLedger(state)
    ledger.append(
        "ArtifactCommitted", run_id=rid,
        node_id=str(run.get("current_node") or ""),
        idempotency_key=f"artifact:{rid}:{name}",
        payload={"name": name})

class WorkflowRuntime:
    """workflow 运行时门面：状态投影 + 事件账本 + 轮次提交。"""

    def __init__(self, state_manager: Any, skill: str = ""):
        self.state_manager, self.skill = state_manager, str(skill or "")

    @property
    def state(self) -> Dict[str, Any]:
        if hasattr(self.state_manager, "state_dict"):
            return self.state_manager.state_dict
        return self.state_manager

    def ensure_run(self) -> Dict[str, Any]:
        """轮始轻量确保（批 3 · B3）：run 已存在且未失败时直接返回，不做
        全量探针重算——账本重算的唯一触发点收敛到写动作落账
        （commit_turn / resolve_decision）与轮末阶段闸 sync_run。
        （2026-09-10 阶段规则去代码化批：DAG 不再编译，run 存在即视为有效，
        不再按 definition_hash 比对；「无 DAG」不置 failure_state。）"""
        run = self.state.get("workflow_run") or {}
        if run.get("run_id") and not run.get("failure_state"):
            return run
        return self.start_run()

    def start_run(self, *, input_present: Optional[bool] = None) -> Dict[str, Any]:
        run = sync_run(self.state, self.skill)
        ledger = EventLedger(self.state)
        ledger.append(
            "RunStarted", run_id=run["run_id"],
            idempotency_key=f"run:{run['run_id']}:started",
            payload={"workflow_id": run.get("workflow_id")})
        # 原料闸机械判定已随用户裁决 2026-08-31 退役（外部标杆对齐：
        # 原料收集归 skill 散文 + 模型自觉）；仅保留调用方显式 input_present 覆盖。
        missing = input_present is False
        if missing:
            # 原料闸挂首节点（默认定义首节点 = analyze_script，行为不变；
            # 声明式 workflow 挂其声明首节点）
            _def = compile_definition(self.skill)
            _input_node = (_def["nodes"][0]["node_id"]
                           if _def and _def.get("nodes") else "analyze_script")
            run["status"] = "waiting_user"
            run["pending_decision"] = {
                "token": f"input:{run['run_id']}", "node_id": _input_node,
                "schema": {"type": "input", "required": True}}
            ledger.append(
                "InputRequested", run_id=run["run_id"], node_id=_input_node,
                idempotency_key=f"run:{run['run_id']}:input",
                payload={"status": "waiting_user"})
        run["event_sequence"] = max(
            (x.sequence for x in ledger.by_run(run["run_id"])), default=0)
        if hasattr(self.state_manager, "save"):
            self.state_manager.save()
        return copy.deepcopy(run)

    def commit_turn(self, result: Any, **kwargs: Any) -> TurnCommit:
        commit = commit_turn(self.state_manager, result, skill=self.skill, **kwargs)
        # 批 3 · B3（V5-1）：写动作落账即全量重算——账本重算唯一常规触发点。
        # 产物（current_node/completed_nodes）只服务审计与判官层回放对照，
        # 不接 UI、不进提示词；用落账后的账本重建返回快照（口径一致）。
        run = sync_run(self.state, self.skill)
        return TurnCommit(
            commit.turn_id, copy.deepcopy(run), commit.result, commit.events,
            commit.idempotent, commit.persisted, commit.event_sequence,
        )

    def resolve_decision(self, token: str, value: Any, *, turn_id: str = "") -> TurnCommit:
        run = sync_run(self.state, self.skill)
        pending = run.get("pending_decision") or {}
        if pending.get("token") != token:
            raise WorkflowCommitError("stale decision token")
        allowed = pending.get("options") or []
        if allowed and str(value) not in {
            str(x.get("value") if isinstance(x, dict) else x) for x in allowed
        }:
            raise WorkflowCommitError("invalid decision value")
        run["pending_decision"] = None
        commit = commit_turn(
            self.state_manager,
            TurnResult(
                turn_id=turn_id or f"decision:{token}:{value}",
                node_id=str(pending.get("node_id") or run.get("current_node") or ""),
                timeline_events=[{
                    "event_type": "DecisionResolved",
                    "payload": {"token": token, "value": value}}]),
            skill=self.skill,
            expected_version=int(run.get("run_version") or 0))
        # 决议落账后全量重算（B3「写动作落账即全量重算」延伸到决议路径）：
        # DecisionResolved 入账后审批节点完成度随 sync 收纳（模块级 commit_turn
        # 不带尾部重算，缺这步会让评审节点永不完成）
        run = sync_run(self.state, self.skill)
        return TurnCommit(
            commit.turn_id, copy.deepcopy(run), commit.result, commit.events,
            commit.idempotent, commit.persisted, commit.event_sequence,
        )

    def recover_run(self) -> Dict[str, Any]:
        run = sync_run(self.state, self.skill)
        events = EventLedger(self.state).by_run(run.get("run_id") or "")
        run["event_sequence"] = max((x.sequence for x in events), default=0)
        if run.get("pending_decision"):
            run["status"] = "waiting_user"
        return copy.deepcopy(run)


__all__ = [
    "WorkflowRuntime", "TurnResult", "TurnCommit", "commit_turn",
    "compile_definition", "sync_run", "record_artifact",
    "apply_interaction", "reduce_interaction", "reduce_session_summary",
    "reduce_gate_overrides", "reduce_drafts_presented",
]

# frontmatter 声明写入即失效编译缓存（声明变更不被缓存遮蔽）
frontmatter.register_write_hook(clear_compile_cache)
