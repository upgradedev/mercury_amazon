"""Probe the live Mercury deployment and write an honest deployment receipt.

This script performs a real HTTP request. It records only what it observed:
the URL, the HTTP status code, a verbatim excerpt of the response body, the
commit SHA reported by the deployment (``null`` when the deployment does not
report one), and the local ``git rev-parse HEAD`` at probe time.

It never asserts that the deployment matches the local checkout. Gate D2/G2 in
``ci/readiness.py`` compare the two fields and fail when they differ.

Usage::

    python scripts/probe_deployment.py                      # probe default URL
    python scripts/probe_deployment.py https://example.com   # probe another URL
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from typing import Any

import httpx

DEFAULT_URL = "https://leol25sezuvokpankox5cvjopm0gtvfa.lambda-url.eu-west-1.on.aws"
RECEIPT_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "deploy_teardown_receipt.json")
BODY_EXCERPT_CHARS = 800


def local_head_sha(repo_root: str) -> str | None:
    """Return ``git rev-parse HEAD`` for the local checkout, or None if unavailable."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, cwd=repo_root, timeout=20,
        )
        sha = out.stdout.strip()
        return sha or None
    except Exception:
        return None


def probe(base_url: str, path: str, timeout: float = 20.0) -> dict[str, Any]:
    """Issue one real GET and record the observed result (or the observed failure)."""
    url = base_url.rstrip("/") + path
    started = time.perf_counter()
    try:
        response = httpx.get(url, timeout=timeout)
        elapsed_ms = round((time.perf_counter() - started) * 1000.0, 2)
        return {
            "url": url,
            "http_status": response.status_code,
            "elapsed_ms": elapsed_ms,
            "body_excerpt": response.text[:BODY_EXCERPT_CHARS],
            "error": None,
        }
    except Exception as exc:
        elapsed_ms = round((time.perf_counter() - started) * 1000.0, 2)
        return {
            "url": url,
            "http_status": None,
            "elapsed_ms": elapsed_ms,
            "body_excerpt": None,
            "error": f"{type(exc).__name__}: {exc}",
        }


def deployed_sha_from(health_probe: dict[str, Any]) -> str | None:
    """Extract ``build_sha`` from the /health body when the deployment reports one."""
    body = health_probe.get("body_excerpt")
    if not body:
        return None
    try:
        parsed = json.loads(body)
    except (ValueError, TypeError):
        return None
    sha = parsed.get("build_sha") if isinstance(parsed, dict) else None
    return sha if isinstance(sha, str) and sha else None


def build_receipt(base_url: str, repo_root: str) -> dict[str, Any]:
    root = probe(base_url, "/")
    health = probe(base_url, "/health")
    head = local_head_sha(repo_root)
    deployed = deployed_sha_from(health)

    return {
        "schema": "mercury.deploy_receipt/2",
        "note": (
            "Every field below was observed by scripts/probe_deployment.py at the recorded time. "
            "deployed_commit_sha is null when the deployment does not report a build_sha from /health."
        ),
        "probed_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "probed_at_epoch": time.time(),
        "base_url": base_url,
        "probes": [root, health],
        "deployed_commit_sha": deployed,
        "local_head_sha": head,
        "deployed_matches_local_head": bool(deployed and head and deployed == head),
        "teardown_verified": False,
        "teardown_note": "No terraform destroy has been executed by this script. Teardown is untested.",
    }


def main() -> int:
    base_url = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("MERCURY_DEPLOY_URL", DEFAULT_URL)
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    receipt = build_receipt(base_url, repo_root)

    with open(RECEIPT_PATH, "w", encoding="utf-8") as handle:
        json.dump(receipt, handle, indent=2)
        handle.write("\n")

    print(json.dumps(receipt, indent=2))
    print(f"\nWrote {RECEIPT_PATH}")
    if not receipt["deployed_matches_local_head"]:
        print("NOTE: the deployment does not report a build SHA equal to local HEAD. Gate G2 will fail.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
