"""Bounded shared incident state for responder handoff."""
from __future__ import annotations

import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Protocol

from src.domain.incident_correlation import CorrelationVerdict

#: A confirmed fact may not carry this code. Naming a change is a temporal candidate,
#: not proof of cause, and the handoff says so in words (IncidentCorrelation.handoff_fact).
CAUSE_CODE = CorrelationVerdict.ANOMALY_ATTRIBUTED.value


class HandoffConflict(ValueError):
    """Raised for stale revisions or malformed handoff updates."""


class HandoffStateStore(Protocol):
    def get_handoff(self, incident_id: str) -> dict | None: ...
    def put_handoff(self, payload: dict, expected_revision: int) -> None: ...


@dataclass(frozen=True)
class IncidentHandoff:
    incident_id: str
    responder: str
    current_action: str
    confirmed_facts: tuple[str, ...]
    next_step: str
    revision: int
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["confirmed_facts"] = list(self.confirmed_facts)
        payload["updated_at"] = self.updated_at.isoformat()
        return payload


class IncidentHandoffStore:
    """Shared state with optimistic concurrency and an optional durable adapter."""

    def __init__(self, max_incidents: int = 50, storage: HandoffStateStore | None = None) -> None:
        self.max_incidents = max_incidents
        self._items: dict[str, IncidentHandoff] = {}
        self._lock = threading.RLock()
        self._storage = storage

    def clear(self) -> None:
        with self._lock:
            self._items.clear()

    def get(self, incident_id: str) -> IncidentHandoff | None:
        with self._lock:
            current = self._items.get(incident_id)
            if self._storage is None:
                return current
            payload = self._storage.get_handoff(incident_id)
            if payload is None:
                return current
            item = IncidentHandoff(
                incident_id=payload["incident_id"], responder=payload["responder"],
                current_action=payload["current_action"],
                confirmed_facts=tuple(payload["confirmed_facts"]), next_step=payload["next_step"],
                revision=int(payload["revision"]),
                updated_at=datetime.fromisoformat(payload["updated_at"]),
            )
            self._items[incident_id] = item
            return item

    def update(
        self,
        *,
        incident_id: str,
        responder: str,
        current_action: str,
        confirmed_facts: list[str],
        next_step: str,
        expected_revision: int | None,
    ) -> IncidentHandoff:
        values = (incident_id, responder, current_action, next_step)
        if any(not value.strip() for value in values):
            raise HandoffConflict("incident, responder, current action and next step are required")
        facts = tuple(dict.fromkeys(fact.strip() for fact in confirmed_facts if fact.strip()))
        if not facts:
            raise HandoffConflict("at least one confirmed fact is required")
        if len(facts) > 10:
            raise HandoffConflict("at most 10 confirmed facts may be shared")
        if any(CAUSE_CODE in fact for fact in facts):
            raise HandoffConflict(
                f"a confirmed fact may not state {CAUSE_CODE}: a named change is a temporal "
                "candidate, not proof of cause"
            )
        with self._lock:
            current = self.get(incident_id)
            actual_revision = current.revision if current else 0
            if expected_revision is not None and expected_revision != actual_revision:
                raise HandoffConflict(
                    f"stale handoff revision {expected_revision}; current revision is {actual_revision}"
                )
            item = IncidentHandoff(
                incident_id=incident_id,
                responder=responder,
                current_action=current_action,
                confirmed_facts=facts,
                next_step=next_step,
                revision=actual_revision + 1,
            )
            if self._storage is not None:
                try:
                    self._storage.put_handoff(item.to_dict(), actual_revision)
                except Exception as exc:
                    if exc.__class__.__name__ == "StateConflict":
                        raise HandoffConflict(str(exc)) from exc
                    raise
            self._items[incident_id] = item
            if len(self._items) > self.max_incidents:
                oldest = min(self._items.values(), key=lambda entry: entry.updated_at)
                del self._items[oldest.incident_id]
            return item
