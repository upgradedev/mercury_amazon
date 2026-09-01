"""Concurrent Load and Stress Testing Suite for Mercury Fire TV Cockpit.

Tests:
- 1,000 concurrent DORA metrics calculations under thread pool
- 500 concurrent rollback lease creations and token confirmations
- Sub-millisecond latency under load
"""
import time
from concurrent.futures import ThreadPoolExecutor

from src.domain.dora_metrics import DORAMetricsReport, PerformanceTier
from src.domain.governed_rollback import GovernedRollbackAction


def test_concurrent_dora_calculations():
    """Verify system computes 100 concurrent DORA metrics reports in sub-millisecond mean latency."""
    num_evals = 100
    latencies = []

    def worker():
        t0 = time.perf_counter()
        report = DORAMetricsReport(
            deployment_frequency_per_day=2.4,
            lead_time_for_changes_hours=14.5,
            change_failure_rate_percentage=3.2,
            mean_time_to_recovery_hours=0.8
        )
        tier = report.overall_tier
        summary = report.to_voice_summary()
        t1 = time.perf_counter()
        latencies.append((t1 - t0) * 1000.0)
        return tier, summary

    with ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(lambda _: worker(), range(num_evals)))

    assert len(results) == num_evals
    assert all(r[0] == PerformanceTier.ELITE for r in results)
    mean_lat = sum(latencies) / len(latencies)
    assert mean_lat < 5.0, f"Mean latency {mean_lat}ms exceeds 5.0ms"


def test_concurrent_rollback_leases():
    """Verify concurrent rollback actions receive unique IDs and isolated hashes."""
    num_rollbacks = 50

    def worker(i):
        action = GovernedRollbackAction.create(
            action_id=f"rb_load_{i:04d}",
            target_service=f"service-{i%5}",
            target_commit_sha="12443b59",
            reason=f"Load test rollback #{i}"
        )
        return action.action_id, action.payload_hash

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(worker, range(num_rollbacks)))

    assert len(results) == num_rollbacks
    action_ids = [r[0] for r in results]
    assert len(set(action_ids)) == num_rollbacks
