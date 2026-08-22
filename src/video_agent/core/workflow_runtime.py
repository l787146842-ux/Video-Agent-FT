# -*- coding: utf-8 -*-
"""Workflow Runtime — 账本 + 裁判数据层（宪法 Rule2 主体回归，ADR-0004）。

正向设计（业界基准：Anthropic workflows-vs-agents / Claude Code hooks 公理 /
Codex loop+approval / Temporal 持久化执行与 LangGraph 检查点恢复；
共识：确定性 = 把关模型发起的动作，不是系统代替模型发起动作）：
模型永远是唯一行动主体，运行时做持久状态、产物账本、投影与裁判数据，
不发起任何行动；越阶由 stage_precondition 闸在工具执行路径首位否决。

职责边界（主体回归后）：
- Skill 激活编译 ``WorkflowDefinition``（canonical slug + revision + content hash，
  源 = sidecar 声明，``validate_sidecar`` 注册期门禁）；
- 持久化 ``WorkflowRun``（current_node/completed_nodes/pending_gate/artifacts），
  **仅本模块 reducer 可改**（StateManager 仍唯一写入点，Rule3）；
  interaction 暂停旗标同经 ``reduce_interaction`` 单一写入；
- 完成度只认客观探针（stage_done，fail-closed）；
- 历史机械直跑/审批直跑能力随 ADR-0004 退役（防复活归
  check_legacy_orchestration 门禁）；「不暂停连跑」语义归自主性档位。
"""
import copy
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from loguru import logger

from src.video_agent.config import settings
from src.video_agent.core import gates_inputs
from src.video_agent.core import pipeline_orchestrator as po
from src.video_agent.core import prompt_gates
from src.video_agent.skill_runtime import registry
from src.video_agent.skill_runtime import sidecar
from src.video_agent.core.workflow_contract import WorkflowDefinitionError, default_v2_workflow
from src.video_agent.core.workflow_events import EventLedger
from src.video_agent.core.turn_commit import (
    TurnCommit, TurnResult, WorkflowCommitError, commit_turn,
)

# per-turn 编译缓存（轮始清理；同轮内 sync_run/排除计算共享）
_COMPILE_CACHE: Dict[str, Optional[Dict[str, Any]]] = {}


def clear_compile_cache() -> None:
    """轮始清理编译缓存（sidecar 声明轮间可能被编辑，缓存仅限本轮）。"""
    _COMPILE_CACHE.clear()


def canonical_slug(name: str) -> str:
    """canonical 身份归一：小写 + 去空格/连字符/下划线/扩展名。

    「AI短剧一站式生成」与「AI-短剧一站式生成」归一到同一身份，
    模型逐字复制显示名的误差不再造成解析失败。"""
    return registry._norm_name(name).replace("-", "").replace("_", "")


def compile_definition(skill: str) -> Optional[Dict[str, Any]]:
    """Skill 激活编译 WorkflowDefinition（canonical slug + revision + hash）。

    源 = sidecar 声明（validate_sidecar 注册期门禁）+ 阶段表；编译失败
    （未注册 Skill）返回 None（runtime 不启用，回落模型循环旧路径）。
    per-turn 缓存（轮始 clear_compile_cache；同轮多次调用共享）。"""
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


def bump_node_attempt(
    state: Dict[str, Any], node_key: str, error: str = "",
) -> int:
    """node_attempts 记账原语（P3-16）：执行器一次真实执行失败 → 对应节点 +1。

    只记账不决策（ADR-0004）：不发起重试、不改 current_node/completed_nodes；
    消费（「重试/换渠道」引导卡数据派生）归 pipeline_orchestrator 闸预检。
    无 run（Skill 未激活）不建壳返 0；成功清账归 clear_node_attempt。"""
    run = state.get("workflow_run")
    if not isinstance(run, dict) or not run.get("run_id") or not node_key:
        return 0
    entry = (run.get("node_attempts") or {}).get(str(node_key))
    entry = dict(entry) if isinstance(entry, dict) else {}
    entry["count"] = int(entry.get("count") or 0) + 1
    entry["last_error"] = str(error or "")[:200]
    entry["updated_at"] = datetime.now(timezone.utc).isoformat()
    run.setdefault("node_attempts", {})[str(node_key)] = entry
    return int(entry["count"])


def clear_node_attempt(state: Dict[str, Any], node_key: str) -> bool:
    """执行器成功后清失败记账：陈旧计数不得再次触发重试引导。

    返回是否确有账目被清（调用方据此决定是否同步清引导数据）。"""
    run = state.get("workflow_run")
    if not isinstance(run, dict) or not node_key:
        return False
    attempts = run.get("node_attempts") or {}
    return attempts.pop(str(node_key), None) is not None


def project(state: Dict[str, Any], turn_id: str = "") -> Dict[str, Any]:
    """workflow 投影（done 载荷/重连 replay 同源）。

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

    伪轮次（turn_id=artifact:{name} 走 commit_turn）退役，
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
        # 原料闸（任务#35 B2）：v3 requires_inputs 声明优先（任一 required 项
        # 未满足即 waiting_user），未声明回落 v2 script_required，两路不叠加。
        if input_present is False:
            missing = True
        elif input_present is None:
            if registry.skill_requires_inputs(self.skill):
                missing = bool(gates_inputs.missing_required_inputs(self.state, self.skill))
            else:
                missing = registry.script_required_active(self.skill) and not prompt_gates.script_present(self.state)
        else:
            missing = False
        if missing:
            run["status"] = "waiting_user"; run["pending_decision"] = {"token": f"input:{run['run_id']}", "node_id": "analyze_script", "schema": {"type": "input", "required": True}}
            ledger.append("InputRequested", run_id=run["run_id"], node_id="analyze_script", idempotency_key=f"run:{run['run_id']}:input", payload={"status": "waiting_user"})
        run["event_sequence"] = max((x.sequence for x in ledger.by_run(run["run_id"])), default=0)
        if hasattr(self.state_manager, "save"): self.state_manager.save()
        return copy.deepcopy(run)
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

__all__ = ["WorkflowRuntime", "TurnResult", "TurnCommit", "commit_turn", "compile_definition", "sync_run", "record_artifact", "apply_interaction", "reduce_interaction", "bump_node_attempt", "clear_node_attempt"]

# sidecar 声明写入即失效编译缓存（声明变更不被缓存遮蔽）
sidecar.register_write_hook(clear_compile_cache)
