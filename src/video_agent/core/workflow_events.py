# -*- coding: utf-8 -*-
"""Durable ordered workflow event ledger."""
from __future__ import annotations
import copy, hashlib, json, uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional

EVENT_TYPES = frozenset({"RunStarted", "InputRequested", "InputAccepted", "StageStarted",
    "ToolStarted", "ToolSucceeded", "ToolFailed", "ArtifactCommitted",
    "DecisionOpened", "DecisionResolved", "StageSucceeded", "TurnCommitted",
    "RunFailed", "RunCancelled", "RunCompleted"})
class EventLedgerError(ValueError): pass
class EventIdempotencyConflict(EventLedgerError): pass
def _now() -> str: return datetime.now(timezone.utc).isoformat()
def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()

@dataclass(frozen=True)
class WorkflowEvent:
    event_id: str
    run_id: str
    sequence: int
    event_type: str
    turn_id: str = ""
    node_id: str = ""
    idempotency_key: str = ""
    timestamp: str = field(default_factory=_now)
    payload: Dict[str, Any] = field(default_factory=dict)
    def __post_init__(self) -> None:
        if not self.event_id or not self.run_id or self.sequence < 1 or not self.event_type or not isinstance(self.payload, dict):
            raise EventLedgerError("invalid workflow event")
    @classmethod
    def create(cls, run_id: str, sequence: int, event_type: str, **kwargs: Any) -> "WorkflowEvent":
        return cls(event_id=str(kwargs.get("event_id") or f"evt_{uuid.uuid4().hex}"), run_id=str(run_id), sequence=int(sequence), event_type=str(event_type), turn_id=str(kwargs.get("turn_id") or ""), node_id=str(kwargs.get("node_id") or ""), idempotency_key=str(kwargs.get("idempotency_key") or ""), timestamp=str(kwargs.get("timestamp") or _now()), payload=copy.deepcopy(dict(kwargs.get("payload") or {})))
    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "WorkflowEvent":
        return cls(event_id=str(raw.get("event_id") or raw.get("eventId") or ""), run_id=str(raw.get("run_id") or raw.get("runId") or ""), sequence=int(raw.get("sequence") or 0), event_type=str(raw.get("event_type") or raw.get("eventType") or ""), turn_id=str(raw.get("turn_id") or raw.get("turnId") or ""), node_id=str(raw.get("node_id") or raw.get("nodeId") or ""), idempotency_key=str(raw.get("idempotency_key") or raw.get("idempotencyKey") or ""), timestamp=str(raw.get("timestamp") or _now()), payload=dict(raw.get("payload") or {}))
    def to_dict(self) -> Dict[str, Any]:
        return {"event_id": self.event_id, "run_id": self.run_id, "sequence": self.sequence, "turn_id": self.turn_id, "event_type": self.event_type, "node_id": self.node_id, "idempotency_key": self.idempotency_key, "timestamp": self.timestamp, "payload": copy.deepcopy(self.payload)}
    @property
    def payload_digest(self) -> str: return _digest({"run_id": self.run_id, "turn_id": self.turn_id, "event_type": self.event_type, "node_id": self.node_id, "payload": self.payload})

class EventLedger:
    def __init__(self, state: Dict[str, Any], state_key: str = "workflow_events"):
        self.state, self.state_key = state, state_key
        raw = state.setdefault(state_key, [])
        if not isinstance(raw, list): raise EventLedgerError(f"{state_key} must be a list")
        for item in raw: WorkflowEvent.from_dict(item)
    @property
    def events(self) -> List[WorkflowEvent]: return [WorkflowEvent.from_dict(x) for x in self.state[self.state_key]]
    def next_sequence(self, run_id: str) -> int: return max((e.sequence for e in self.events if e.run_id == str(run_id)), default=0) + 1
    def _find(self, key: str, run_id: str = "") -> Optional[WorkflowEvent]:
        return next((e for e in self.events if e.idempotency_key == key and (not run_id or e.run_id == str(run_id))), None) if key else None
    def append(self, event_type: str, *, run_id: str, turn_id: str = "", node_id: str = "", idempotency_key: str = "", payload: Optional[Mapping[str, Any]] = None, timestamp: Optional[str] = None) -> WorkflowEvent:
        if event_type not in EVENT_TYPES: raise EventLedgerError(f"unsupported workflow event type: {event_type!r}")
        data = dict(payload or {}); old = self._find(idempotency_key, run_id)
        if old:
            probe = WorkflowEvent.create(run_id, old.sequence, event_type, turn_id=turn_id, node_id=node_id, idempotency_key=idempotency_key, payload=data)
            if probe.payload_digest != old.payload_digest: raise EventIdempotencyConflict(idempotency_key)
            return old
        event = WorkflowEvent.create(run_id, self.next_sequence(run_id), event_type, turn_id=turn_id, node_id=node_id, idempotency_key=idempotency_key, payload=data, timestamp=timestamp)
        self.state[self.state_key].append(event.to_dict()); return event
    def by_run(self, run_id: str, after_sequence: int = 0) -> List[WorkflowEvent]: return [e for e in self.events if e.run_id == str(run_id) and e.sequence > int(after_sequence)]
    def find_turn(self, run_id: str, turn_id: str) -> Optional[WorkflowEvent]: return next((e for e in reversed(self.events) if e.run_id == str(run_id) and e.turn_id == str(turn_id) and e.event_type == "TurnCommitted"), None)

__all__ = ["EVENT_TYPES", "EventLedger", "EventLedgerError", "EventIdempotencyConflict", "WorkflowEvent"]
