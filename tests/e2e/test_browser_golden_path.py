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
            page.wait_for_function("document.querySelector('#heroEyebrow').textContent.includes('recorded, not sent')")
            assert "No deployment pipeline was contacted" in page.locator("#incidentOutput").inner_text()

            assert page.evaluate("window.mercuryNav.current && window.mercuryNav.current.id") == "btnHandoff"
            # The payoff stays on screen: Publish handoff is the next stop, but the
            # board does not scroll to it and no ring is drawn until the next press.
            hero = page.evaluate(
                "(() => { const r = document.querySelector('#heroFigure').getBoundingClientRect();"
                " return { top: r.top, bottom: r.bottom, text: document.querySelector('#heroFigure').textContent,"
                " label: document.querySelector('#heroFigureLabel').textContent,"
                " rings: document.querySelectorAll('.tv-focused').length,"
                " evidence: document.querySelector('#heroProvenance').textContent,"
                " active: document.activeElement && document.activeElement.id }; })()")
            assert hero["text"] == "RECORDED" and hero["label"] == "no pipeline contacted", hero
            assert 0 <= hero["top"] and hero["bottom"] <= 1080, f"the RECORDED hero left the screen: {hero}"
            assert hero["rings"] == 0, hero
            # Keyboard focus agrees: it waits on the board, not on the off-screen control.
            assert hero["active"] == "hero", hero
            # The evidence keeps the held-out measurement of the answer that was acted on.
            assert "held-out split" in hero["evidence"], hero
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


# The host stub the Fire TV app injects, reduced to what the smoke script reads: every
# journey event, in order. Its presence also turns the page into its TV-host layout.
HOST_STUB = """
window.__journey = [];
window.MercuryHost = { reportJourney: function (name, detail) { window.__journey.push(name + ':' + detail); } };
"""


def _start_server(port: int) -> subprocess.Popen:
    env = os.environ.copy()
    env.update({
        "MERCURY_OFFLINE": "1",
        "MERCURY_SEED_RECORDED_DEMO": "1",
        "MERCURY_ROLLBACK_SECRET": "browser-test-secret",
    })
    env.pop("MERCURY_ROLLBACK_DISPATCH", None)
    env.pop("MERCURY_STATE_TABLE", None)
    return subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "src.interfaces.mcp_server:app",
         "--host", "127.0.0.1", "--port", str(port)],
        cwd=REPO_ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )


def _stop_server(process: subprocess.Popen) -> None:
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def test_every_later_screen_can_still_publish_the_shared_handoff_by_d_pad():
    """The second viewer of a shared deployment used to be refused at the last step.

    The page sent revision 0 on every load, so once one screen had published, every
    later load that pressed Publish got HTTP 409 and no handoff_published event, and the
    Android smoke script would hang waiting for it on any re-run against the same
    endpoint. Two loads against one server, each driven by the remote's own keys, must
    both publish, and the second must land on the next revision.
    """
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    sync_playwright = _browser_api()
    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    process = _start_server(port)
    try:
        _wait_for_server(base, process)
        published = []
        with sync_playwright() as driver:
            browser = driver.chromium.launch()
            for _ in range(2):
                context = browser.new_context(viewport={"width": 960, "height": 540})
                context.add_init_script(HOST_STUB)
                page = context.new_page()
                errors = []
                page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
                page.goto(base, wait_until="domcontentloaded")
                page.locator("#btnStage:not([disabled])").wait_for(timeout=15_000)
                page.evaluate("window.navigateDpad('RIGHT')")
                page.evaluate("window.navigateDpad('SELECT')")
                page.locator("#btnConfirm:not([disabled])").wait_for(timeout=10_000)
                page.evaluate("window.navigateDpad('RIGHT')")
                page.evaluate("window.navigateDpad('SELECT')")
                page.wait_for_function(
                    "window.__journey.some(e => e.indexOf('rollback_confirmed:') === 0)", timeout=10_000)
                in_view = page.evaluate(
                    "(() => { const r = document.querySelector('#heroFigure').getBoundingClientRect();"
                    " return r.top >= 0 && r.bottom <= innerHeight"
                    " && document.querySelector('#heroFigure').textContent === 'RECORDED'; })()")
                assert in_view, "after Confirm the RECORDED hero has to stay on the TV screen"
                page.evaluate("window.navigateDpad('SELECT')")
                page.wait_for_function(
                    "window.__journey.some(e => e.indexOf('handoff_published:') === 0)", timeout=10_000)
                event = page.evaluate(
                    "window.__journey.filter(e => e.indexOf('handoff_published:') === 0)[0]")
                published.append(event)
                assert "Request failed" not in page.locator("#handoffOutput").inner_text()
                assert not errors, f"the journey logged console errors: {errors}"
                context.close()
            browser.close()
        assert published[0].startswith("handoff_published:checkout-api-active:revision-1:")
        assert published[1].startswith("handoff_published:checkout-api-active:revision-2:")
    finally:
        _stop_server(process)
