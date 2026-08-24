# -*- coding: utf-8 -*-
"""Atomic, idempotent TurnCommit for workflow state and projections."""
from __future__ import annotations
import asyncio
import copy, inspect, uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple, Union
from .workflow_events import EventLedger, WorkflowEvent

class WorkflowCommitError(ValueError): pass
class WorkflowConcurrencyError(WorkflowCommitError): pass
def _now() -> str: return datetime.now(timezone.utc).isoformat()
def _dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, Mapping): return copy.deepcopy(dict(value))
    if hasattr(value, "to_dict"): return _dict(value.to_dict())
    if hasattr(value, "model_dump"): return _dict(value.model_dump())
    raise TypeError(type(value).__name__)

@dataclass
class ArtifactRef:
    name: str
    kind: str = "artifact"
    artifact_id: str = ""
    uri: str = ""
    content: Any = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    @classmethod
    def from_value(cls, value: Any) -> "ArtifactRef":
        if isinstance(value, str): return cls(value)
        raw = _dict(value); name = str(raw.get("name") or raw.get("id") or "")
        if not name: raise WorkflowCommitError("artifact.name is required")
        return cls(name, str(raw.get("kind") or raw.get("type") or "artifact"), str(raw.get("artifact_id") or raw.get("id") or ""), str(raw.get("uri") or raw.get("path") or ""), copy.deepcopy(raw.get("content")), copy.deepcopy(raw.get("metadata") or {}))
    def to_dict(self) -> Dict[str, Any]:
        out = {"name": self.name, "kind": self.kind, "artifact_id": self.artifact_id or f"artifact_{uuid.uuid4().hex}", "uri": self.uri, "metadata": copy.deepcopy(self.metadata)}
        if self.content is not None: out["content"] = copy.deepcopy(self.content)
        return out

@dataclass
class DecisionRequest:
    token: str
    prompt: str = ""
    options: List[Dict[str, Any]] = field(default_factory=list)
    node_id: str = ""
    schema: Dict[str, Any] = field(default_factory=dict)
    @classmethod
    def from_value(cls, value: Any) -> Optional["DecisionRequest"]:
        if not value: return None
        raw = _dict(value); options = raw.get("options") or []
        if not isinstance(options, list): raise WorkflowCommitError("decision options must be a list")
        return cls(str(raw.get("token") or raw.get("id") or f"decision_{uuid.uuid4().hex}"), str(raw.get("prompt") or raw.get("question") or ""), [dict(x) if isinstance(x, Mapping) else {"value": x} for x in options], str(raw.get("node_id") or ""), copy.deepcopy(raw.get("schema") or {}))
    def to_dict(self) -> Dict[str, Any]: return {"token": self.token, "prompt": self.prompt, "options": copy.deepcopy(self.options), "node_id": self.node_id, "schema": copy.deepcopy(self.schema)}

@dataclass
class TurnResult:
    turn_id: str = ""
    body: str = ""
    artifacts: List[ArtifactRef] = field(default_factory=list)
    timeline_events: List[Dict[str, Any]] = field(default_factory=list)
    decision_request: Optional[DecisionRequest] = None
    next_transition: Dict[str, Any] = field(default_factory=dict)
    node_id: str = ""
    run_version: Optional[int] = None
    persist_message: bool = False
    def __post_init__(self) -> None:
        self.turn_id = str(self.turn_id or f"turn_{uuid.uuid4().hex}")
        self.body = str(self.body or "")
        self.artifacts = [x if isinstance(x, ArtifactRef) else ArtifactRef.from_value(x) for x in (self.artifacts or [])]
        self.timeline_events = [copy.deepcopy(dict(x)) for x in (self.timeline_events or []) if isinstance(x, Mapping)]
        self.decision_request = DecisionRequest.from_value(self.decision_request)
        self.next_transition = copy.deepcopy(dict(self.next_transition or {}))
    @classmethod
    def from_value(cls, value: Any) -> "TurnResult":
        if isinstance(value, cls): return copy.deepcopy(value)
        raw = _dict(value)
        return cls(str(raw.get("turn_id") or raw.get("turnId") or ""), str(raw.get("body") if raw.get("body") is not None else raw.get("text") or ""), list(raw.get("artifacts") or []), list(raw.get("timeline_events") or raw.get("timelineEvents") or []), raw.get("decision_request") or raw.get("decisionRequest"), raw.get("next_transition") or raw.get("nextTransition") or {}, str(raw.get("node_id") or raw.get("nodeId") or ""), int(raw["run_version"]) if raw.get("run_version") is not None else None, bool(raw.get("persist_message", False)))
    def to_dict(self) -> Dict[str, Any]: return {"turn_id": self.turn_id, "body": self.body, "artifacts": [x.to_dict() for x in self.artifacts], "timeline_events": copy.deepcopy(self.timeline_events), "decision_request": self.decision_request.to_dict() if self.decision_request else None, "next_transition": copy.deepcopy(self.next_transition), "node_id": self.node_id, "run_version": self.run_version, "persist_message": self.persist_message}

@dataclass
class TurnCommit:
    turn_id: str
    run: Dict[str, Any]
    result: TurnResult
    events: List[WorkflowEvent]
    idempotent: bool = False
    persisted: bool = False
    event_sequence: int = 0
    def to_dict(self) -> Dict[str, Any]: return {"turn_id": self.turn_id, "run": copy.deepcopy(self.run), "result": self.result.to_dict(), "events": [e.to_dict() for e in self.events], "idempotent": self.idempotent, "persisted": self.persisted, "event_sequence": self.event_sequence}
    def get(self, key: str, default: Any = None) -> Any: return self.to_dict().get(key, default)
    def __getitem__(self, key: str) -> Any: return self.to_dict()[key]

def _target(target: Any) -> Tuple[Dict[str, Any], Optional[Any]]:
    if isinstance(target, dict): return target, None
    state = getattr(target, "state_dict", None)
    if isinstance(state, dict): return state, target
    raise TypeError("commit target must be state dict or StateManager")

def commit_turn(target: Any, result: Union[TurnResult, Mapping[str, Any]], *, run_id: str = "", skill: str = "", expected_version: Optional[int] = None, persist: bool = True, persist_message: Optional[bool] = None, publish: Optional[Callable[[WorkflowEvent], Any]] = None) -> TurnCommit:
    state, svc = _target(target); turn = TurnResult.from_value(result)
    if persist_message is not None: turn.persist_message = bool(persist_message)
    run = state.setdefault("workflow_run", {}); run_id = str(run.get("run_id") or run_id or f"run_{uuid.uuid4().hex}")
    for old in reversed(state.setdefault("workflow_turns", [])):
        if isinstance(old, Mapping) and str(old.get("turn_id") or "") == turn.turn_id:
            events = [WorkflowEvent.from_dict(x) for x in old.get("events") or []]
            return TurnCommit(turn.turn_id, copy.deepcopy(run), TurnResult.from_value(old.get("result") or old), events, True, True, int(run.get("event_sequence") or 0))
    version = int(run.get("run_version") or run.get("version") or 0); expected = expected_version if expected_version is not None else turn.run_version
    if expected is not None and int(expected) != version: raise WorkflowConcurrencyError(f"expected {expected}, current {version}")
    original = copy.deepcopy(state)
    try:
        now = _now(); run.setdefault("run_id", run_id); run.setdefault("workflow_id", skill or "adhoc"); run.setdefault("definition_revision", ""); run.setdefault("definition_hash", ""); run.setdefault("status", "running"); run.setdefault("current_node", turn.node_id); run.setdefault("completed_nodes", []); run.setdefault("pending_decision", None); run.setdefault("artifacts", []); run.setdefault("failure_state", None); run.setdefault("created_at", now)
        ledger = EventLedger(state); events = []; node_id = turn.node_id or str(run.get("current_node") or "")
        for index, item in enumerate(turn.timeline_events):
            etype = str(item.get("event_type") or item.get("eventType") or "ToolSucceeded")
            if etype not in {"StageStarted", "ToolStarted", "ToolSucceeded", "ToolFailed", "InputRequested", "InputAccepted", "DecisionOpened", "DecisionResolved"}: etype = "ToolSucceeded"
            events.append(ledger.append(etype, run_id=run_id, turn_id=turn.turn_id, node_id=node_id, idempotency_key=str(item.get("idempotency_key") or f"{turn.turn_id}:timeline:{index}"), payload=dict(item.get("payload") or item)))
        artifacts = []
        for index, artifact in enumerate(turn.artifacts):
            record = artifact.to_dict(); artifacts.append(record); name = record["name"]
            if record.get("kind") == "document" and record.get("content") is not None:
                docs = state.setdefault("documents", []); existing = next((x for x in docs if isinstance(x, Mapping) and x.get("name") == name), None)
                if existing is None: docs.insert(0, {"id": f"doc_{uuid.uuid4().hex}", "name": name, "content": copy.deepcopy(record["content"]), "created_at": now, "updated_at": now})
                else: existing["content"], existing["updated_at"] = copy.deepcopy(record["content"]), now
            if name not in run["artifacts"]: run["artifacts"].append(name)
            all_artifacts = state.setdefault("workflow_artifacts", [])
            if not any(isinstance(x, Mapping) and x.get("name") == name for x in all_artifacts): all_artifacts.append(copy.deepcopy(record))
            events.append(ledger.append("ArtifactCommitted", run_id=run_id, turn_id=turn.turn_id, node_id=node_id, idempotency_key=f"{turn.turn_id}:artifact:{record.get('artifact_id') or index}", payload=record))
        decision = turn.decision_request
        if decision:
            decision.node_id = decision.node_id or node_id; run["pending_decision"] = decision.to_dict(); run["status"] = "waiting_user"
            events.append(ledger.append("DecisionOpened", run_id=run_id, turn_id=turn.turn_id, node_id=node_id, idempotency_key=f"{turn.turn_id}:decision:{decision.token}", payload=decision.to_dict()))
        transition = turn.next_transition; completed = transition.get("completed_node") or transition.get("complete_node")
        if completed:
            completed = str(completed)
            if completed not in run["completed_nodes"]: run["completed_nodes"].append(completed)
            events.append(ledger.append("StageSucceeded", run_id=run_id, turn_id=turn.turn_id, node_id=completed, idempotency_key=f"{turn.turn_id}:stage:{completed}", payload={"node_id": completed}))
        if transition.get("next_node") is not None: run["current_node"] = str(transition.get("next_node") or "")
        if transition.get("status"): run["status"] = str(transition["status"])
        elif not decision: run["status"] = "ready"
        if transition.get("failure_state") is not None: run["failure_state"] = copy.deepcopy(transition["failure_state"])
        if transition.get("run_completed") or run.get("status") == "completed":
            run["status"] = "completed"; events.append(ledger.append("RunCompleted", run_id=run_id, turn_id=turn.turn_id, node_id=node_id, idempotency_key=f"{turn.turn_id}:run-completed", payload={}))
        events.append(ledger.append("TurnCommitted", run_id=run_id, turn_id=turn.turn_id, node_id=node_id, idempotency_key=f"turn:{turn.turn_id}", payload={"body": turn.body, "artifact_names": [x["name"] for x in artifacts], "decision_token": decision.token if decision else ""}))
        run["run_version"] = version + 1; run["version"] = run["run_version"]; run["event_sequence"] = max((x.sequence for x in events), default=int(run.get("event_sequence") or 0)); run["updated_at"] = now
        state["workflow_turns"].append({"turn_id": turn.turn_id, "run_id": run_id, "result": turn.to_dict(), "events": [x.to_dict() for x in events], "run_version": run["run_version"], "committed_at": now})
        if turn.persist_message:
            messages = state.setdefault("chatMessages", [])
            if not any(isinstance(x, Mapping) and x.get("turnId") == turn.turn_id for x in messages):
                entry = {"sender": "agent", "text": turn.body, "turnId": turn.turn_id}
                if artifacts: entry["docCard"] = artifacts[0]["name"]
                if decision: entry["decisionRequest"] = decision.to_dict()
                messages.append(entry)
        if svc is not None and persist: svc.save()
    except Exception:
        state.clear(); state.update(original); raise
    if publish:
        for event in events:
            value = publish(event)
            if inspect.isawaitable(value):
                asyncio.create_task(value)
    return TurnCommit(turn.turn_id, copy.deepcopy(run), turn, events, False, bool(svc is not None and persist), int(run.get("event_sequence") or 0))

__all__ = ["ArtifactRef", "DecisionRequest", "TurnCommit", "TurnResult", "WorkflowCommitError", "WorkflowConcurrencyError", "commit_turn"]
