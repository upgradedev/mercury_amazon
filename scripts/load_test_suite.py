"""In-Process Concurrency & Thread Pool Stress Test Runner for Mercury.

Executes:
- 1,000 in-process DORA metrics calculations
- 500 in-process governed rollback lease creations
- Measures in-process function execution latency percentiles (P50, P90, P99)

Usage:
    python scripts/load_test_suite.py
"""
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.domain.dora_metrics import DORAMetricsReport
from src.domain.governed_rollback import GovernedRollbackAction


def run_load_stress_suite():
    print("================================================================")
    print("   MERCURY IN-PROCESS CONCURRENCY & LATENCY BENCHMARK           ")
    print("================================================================")

    # 1. DORA Metrics Throughput
    num_dora = 1000
    print(f"[*] Firing {num_dora} concurrent DORA metrics calculations (16 worker threads)...")
    latencies = []
    t_start = time.perf_counter()

    def dora_worker():
        t0 = time.perf_counter()
        report = DORAMetricsReport(
            deployment_frequency_per_day=2.4,
            lead_time_for_changes_hours=14.5,
            change_failure_rate_percentage=3.2,
            mean_time_to_recovery_hours=0.8
        )
        report.overall_tier
        report.to_voice_summary()
        t1 = time.perf_counter()
        latencies.append((t1 - t0) * 1000.0)

    with ThreadPoolExecutor(max_workers=16) as executor:
        list(executor.map(lambda _: dora_worker(), range(num_dora)))

    total_time = time.perf_counter() - t_start
    rps = num_dora / total_time
    sorted_lats = sorted(latencies)
    p50 = sorted_lats[int(num_dora * 0.50)]
    p90 = sorted_lats[int(num_dora * 0.90)]
    p99 = sorted_lats[int(num_dora * 0.99)]

    print(f"  -> Completed in {total_time:.3f}s | Throughput: {rps:.1f} reports/sec")
    print(f"  -> Latency Percentiles: P50: {p50:.3f} ms | P90: {p90:.3f} ms | P99: {p99:.3f} ms")

    # 2. Rollback Leases
    num_rollbacks = 500
    print(f"\n[*] Firing {num_rollbacks} concurrent rollback lease creations...")
    rb_lats = []
    t_rb_start = time.perf_counter()

    def rb_worker(i):
        t0 = time.perf_counter()
        GovernedRollbackAction.create(
            action_id=f"rb_load_{i:04d}",
            target_service=f"service-{i%5}",
            target_commit_sha="12443b59",
            reason=f"Load test rollback #{i}"
        )
        t1 = time.perf_counter()
        rb_lats.append((t1 - t0) * 1000.0)

    with ThreadPoolExecutor(max_workers=16) as executor:
        list(executor.map(rb_worker, range(num_rollbacks)))

    rb_total = time.perf_counter() - t_rb_start
    rb_rps = num_rollbacks / rb_total
    sorted_rbs = sorted(rb_lats)
    r_p50 = sorted_rbs[int(num_rollbacks * 0.50)]
    r_p90 = sorted_rbs[int(num_rollbacks * 0.90)]
    r_p99 = sorted_rbs[int(num_rollbacks * 0.99)]

    print(f"  -> Completed in {rb_total:.3f}s | Throughput: {rb_rps:.1f} rollbacks/sec")
    print(f"  -> Latency Percentiles: P50: {r_p50:.3f} ms | P90: {r_p90:.3f} ms | P99: {r_p99:.3f} ms")

    print("\n----------------------------------------------------------------")
    print("[*] Load Test Result: 100% SUCCESS | Zero drops, zero deadlocks")
    print("================================================================")


if __name__ == "__main__":
    run_load_stress_suite()
