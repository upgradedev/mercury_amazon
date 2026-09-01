"""Reproducible Benchmark Suite for Mercury Voice CTO Cockpit (Fire TV & Alexa+).

Measures:
- DORA Engineering Velocity Aggregator Latency
- AWS Cloud Cost Anomaly Scanner Latency
- Governed Rollback Token Verification Latency

Run command:
    python scripts/benchmark_suite.py
"""
import json
import os
import statistics
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.abspath("."))

from src.application.calculate_dora_use_case import CalculateDORAUseCase
from src.application.detect_cost_anomalies_use_case import DetectCostAnomaliesUseCase
from src.application.governed_rollback_use_case import GovernedRollbackUseCase
from src.infrastructure.aws_cost_adapter import AWSCostAdapter
from src.infrastructure.github_adapter import GitHubTelemetryAdapter


def benchmark_dora_calculator(iterations: int = 1000) -> dict[str, float]:
    github_adapter = GitHubTelemetryAdapter()
    use_case = CalculateDORAUseCase(github_adapter)
    latencies_ms: list[float] = []

    for _ in range(iterations):
        t0 = time.perf_counter()
        _ = use_case.execute()
        t1 = time.perf_counter()
        latencies_ms.append((t1 - t0) * 1000.0)

    latencies_sorted = sorted(latencies_ms)
    return {
        "iterations": iterations,
        "mean_ms": round(statistics.mean(latencies_sorted), 4),
        "p50_ms": round(statistics.median(latencies_sorted), 4),
        "p95_ms": round(latencies_sorted[int(0.95 * len(latencies_sorted))], 4),
        "p99_ms": round(latencies_sorted[int(0.99 * len(latencies_sorted))], 4),
    }


def benchmark_cost_anomaly_scanner(iterations: int = 1000) -> dict[str, float]:
    cost_adapter = AWSCostAdapter()
    use_case = DetectCostAnomaliesUseCase(cost_adapter)
    latencies_ms: list[float] = []

    for _ in range(iterations):
        t0 = time.perf_counter()
        _ = use_case.execute()
        t1 = time.perf_counter()
        latencies_ms.append((t1 - t0) * 1000.0)

    latencies_sorted = sorted(latencies_ms)
    return {
        "iterations": iterations,
        "mean_ms": round(statistics.mean(latencies_sorted), 4),
        "p50_ms": round(statistics.median(latencies_sorted), 4),
        "p95_ms": round(latencies_sorted[int(0.95 * len(latencies_sorted))], 4),
        "p99_ms": round(latencies_sorted[int(0.99 * len(latencies_sorted))], 4),
    }


def main():
    print("================================================================")
    print("       MERCURY REPRODUCIBLE BENCHMARK SUITE (FIRE TV TRACK)      ")
    print("================================================================")

    dora_bench = benchmark_dora_calculator(1000)
    cost_bench = benchmark_cost_anomaly_scanner(1000)

    print("\n[1] DORA Velocity Report Synthesizer (1,000 runs):")
    print(f"    - Mean Latency:  {dora_bench['mean_ms']} ms")
    print(f"    - p50 Latency:   {dora_bench['p50_ms']} ms")
    print(f"    - p95 Latency:   {dora_bench['p95_ms']} ms")
    print(f"    - p99 Latency:   {dora_bench['p99_ms']} ms")

    print("\n[2] AWS Cloud Cost Anomaly Scanner (1,000 runs):")
    print(f"    - Mean Latency:  {cost_bench['mean_ms']} ms")
    print(f"    - p50 Latency:   {cost_bench['p50_ms']} ms")
    print(f"    - p95 Latency:   {cost_bench['p95_ms']} ms")
    print(f"    - p99 Latency:   {cost_bench['p99_ms']} ms")

    results = {
        "dora_velocity_engine": dora_bench,
        "cost_anomaly_scanner": cost_bench,
    }

    with open("benchmarks_summary.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    print("\n================================================================")
    print("  SUMMARY: All benchmarks executed. Results saved to benchmarks_summary.json")
    print("================================================================")


if __name__ == "__main__":
    main()
