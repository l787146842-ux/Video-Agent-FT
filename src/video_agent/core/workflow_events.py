# -*- coding: utf-8 -*-
"""Durable ordered workflow event ledger."""
from __future__ import annotations

import copy
import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional

EVENT_TYPES = frozenset({
    "RunStarted", "InputRequested", "InputAccepted", "StageStarted",
    "ToolStarted", "ToolSucceeded", "ToolFailed", "ArtifactCommitted",
    "DecisionOpened", "DecisionResolved", "StageSucceeded", "TurnCommitted",
    "RunFailed", "RunCancelled", "RunCompleted",
})


class EventLedgerError(ValueError):
    """事件账本通用错误。"""
    pass


class EventIdempotencyConflict(EventLedgerError):
    """同幂等键但载荷摘要冲突。"""
    pass


def _now() -> str:
    """当前 UTC 时间的 ISO 字符串。"""
    return datetime.now(timezone.utc).isoformat()


def _digest(value: Any) -> str:
    """对任意值做规范化 JSON 序列化后取 sha256 十六进制摘要。"""
    raw = json.dumps(
        value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), default=str,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class WorkflowEvent:
    """不可变的有序 workflow 事件记录。"""

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
        """校验必填字段与载荷类型，非法即抛 EventLedgerError。"""
        if (
            not self.event_id
            or not self.run_id
            or self.sequence < 1
            or not self.event_type
            or not isinstance(self.payload, dict)
        ):
            raise EventLedgerError("invalid workflow event")

    @classmethod
    def create(cls, run_id: str, sequence: int, event_type: str, **kwargs: Any) -> "WorkflowEvent":
        """从关键字参数构造事件（缺省 event_id/timestamp 自动生成）。"""
        return cls(
            event_id=str(kwargs.get("event_id") or f"evt_{uuid.uuid4().hex}"),
            run_id=str(run_id),
            sequence=int(sequence),
            event_type=str(event_type),
            turn_id=str(kwargs.get("turn_id") or ""),
            node_id=str(kwargs.get("node_id") or ""),
            idempotency_key=str(kwargs.get("idempotency_key") or ""),
            timestamp=str(kwargs.get("timestamp") or _now()),
            payload=copy.deepcopy(dict(kwargs.get("payload") or {})),
        )

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "WorkflowEvent":
        """从字典还原事件（兼容 snake_case 与 camelCase 键）。"""
        return cls(
            event_id=str(raw.get("event_id") or raw.get("eventId") or ""),
            run_id=str(raw.get("run_id") or raw.get("runId") or ""),
            sequence=int(raw.get("sequence") or 0),
            event_type=str(raw.get("event_type") or raw.get("eventType") or ""),
            turn_id=str(raw.get("turn_id") or raw.get("turnId") or ""),
            node_id=str(raw.get("node_id") or raw.get("nodeId") or ""),
            idempotency_key=str(raw.get("idempotency_key") or raw.get("idempotencyKey") or ""),
            timestamp=str(raw.get("timestamp") or _now()),
            payload=dict(raw.get("payload") or {}),
        )

    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典（payload 深拷贝）。"""
        return {
            "event_id": self.event_id,
            "run_id": self.run_id,
            "sequence": self.sequence,
            "turn_id": self.turn_id,
            "event_type": self.event_type,
            "node_id": self.node_id,
            "idempotency_key": self.idempotency_key,
            "timestamp": self.timestamp,
            "payload": copy.deepcopy(self.payload),
        }

    @property
    def payload_digest(self) -> str:
        """事件身份字段 + payload 的规范化摘要（幂等冲突判定依据）。"""
        return _digest({
            "run_id": self.run_id,
            "turn_id": self.turn_id,
            "event_type": self.event_type,
            "node_id": self.node_id,
            "payload": self.payload,
        })


class EventLedger:
    """写入 state 的持久有序事件账本（幂等追加 + 按 run 检索）。"""

    def __init__(self, state: Dict[str, Any], state_key: str = "workflow_events"):
        """绑定 state 与账本键，并校验既有条目可还原。"""
        self.state, self.state_key = state, state_key
        raw = state.setdefault(state_key, [])
        if not isinstance(raw, list):
            raise EventLedgerError(f"{state_key} must be a list")
        for item in raw:
            WorkflowEvent.from_dict(item)
        # by_run 索引 + 事件缓存：账本追加式增长，实例内多次检索
        #（by_run/next_sequence/find_turn/events）复用同一份重建结果，
        # 避免每次全表 from_dict 重建 + 线性过滤（O(n)/次 → 摊销 O(1) 建 + O(k)/run）。
        self._events_cache: List[WorkflowEvent] = []
        self._index: Dict[str, List[WorkflowEvent]] = {}
        self._indexed: int = 0  # 已纳入缓存/索引的 raw 前缀长度
        # 尾部指纹：已缓存 raw 末元素的 event_id——用于探测「等长但原地换内容」
        self._tail_id: Optional[str] = None

    @staticmethod
    def _raw_tail_id(raw: List[Any]) -> Optional[str]:
        """raw 末元素的 event_id 指纹（空列表/非 dict 末元素返 None）。"""
        if not raw:
            return None
        last = raw[-1]
        if isinstance(last, dict):
            return str(last.get("event_id") or "")
        return None

    def _sync(self) -> None:
        """按 raw 列表长度 + 尾部指纹增量同步事件缓存与 by_run 索引。

        追加式增长：只重建新增尾部；raw 被外部整体替换/截断（长度回退），
        或等长但尾部指纹（末元素 event_id）变化（原地换内容）时全量重建，
        保证缓存/索引与账本一致（原仅按长度判增量，等长换内容会漏重建，
        与 docstring 承诺不符）。
        """
        raw = self.state[self.state_key]
        n = len(raw)
        tail_id = self._raw_tail_id(raw)
        if n == self._indexed and tail_id == self._tail_id:
            return
        if n < self._indexed or (n == self._indexed and tail_id != self._tail_id):
            # 截断/重载/等长换内容：丢弃旧缓存全量重建
            self._events_cache = []
            self._index = {}
            self._indexed = 0
        for item in raw[self._indexed:]:
            ev = WorkflowEvent.from_dict(item)
            self._events_cache.append(ev)
            self._index.setdefault(ev.run_id, []).append(ev)
        self._indexed = n
        self._tail_id = tail_id

    @property
    def events(self) -> List[WorkflowEvent]:
        """账本内全部事件（按存储顺序还原；实例内复用缓存）。"""
        self._sync()
        return list(self._events_cache)

    def next_sequence(self, run_id: str) -> int:
        """指定 run 的下一个序号（现有最大序号 + 1；走 by_run 索引）。"""
        self._sync()
        return max((e.sequence for e in self._index.get(str(run_id), ())), default=0) + 1

    def _find(self, key: str, run_id: str = "") -> Optional[WorkflowEvent]:
        """按幂等键（可选限定 run）查找既有事件。"""
        if not key:
            return None
        self._sync()
        return next(
            (
                e for e in self._events_cache
                if e.idempotency_key == key and (not run_id or e.run_id == str(run_id))
            ),
            None,
        )

    def append(
        self,
        event_type: str,
        *,
        run_id: str,
        turn_id: str = "",
        node_id: str = "",
        idempotency_key: str = "",
        payload: Optional[Mapping[str, Any]] = None,
        timestamp: Optional[str] = None,
    ) -> WorkflowEvent:
        """幂等追加事件：命中同键且摘要一致则返回旧事件，冲突则抛错。"""
        if event_type not in EVENT_TYPES:
            raise EventLedgerError(f"unsupported workflow event type: {event_type!r}")
        data = dict(payload or {})
        old = self._find(idempotency_key, run_id)
        if old:
            probe = WorkflowEvent.create(
                run_id, old.sequence, event_type,
                turn_id=turn_id, node_id=node_id,
                idempotency_key=idempotency_key, payload=data,
            )
            if probe.payload_digest != old.payload_digest:
                raise EventIdempotencyConflict(idempotency_key)
            return old
        event = WorkflowEvent.create(
            run_id, self.next_sequence(run_id), event_type,
            turn_id=turn_id, node_id=node_id,
            idempotency_key=idempotency_key, payload=data, timestamp=timestamp,
        )
        self.state[self.state_key].append(event.to_dict())
        return event

    def by_run(self, run_id: str, after_sequence: int = 0) -> List[WorkflowEvent]:
        """返回指定 run 中序号大于 after_sequence 的事件（走 by_run 索引，
        不再全表线性推导）。"""
        self._sync()
        after = int(after_sequence)
        return [e for e in self._index.get(str(run_id), ()) if e.sequence > after]

    def find_turn(self, run_id: str, turn_id: str) -> Optional[WorkflowEvent]:
        """逆序查找指定 run/turn 的最近一条 TurnCommitted 事件（走 by_run 索引）。"""
        self._sync()
        return next(
            (
                e for e in reversed(self._index.get(str(run_id), ()))
                if e.turn_id == str(turn_id)
                and e.event_type == "TurnCommitted"
            ),
            None,
        )


__all__ = [
    "EVENT_TYPES", "EventLedger", "EventLedgerError",
    "EventIdempotencyConflict", "WorkflowEvent",
]
