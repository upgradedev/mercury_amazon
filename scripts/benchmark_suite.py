"""Reproducible latency benchmark for the Mercury cockpit.

Measures what the Fire TV actually waits for: the round trip of each tool
endpoint through the ASGI application, and the cost of the governance check that
guards a rollback. Both are measured in-process against the real application, so
the numbers exclude network transit and are a floor, not a field measurement.

Every number this prints is written to ``benchmarks_summary.json`` together with
the iteration count and the timestamp, so the file can be checked against a rerun.

Run::

    python scripts/benchmark_suite.py            # default iteration counts
    python scripts/benchmark_suite.py 50 2000    # http iterations, crypto iterations
"""
from __future__ import annotations

import json
import os
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault("MERCURY_ROLLBACK_SECRET", "benchmark-secret")

from fastapi.testclient import TestClient  # noqa: E402

from src.domain.governed_rollback import (  # noqa: E402
    compute_payload_hash,
    mint_governance_token,
    verify_governance_token,
)
from src.interfaces.mcp_server import app  # noqa: E402

DEFAULT_HTTP_ITERATIONS = 60
DEFAULT_CRYPTO_ITERATIONS = 2000
SUMMARY_PATH = REPO_ROOT / "benchmarks_summary.json"

ENDPOINTS = [
    ("get_dora_velocity_report", "/mcp/tools/get_dora_velocity_report"),
    ("get_pr_bottlenecks", "/mcp/tools/get_pr_bottlenecks"),
    ("get_aws_cost_anomalies", "/mcp/tools/get_aws_cost_anomalies"),
    ("what_changed", "/mcp/tools/what_changed"),
]


def summarize(latencies_ms: list[float], iterations: int) -> dict[str, float]:
    ordered = sorted(latencies_ms)
    return {
        "iterations": iterations,
        "mean_ms": round(statistics.mean(ordered), 4),
        "p50_ms": round(statistics.median(ordered), 4),
        "p95_ms": round(ordered[min(int(0.95 * len(ordered)), len(ordered) - 1)], 4),
        "p99_ms": round(ordered[min(int(0.99 * len(ordered)), len(ordered) - 1)], 4),
        "max_ms": round(ordered[-1], 4),
    }


def benchmark_endpoint(client: TestClient, path: str, iterations: int) -> dict[str, float]:
    # One warm-up call so first-request import and fixture reads are not counted.
    client.post(path)
    latencies: list[float] = []
    for _ in range(iterations):
        started = time.perf_counter()
        response = client.post(path)
        latencies.append((time.perf_counter() - started) * 1000.0)
        if response.status_code != 200:
            raise RuntimeError(f"{path} returned {response.status_code}, refusing to report a number")
    return summarize(latencies, iterations)


def benchmark_governance_check(iterations: int) -> dict[str, float]:
    """Cost of minting and verifying one content-bound governance token."""
    payload_hash = compute_payload_hash("bench", "checkout-api", "3e9d10c", "benchmark")
    latencies: list[float] = []
    for _ in range(iterations):
        started = time.perf_counter()
        token = mint_governance_token("benchmark-secret", "bench", payload_hash)
        verify_governance_token("benchmark-secret", token, "bench", payload_hash)
        latencies.append((time.perf_counter() - started) * 1000.0)
    return summarize(latencies, iterations)


def main() -> int:
    http_iterations = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_HTTP_ITERATIONS
    crypto_iterations = int(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_CRYPTO_ITERATIONS

    print("=" * 64)
    print("  MERCURY LATENCY BENCHMARK (in-process ASGI, no network transit)")
    print("=" * 64)

    client = TestClient(app)
    results: dict[str, dict] = {}

    for name, path in ENDPOINTS:
        stats = benchmark_endpoint(client, path, http_iterations)
        results[name] = stats
        print(f"\n{name}  ({stats['iterations']} requests)")
        print(f"    mean {stats['mean_ms']} ms | p50 {stats['p50_ms']} ms | "
              f"p95 {stats['p95_ms']} ms | p99 {stats['p99_ms']} ms | max {stats['max_ms']} ms")

    governance = benchmark_governance_check(crypto_iterations)
    results["governance_token_mint_and_verify"] = governance
    print(f"\ngovernance_token_mint_and_verify  ({governance['iterations']} cycles)")
    print(f"    mean {governance['mean_ms']} ms | p95 {governance['p95_ms']} ms")

    summary = {
        "schema": "mercury.benchmarks/2",
        "note": (
            "Measured in-process against the ASGI application with fastapi TestClient. "
            "Excludes network transit, so these are a floor for a local run, not a "
            "field measurement from a Fire TV on a home network."
        ),
        "measured_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "measured_by_command": "python scripts/benchmark_suite.py",
        "python_version": sys.version.split()[0],
        "platform": sys.platform,
        "data_mode": "offline-fixture (no GITHUB_TOKEN and no AWS credentials present)",
        "results": results,
    }

    with open(SUMMARY_PATH, "w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2)
        handle.write("\n")

    print("\n" + "=" * 64)
    print(f"  Wrote {SUMMARY_PATH.name}")
    print("=" * 64)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
