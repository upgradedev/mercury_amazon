from datetime import datetime, timedelta, timezone

import pytest

from src.domain.deployment_evidence import (
    DeploymentEvidenceError,
    DeploymentEvidenceLedger,
    DeploymentMarker,
)


def marker(marker_id, revision, digest, hour):
    deployed = datetime(2026, 9, 23, hour, tzinfo=timezone.utc)
    return DeploymentMarker.from_values(
        marker_id=marker_id,
        service="checkout-api",
        environment="production",
        revision=revision,
        artifact_sha256=digest,
        deployed_at=deployed,
        health_checked_at=deployed + timedelta(minutes=2),
        health_status="HEALTHY",
        health_observed_revision=revision,
        health_observed_artifact_sha256=digest,
        health_url="https://test.invalid/health",
    )


def test_last_known_good_is_the_preceding_verified_deployment_not_git_order():
    ledger = DeploymentEvidenceLedger()
    good = marker("good", "release-17", "1" * 64, 8)
    current = marker("current", "release-19", "2" * 64, 9)
    ledger.record(good)
    ledger.record(current)

    assert ledger.rollback_pair("checkout-api", "production", "release-19") == (current, good)
    assert ledger.rollback_pair("checkout-api", "production", "git-commit-between") is None


def test_health_readback_must_match_both_revision_and_artifact():
    with pytest.raises(DeploymentEvidenceError, match="revision does not match"):
        DeploymentMarker.from_values(
            marker_id="bad", service="checkout-api", environment="production",
            revision="release-17", artifact_sha256="1" * 64,
            deployed_at="2026-09-23T08:00:00Z",
            health_checked_at="2026-09-23T08:02:00Z",
            health_status="HEALTHY", health_observed_revision="release-18",
            health_observed_artifact_sha256="1" * 64,
        )


def test_marker_id_is_idempotent_but_cannot_be_reused_for_other_evidence():
    ledger = DeploymentEvidenceLedger()
    first = marker("deploy-1", "release-17", "1" * 64, 8)
    assert ledger.record(first) is first
    assert ledger.record(first) == first
    with pytest.raises(DeploymentEvidenceError, match="different evidence"):
        ledger.record(marker("deploy-1", "release-18", "2" * 64, 9))


def test_ledger_is_bounded():
    ledger = DeploymentEvidenceLedger(max_entries=2)
    ledger.record(marker("one", "r1", "1" * 64, 7))
    ledger.record(marker("two", "r2", "2" * 64, 8))
    ledger.record(marker("three", "r3", "3" * 64, 9))
    assert ledger.get("one") is None
    assert [m.marker_id for m in ledger.timeline("checkout-api", "production")] == ["three", "two"]
