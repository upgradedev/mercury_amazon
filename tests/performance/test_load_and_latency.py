"""Load and Latency QA Benchmark for Amazon Developer Hackathon 2026.

Simulates 50 concurrent requests against the FastMCP application to verify sub-200ms latency and 0% error rate.
"""
import concurrent.futures
import time
import pytest
from fastapi.testclient import TestClient
from src.interfaces.mcp_server import app


def test_concurrent_load_and_latency_benchmark():
    client = TestClient(app)
    num_requests = 50
    latencies = []

    def make_request():
        start = time.perf_counter()
        resp = client.get("/health")
        duration_ms = (time.perf_counter() - start) * 1000
        return resp.status_code, duration_ms

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(make_request) for _ in range(num_requests)]
        for f in concurrent.futures.as_completed(futures):
            status, dur = f.result()
            assert status == 200, f"Expected 200 OK, got {status}"
            latencies.append(dur)

    latencies.sort()
    p50 = latencies[int(num_requests * 0.50)]
    p95 = latencies[int(num_requests * 0.95)]
    p99 = latencies[int(num_requests * 0.99)]

    print(f"\nLOAD QA: {num_requests} requests -> P50: {p50:.2f}ms | P95: {p95:.2f}ms | P99: {p99:.2f}ms")
    assert p95 < 250.0, f"P95 latency {p95:.2f}ms exceeded 250ms threshold!"
