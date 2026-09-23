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
    return {
        "incident_id": "checkout-api-active",
        "responder": "D-pad demo responder",
        "current_action": "Reviewing the recorded, evidence-bound rollback target",
        "confirmed_facts": [
            f"{correlation.metric_name} is {correlation.current_value} against baseline "
            f"{correlation.baseline_value}",
            f"{correlation.verdict.value}: {correlation.explanation}",
            f"Recorded demo marker {target.marker_id} points to {target.revision}",
        ],
        "next_step": (
            "Review the record-only proposal on the TV. This fixture never contacts a "
            "deployment pipeline."
        ),
    }
