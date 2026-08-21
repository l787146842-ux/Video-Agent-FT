# -*- coding: utf-8 -*-
"""Workflow Runtime — 控制流唯一驱动器（宪法 v6 Rule2，ADR-0003）。

正向设计（业界基准：Anthropic workflows-vs-agents / Claude Code hooks 公理 /
Codex loop+approval / Flova runtime contract）：模型只做节点内语义创作，
运行时做确定性顺序、持久状态、审批恢复与产物账本。

v1 边界（声明式可扩展）：
- 直跑面 = sidecar 声明 ``flow.direct_run_nodes``（缺失回落 analysis 节点），
  runtime 按声明机械直跑（零模型规划轮），经 FCToolRunner 合成 FC 批执行——
  闸机链（stage_precondition 等）仍在执行路径首位承重（hooks guarantee behavior）；
- 审批直跑能力（workflow_pause 执行器节点）已实现但默认不入名单：
  与模型循环暂停的语义去重需用户裁决后启用；
- 声明外阶段（含创作型与多执行器阶段）交接有界模型循环（agent_loop 节点内
  唯一实现），平台否决权不变；
- 生成类阶段（高风险工具，§2.7）入直跑声明须另行设计审批语义。

WorkflowRun 持久化于 ``state["workflow_run"]``，**仅本模块 reducer 可改**
（StateManager 仍唯一写入点，Rule3）；interaction 暂停旗标同经
``reduce_interaction`` 单一写入。完成度只认客观探针（stage_done，fail-closed）。
"""
import copy
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from loguru import logger

from src.video_agent.config import settings
from src.video_agent.core import pipeline_orchestrator as po
from src.video_agent.core import prompt_gates
from src.video_agent.skill_runtime import registry
from src.video_agent.skill_runtime import sidecar
from src.video_agent.core.workflow_contract import WorkflowDefinitionError, default_v2_workflow
from src.video_agent.core.workflow_events import EventLedger
from src.video_agent.core.turn_commit import (
    TurnCommit, TurnResult, WorkflowCommitError, commit_turn,
)

# 批4 泛化：直跑面改由 sidecar 声明驱动（flow.direct_run_nodes），
# DIRECT_RUN_STAGES 硬编码白名单退役；缺失声明回落 analysis 节点（存量不变）。
_DEFAULT_DIRECT_RUN_NODES = frozenset({"analyze_script"})
# 节点 → 阶段键映射（_run_direct_stage 消费：stage_done 探针/后台预取挂钩）
_NODE_STAGE_KEYS = {"analyze_script": "analysis"}
# per-turn 编译缓存（轮始清理；同轮内 sync_run/drive_turn/排除计算共享）
_COMPILE_CACHE: Dict[str, Optional[Dict[str, Any]]] = {}


def clear_compile_cache() -> None:
    """轮始清理编译缓存（批4：sidecar 声明在轮间可能被编辑，缓存只活一轮）。"""
    _COMPILE_CACHE.clear()


def direct_run_nodes(skill: str) -> frozenset:
    """直跑面声明（批4）：sidecar flow.direct_run_nodes 优先，缺失回落默认。"""
    try:
        manifest = registry.skill_manifest_of(skill) or {}
    except Exception:
        manifest = {}
    declared = ((manifest.get("flow") or {}).get("direct_run_nodes"))
    if isinstance(declared, list) and declared:
        return frozenset(str(x) for x in declared if str(x).strip())
    return _DEFAULT_DIRECT_RUN_NODES


def canonical_slug(name: str) -> str:
    """canonical 身份归一：小写 + 去空格/连字符/下划线/扩展名。

    「AI短剧一站式生成」与「AI-短剧一站式生成」归一到同一身份，
    模型逐字复制显示名的误差不再造成解析失败。"""
    return registry._norm_name(name).replace("-", "").replace("_", "")


def compile_definition(skill: str) -> Optional[Dict[str, Any]]:
    """Skill 激活编译 WorkflowDefinition（canonical slug + revision + hash）。

    源 = sidecar 声明（validate_sidecar 注册期门禁）+ 阶段表；编译失败
    （未注册 Skill）返回 None（runtime 不启用，回落模型循环旧路径）。
    批4：per-turn 缓存（轮始 clear_compile_cache；同轮多次调用共享）。"""
    cache_key = canonical_slug(skill) or str(skill or "")
    if cache_key in _COMPILE_CACHE:
        hit = _COMPILE_CACHE[cache_key]
        return copy.deepcopy(hit) if hit is not None else None
    entry = registry.resolve_entry(skill)
    if entry is None:
        _COMPILE_CACHE[cache_key] = None
        return None
    # v2 收尾：sidecar 体检门禁——非法声明拒入 workflow（计划§1/§6：
    # 无效 sidecar 不得“只告警后继续”驱动运行时；散文通道仍可工作）
    issues = sidecar.validate_sidecar(
        sidecar.load_sidecar(str(entry.slug or skill)))
    if issues:
        logger.warning(
            "[WorkflowRuntime] sidecar 非法，workflow 拒入（{}）: {}",
            skill, ";".join(issues))
        _COMPILE_CACHE[cache_key] = None
        return None
    definition = default_v2_workflow(str(entry.slug or skill))
    titles = {"analyze_script": "剧本分析", "collect_spec": "规格候选收集",
              "write_spec": "规格文档", "review_spec": "规格审核",
              "storyboard_key_elements": "关键元素拆解",
              "review_key_elements": "关键元素审核",
              "storyboard_shots": "分镜设计", "storyboard_audio": "音频层设计"}
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


def sync_run(state: Dict[str, Any], skill: str) -> Dict[str, Any]:
    """同步 WorkflowRun：定义变更重初始化；完成度按客观探针重算。

    current_node = 阶段表首个未完成步；completed_nodes 只认 stage_done
    （fail-closed）。run 块为 reducer 单一写入点。"""
    definition = compile_definition(skill)
    run = state.setdefault("workflow_run", {})
    if definition is None:
        run.setdefault("failure_state", {"code": "INVALID_SKILL", "skill": skill})
        return run
    now = datetime.now(timezone.utc).isoformat()
    if not run:
        run.update({"run_id": f"run_{uuid.uuid4().hex}", "workflow_id": definition["workflow_id"],
                    "definition_revision": definition["revision"], "definition_hash": definition["definition_hash"],
                    "slug": definition["slug"], "name": definition["name"], "revision": definition["revision"],
                    "status": "ready", "current_node": "analyze_script", "completed_nodes": [],
                    "pending_decision": None, "artifacts": [], "run_version": 0,
                    "event_sequence": 0, "node_attempts": {}, "failure_state": None,
                    "created_at": now, "updated_at": now})
    elif run.get("definition_hash") and run.get("definition_hash") != definition["definition_hash"]:
        run.setdefault("definition_change_detected", {"active_hash": run.get("definition_hash"), "available_hash": definition["definition_hash"]})
        return run
    for key, value in (("workflow_id", definition["workflow_id"]), ("definition_revision", definition["revision"]),
                       ("definition_hash", definition["definition_hash"]), ("status", "ready"),
                       ("completed_nodes", []), ("pending_decision", None), ("artifacts", []),
                       ("run_version", 0), ("event_sequence", 0), ("node_attempts", {}),
                       ("failure_state", None), ("created_at", now)):
        run.setdefault(key, copy.deepcopy(value))
    completed = list(dict.fromkeys(str(x) for x in run.get("completed_nodes") or []))
    if po.stage_done("analysis", state, skill) and "analyze_script" not in completed: completed.append("analyze_script")
    if prompt_gates.has_spec_document(state) and "write_spec" not in completed: completed.append("write_spec")
    run["completed_nodes"] = completed
    if not run.get("current_node") or run.get("current_node") in completed:
        for node in definition["nodes"]:
            if node["node_id"] not in completed and all(x in completed for x in node.get("prerequisites") or []):
                run["current_node"] = node["node_id"]; break
    if run.get("pending_decision"): run["status"] = "waiting_user"
    run["updated_at"] = now
    return run


def apply_interaction(
    state: Dict[str, Any],
    set_flags: Optional[Dict[str, Any]] = None,
    pop_flags: tuple = (),
) -> Dict[str, Any]:
    """interaction 旗标写入原语（不落盘）：reducer 族唯一写入原语。

    不经 StateManager 的持态调用点（轮末策略/执行器批内等）用本原语，
    落盘由调用方或 reduce_interaction 承担；散落直写禁止（Rule2 v6）。"""
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
    """interaction 暂停旗标唯一写入点（reducer 语义，Rule2 v6）。

    散落直写已收敛到此；flush=True 时即时落盘（暂停闭环等承重路径）。
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


def drive_turn(
    state: Dict[str, Any], skill: str, advance_signal: str = "",
) -> Optional[Dict[str, Any]]:
    """轮始驱动判定（批4 泛化）：声明直跑面内的当前节点就绪 → direct_run；
    其余 None（交接）。只认客观状态事实：阶段表 + 直跑声明 + 原料闸客观条件；
    零语料、零模型参与。

    advance_signal 为轮始客观推进信号（暂停消费/附件/系统继续选项点选，
    由开场编排装配）：无信号的自由提问轮不直跑，交接模型循环（防提问误抓）。
    审批节点（workflow_pause 执行器）直跑能力已实现但未入默认声明：
    与模型循环暂停的语义去重需裁决后启用（防双暂停）。
    原料缺失时返回 None，由闸预检装配提醒卡（不抢先对话）。"""
    if not (getattr(settings, "workflow_runtime_enabled", True) and skill):
        return None
    if not str(advance_signal or "").strip():
        return None
    run = sync_run(state, skill)
    definition = compile_definition(skill) or {}
    node_id = str(run.get("current_node") or "")
    node = next((x for x in definition.get("nodes") or [] if x.get("node_id") == node_id), None)
    if node is None or node_id not in direct_run_nodes(skill):
        return None
    # 审批直跑能力（workflow_pause 节点）：声明入名单才生效；
    # 当前默认名单不含审批节点（语义去重待裁决，防双暂停）
    if str(node.get("executor") or "") == "workflow_pause":
        logger.info("[ControlFlow] runtime approval_pause node={}（预留能力）", node_id)
        return {"kind": "approval_pause", "node_id": node_id,
                "stage_title": node.get("title") or node_id}
    executors = list(node.get("executors") or [])
    if not executors:
        return None
    # 原料闸客观前置：需剧本 Skill 剧本缺失且未豁免 → 交接闸预检提醒卡
    if node_id == "analyze_script" and (
        registry.script_required_active(skill)
        and not prompt_gates.script_present(state)
        and not (state.get("interaction") or {}).get("script_waived")
    ):
        return None
    logger.info("[ControlFlow] runtime direct_run node={}", node_id)
    return {
        "kind": "direct_run",
        "stage_key": _NODE_STAGE_KEYS.get(node_id, node_id),
        "node_id": node_id,
        "stage_title": node.get("title") or node_id,
        "executors": executors,
    }


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
    """v2 批3：workflow 投影（done 载荷/重连 replay 同源）。

    run 级快照 + 本轮事件序列（前端历史重载与实时 SSE 一致重建）。
    只读派生，不改状态。"""
    run = state.get("workflow_run") or {}
    proj = {
        "run_id": run.get("run_id") or "",
        "status": run.get("status") or "",
        "current_node": run.get("current_node") or "",
        "completed_nodes": list(run.get("completed_nodes") or []),
        "event_sequence": int(run.get("event_sequence") or 0),
        "pending_decision": bool(run.get("pending_decision")),
    }
    if turn_id:
        ledger = EventLedger(state)
        proj["turn_events"] = [
            e.to_dict() for e in ledger.events if e.turn_id == str(turn_id)
        ]
    return proj


def record_artifact(state: Dict[str, Any], skill: str, name: str) -> None:
    """产物账本一等条目（ArtifactCommitted）：reducer 单一写入。

    批4 正名：伪轮次（turn_id=artifact:{name} 走 commit_turn）退役，
    改为独立事件入账 + run.artifacts 单一写入（行为等价：幂等去重）。"""
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
    def __init__(self, state_manager: Any, skill: str = ""):
        self.state_manager, self.skill = state_manager, str(skill or "")
    @property
    def state(self) -> Dict[str, Any]: return self.state_manager.state_dict if hasattr(self.state_manager, "state_dict") else self.state_manager
    def start_run(self, *, input_present: Optional[bool] = None) -> Dict[str, Any]:
        run = sync_run(self.state, self.skill); ledger = EventLedger(self.state)
        ledger.append("RunStarted", run_id=run["run_id"], idempotency_key=f"run:{run['run_id']}:started", payload={"workflow_id": run.get("workflow_id")})
        missing = input_present is False or (input_present is None and registry.script_required_active(self.skill) and not prompt_gates.script_present(self.state))
        if missing:
            run["status"] = "waiting_user"; run["pending_decision"] = {"token": f"input:{run['run_id']}", "node_id": "analyze_script", "schema": {"type": "input", "required": True}}
            ledger.append("InputRequested", run_id=run["run_id"], node_id="analyze_script", idempotency_key=f"run:{run['run_id']}:input", payload={"status": "waiting_user"})
        run["event_sequence"] = max((x.sequence for x in ledger.by_run(run["run_id"])), default=0)
        if hasattr(self.state_manager, "save"): self.state_manager.save()
        return copy.deepcopy(run)
    def dispatch(self, *, advance_signal: str = "") -> Optional[Dict[str, Any]]: return drive_turn(self.state, self.skill, advance_signal)
    def commit_turn(self, result: Any, **kwargs: Any) -> TurnCommit: return commit_turn(self.state_manager, result, skill=self.skill, **kwargs)
    def resolve_decision(self, token: str, value: Any, *, turn_id: str = "") -> TurnCommit:
        run = sync_run(self.state, self.skill); pending = run.get("pending_decision") or {}
        if pending.get("token") != token: raise WorkflowCommitError("stale decision token")
        allowed = pending.get("options") or []
        if allowed and str(value) not in {str(x.get("value") if isinstance(x, dict) else x) for x in allowed}: raise WorkflowCommitError("invalid decision value")
        run["pending_decision"] = None
        return commit_turn(self.state_manager, TurnResult(turn_id=turn_id or f"decision:{token}:{value}", node_id=str(pending.get("node_id") or run.get("current_node") or ""), timeline_events=[{"event_type": "DecisionResolved", "payload": {"token": token, "value": value}}]), skill=self.skill, expected_version=int(run.get("run_version") or 0))
    def recover_run(self) -> Dict[str, Any]:
        run = sync_run(self.state, self.skill); events = EventLedger(self.state).by_run(run.get("run_id") or "")
        run["event_sequence"] = max((x.sequence for x in events), default=0)
        if run.get("pending_decision"): run["status"] = "waiting_user"
        return copy.deepcopy(run)

__all__ = ["WorkflowRuntime", "TurnResult", "TurnCommit", "commit_turn", "compile_definition", "sync_run", "drive_turn", "record_artifact", "apply_interaction", "reduce_interaction"]

# 批4：sidecar 声明写入即失效编译缓存（门禁/直跑声明变更不被缓存遮蔽）
sidecar.register_write_hook(clear_compile_cache)
