"""The departures board, driven in Chromium against a real local server.

These were scratch scripts during the redesign; they are committed here so the
claims they checked stay checked:

* the page renders its own fonts with every request to another origin aborted,
  which is the Fire TV case where a font CDN is unreachable;
* the split-flap verdict line starts only after the what_changed response it
  shows has returned, settles to one text node equal to the server's verdict,
  and draws no letter cells at all under prefers-reduced-motion;
* the D-pad cursor starts on the primary action and the remote reaches every
  visible control through window.navigateDpad, the entry point the app calls;

It lives in ``tests/ux`` for the reason ``test_ten_foot_legibility.py`` gives:
readiness gate C5 looks for a user-journey browser test under ``tests/e2e``, and
these are measurements of the board, not a journey.

Needs the optional browser extra, and skips where it is absent::

    pip install -e ".[ux]" && playwright install chromium
"""
from __future__ import annotations

import asyncio
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
FAMILIES = ("Barlow", "Barlow Condensed", "JetBrains Mono")


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
        # pytest-asyncio installs a selector policy on Windows, while Playwright's
        # Node driver needs subprocess support from the proactor policy.
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    return factory


@pytest.fixture(scope="module")
def base_url(tmp_path_factory):
    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    env = os.environ.copy()
    env["MERCURY_OFFLINE"] = "1"
    for name in ("MERCURY_ROLLBACK_DISPATCH", "MERCURY_STATE_TABLE", "GITHUB_TOKEN"):
        env.pop(name, None)
    # The server's access log goes to a file, not a pipe: nothing drains a pipe while
    # the browser runs, and a full one stalls the server mid-module.
    log_path = tmp_path_factory.mktemp("server") / "uvicorn.log"
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
        except Exception as error:  # the browser download is a separate step
            if os.getenv("MERCURY_REQUIRE_BROWSER") == "1":
                raise
            pytest.skip(f"Chromium is not installed: {error}")
        yield launched
        launched.close()


def open_board(browser, base_url, *, width=1920, height=1080, host=False, reduced_motion=None,
               offline=False, init_script=None):
    """Open the board and return (context, page, console_errors, refused_requests)."""
    options = {"viewport": {"width": width, "height": height}, "device_scale_factor": 1,
               "color_scheme": "dark"}
    if reduced_motion:
        options["reduced_motion"] = reduced_motion
    context = browser.new_context(**options)
    if host:
        # What the Fire TV app injects before the page runs (MainActivity.MercuryHost).
        context.add_init_script("window.MercuryHost = { reportJourney: function () {} };")
    if init_script:
        context.add_init_script(init_script)
    refused: list[str] = []
    if offline:
        local = urlsplit(base_url).netloc

        def only_this_origin(route):
            if urlsplit(route.request.url).netloc == local:
                route.continue_()
            else:
                refused.append(route.request.url)
                route.abort()

        context.route("**/*", only_this_origin)
    page = context.new_page()
    errors: list[str] = []
    page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(base_url + "/", wait_until="domcontentloaded")
    return context, page, errors, refused


def wait_for_board(page, service="checkout-api"):
    """Every row has its own answer, and the verdict line has stopped flipping."""
    page.wait_for_function(
        """() => [...document.querySelectorAll('.btn-demo [data-row-verdict]')]
                 .every(v => v.dataset.verdict && v.dataset.verdict !== 'pending')""",
        timeout=20_000,
    )
    page.wait_for_function(
        """s => document.querySelector('#heroService').textContent === s
               && !document.querySelector('#heroLive').hasAttribute('aria-busy')
               && document.querySelector('#hero').dataset.verdict !== 'asking'""",
        arg=service, timeout=20_000,
    )


# ----------------------------------------------------------------------- Fonts

def test_the_board_renders_its_own_fonts_with_every_other_origin_unreachable(browser, base_url):
    """The Fire TV case: nothing but the Mercury origin answers.

    Every request not addressed to the local server is aborted and recorded. The
    board has to settle with no such request made, every family loaded from this
    origin, and no console error.
    """
    context, page, errors, refused = open_board(browser, base_url, offline=True)
    try:
        wait_for_board(page)
        page.evaluate("document.fonts.ready.then(() => true)")
        loaded = page.evaluate(
            """families => families.map(family => ({
                 family,
                 check: document.fonts.check('600 24px "' + family + '"'),
                 faces: [...document.fonts].filter(f => f.family.replace(/["']/g, '') === family
                                                    && f.status === 'loaded').length
               }))""",
            list(FAMILIES),
        )
        assert refused == [], f"the board asked another origin for {refused}"
        for entry in loaded:
            assert entry["check"], f"{entry['family']} is not available to render"
            # check() is also true when no @font-face names the family at all, so a
            # face with that family has to have actually loaded.
            assert entry["faces"] >= 1, f"no {entry['family']} face loaded"
        assert errors == [], errors
    finally:
        context.close()



# ------------------------------------------------------------------ Split flap

HOLD_MS = 700

# Records every letter cell the split flap inserts, and holds each what_changed
# response in the page for HOLD_MS before the page's own code sees it, noting when
# it was released. The flap may only start after that moment.
FLAP_PROBE = """
(() => {
  const probe = window.__flapProbe = { cells: [], released: {}, bodies: {} };
  new MutationObserver(mutations => {
    for (const mutation of mutations) {
      for (const node of mutation.addedNodes) {
        if (node.nodeType === 1 && (node.matches('.flap-cell') || node.querySelector('.flap-cell'))) {
          probe.cells.push(performance.now());
        }
      }
    }
  }).observe(document, { childList: true, subtree: true });
  const realFetch = window.fetch;
  window.fetch = async function (url, options) {
    const response = await realFetch.apply(this, arguments);
    if (String(url).indexOf('/mcp/tools/what_changed') !== -1) {
      const asked = JSON.parse(options.body).service_name;
      const body = await response.clone().json();
      await new Promise(resolve => setTimeout(resolve, HOLD_MS));
      if (!(asked in probe.released)) { probe.released[asked] = performance.now(); }
      probe.bodies[asked] = body;
    }
    return response;
  };
})();
""".replace("HOLD_MS", str(HOLD_MS))

HEADLINE_STATE = """() => {
  const node = document.querySelector('#heroHeadline');
  return { nodes: node.childNodes.length, isText: !!node.firstChild && node.firstChild.nodeType === 3,
           text: node.textContent };
}"""


def test_the_verdict_line_flips_only_after_the_answer_and_settles_to_the_server_verdict(
        browser, base_url):
    context, page, errors, _ = open_board(browser, base_url, init_script=FLAP_PROBE)
    try:
        wait_for_board(page)
        probe = page.evaluate("window.__flapProbe")
        body = probe["bodies"]["checkout-api"]
        assert body["verdict"] == "ANOMALY_ATTRIBUTED", "the fixture no longer attributes checkout-api"
        released = probe["released"]["checkout-api"]
        assert probe["cells"], "the verdict line did not flip at all, so this proves nothing"
        early = [at for at in probe["cells"] if at < released]
        assert early == [], f"{len(early)} flap cells appeared while the answer was still held"
        headline = page.evaluate(HEADLINE_STATE)
        assert headline == {"nodes": 1, "isText": True,
                            "text": "Commit " + body["offending_commit"]["sha"]}
        assert errors == [], errors
    finally:
        context.close()


def test_the_verdict_line_is_instant_under_reduced_motion(browser, base_url):
    context, page, errors, _ = open_board(browser, base_url, init_script=FLAP_PROBE,
                                          reduced_motion="reduce")
    try:
        wait_for_board(page)
        probe = page.evaluate("window.__flapProbe")
        assert probe["cells"] == [], "letter cells were drawn although motion is reduced"
        headline = page.evaluate(HEADLINE_STATE)
        sha = probe["bodies"]["checkout-api"]["offending_commit"]["sha"]
        assert headline == {"nodes": 1, "isText": True, "text": "Commit " + sha}
        assert errors == [], errors
    finally:
        context.close()


# -------------------------------------------------------------------- D-pad ring

REACHABLE_BY_DPAD = """() => {
  const nav = window.mercuryNav;
  const selector = window.mercuryNavInternals.FOCUSABLE_SELECTOR;
  const visible = el => { const r = el.getBoundingClientRect(); return !el.hidden && r.width > 0 && r.height > 0; };
  const name = el => el.id || el.getAttribute('data-tv-label') || el.textContent.trim().slice(0, 40);
  const all = [...document.querySelectorAll(selector)].filter(visible);
  const start = nav.current;
  const seen = new Set([start]);
  const queue = [start];
  while (queue.length) {
    const from = queue.shift();
    for (const direction of ['UP', 'DOWN', 'LEFT', 'RIGHT']) {
      nav.setFocus(from);
      if (window.navigateDpad(direction) !== true) { return { error: 'navigateDpad refused ' + direction }; }
      const to = nav.current;
      if (to && !seen.has(to)) { seen.add(to); queue.push(to); }
    }
  }
  nav.setFocus(start);
  window.scrollTo(0, 0);
  return { total: all.length, reached: seen.size,
           unreachable: all.filter(el => !seen.has(el)).map(name) };
}"""


def test_focus_starts_on_the_primary_and_the_remote_reaches_every_visible_control(
        browser, base_url):
    context, page, errors, _ = open_board(browser, base_url)
    try:
        wait_for_board(page)
        start = page.evaluate(
            "() => ({ id: window.mercuryNav.current && window.mercuryNav.current.id,"
            " ring: document.querySelector('.tv-focused') && document.querySelector('.tv-focused').id })"
        )
        assert start == {"id": "btnWhatChanged", "ring": "btnWhatChanged"}
        result = page.evaluate(REACHABLE_BY_DPAD)
        assert "error" not in result, result
        assert result["total"] >= 10, "almost nothing is focusable, so this proves little"
        assert result["unreachable"] == [], (
            f"{len(result['unreachable'])} of {result['total']} visible controls cannot be reached "
            f"with the remote: {result['unreachable']}"
        )
        assert errors == [], errors
    finally:
        context.close()

