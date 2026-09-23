"""Deployment evidence used to choose a rollback target.

Git history is not deployment history.  This module keeps the two separate: a
revision becomes eligible as a rollback target only after an authenticated
deployment marker and a matching health readback have both been recorded.
"""
from __future__ import annotations

import re
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Protocol

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class DeploymentEvidenceError(ValueError):
    """Raised when a marker is malformed or cannot prove a healthy deployment."""


class DeploymentMarkerStore(Protocol):
    def put_deployment_marker(self, payload: dict) -> None: ...
    def list_deployment_markers(self, service: str, environment: str) -> list[dict]: ...


@dataclass(frozen=True)
class DeploymentMarker:
    marker_id: str
    service: str
    environment: str
    revision: str
    artifact_sha256: str
    deployed_at: datetime
    health_checked_at: datetime
    health_status: str
    health_observed_revision: str
    health_observed_artifact_sha256: str
    source: str = "authenticated-deployment-marker"
    health_url: str = ""

    def __post_init__(self) -> None:
        for name in ("marker_id", "service", "environment", "revision", "source"):
            if not str(getattr(self, name)).strip():
                raise DeploymentEvidenceError(f"{name} must not be empty")
        if self.deployed_at.tzinfo is None or self.health_checked_at.tzinfo is None:
            raise DeploymentEvidenceError("deployment timestamps must include a timezone")
        if not _SHA256.fullmatch(self.artifact_sha256.lower()):
            raise DeploymentEvidenceError("artifact_sha256 must be 64 lowercase hex characters")
        if not _SHA256.fullmatch(self.health_observed_artifact_sha256.lower()):
            raise DeploymentEvidenceError(
                "health_observed_artifact_sha256 must be 64 lowercase hex characters"
            )
        if self.health_status.upper() != "HEALTHY":
            raise DeploymentEvidenceError("only a HEALTHY readback can become rollback evidence")
        if self.health_checked_at < self.deployed_at:
            raise DeploymentEvidenceError("health readback predates the deployment marker")
        if self.health_observed_revision != self.revision:
            raise DeploymentEvidenceError("health readback revision does not match the marker")
        if self.health_observed_artifact_sha256.lower() != self.artifact_sha256.lower():
            raise DeploymentEvidenceError("health readback artifact digest does not match the marker")

    @classmethod
    def from_values(
        cls,
        *,
        marker_id: str,
        service: str,
        environment: str,
        revision: str,
        artifact_sha256: str,
        deployed_at: str | datetime,
        health_checked_at: str | datetime,
        health_status: str,
        health_observed_revision: str,
        health_observed_artifact_sha256: str,
        source: str = "authenticated-deployment-marker",
        health_url: str = "",
    ) -> "DeploymentMarker":
        def parse(value: str | datetime) -> datetime:
            if isinstance(value, datetime):
                parsed = value
            else:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise DeploymentEvidenceError("deployment timestamps must include a timezone")
            return parsed.astimezone(timezone.utc)

        return cls(
            marker_id=marker_id.strip(),
            service=service.strip(),
            environment=environment.strip(),
            revision=revision.strip(),
            artifact_sha256=artifact_sha256.strip().lower(),
            deployed_at=parse(deployed_at),
            health_checked_at=parse(health_checked_at),
            health_status=health_status.strip().upper(),
            health_observed_revision=health_observed_revision.strip(),
            health_observed_artifact_sha256=health_observed_artifact_sha256.strip().lower(),
            source=source.strip(),
            health_url=health_url.strip(),
        )

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["deployed_at"] = self.deployed_at.isoformat()
        payload["health_checked_at"] = self.health_checked_at.isoformat()
        return payload


class DeploymentEvidenceLedger:
    """Thread-safe bounded ledger of verified deployment markers."""

    def __init__(self, max_entries: int = 200, storage: DeploymentMarkerStore | None = None) -> None:
        if max_entries < 2:
            raise ValueError("max_entries must be at least 2")
        self.max_entries = max_entries
        self._markers: list[DeploymentMarker] = []
        self._lock = threading.RLock()
        self._storage = storage

    def clear(self) -> None:
        with self._lock:
            self._markers.clear()

    def record(self, marker: DeploymentMarker) -> DeploymentMarker:
        with self._lock:
            existing = next((m for m in self._markers if m.marker_id == marker.marker_id), None)
            if existing is not None:
                if existing != marker:
                    raise DeploymentEvidenceError(
                        f"marker_id '{marker.marker_id}' already names different evidence"
                    )
                return existing
            self._markers.append(marker)
            self._markers.sort(key=lambda m: (m.deployed_at, m.marker_id))
            if len(self._markers) > self.max_entries:
                del self._markers[: len(self._markers) - self.max_entries]
            if self._storage is not None:
                self._storage.put_deployment_marker(marker.to_dict())
            return marker

    def get(self, marker_id: str) -> DeploymentMarker | None:
        with self._lock:
            return next((m for m in self._markers if m.marker_id == marker_id), None)

    def timeline(self, service: str, environment: str) -> list[DeploymentMarker]:
        with self._lock:
            combined = {
                m.marker_id: m for m in self._markers
                if m.service == service and m.environment == environment
            }
            if self._storage is not None:
                for payload in self._storage.list_deployment_markers(service, environment):
                    marker = DeploymentMarker.from_values(**payload)
                    combined[marker.marker_id] = marker
            return sorted(combined.values(), key=lambda m: (m.deployed_at, m.marker_id), reverse=True)

    def rollback_pair(
        self, service: str, environment: str, offending_revision: str
    ) -> tuple[DeploymentMarker, DeploymentMarker] | None:
        """Return current deployed evidence and the preceding healthy deployment."""
        ordered = list(reversed(self.timeline(service, environment)))
        current_index = next(
            (index for index, marker in enumerate(ordered) if marker.revision == offending_revision),
            None,
        )
        if current_index is None or current_index == 0:
            return None
        return ordered[current_index], ordered[current_index - 1]

    def validate_pair(
        self,
        *,
        service: str,
        environment: str,
        offending_marker_id: str,
        target_marker_id: str,
        target_revision: str,
        target_artifact_sha256: str,
    ) -> tuple[DeploymentMarker, DeploymentMarker]:
        offending = self.get(offending_marker_id)
        target = self.get(target_marker_id)
        if offending is None or target is None:
            raise DeploymentEvidenceError("both deployment marker IDs must exist in the ledger")
        if any(m.service != service or m.environment != environment for m in (offending, target)):
            raise DeploymentEvidenceError("deployment evidence belongs to another service or environment")
        pair = self.rollback_pair(service, environment, offending.revision)
        if pair is None or pair != (offending, target):
            raise DeploymentEvidenceError("target is not the last known healthy deployment before the incident")
        if target.revision != target_revision:
            raise DeploymentEvidenceError("target revision does not match deployment evidence")
        if target.artifact_sha256 != target_artifact_sha256.lower():
            raise DeploymentEvidenceError("target artifact digest does not match deployment evidence")
        return offending, target
