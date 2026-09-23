"""Real-browser proof of the same D-pad journey shown by the Android TV app."""
from __future__ import annotations

import asyncio
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _browser_api():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        if os.getenv("MERCURY_REQUIRE_BROWSER") == "1":
            pytest.fail("MERCURY_REQUIRE_BROWSER=1 but Playwright is not installed")
        pytest.skip("Playwright is optional locally; CI installs and requires it")
    return sync_playwright


def _wait_for_server(base: str, process: subprocess.Popen, timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            stdout, _ = process.communicate(timeout=2)
            pytest.fail(f"Mercury server exited before the browser journey:\n{stdout}")
        try:
            with urllib.request.urlopen(f"{base}/health", timeout=1) as response:
                if response.status == 200:
                    return
        except OSError:
            time.sleep(0.1)
    pytest.fail("Mercury server did not become healthy for the browser journey")


def test_browser_completes_record_only_dpad_journey_without_a_typed_secret():
    """Drive attribution, staged approval, confirmation and handoff in Chromium."""
    if sys.platform == "win32":
        # pytest-asyncio installs a selector policy on Windows, while Playwright's
        # Node driver requires subprocess support from the proactor policy.
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    sync_playwright = _browser_api()
    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    env = os.environ.copy()
    env.update({
        "MERCURY_OFFLINE": "1",
        "MERCURY_SEED_RECORDED_DEMO": "1",
        "MERCURY_ROLLBACK_SECRET": "browser-test-secret",
    })
    env.pop("MERCURY_ROLLBACK_DISPATCH", None)
    env.pop("MERCURY_STATE_TABLE", None)
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "src.interfaces.mcp_server:app",
         "--host", "127.0.0.1", "--port", str(port)],
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        _wait_for_server(base, process)
        calls: list[tuple[str, str | None]] = []
        with sync_playwright() as driver:
            browser = driver.chromium.launch()
            page = browser.new_page(viewport={"width": 1920, "height": 1080})
            page.on(
                "request",
                lambda request: calls.append(
                    (request.url, request.headers.get("authorization"))
                ) if "/mcp/" in request.url else None,
            )
            page.goto(base, wait_until="domcontentloaded")
            page.locator("#btnStage:not([disabled])").wait_for(timeout=15_000)
            assert "ANOMALY" in page.locator("#incidentOutput").inner_text()
            assert "record-only" in page.locator("#stageReason").inner_text().lower()

            # The app receives these same directions from MainActivity's remote
            # key bridge. Focus starts on Ask what changed.
            page.locator("#btnWhatChanged").focus()
            page.keyboard.press("ArrowRight")
            assert page.evaluate("window.mercuryNav.current && window.mercuryNav.current.id") == "btnStage"
            page.keyboard.press("Enter")
            page.locator("#btnConfirm:not([disabled])").wait_for(timeout=10_000)
            assert "PENDING_CONFIRMATION" in page.locator("#incidentOutput").inner_text()

            page.keyboard.press("ArrowRight")
            assert page.evaluate("window.mercuryNav.current && window.mercuryNav.current.id") == "btnConfirm"
            page.keyboard.press("Enter")
            page.wait_for_function("document.querySelector('#heroEyebrow').textContent.includes('recorded_only')")
            assert "No deployment pipeline was contacted" in page.locator("#incidentOutput").inner_text()

            assert page.evaluate("window.mercuryNav.current && window.mercuryNav.current.id") == "btnHandoff"
            page.keyboard.press("Enter")
            page.locator("#handoffOutput .tag-live").wait_for(timeout=10_000)
            assert "D-pad demo responder" in page.locator("#handoffOutput").inner_text()
            browser.close()

        demo_calls = [(url, auth) for url, auth in calls if "/demo_" in url or "/demo-handoff" in url]
        assert any("demo_stage_rollback" in url for url, _ in demo_calls)
        assert any("demo_confirm_rollback" in url for url, _ in demo_calls)
        assert any("demo_update_handoff" in url for url, _ in demo_calls)
        assert all(auth is None for _, auth in demo_calls)
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
