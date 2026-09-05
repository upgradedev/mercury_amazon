"""Latency regression guard for the cockpit's read endpoints.

This is a guard, not a benchmark. The published numbers come from
``python scripts/benchmark_suite.py``, which records the machine, the iteration
count and the observed data mode. The thresholds here are deliberately loose so
they catch a regression of the kind the benchmark already caught once, where
credential resolution ran per request and cost over a second, without failing on
a slow CI runner.
"""
import time

from fastapi.testclient import TestClient

from src.interfaces.mcp_server import app

ITERATIONS = 20
HEALTH_P95_BUDGET_MS = 300.0
TELEMETRY_P95_BUDGET_MS = 1000.0


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = min(int(fraction * len(ordered)), len(ordered) - 1)
    return ordered[index]


def _measure(client: TestClient, method: str, path: str) -> list[float]:
    getattr(client, method)(path)  # warm up, not measured
    latencies = []
    for _ in range(ITERATIONS):
        start = time.perf_counter()
        response = getattr(client, method)(path)
        latencies.append((time.perf_counter() - start) * 1000)
        assert response.status_code == 200, f"{path} returned {response.status_code}"
    return latencies


def test_health_endpoint_latency_stays_within_budget():
    p95 = _percentile(_measure(TestClient(app), "get", "/health"), 0.95)
    assert p95 < HEALTH_P95_BUDGET_MS, f"/health p95 was {p95:.2f} ms over {ITERATIONS} requests"


def test_telemetry_endpoints_do_not_resolve_credentials_per_request():
    """The regression this exists for: a per-request credential probe.

    When boto3 credential resolution ran on every call, this endpoint took over a
    second per request on a machine without credentials. The budget is far above
    the measured 3 ms so a slow runner does not fail, but well below the 1154 ms
    the bug produced.
    """
    client = TestClient(app)
    for path in ["/mcp/tools/get_aws_cost_anomalies", "/mcp/tools/get_dora_velocity_report"]:
        p95 = _percentile(_measure(client, "post", path), 0.95)
        assert p95 < TELEMETRY_P95_BUDGET_MS, f"{path} p95 was {p95:.2f} ms over {ITERATIONS} requests"
