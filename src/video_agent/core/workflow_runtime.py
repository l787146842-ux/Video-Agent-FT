# -*- coding: utf-8 -*-
"""Workflow Runtime — 账本 + 裁判数据层。

正向设计（业界基准：Anthropic workflows-vs-agents / Claude Code hooks 公理 /
Codex loop+approval / Temporal 持久化执行与 LangGraph 检查点恢复；
共识：确定性 = 把关模型发起的动作，不是系统代替模型发起动作）：
模型永远是唯一行动主体，运行时做持久状态、产物账本、投影与裁判数据，
不发起任何行动（stage_precondition 越阶硬闸已随 C1b 裁决 2026-08-31 退役）。

职责边界：
- Skill 激活编译 ``WorkflowDefinition``（canonical slug + revision + content hash，
  源 = frontmatter 声明，``validate_manifest`` 注册期门禁）；
- 持久化 ``WorkflowRun``（current_node/completed_nodes/pending_gate/artifacts），
  **仅本模块 reducer 可改**（StateManager 仍唯一写入点，Rule3）；
  interaction 全域经 reducer 族（reduce_interaction / reduce_session_summary /
  reduce_gate_overrides / reduce_drafts_presented）单一写入；
- 完成度只认客观探针（stage_done，fail-closed）；
- 「不暂停连跑」语义归自主性档位。
"""
import copy
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from loguru import logger

from src.video_agent.config import settings
from src.video_agent.core import stage_probes as po
from src.video_agent.core import prompt_gates
from src.video_agent.skill_runtime import registry
from src.video_agent.skill_runtime import frontmatter
from src.video_agent.skill_runtime.manifest_schema import split_issue_warnings
from src.video_agent.core.workflow_contract import (
    WorkflowDefinition, WorkflowDefinitionError, default_v2_workflow,
    DEFAULT_V2_NODE_TITLES,
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
    """Skill 激活编译 WorkflowDefinition（canonical slug + revision + hash）。

    源 = frontmatter 声明（validate_manifest 注册期门禁）+ 阶段表；编译失败
    （未注册 Skill）返回 None（runtime 不启用，回落模型循环旧路径）。
    统一定义 = default_v2_workflow（默认 workflow 自带标题
    DEFAULT_V2_NODE_TITLES）。（C1b 裁决 2026-08-31：flow.stages 声明式
    编译退役——声明忽略，机械工作流层整体退役。）
    per-turn 缓存（轮始 clear_compile_cache；同轮多次调用共享）。"""
    cache_key = canonical_slug(skill) or str(skill or "")
    if cache_key in _COMPILE_CACHE:
        hit = _COMPILE_CACHE[cache_key]
        return copy.deepcopy(hit) if hit is not None else None
    entry = registry.resolve_entry(skill)
    if entry is None:
        _COMPILE_CACHE[cache_key] = None
        return None
    # v2 收尾：frontmatter 体检门禁——非法声明拒入 workflow（计划§1/§6：
    # 无效声明不能“只告警后继续”驱动运行时；散文通道仍可工作）
    # 问题分级：只按错误级拒入；WARN 级（开放注册降级/
    # 废除键过渡告警）记录日志后放行，与注册门禁同口径。
    manifest = frontmatter.load_manifest(str(entry.slug or skill))
    _issues = frontmatter.validate_manifest(manifest)
    issues, _warns = split_issue_warnings(_issues)
    for _w in _warns:
        logger.warning("[WorkflowRuntime] frontmatter 告警（{}）: {}", skill, _w)
    if issues:
        logger.warning(
            "[WorkflowRuntime] frontmatter 非法，workflow 拒入（{}）: {}",
            skill, ";".join(issues))
        _COMPILE_CACHE[cache_key] = None
        return None
    # C1b 裁决 2026-08-31：flow.stages 声明式编译退役，统一定义回落默认链。
    definition = default_v2_workflow(str(entry.slug or skill))
    titles = DEFAULT_V2_NODE_TITLES
    nodes = [{**node.to_dict(), "key": node.node_id,
              "title": titles.get(node.node_id, node.node_id),
              "executors": [] if node.executor == "workflow_pause" else [node.executor]}
             for node in definition.nodes]
    result = {
        "slug": str(entry.slug or ""),
        "name": str(entry.name or skill),
        "workflow_id": definition.workflow_id,
        "revision": definition.revision,
        "definition_hash": definition.content_hash,
        "nodes": nodes,
    }
    _COMPILE_CACHE[cache_key] = copy.deepcopy(result)
    return result


# 节点 → 客观探针键映射（账本无自报）：completed_nodes 全量
# 由 stage_done 探针重算；turn_commit 的自报 completed_node 降级为非权威
# 提示——下次 sync 即被本重算覆盖，不再具有账本效力。
# - collect_spec 与 write_spec 同证同源：规格文档在场即证明收集已发生；
# - storyboard 三个结构节点用节点级探针（key_elements/shots_groups/
#   audio_groups，运行时内部键，不可声明覆盖）；
# - 两个评审节点的「已评审」客观证据 = 账本 DecisionResolved 事件
#   （resolve_decision 提交），前置产物在场但未落账决议时不予完成
#   （fail-closed：不因文档存在而跳过评审暂停）。
# （C1b 裁决 2026-08-31：声明式 workflow（flow.stages 数组）节点→探针映射
# 随机械工作流层整体退役删除。）
_NODE_PROBE_KEYS = {
    "analyze_script": "analysis",
    "collect_spec": "spec",
    "write_spec": "spec",
}
_NODE_STRUCTURE_KEYS = {
    "storyboard_key_elements": "key_elements",
    "storyboard_shots": "shots_groups",
    "storyboard_audio": "audio_groups",
}
_REVIEW_NODES = ("review_spec", "review_key_elements")


def _node_objectively_done(node_id: str, run: Dict[str, Any],
                           state: Dict[str, Any], skill: str) -> bool:
    """workflow_contract 单节点完成度客观判定（默认 8/8 节点全覆盖）。"""
    if node_id in _NODE_PROBE_KEYS:
        return po.stage_done(_NODE_PROBE_KEYS[node_id], state, skill)
    if node_id in _NODE_STRUCTURE_KEYS:
        return po.stage_done(_NODE_STRUCTURE_KEYS[node_id], state, skill)
    if node_id in _REVIEW_NODES:
        prereq = "spec" if node_id == "review_spec" else "key_elements"
        if not po.stage_done(prereq, state, skill):
            return False
        rid = str(run.get("run_id") or "")
        return any(e.node_id == node_id and e.event_type == "DecisionResolved"
                   for e in EventLedger(state).by_run(rid))
    return False


def sync_run(state: Dict[str, Any], skill: str) -> Dict[str, Any]:
    """同步 WorkflowRun：定义变更重初始化；完成度按客观探针全量重算。

    current_node = 阶段表首个未完成步；completed_nodes 只认 stage_done
    探针与账本 DecisionResolved 事件（fail-closed），自报条目无账本效力。
    run 块为 reducer 单一写入点。"""
    definition = compile_definition(skill)
    run = state.setdefault("workflow_run", {})
    if definition is None:
        run.setdefault("failure_state", {"code": "INVALID_SKILL", "skill": skill})
        return run
    now = datetime.now(timezone.utc).isoformat()
    first_node = definition["nodes"][0]["node_id"]
    if not run:
        run.update({"run_id": f"run_{uuid.uuid4().hex}", "workflow_id": definition["workflow_id"],
                    "definition_revision": definition["revision"], "definition_hash": definition["definition_hash"],
                    "slug": definition["slug"], "name": definition["name"], "revision": definition["revision"],
                    "status": "ready", "current_node": first_node, "completed_nodes": [],
                    "pending_decision": None, "artifacts": [], "run_version": 0,
                    "event_sequence": 0, "failure_state": None,
                    "created_at": now, "updated_at": now})
    elif run.get("definition_hash") and run.get("definition_hash") != definition["definition_hash"]:
        # 定义变更时保留旧 run 的早退语义不变
        return run
    for key, value in (("workflow_id", definition["workflow_id"]), ("definition_revision", definition["revision"]),
                       ("definition_hash", definition["definition_hash"]), ("status", "ready"),
                       ("completed_nodes", []), ("pending_decision", None), ("artifacts", []),
                       ("run_version", 0), ("event_sequence", 0),
                       ("failure_state", None), ("created_at", now)):
        run.setdefault(key, copy.deepcopy(value))
    # 账本无自报：8/8 节点全量探针重算，覆盖任何历史自报条目
    run["completed_nodes"] = [
        n["node_id"] for n in definition["nodes"]
        if _node_objectively_done(n["node_id"], run, state, skill)]
    if not run.get("current_node") or run.get("current_node") in run["completed_nodes"]:
        for node in definition["nodes"]:
            if node["node_id"] not in run["completed_nodes"] and all(
                    x in run["completed_nodes"] for x in node.get("prerequisites") or []):
                run["current_node"] = node["node_id"]
                break
    if run.get("pending_decision"):
        run["status"] = "waiting_user"
    run["updated_at"] = now
    return run


def current_node_title(state: Dict[str, Any], skill: str) -> Optional[str]:
    """只读投影：当前 run 的 current_node 标题（标题事实源 =
    compile_definition 节点 title，即 DEFAULT_V2_NODE_TITLES）。

    无 Skill 编译定义 / 无 active run / 无 current_node / 定义变更早退
    一律返回 None（调用方回落）；不写 run 块（sync_run 仍是 reducer 单一写入点）。"""
    definition = compile_definition(skill)
    if not definition:
        return None
    run = (state or {}).get("workflow_run") or {}
    if not run.get("run_id") or run.get("failure_state"):
        return None
    if run.get("definition_hash") and run.get("definition_hash") != definition["definition_hash"]:
        # sync_run 同语义：定义变更的旧 run 早退，不作节点判定依据
        return None
    current = str(run.get("current_node") or "")
    if not current:
        return None
    for node in definition["nodes"]:
        if node["node_id"] == current:
            return str(node.get("title") or current)
    return None


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

    def start_run(self, *, input_present: Optional[bool] = None) -> Dict[str, Any]:
        run = sync_run(self.state, self.skill)
        ledger = EventLedger(self.state)
        ledger.append(
            "RunStarted", run_id=run["run_id"],
            idempotency_key=f"run:{run['run_id']}:started",
            payload={"workflow_id": run.get("workflow_id")})
        # 原料闸机械判定已随用户裁决 2026-08-31 退役（Flova 对齐：
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
        return commit_turn(self.state_manager, result, skill=self.skill, **kwargs)

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
        return commit_turn(
            self.state_manager,
            TurnResult(
                turn_id=turn_id or f"decision:{token}:{value}",
                node_id=str(pending.get("node_id") or run.get("current_node") or ""),
                timeline_events=[{
                    "event_type": "DecisionResolved",
                    "payload": {"token": token, "value": value}}]),
            skill=self.skill,
            expected_version=int(run.get("run_version") or 0))

    def recover_run(self) -> Dict[str, Any]:
        run = sync_run(self.state, self.skill)
        events = EventLedger(self.state).by_run(run.get("run_id") or "")
        run["event_sequence"] = max((x.sequence for x in events), default=0)
        if run.get("pending_decision"):
            run["status"] = "waiting_user"
        return copy.deepcopy(run)


__all__ = [
    "WorkflowRuntime", "TurnResult", "TurnCommit", "commit_turn",
    "compile_definition", "sync_run", "current_node_title", "record_artifact",
    "apply_interaction", "reduce_interaction", "reduce_session_summary",
    "reduce_gate_overrides", "reduce_drafts_presented",
]

# frontmatter 声明写入即失效编译缓存（声明变更不被缓存遮蔽）
frontmatter.register_write_hook(clear_compile_cache)
