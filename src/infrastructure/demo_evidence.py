"""Compose internally consistent, explicitly recorded evidence for the offline demo."""
from __future__ import annotations

import hashlib
import os
from datetime import timedelta

from src.domain.deployment_evidence import DeploymentEvidenceLedger, DeploymentMarker


def seed_recorded_demo_evidence(incident_use_case, deployment_evidence: DeploymentEvidenceLedger) -> None:
    """Seed two fixture markers around the revision the demo will name."""
    if os.environ.get("MERCURY_SEED_RECORDED_DEMO", "1").strip().lower() in {"0", "false", "no"}:
        return
    correlation = incident_use_case.execute("checkout-api", 60)
    offending = correlation.offending_commit
    if offending is None:
        return
    commits, _ = incident_use_case._gather_commits()
    older = sorted(
        (item for item in commits if item.committed_at < offending.committed_at),
        key=lambda item: item.committed_at,
        reverse=True,
    )
    if not older:
        # Same fetch-edge as the correlator's rollback target: the offending
        # commit can be the oldest one fetched while its parent still exists
        # in history (9885eac). Resolve it through the local checkout when
        # one is behind the use case; anything unresolvable keeps the old
        # behavior of seeding nothing.
        try:
            from src.application.diagnose_incident_use_case import (
                _commit_ref_from_entry,
            )
            local = getattr(incident_use_case, "_local_commits", None)
            entry = (local.parent_of(offending.sha)
                     if local is not None and hasattr(local, "parent_of")
                     else None)
            ref = _commit_ref_from_entry(entry) if entry else None
            older = [ref] if ref is not None else []
        except Exception:
            older = []
    if not older:
        return
    source = "offline-fixture-recorded-mercury-commits-not-service-deployments"
    for position, commit in enumerate((older[0], offending), start=1):
        artifact = hashlib.sha256(f"mercury-recorded-demo:{commit.sha}".encode()).hexdigest()
        deployment_evidence.record(DeploymentMarker.from_values(
            marker_id=f"recorded-demo-{position}-{commit.sha}", service="checkout-api",
            environment="production", revision=commit.sha, artifact_sha256=artifact,
            deployed_at=commit.committed_at,
            health_checked_at=commit.committed_at + timedelta(minutes=1), health_status="HEALTHY",
            health_observed_revision=commit.sha, health_observed_artifact_sha256=artifact,
            source=source, health_url="",
        ))


def recorded_demo_handoff(incident_use_case, deployment_evidence: DeploymentEvidenceLedger) -> dict | None:
    """Return fixed handoff content only when the complete labelled fixture exists."""
    correlation = incident_use_case.execute("checkout-api", 60)
    offending = correlation.offending_commit
    if not correlation.rollback_is_available or offending is None:
        return None
    pair = deployment_evidence.rollback_pair("checkout-api", "production", offending.sha)
    if pair is None or not all(marker.source.startswith("offline-fixture") for marker in pair):
        return None
    _, target = pair
    # The second fact used to read "ANOMALY_ATTRIBUTED: ...", the raw verdict
    # enum, inside Confirmed facts: a numeric cause claim the hero, tile, rows
    # and announcement all refuse to make. It now carries the same
    # claim-strength qualifier the page speaks, in the explanation's own
    # "closest change" words; the enum stays on the diagnosis payload.
    candidate = (
        f"Temporal candidate, not proof of cause: commit {offending.sha} by "
        f"{offending.author} is the closest change inside "
        f"{correlation.attribution_window_minutes} minute attribution window."
    )
    return {
        "incident_id": "checkout-api-active",
        "responder": "D-pad demo responder",
        "current_action": "Reviewing the recorded, evidence-bound rollback target",
        "confirmed_facts": [
            f"{correlation.metric_name} is {correlation.current_value} against baseline "
            f"{correlation.baseline_value}",
            candidate,
            f"Recorded demo marker {target.marker_id} points to {target.revision}",
        ],
        "next_step": (
            "Review the record-only proposal on the TV. This fixture never contacts a "
            "deployment pipeline."
        ),
    }
