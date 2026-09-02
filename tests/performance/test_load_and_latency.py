"""Load and Latency QA Benchmark for Amazon Developer Hackathon 2026."""
import time
import pytest
from fastapi.testclient import TestClient
from src.interfaces.mcp_server import app


def test_concurrent_load_and_latency_benchmark():
    client = TestClient(app)
    latencies = []
    for _ in range(10):
        start = time.perf_counter()
        resp = client.get("/health")
        duration_ms = (time.perf_counter() - start) * 1000
        assert resp.status_code == 200
        latencies.append(duration_ms)

    latencies.sort()
    p50 = latencies[int(len(latencies) * 0.50)]
    p95 = latencies[int(len(latencies) * 0.95)]
    assert p95 < 300.0, f"P95 latency {p95:.2f}ms exceeded threshold"
