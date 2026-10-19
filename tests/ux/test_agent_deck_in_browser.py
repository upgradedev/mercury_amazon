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
import random
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
    """A free local port, looked for in 8900-8999 first.

    Machines that run several agents' servers side by side keep test servers in that
    band, so a test server never lands on a port somebody else is about to take.
    """
    start = random.randrange(100)
    for offset in range(100):
        port = 8900 + (start + offset) % 100
        with socket.socket() as sock:
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
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
            "model_fields": ["commander_brief_10ft"],
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
        card = page.locator("#card-agent-brief").inner_text()
        # Only the field the model wrote is labelled as the model's.
        assert "Brief above: model." in card, card
        assert "does not show (deterministic template)" in card, card
        assert "Draft handoff (deterministic template)" in card, card
    finally:
        context.close()


def test_a_rejected_model_answer_is_labelled_as_rejected(browser, base_url):
    rejected = {
        "service": "checkout-api",
        "verdict": "ANOMALY_ATTRIBUTED",
        "data_label": "OFFLINE FIXTURE",
        "rollback_dispatch": "record-only",
        "agent_synthesis": {
            "synthesis_mode": "deterministic",
            "model_answered": None,
            "model_id": None,
            "fallback_reason": "model_claim_rejected",
            "incident_severity": "SEV-1_ROLLBACK_READY",
            "commander_brief_10ft": "A deterministic line.",
            "root_cause_hypothesis": "A temporal candidate only.",
            "responder_handoff_draft": {"current_action": "Review", "next_step": "Decide"},
            "latency_ms": 12,
            "cached": False,
        },
    }
    context, page, _calls, _errors = _open(
        browser, base_url + "/",
        routes=[("**/mcp/tools/agent_incident_brief", _fulfil_json(200, rejected))])
    try:
        _press_center_on(page, "#btnAgentBrief")
        page.locator("#card-agent-brief").wait_for(timeout=10_000)
        engine = page.locator("#card-agent-brief [data-agent-engine]").inner_text()
        assert "model answer rejected (claim guard)" in engine, engine
        assert "no model answered" not in engine, engine
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


#: The D-pad path the owner's recording takes after the journey, measured on ddccb3e:
#: Stage, Confirm, Publish handoff, then Ask the agent. Before the fix the answer card
#: rendered behind the fixed key bar with only the console header showing.
_PATH_TO_THE_AGENT = (
    ("RIGHT", None), ("SELECT", "#btnConfirm:not([disabled])"),
    ("RIGHT", None), ("SELECT", "#btnHandoff:not([disabled])"),
    ("DOWN", None), ("SELECT", None),
    ("DOWN", None),
)

_CARD_GEOMETRY = """card => {
  const box = s => { const e = document.querySelector(s); if (!e) return null;
    const r = e.getBoundingClientRect(); return { top: Math.round(r.top), bottom: Math.round(r.bottom) }; };
  const bar = document.querySelector('.keybar');
  const shown = bar && getComputedStyle(bar).display !== 'none' && bar.getBoundingClientRect().height > 0;
  const current = window.mercuryNav.current;
  return {
    viewport: [innerWidth, innerHeight], tvHost: document.documentElement.classList.contains('tv-host'),
    keybarTop: shown ? Math.round(bar.getBoundingClientRect().top) : innerHeight,
    card: box(card), pill: box(card + ' .agent-pills:nth-of-type(2)'),
    engine: box(card + ' [data-agent-engine]'),
    brief: box(card + ' .agent-brief-10ft'), scrollY: Math.round(scrollY),
    focus: current && current.id,
    focusBox: current ? (r => ({ top: Math.round(r.top), bottom: Math.round(r.bottom) }))(current.getBoundingClientRect()) : null,
  };
}"""

_ACTIVE_ID = "document.activeElement && document.activeElement.id"

_TV_SIZES = pytest.mark.parametrize(
    "width, height, host", [(1920, 1080, False), (960, 540, True)],
    ids=["1080p", "firetv-webview-960x540"])


def _open_tv(browser, base_url, width, height, host, init_script=None, routes=()):
    """The board as the TV shows it; ``host`` injects what the Fire TV app injects."""
    context = browser.new_context(viewport={"width": width, "height": height}, color_scheme="dark")
    if host:
        # MainActivity.MercuryHost, as tests/ux/test_board_in_browser.py open_board(host=True).
        context.add_init_script("window.MercuryHost = { reportJourney: function () {} };")
    if init_script:
        context.add_init_script(init_script)
    for pattern, handler in routes:
        context.route(pattern, handler)
    page = context.new_page()
    calls: list[str] = []
    page.on("request", lambda request: calls.append(urlsplit(request.url).path)
            if urlsplit(request.url).path.startswith("/mcp/tools/") else None)
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(base_url + "/", wait_until="domcontentloaded")
    page.locator("#bedrockAgentSection").wait_for(state="attached", timeout=10_000)
    page.locator("#btnStage:not([disabled])").wait_for(timeout=15_000)
    return context, page, calls, errors


def _walk_to_the_agent(page):
    """The recorded path, key by key. It has to reach Ask the agent on its own."""
    page.evaluate("window.mercuryNav.setFocus(document.querySelector('#btnWhatChanged'))")
    for key, wait_for in _PATH_TO_THE_AGENT:
        page.evaluate(f"window.navigateDpad('{key}')")
        if wait_for:
            page.locator(wait_for).wait_for(timeout=10_000)
        page.wait_for_timeout(250)
    # No fallback: if a new stop lands between Publish handoff and Ask the agent, or
    # DOWN goes somewhere else, this is the regression the test exists for.
    assert page.evaluate("window.mercuryNav.current && window.mercuryNav.current.id") == "btnAgentBrief"


def _assert_card_clear_of_the_key_bar(geometry, focus):
    assert geometry["pill"]["top"] >= 0, geometry
    assert geometry["pill"]["bottom"] <= geometry["keybarTop"], geometry
    if geometry["engine"] is not None:
        assert geometry["engine"]["bottom"] < geometry["keybarTop"], geometry
    if geometry["brief"] is not None:
        assert geometry["brief"]["bottom"] <= geometry["keybarTop"], geometry
    assert geometry["focus"] == focus, geometry
    # The control the viewer is on stays on the screen too.
    assert geometry["focusBox"]["top"] >= 0, geometry
    assert geometry["focusBox"]["bottom"] <= geometry["keybarTop"], geometry


@_TV_SIZES
def test_the_agent_answer_is_brought_up_above_the_key_bar(browser, base_url, width, height, host):
    context, page, calls, errors = _open_tv(browser, base_url, width, height, host)
    try:
        _walk_to_the_agent(page)
        page.evaluate("window.navigateDpad('SELECT')")
        page.locator("#card-agent-brief [data-agent-engine]").wait_for(timeout=10_000)
        page.wait_for_timeout(300)
        geometry = page.evaluate(_CARD_GEOMETRY, "#card-agent-brief")
        print("agent card geometry:", json.dumps(geometry))
        # 960x540 is measured as the Fire TV host lays it out, not as a small browser.
        assert geometry["tvHost"] is host, geometry
        _assert_card_clear_of_the_key_bar(geometry, "btnAgentBrief")
        # Keyboard focus is back on the control the cursor is on: the button was
        # disabled while the call ran, which dropped focus to the page body.
        page.wait_for_function("document.querySelector('#btnAgentBrief').disabled === false")
        assert page.evaluate(_ACTIVE_ID) == "btnAgentBrief"
        # Focus stayed on Ask the agent, so a second Center asks again, and the second
        # card is just as visible.
        page.evaluate("window.navigateDpad('SELECT')")
        page.wait_for_function("document.querySelector('#btnAgentBrief').disabled === false")
        page.wait_for_timeout(500)
        assert calls.count("/mcp/tools/agent_incident_brief") == 2, calls
        again = page.evaluate(_CARD_GEOMETRY, "#card-agent-brief")
        print("second agent card geometry:", json.dumps(again))
        _assert_card_clear_of_the_key_bar(again, "btnAgentBrief")
        assert errors == [], errors
    finally:
        context.close()


@_TV_SIZES
def test_the_recorded_handoff_card_stays_above_the_key_bar_and_keeps_the_cursor(
        browser, base_url, width, height, host):
    """Publish recorded demo handoff, one step right of Ask the agent.

    The deck refreshes the page's shared handoff with a click on its button. That click
    used to leave the D-pad cursor on 'Refresh shared handoff' in the rollback section,
    and the refreshed handoff rendered above the deck after the card did, pushing the
    card back under the key bar.
    """
    context, page, calls, errors = _open_tv(browser, base_url, width, height, host)
    try:
        _walk_to_the_agent(page)
        page.evaluate("window.navigateDpad('RIGHT')")
        page.wait_for_timeout(250)
        assert page.evaluate("window.mercuryNav.current.id") == "btnAgentPublishHandoff"
        page.evaluate("window.navigateDpad('SELECT')")
        page.locator("#card-agent-handoff").wait_for(timeout=10_000)
        # Let the page's own refresh render this revision of the shared handoff above
        # the deck: that render is what used to push the card back under the bar.
        revision = re.search(r"Revision: (\d+)", page.locator("#card-agent-handoff").inner_text()).group(1)
        page.wait_for_function(
            "r => (document.querySelector('#handoffOutput').textContent || '').includes('SHARED REVISION ' + r)",
            arg=revision, timeout=10_000)
        page.wait_for_timeout(500)
        geometry = page.evaluate(_CARD_GEOMETRY, "#card-agent-handoff")
        print("handoff card geometry:", json.dumps(geometry))
        assert "/mcp/tools/demo_update_handoff" in calls, calls
        _assert_card_clear_of_the_key_bar(geometry, "btnAgentPublishHandoff")
        # Keyboard focus agrees with the cursor. It used to stay on the off-screen
        # 'Refresh shared handoff' the deck clicks, so Shift+Tab jumped the page up to
        # 'Publish responder handoff' outside the deck instead of reaching Ask the agent.
        assert page.evaluate(_ACTIVE_ID) == "btnAgentPublishHandoff"
        scrolled = page.evaluate("Math.round(scrollY)")
        page.keyboard.press("Shift+Tab")
        page.wait_for_timeout(200)
        assert page.evaluate(_ACTIVE_ID) == "btnAgentBrief"
        assert abs(page.evaluate("Math.round(scrollY)") - scrolled) <= 2
        # The hint under the board names the control the remote is on.
        assert "Refresh shared handoff" not in page.evaluate(
            "window.mercuryNav.current.getAttribute('data-tv-label') || ''")
        assert errors == [], errors
    finally:
        context.close()


def test_a_refused_demo_handoff_shows_the_servers_reason(browser, base_url):
    """A live row has no recorded demo handoff; the server says so with a 422."""
    detail = "No recorded demo handoff exists for this service; handoffs are demo-only."
    context, page, _calls, _errors = _open(
        browser, base_url + "/",
        routes=[("**/mcp/tools/demo_update_handoff", _fulfil_json(422, {"detail": detail}))])
    try:
        _press_center_on(page, "#btnAgentPublishHandoff")
        page.locator("#card-agent-error").wait_for(timeout=10_000)
        text = page.locator("#card-agent-error").inner_text()
        assert "HTTP 422" in text and detail in text, text
        assert "refused" in text and "No answer from" not in text, text
        assert "race" not in text.lower() and "conflict" not in text.lower(), text
    finally:
        context.close()


#: Holds the agent's answer back, as a cold start or a model answer would.
_SLOW_AGENT = """(() => {
  const real = window.fetch.bind(window);
  window.fetch = (url, options) => String(url).includes('/mcp/tools/agent_incident_brief')
    ? new Promise(resolve => setTimeout(resolve, 2500)).then(() => real(url, options))
    : real(url, options);
})();"""


@_TV_SIZES
def test_a_late_answer_does_not_scroll_away_from_where_the_viewer_moved(
        browser, base_url, width, height, host):
    context, page, _calls, errors = _open_tv(
        browser, base_url, width, height, host, init_script=_SLOW_AGENT)
    try:
        _walk_to_the_agent(page)
        page.evaluate("window.navigateDpad('SELECT')")
        page.wait_for_timeout(200)
        page.evaluate("window.navigateDpad('UP')")
        page.evaluate("window.navigateDpad('UP')")
        page.wait_for_timeout(400)
        before = page.evaluate(_CARD_GEOMETRY, "#card-agent-brief")
        assert before["focus"] != "btnAgentBrief", before
        page.locator("#card-agent-brief").wait_for(state="attached", timeout=10_000)
        page.wait_for_timeout(300)
        after = page.evaluate(_CARD_GEOMETRY, "#card-agent-brief")
        print("late answer:", json.dumps(before), json.dumps(after))
        assert after["focus"] == before["focus"], (before, after)
        assert after["scrollY"] == before["scrollY"], (before, after)
        assert after["focusBox"]["top"] >= 0 and after["focusBox"]["bottom"] <= after["keybarTop"], after
        assert errors == [], errors
    finally:
        context.close()
