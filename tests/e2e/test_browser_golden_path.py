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
            assert "PENDING_CONFIRMATION" in page.locator("#rollbackOutput").inner_text()

            page.keyboard.press("ArrowRight")
            assert page.evaluate("window.mercuryNav.current && window.mercuryNav.current.id") == "btnConfirm"
            page.keyboard.press("Enter")
            page.wait_for_function("document.querySelector('#heroEyebrow').textContent.includes('recorded, not sent')")
            assert "No deployment pipeline was contacted" in page.locator("#rollbackOutput").inner_text()

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
            # And the wait is visible: the parked board draws the ring the
            # deferred cursor withholds, so the screen never shows no ring.
            outline = page.evaluate(
                "(() => { const s = getComputedStyle(document.querySelector('#hero'));"
                " return { style: s.outlineStyle, width: s.outlineWidth }; })()")
            assert outline["style"] == "solid" and float(outline["width"].replace("px", "")) >= 2, (
                f"the parked board shows no visible ring: {outline}")
            # The evidence keeps the held-out measurement of the answer that was acted on.
            assert "held-out split" in hero["evidence"], hero
            page.keyboard.press("Enter")
            page.locator("#handoffOutput .tag-live").wait_for(timeout=10_000)
            assert "D-pad demo responder" in page.locator("#handoffOutput").inner_text()
            # The payoff of Publish is on screen: the cursor stays on Publish, and the
            # handoff's last line clears the remote's key bar. The cursor used to move
            # on to Refresh while the responder, facts and next step sat under the bar.
            shown = page.evaluate(
                "(() => { const out = document.querySelector('#handoffOutput').getBoundingClientRect();"
                " const bar = document.querySelector('.keybar').getBoundingClientRect();"
                " const publish = document.querySelector('#btnHandoff').getBoundingClientRect();"
                " return { cursor: window.mercuryNav.current.id, bottom: out.bottom, bar: bar.top,"
                " publishTop: publish.top }; })()")
            assert shown["cursor"] == "btnHandoff", shown
            assert shown["bottom"] <= shown["bar"], f"the handoff answer is under the key bar: {shown}"
            assert shown["publishTop"] >= 0, f"Publish handoff left the top of the screen: {shown}"
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


# What a viewer of the TV sees after Confirm: where the RECORDED figure sits, what the
# legend says the next press does, and whether anything has scrolled or drawn a ring.
READ_PAYOFF = """(() => {
  const figure = document.querySelector('#heroFigure');
  const box = figure.getBoundingClientRect();
  return { y: scrollY, top: box.top, bottom: box.bottom, height: innerHeight,
           figure: figure.textContent, legend: document.querySelector('#hintFocus').textContent,
           rings: document.querySelectorAll('.tv-focused').length,
           active: document.activeElement && document.activeElement.id };
})()"""

READ_HANDOFF = """(() => {
  const out = document.querySelector('#handoffOutput').getBoundingClientRect();
  const bar = document.querySelector('.keybar').getBoundingClientRect();
  const publish = document.querySelector('#btnHandoff').getBoundingClientRect();
  return { cursor: window.mercuryNav.current.id, bottom: out.bottom, bar: bar.top,
           publishTop: publish.top, publishBottom: publish.bottom,
           text: document.querySelector('#handoffOutput').innerText };
})()"""


def _confirm_on_the_tv(browser, base: str):
    """Drive the journey to RECORDED as the Android TV app does, and return the page.

    The CI emulator is 1920x1080 at hw.lcd.density 320, and MainActivity sets no wide
    viewport or zoom, so the WebView lays the page out at 960x540 CSS pixels with two
    device pixels to each. Keys go through window.navigateDpad, the bridge the app
    calls, in the order scripts/android_tv_smoke.sh presses them.
    """
    context = browser.new_context(viewport={"width": 960, "height": 540}, device_scale_factor=2)
    context.add_init_script(HOST_STUB)
    page = context.new_page()
    page.goto(base, wait_until="domcontentloaded")
    page.locator("#btnStage:not([disabled])").wait_for(timeout=15_000)
    page.evaluate("window.navigateDpad('RIGHT')")
    page.evaluate("window.navigateDpad('SELECT')")
    page.locator("#btnConfirm:not([disabled])").wait_for(timeout=10_000)
    page.evaluate("window.navigateDpad('RIGHT')")
    page.evaluate("window.navigateDpad('SELECT')")
    page.wait_for_function(
        "window.__journey.some(e => e.indexOf('rollback_confirmed:') === 0)", timeout=10_000)
    return context, page


def _publish_and_check_the_answer_is_on_screen(page) -> None:
    page.evaluate("window.navigateDpad('SELECT')")
    page.wait_for_function(
        "window.__journey.some(e => e.indexOf('handoff_published:') === 0)", timeout=10_000)
    shown = page.evaluate(READ_HANDOFF)
    assert "D-pad demo responder" in shown["text"], shown
    assert shown["cursor"] == "btnHandoff", shown
    assert shown["bottom"] <= shown["bar"], f"the handoff answer is under the key bar: {shown}"
    assert shown["publishTop"] >= 0, f"Publish handoff left the top of the screen: {shown}"


def test_a_direction_arriving_with_the_confirm_answer_leaves_recorded_on_the_tv_screen():
    """The emulator footage showed the payoff for about half a second.

    In the Android TV run for f423ba5, the board read RECORDED with the legend
    "Next press: Publish responder handoff" from 21.25 s, and at 21.81 s, with no key
    pressed until the Center that published, the page had scrolled to Publish handoff
    with the ring on it and the legend reading "Focused". That end state is exactly
    what a D-pad direction does to the deferred cursor: reveal it, which scrolls it
    into view. Desktop Chromium never sends that direction, so it is sent here, as the
    answer lands. On a television a direction that arrives within DEFER_SETTLE_MS of
    the answer is held: the board stays, and the next Center still publishes and
    brings the handoff answer up above the key bar.
    """
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    sync_playwright = _browser_api()
    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    process = _start_server(port)
    try:
        _wait_for_server(base, process)
        with sync_playwright() as driver:
            browser = driver.chromium.launch()
            context, page = _confirm_on_the_tv(browser, base)
            errors = []
            page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
            before = page.evaluate(READ_PAYOFF)
            assert before["figure"] == "RECORDED" and before["y"] == 0, before
            page.evaluate("window.navigateDpad('RIGHT')")
            for _ in range(8):
                seen = page.evaluate(READ_PAYOFF)
                assert seen["y"] == before["y"], f"the board scrolled away from RECORDED: {seen}"
                assert seen["figure"] == "RECORDED", seen
                assert 0 <= seen["top"] and seen["bottom"] <= seen["height"], (
                    f"the RECORDED figure left the TV screen: {seen}")
                assert seen["legend"] == "Next press: Publish responder handoff", seen
                assert seen["rings"] == 0 and seen["active"] == "hero", seen
                page.wait_for_timeout(200)
            _publish_and_check_the_answer_is_on_screen(page)
            assert not errors, f"the journey logged console errors: {errors}"
            context.close()
            browser.close()
    finally:
        _stop_server(process)


def test_a_direction_pressed_after_the_answer_still_brings_publish_into_view_on_the_tv():
    """The hold is for the moment the answer lands, not for the viewer's next press."""
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    sync_playwright = _browser_api()
    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    process = _start_server(port)
    try:
        _wait_for_server(base, process)
        with sync_playwright() as driver:
            browser = driver.chromium.launch()
            context, page = _confirm_on_the_tv(browser, base)
            settle = page.evaluate("window.mercuryNavInternals.DEFER_SETTLE_MS || 0")
            assert settle <= 1500, f"a hold longer than 1.5 s would eat a real press: {settle}"
            page.wait_for_timeout(settle + 200)
            page.evaluate("window.navigateDpad('DOWN')")
            shown = page.evaluate(READ_HANDOFF)
            legend = page.evaluate("document.querySelector('#hintFocus').textContent")
            assert shown["cursor"] == "btnHandoff", shown
            assert legend == "Focused: Publish responder handoff", legend
            assert 0 <= shown["publishTop"] and shown["publishBottom"] <= shown["bar"], (
                f"the press did not bring Publish handoff into view above the key bar: {shown}")
            _publish_and_check_the_answer_is_on_screen(page)
            context.close()
            browser.close()
    finally:
        _stop_server(process)


# The incident panel's consoles, each as the header's endpoint and the text under it.
# The panel is hidden until opened, so this reads textContent, not what is painted.
READ_INCIDENT_CONSOLES = """
Array.from(document.querySelectorAll('#panel-incident .console')).map(c => ({
  header: c.querySelector('.console-header span').textContent.trim(),
  text: c.querySelector('.console-header').nextElementSibling.textContent
}))
"""


def _markers(tool: str, body: dict) -> list[str]:
    """Strings that only a rendering of this tool's response would put on screen."""
    if tool == "what_changed":
        return ["Baseline mean", body["explanation"]]
    if tool == "demo_stage_rollback":
        return [body["state"], body["payload_hash"][:24]]
    if tool == "demo_confirm_rollback":
        return [body["status"], body["output"]]
    raise AssertionError(f"no markers defined for {tool}")


def _assert_every_console_shows_what_it_names(page, bodies: dict, step: str) -> list[dict]:
    """Each console header names one call; the text under it must be that call's answer.

    The header is read from the page and the expected answer from the network, so the
    check does not trust anything the page says about itself.
    """
    import re

    consoles = page.evaluate(READ_INCIDENT_CONSOLES)
    for console in consoles:
        named = re.match(r"POST /mcp/tools/(\w+)$", console["header"])
        for tool, body in bodies.items():
            shown = [m for m in _markers(tool, body) if m in console["text"]]
            if named and named.group(1) == tool:
                assert len(shown) == len(_markers(tool, body)), (
                    f"after {step}, the console headed {console['header']!r} does not show that"
                    f" call's answer: {console}")
            else:
                assert not shown, (
                    f"after {step}, the console headed {console['header']!r} shows the answer of"
                    f" {tool}: {shown} in {console}")
        if named:
            assert named.group(1) in bodies, (
                f"after {step}, a console names {console['header']!r}, which was never called")
    return consoles


def test_each_incident_console_shows_the_request_its_header_names():
    """Ask, Stage and Confirm used to share one console headed POST /mcp/tools/what_changed.

    After Confirm, the Incident evidence panel showed RECORDED_ONLY, the action and the
    commit under that header, and the metric series, baseline and window it promised were
    gone until the next load. Every step of the journey now has to leave each console
    showing the answer of the call its header names, and a fresh Ask has to put the
    correlation back and clear the rollback that belonged to the previous answer.
    """
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    sync_playwright = _browser_api()
    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    process = _start_server(port)
    try:
        _wait_for_server(base, process)
        with sync_playwright() as driver:
            browser = driver.chromium.launch()
            page = browser.new_page(viewport={"width": 1920, "height": 1080})
            bodies: dict = {}

            def answered(tool: str, press) -> None:
                with page.expect_response(lambda r: r.url.endswith("/mcp/tools/" + tool)) as info:
                    press()
                bodies[tool] = info.value.json()

            page.goto(base, wait_until="domcontentloaded")
            page.locator("#btnStage:not([disabled])").wait_for(timeout=15_000)
            # The board also asks for every other service row on load. Let those land
            # first, so the answer recorded below is the one this press asked for.
            page.wait_for_load_state("networkidle")

            # Ask, from the remote: CENTER on Ask what changed.
            page.locator("#btnWhatChanged").focus()
            answered("what_changed", lambda: page.keyboard.press("Enter"))
            page.locator("#btnStage:not([disabled])").wait_for(timeout=10_000)
            page.wait_for_function("!document.querySelector('#incidentOutput .loading-card')")
            _assert_every_console_shows_what_it_names(page, bodies, "Ask")

            page.keyboard.press("ArrowRight")
            answered("demo_stage_rollback", lambda: page.keyboard.press("Enter"))
            page.locator("#btnConfirm:not([disabled])").wait_for(timeout=10_000)
            _assert_every_console_shows_what_it_names(page, bodies, "Stage")

            page.keyboard.press("ArrowRight")
            answered("demo_confirm_rollback", lambda: page.keyboard.press("Enter"))
            page.wait_for_function(
                "document.querySelector('#heroEyebrow').textContent.includes('recorded, not sent')")
            _assert_every_console_shows_what_it_names(page, bodies, "Confirm")

            # Open the panel the way a viewer does and read what is painted.
            page.locator('.tile[data-panel="incident"]').click()
            painted = page.locator("#panel-incident").inner_text()
            assert "Baseline mean" in painted, painted
            assert bodies["demo_confirm_rollback"]["status"] in painted, painted
            headers = [c["header"] for c in page.evaluate(READ_INCIDENT_CONSOLES)]
            assert "POST /mcp/tools/what_changed" in headers, headers
            assert "POST /mcp/tools/demo_confirm_rollback" in headers, headers

            # A fresh Ask owns the panel again: its correlation is shown, and the
            # rollback console no longer names or shows the spent rollback.
            del bodies["demo_stage_rollback"], bodies["demo_confirm_rollback"]
            spent = page.evaluate(READ_INCIDENT_CONSOLES)
            answered("what_changed", lambda: page.locator("#btnWhatChanged").click())
            page.wait_for_function("!document.querySelector('#incidentOutput .loading-card')")
            consoles = _assert_every_console_shows_what_it_names(page, bodies, "a second Ask")
            for console in consoles:
                assert "RECORDED_ONLY" not in console["text"], console
                assert not console["header"].endswith("_rollback"), console
            assert len(consoles) == len(spent), (spent, consoles)
            browser.close()
    finally:
        _stop_server(process)


def test_a_slow_first_answer_never_lands_under_the_second_call_in_its_console():
    """Opening Delivery velocity fires the DORA call; Scan stale pull requests shares its console.

    If the viewer pressed Scan while DORA was still in flight, the header switched to
    get_pr_bottlenecks and the late DORA body was then painted under it. The DORA
    response is held here until the pull request answer is on screen, then released.
    """
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    sync_playwright = _browser_api()
    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    process = _start_server(port)
    try:
        _wait_for_server(base, process)
        with sync_playwright() as driver:
            browser = driver.chromium.launch()
            page = browser.new_page(viewport={"width": 1920, "height": 1080})
            held = []
            page.route("**/mcp/tools/get_dora_velocity_report", lambda route: held.append(route))
            page.goto(base, wait_until="domcontentloaded")
            page.locator("#btnStage:not([disabled])").wait_for(timeout=15_000)

            page.locator('.tile[data-panel="velocity"]').click()
            page.wait_for_function("document.querySelector('#doraOutput .loading-card') !== null")
            assert len(held) == 1, "opening the panel should have sent the DORA call"
            page.locator('[data-action="prs"]').click()
            page.wait_for_function("!document.querySelector('#doraOutput .loading-card')")
            assert "Past the 36 hour SLA" in page.locator("#doraOutput").inner_text()

            with page.expect_response(lambda r: r.url.endswith("/get_dora_velocity_report")):
                held[0].continue_()
            # Give the late answer every chance to paint before reading the console.
            page.evaluate("new Promise(r => setTimeout(r, 300))")
            header = page.locator("#doraEndpoint").inner_text()
            shown = page.locator("#doraOutput").inner_text()
            assert header == "POST /mcp/tools/get_pr_bottlenecks", header
            assert "Past the 36 hour SLA" in shown, shown
            assert "Deploys per day" not in shown, shown
            browser.close()
    finally:
        _stop_server(process)


def test_a_refused_confirm_puts_its_reason_on_screen_above_the_key_bar():
    """A refused Confirm opens Incident evidence, and the refusal has to be in view.

    The rollback answers moved out of the correlation's console into their own. Placed
    under the correlation, a refusal rendered below a panel longer than the screen, so
    the viewer was sent to the panel and shown no reason. The server's refusal is
    stood in for here by a 409 at the network, at the TV size and at the host layout.
    """
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    sync_playwright = _browser_api()
    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    process = _start_server(port)
    try:
        _wait_for_server(base, process)
        with sync_playwright() as driver:
            browser = driver.chromium.launch()
            for width, height, host in [(1920, 1080, False), (960, 540, True)]:
                context = browser.new_context(viewport={"width": width, "height": height})
                if host:
                    context.add_init_script(HOST_STUB)
                page = context.new_page()
                page.route("**/mcp/tools/demo_confirm_rollback", lambda route: route.fulfill(
                    status=409, content_type="application/json",
                    body='{"detail": "TOKEN_ALREADY_USED: that token has been spent"}'))
                page.goto(base, wait_until="domcontentloaded")
                page.locator("#btnStage:not([disabled])").wait_for(timeout=15_000)
                page.evaluate("window.navigateDpad('RIGHT')")
                page.evaluate("window.navigateDpad('SELECT')")
                page.locator("#btnConfirm:not([disabled])").wait_for(timeout=10_000)
                page.evaluate("window.navigateDpad('RIGHT')")
                page.evaluate("window.navigateDpad('SELECT')")
                page.locator("#rollbackOutput .error-card").wait_for(timeout=10_000)
                shown = page.evaluate(
                    "(() => { const c = document.querySelector('#rollbackOutput .error-card').getBoundingClientRect();"
                    " const bar = document.querySelector('.keybar').getBoundingClientRect();"
                    " return { top: c.top, bottom: c.bottom, bar: bar.top,"
                    " header: document.querySelector('#rollbackEndpoint').textContent,"
                    " text: document.querySelector('#rollbackOutput').innerText }; })()")
                assert "TOKEN_ALREADY_USED" in shown["text"], shown
                assert shown["header"] == "POST /mcp/tools/demo_confirm_rollback", shown
                assert 0 <= shown["top"] and shown["bottom"] <= shown["bar"], (
                    f"at {width}x{height} the refusal is off screen or under the key bar: {shown}")
                context.close()
            browser.close()
    finally:
        _stop_server(process)
