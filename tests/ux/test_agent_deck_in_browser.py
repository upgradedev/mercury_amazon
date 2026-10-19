"""The agent deck, driven in Chromium against the page the server actually serves.

Judges get docs/index.html with /mcp/agent-deck.js injected. These tests load that
same page from a local server and check four promises the deck makes:

1. Nothing calls the agent, the model or the MCP endpoint on page load or when a
   departures row is selected. The only call is an explicit Center press on the
   control labelled 'Ask the agent'.
2. The answer card carries the OFFLINE FIXTURE and record-only stamps.
3. The engine label names a model only when a model actually answered, and an error
   response is shown as an error, never as a brief.
4. The deck adds no stop to the hero's D-pad row, so the order the Android TV
   emulator run proved is the order judges get.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
AGENT_CALL_PATHS = ("/mcp/tools/agent_incident_brief", "/mcp/tools/agent_status")


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture(scope="module")
def sync_playwright():
    try:
        from playwright.sync_api import sync_playwright as factory
    except ImportError:
        if os.getenv("MERCURY_REQUIRE_BROWSER") == "1":
            pytest.fail("MERCURY_REQUIRE_BROWSER=1 but Playwright is not installed")
        pytest.skip("Playwright is optional locally; CI installs and requires it")
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    return factory


@pytest.fixture(scope="module")
def base_url(tmp_path_factory):
    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    env = os.environ.copy()
    env.update({
        "MERCURY_OFFLINE": "1",
        "MERCURY_SEED_RECORDED_DEMO": "1",
        "MERCURY_ROLLBACK_SECRET": "agent-deck-browser-test",
    })
    for name in ("MERCURY_ROLLBACK_DISPATCH", "MERCURY_STATE_TABLE", "GITHUB_TOKEN"):
        env.pop(name, None)
    log_path = tmp_path_factory.mktemp("deck_server") / "uvicorn.log"
    log = open(log_path, "w", encoding="utf-8")
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "src.interfaces.mcp_server:app",
         "--host", "127.0.0.1", "--port", str(port)],
        cwd=REPO_ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, text=True,
    )
    try:
        deadline = time.monotonic() + 20
        while True:
            if process.poll() is not None:
                pytest.fail(f"the Mercury server exited:\n{log_path.read_text(encoding='utf-8')}")
            try:
                with urllib.request.urlopen(f"{base}/health", timeout=1) as response:
                    if response.status == 200:
                        break
            except OSError:
                if time.monotonic() > deadline:
                    pytest.fail("the Mercury server did not become healthy")
                time.sleep(0.1)
        yield base
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        log.close()


@pytest.fixture(scope="module")
def browser(sync_playwright):
    with sync_playwright() as driver:
        try:
            launched = driver.chromium.launch()
        except Exception as error:
            if os.getenv("MERCURY_REQUIRE_BROWSER") == "1":
                raise
            pytest.skip(f"Chromium is not installed: {error}")
        yield launched
        launched.close()


def _open(browser, url, routes=()):
    context = browser.new_context(viewport={"width": 1920, "height": 1080}, color_scheme="dark")
    for pattern, handler in routes:
        context.route(pattern, handler)
    page = context.new_page()
    calls: list[str] = []

    def record(request):
        path = urlsplit(request.url).path
        if path in AGENT_CALL_PATHS or (path == "/mcp" and request.method == "POST"):
            calls.append(path)

    page.on("request", record)
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(url, wait_until="domcontentloaded")
    # The deck has to be on the page, or the rest of the test proves nothing.
    page.locator("#bedrockAgentSection").wait_for(state="attached", timeout=10_000)
    page.locator("#btnStage:not([disabled])").wait_for(timeout=15_000)
    return context, page, calls, errors


def _press_center_on(page, selector):
    """Move the D-pad cursor onto an element and press Center, as the remote does."""
    page.evaluate(
        "sel => window.mercuryNav.setFocus(document.querySelector(sel))", selector)
    page.evaluate("window.navigateDpad('SELECT')")


@pytest.mark.parametrize("path", ["/", "/?agent=1"])
def test_no_agent_or_model_call_on_load_or_on_row_select(browser, base_url, path):
    context, page, calls, errors = _open(browser, base_url + path)
    try:
        page.wait_for_timeout(1500)
        assert calls == [], f"the page called the agent on load: {calls}"

        _press_center_on(page, '.btn-demo[data-service="search-indexer"]')
        page.wait_for_function(
            "document.querySelector('.btn-demo[data-service=\"search-indexer\"]')"
            ".getAttribute('aria-pressed') === 'true'")
        page.wait_for_timeout(800)
        assert calls == [], f"selecting a row called the agent: {calls}"
        assert not errors, errors
    finally:
        context.close()


def test_ask_the_agent_press_makes_one_call_and_the_card_carries_both_stamps(browser, base_url):
    context, page, calls, errors = _open(browser, base_url + "/")
    try:
        ask = page.locator("#btnAgentBrief")
        assert ask.text_content().strip() == "Ask the agent"
        assert ask.get_attribute("data-tv-label") == "Ask the agent"

        _press_center_on(page, "#btnAgentBrief")
        page.locator("#card-agent-brief").wait_for(timeout=10_000)
        assert calls == ["/mcp/tools/agent_incident_brief"], calls

        card = page.locator("#card-agent-brief").inner_text()
        assert "OFFLINE FIXTURE" in card, card
        assert "record-only" in card.lower(), card
        engine = page.locator("#card-agent-brief [data-agent-engine]").inner_text()
        assert "deterministic" in engine.lower(), engine
        assert not re.search(r"sonnet|claude", engine, re.IGNORECASE), engine
        assert not re.search(r"\b(is|was|has been) staged\b|awaiting authori", card, re.IGNORECASE), card
        assert not errors, errors
    finally:
        context.close()


@pytest.mark.parametrize("path", ["/", "/?agent=1"])
def test_no_model_name_in_the_hero_or_the_deck_before_a_model_answers(browser, base_url, path):
    context, page, _calls, _errors = _open(browser, base_url + path)
    try:
        hero = page.locator("#hero").inner_text()
        # 'claude' alone is not checked: a fixture commit message names a claude/ branch.
        assert not re.search(r"sonnet|bedrock", hero, re.IGNORECASE), hero
        assert page.locator("#btnHeroJumpToAgent").count() == 0
        deck = page.locator("#bedrockAgentSection").inner_text()
        assert not re.search(r"\blive\b", deck, re.IGNORECASE), deck
        assert "Hydrating" not in deck
    finally:
        context.close()


def _fulfil_json(status, body):
    def handler(route):
        route.fulfill(status=status, content_type="application/json", body=json.dumps(body))
    return handler


def test_engine_label_names_the_model_only_when_a_model_answered(browser, base_url):
    answered = {
        "service": "checkout-api",
        "verdict": "ANOMALY_ATTRIBUTED",
        "data_label": "OFFLINE FIXTURE",
        "rollback_dispatch": "record-only",
        "agent_synthesis": {
            "synthesis_mode": "bedrock",
            "model_answered": "anthropic.claude-sonnet-5",
            "model_id": "anthropic.claude-sonnet-5",
            "incident_severity": "SEV-1_ROLLBACK_READY",
            "commander_brief_10ft": "A model drafted this line.",
            "root_cause_hypothesis": "A temporal candidate only.",
            "responder_handoff_draft": {"current_action": "Review", "next_step": "Decide"},
            "latency_ms": 12,
            "cached": False,
        },
    }
    context, page, _calls, _errors = _open(
        browser, base_url + "/",
        routes=[("**/mcp/tools/agent_incident_brief", _fulfil_json(200, answered))])
    try:
        _press_center_on(page, "#btnAgentBrief")
        page.locator("#card-agent-brief").wait_for(timeout=10_000)
        engine = page.locator("#card-agent-brief [data-agent-engine]").inner_text()
        assert "anthropic.claude-sonnet-5" in engine, engine
        assert "model answered" in engine.lower(), engine
    finally:
        context.close()


@pytest.mark.parametrize("status,body", [
    (500, {"detail": "Internal Server Error"}),
    (422, {"detail": [{"msg": "field required"}]}),
])
def test_an_error_response_is_shown_as_an_error_not_as_a_brief(browser, base_url, status, body):
    context, page, _calls, _errors = _open(
        browser, base_url + "/",
        routes=[("**/mcp/tools/agent_incident_brief", _fulfil_json(status, body))])
    try:
        _press_center_on(page, "#btnAgentBrief")
        page.locator("#card-agent-error").wait_for(timeout=10_000)
        assert page.locator("#card-agent-brief").count() == 0
        text = page.locator("#card-agent-error").inner_text()
        assert f"HTTP {status}" in text, text
        assert not re.search(r"sonnet|bedrock", text, re.IGNORECASE), text
    finally:
        context.close()


@pytest.mark.parametrize("path", ["/", "/?agent=1"])
def test_the_deck_adds_no_stop_to_the_hero_row(browser, base_url, path):
    context, page, _calls, _errors = _open(browser, base_url + path)
    try:
        ids = page.evaluate(
            "Array.from(document.querySelectorAll('.hero-actions [data-tv-focusable]')).map(e => e.id)")
        assert ids == ["btnWhatChanged", "btnStage", "btnConfirm"], ids
        page.evaluate("window.mercuryNav.setFocus(document.querySelector('#btnWhatChanged'))")
        page.evaluate("window.navigateDpad('RIGHT')")
        assert page.evaluate("window.mercuryNav.current.id") == "btnStage"
    finally:
        context.close()
