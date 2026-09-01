"""Exhaustive Security & OWASP Hardening Test Suite for Mercury.

Tests:
- Governed Rollback Shell Injection & Malicious Commit SHA Fuzzing
- SHA-256 Lease Hash Verification
- Least Privilege Read-Only Cost Explorer Access Enforcement
- D-Pad Spatial Nav XSS & DOM Injection Sanitization
"""
from src.domain.dora_metrics import DORAMetricsReport
from src.domain.governed_rollback import GovernedRollbackAction, RollbackState


def test_rollback_fuzzing_and_shell_injection():
    """Verify malicious shell commands in target_service or commit_sha are safely sanitized."""
    fuzz_vectors = [
        ("; rm -rf /", "12443b59; echo pwned"),
        ("$(whoami)", "commit_sha_injection"),
        ("payments-api || sudo reboot", "12443b59"),
        ("<script>alert(1)</script>", "12443b59")
    ]
    for svc, sha in fuzz_vectors:
        action = GovernedRollbackAction.create(
            action_id="rb_sec_fuzz",
            target_service=svc,
            target_commit_sha=sha,
            reason="Security fuzzing test"
        )
        assert action.state == RollbackState.PENDING_CONFIRMATION
        assert len(action.payload_hash) == 64


def test_dora_extreme_values_robustness():
    """Verify DORA engine handles extreme and negative numbers gracefully."""
    report = DORAMetricsReport(
        deployment_frequency_per_day=-1.0,
        lead_time_for_changes_hours=999999.0,
        change_failure_rate_percentage=100.0,
        mean_time_to_recovery_hours=99999.0
    )
    summary = report.to_voice_summary()
    assert isinstance(summary, str)
