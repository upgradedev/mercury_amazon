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
* in every verdict, every board row stays above the remote's key bar, both at
  1920x1080 and in the Fire TV WebView's 960x540 CSS viewport.

It lives in ``tests/ux`` for the reason ``test_ten_foot_legibility.py`` gives:
readiness gate C5 looks for a user-journey browser test under ``tests/e2e``, and
these are measurements of the board, not a journey.

Needs the optional browser extra, and skips where it is absent::

    pip install -e ".[ux]" && playwright install chromium
"""
from __future__ import annotations

import asyncio
import json
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


# ------------------------------------------------------------ The quoted commit

COMMIT_BADGE = """() => {
  const badges = [...document.querySelectorAll('#heroSource .src-badge')];
  const commits = badges.find(b => b.textContent.includes('commits'));
  const note = document.querySelector('#standInNote');
  return { description: commits && commits.getAttribute('aria-description'),
           title: commits && commits.title,
           visible: commits && commits.textContent,
           note: note && note.textContent.replace(/\\s+/g, ' ').trim() };
}"""


def test_the_quoted_commit_is_described_as_this_repositorys_history_standing_in_for_a_deploy(
        browser, base_url):
    """Offline, the board quotes one of Mercury's own commits against checkout-api.

    The page has to say where that commit came from: the commits badge carries the
    server's own provenance sentence as its accessible description, prefixed with
    what the commit stands in for, and the evidence note says it in one line.

    The visible text changed. It was a green LIVE stamp and the slug local-git, and on
    a television, which has no hover, that read as a live deploy feed. Commits from
    this repository's own history now show a STAND-IN stamp and say whose they are.
    """
    request = urllib.request.Request(
        base_url + "/mcp/tools/what_changed", data=b'{"service": "checkout-api"}',
        headers={"content-type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=20) as response:
        body = json.load(response)
    provenance = body["commit_provenance"]
    assert provenance["data_source"] in ("local-git", "offline-fixture"), provenance
    sha = body["offending_commit"]["sha"]
    # Real history, never an invented commit: the named sha is in this checkout.
    if (REPO_ROOT / ".git").exists():
        subprocess.run(["git", "cat-file", "-e", sha + "^{commit}"], cwd=REPO_ROOT, check=True)

    context, page, errors, _ = open_board(browser, base_url)
    try:
        wait_for_board(page)
        badge = page.evaluate(COMMIT_BADGE)
        expected = "Standing in for deploys of checkout-api: " + provenance["detail"]
        assert badge["description"] == expected
        assert badge["title"] == expected
        if provenance["data_source"] == "local-git":
            assert badge["visible"] == "STAND-IN" + "Mercury’s commits"
        else:
            slug = provenance["data_source"]
            repeats = slug.replace("-", " ").lower() == provenance["display_label"].lower()
            assert badge["visible"] == provenance["display_label"] + "commits" + ("" if repeats else ": " + slug)
        assert badge["note"] == ("Without a GitHub token, the commit named under a spike is the newest "
                                 "lone commit in Mercury's own git history, standing in for a deploy.")
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


DPAD_FROM_THE_PRIMARY = """() => {
  const nav = window.mercuryNav;
  const id = el => el && (el.id || el.getAttribute('data-service'));
  const ask = document.querySelector('#btnWhatChanged');
  nav.setFocus(ask);
  window.navigateDpad('DOWN');
  const down = id(nav.current);
  window.navigateDpad('UP');
  const up = id(nav.current);
  const row = document.querySelector('.btn-demo[data-service="search-indexer"]');
  nav.setFocus(row);
  window.navigateDpad('RIGHT');
  const right = id(nav.current);
  nav.setFocus(ask);
  window.scrollTo(0, 0);
  return { down, up, right };
}"""


@pytest.mark.parametrize(
    "width, height, host",
    [(1920, 1080, False), (1280, 720, False), (960, 540, True)],
    ids=["tv-browser-1920x1080", "laptop-1280x720", "firetv-webview-960x540"],
)
def test_down_from_the_primary_enters_the_board_and_up_comes_back(browser, base_url, width, height, host):
    """DOWN from the landing focus used to skip all five departures.

    The navigator scored centre to centre, so the full-width rows 21px under the narrow
    primary button counted as 680px off to the side, and DOWN jumped about 1400px to
    Publish handoff. UP from the first row went to Stage, and RIGHT from any row jumped
    down the page to a tile. Measured on the page at all three sizes the review used.
    """
    context, page, errors, _ = open_board(browser, base_url, width=width, height=height, host=host)
    try:
        wait_for_board(page)
        moves = page.evaluate(DPAD_FROM_THE_PRIMARY)
        assert moves == {"down": "checkout-api", "up": "btnWhatChanged", "right": "search-indexer"}, moves
        assert errors == [], errors
    finally:
        context.close()


WHERE_THE_CURSOR_IS = """() => {
  const c = window.mercuryNav.current;
  const panel = c && c.closest('[data-panel-body]');
  return { panel: panel ? panel.id : null,
           label: c && (c.getAttribute('data-tv-label') || c.id),
           tile: c && c.getAttribute('data-panel'),
           move: document.querySelector('#hintMove').textContent,
           back: document.querySelector('#hintBack').textContent };
}"""


@pytest.mark.parametrize(
    "width, height, host",
    [(1920, 1080, False), (960, 540, True)],
    ids=["tv-browser-1920x1080-keyboard", "firetv-webview-960x540-bridge"],
)
def test_an_open_panel_holds_the_remote_until_back_closes_it(browser, base_url, width, height, host):
    """With a panel open, DOWN used to walk out to Connection > Check.

    The legend still said BACK goes back to the wall, and UP walked on to the board.
    Every direction, pressed again and again, has to keep the cursor inside the open
    panel, and the legend has to say so; BACK then closes the panel onto its tile and
    the whole page is reachable again. At 1920x1080 the keys are real key presses; in
    the Fire TV WebView they go through window.navigateDpad, as the remote's do.
    """
    context, page, errors, _ = open_board(browser, base_url, width=width, height=height, host=host)

    def press(direction):
        if host:
            assert page.evaluate(f"window.navigateDpad('{direction}')") is True
        else:
            page.keyboard.press("Arrow" + direction.capitalize())

    try:
        wait_for_board(page)
        for panel in ("incident", "velocity", "spend", "how"):
            page.evaluate(
                f"""() => {{ window.mercuryNav.setFocus(document.querySelector('.tile[data-panel="{panel}"]'));
                            return window.navigateDpad('SELECT'); }}""")
            opened = page.evaluate(WHERE_THE_CURSOR_IS)
            assert opened["panel"] == f"panel-{panel}", opened
            assert opened["move"] == "Move in panel", opened
            assert opened["back"] == "Back to the wall", opened
            for direction in ["DOWN"] * 5 + ["RIGHT"] * 3 + ["UP"] * 5 + ["LEFT"] * 3 + ["DOWN"] * 3:
                press(direction)
                where = page.evaluate(WHERE_THE_CURSOR_IS)
                assert where["panel"] == f"panel-{panel}", (
                    f"{direction} in the {panel} panel moved the cursor out to {where['label']}")
                assert where["move"] == "Move in panel" and where["back"] == "Back to the wall", where
            assert page.evaluate("window.navigateDpad('BACK')") is True
            closed = page.evaluate(WHERE_THE_CURSOR_IS)
            assert closed["tile"] == panel and closed["panel"] is None, closed
            assert closed["move"] == "Move" and closed["back"] == "Exit to the Fire TV launcher", closed
        # Closed, the page is whole again: DOWN from the last tile reaches Connection.
        page.evaluate("window.navigateDpad('DOWN')")
        assert page.evaluate("window.mercuryNav.current.id") == "btnCheck"
        assert errors == [], errors
    finally:
        context.close()


def test_down_at_the_foot_of_a_long_panel_scrolls_it_into_view_above_the_key_bar(browser, base_url):
    """Held inside the panel, the remote still reads all of it.

    The incident evidence runs well past one 960x540 screen. Before containment the
    only way to see its foot with the remote was to walk out of the panel. DOWN at the
    panel's last control now scrolls it, a step at a time, until its bottom clears the
    key bar, and UP brings its heading back.
    """
    context, page, errors, _ = open_board(browser, base_url, width=960, height=540, host=True)
    try:
        wait_for_board(page)
        page.evaluate(
            """() => { window.mercuryNav.setFocus(document.querySelector('.tile[data-panel="incident"]'));
                      return window.navigateDpad('SELECT'); }""")
        geometry = """() => { const r = document.querySelector('#panel-incident').getBoundingClientRect();
            const bar = document.querySelector('.keybar').getBoundingClientRect();
            return { top: r.top, bottom: r.bottom, bar: bar.top, inner: innerHeight }; }"""
        start = page.evaluate(geometry)
        assert start["bottom"] > start["bar"], f"the panel fits, so this proves nothing: {start}"
        for _ in range(12):
            page.evaluate("window.navigateDpad('DOWN')")
        end = page.evaluate(geometry)
        assert abs(end["bottom"] - end["bar"]) <= 2, f"the panel's foot is not just above the key bar: {end}"
        assert page.evaluate(WHERE_THE_CURSOR_IS)["panel"] == "panel-incident"
        for _ in range(12):
            page.evaluate("window.navigateDpad('UP')")
        top = page.evaluate(geometry)
        assert abs(top["top"]) <= 1, f"UP did not bring the panel heading back: {top}"
        assert errors == [], errors
    finally:
        context.close()


def test_the_held_out_sentence_stays_in_the_evidence_whichever_row_is_asked(browser, base_url):
    """The evidence header measures the correlator, and the server ships it with every answer.

    The page used to clear it when the viewer walked to Nothing to revert or
    Insufficient data, so the sentence under the board changed as the cursor moved.
    The short figure under the verdict stays with a named commit only.
    """
    context, page, errors, _ = open_board(browser, base_url)
    try:
        wait_for_board(page)
        for service in ("payments-worker", "quiet-service", "search-indexer", "checkout-api"):
            page.evaluate(
                f"""() => {{ window.mercuryNav.setFocus(document.querySelector('.btn-demo[data-service="{service}"]'));
                            return window.navigateDpad('SELECT'); }}""")
            wait_for_board(page, service)
            shown = page.evaluate(
                "() => ({ evidence: document.querySelector('#heroProvenance').textContent,"
                " short: document.querySelector('#heroAccuracy').textContent,"
                " verdict: document.querySelector('#hero').dataset.verdict })")
            assert "Measured on a held-out split" in shown["evidence"], (service, shown)
            if shown["verdict"] == "attributed":
                assert "held-out precision" in shown["short"], (service, shown)
            else:
                assert shown["short"] == "", (service, shown)
        assert errors == [], errors
    finally:
        context.close()


def test_nothing_is_announced_on_load_and_a_press_is_answered_in_one_sentence(browser, base_url):
    """The board used to be read out by a screen reader the moment the page loaded.

    No live region may change while nobody has pressed anything: the only live
    region outside the closed panels is the status line, and it stays empty through
    the load, the flap and the four row calls. Pressing a row then puts one short
    sentence in it.
    """
    context, page, errors, _ = open_board(browser, base_url)
    try:
        wait_for_board(page)
        page.wait_for_timeout(300)
        live = page.evaluate(
            """() => [...document.querySelectorAll('[aria-live], [role="status"], [role="alert"]')]
                   .filter(el => !el.closest('[hidden]'))
                   .map(el => ({ id: el.id, text: el.textContent.trim() }))""")
        assert live == [{"id": "boardStatus", "text": ""}], live
        page.evaluate(
            """() => { window.mercuryNav.setFocus(document.querySelector('.btn-demo[data-service="search-indexer"]'));
                      return window.navigateDpad('SELECT'); }""")
        wait_for_board(page, "search-indexer")
        page.wait_for_function("document.querySelector('#boardStatus').textContent.length > 0")
        said = page.evaluate("document.querySelector('#boardStatus').textContent")
        assert said == "search-indexer: cannot attribute.", said
        assert errors == [], errors
    finally:
        context.close()


@pytest.mark.parametrize("host", [False, True], ids=["desktop-browser", "firetv-host"])
def test_keyboard_focus_moves_on_load_only_on_a_television(browser, base_url, host):
    """On a laptop the first Tab reaches the skip link; on the TV the remote starts on Ask.

    The page used to call focus() on the primary button at load everywhere, so the
    skip link was never the first stop for a keyboard user. The D-pad cursor still
    starts on Ask in both cases, which is what the Android smoke path relies on.
    """
    width, height = (960, 540) if host else (1280, 720)
    context, page, errors, _ = open_board(browser, base_url, width=width, height=height, host=host)
    try:
        wait_for_board(page)
        state = page.evaluate(
            "() => ({ cursor: window.mercuryNav.current && window.mercuryNav.current.id,"
            " active: document.activeElement && (document.activeElement.id || document.activeElement.className) })")
        assert state["cursor"] == "btnWhatChanged"
        if host:
            assert state["active"] == "btnWhatChanged"
        else:
            assert state["active"] != "btnWhatChanged"
            page.keyboard.press("Tab")
            first = page.evaluate("document.activeElement.className")
            assert first == "skip-link", first
            assert page.evaluate("document.querySelectorAll('.tv-focused').length") == 0, (
                "the D-pad ring steps aside while keyboard focus is outside it")
            page.keyboard.press("ArrowRight")
            assert page.evaluate("window.mercuryNav.current.id") == "btnStage"
        assert errors == [], errors
    finally:
        context.close()


# ------------------------------------------------------- Every verdict, every row

EXPECTED_VERDICTS = {
    "checkout-api": "attributed",
    "payments-worker": "nothing",
    "search-indexer": "cannot",
    "release-train": "cannot",
    "quiet-service": "insufficient",
}

BOARD_GEOMETRY = """() => {
  const bar = document.querySelector('.keybar');
  const shown = getComputedStyle(bar).display !== 'none';
  const floor = shown ? bar.getBoundingClientRect().top : innerHeight;
  const box = el => { const r = el.getBoundingClientRect();
                      return { top: r.top, bottom: r.bottom, left: r.left, right: r.right }; };
  let smallest = Infinity;
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  while (walker.nextNode()) {
    const text = walker.currentNode;
    if (!text.textContent.trim()) continue;
    const style = getComputedStyle(text.parentElement);
    if (style.display === 'none' || style.visibility === 'hidden') continue;
    const range = document.createRange(); range.selectNodeContents(text);
    const r = range.getBoundingClientRect();
    if (r.width < 1 || r.height < 1 || r.top >= innerHeight || r.bottom <= 0) continue;
    smallest = Math.min(smallest, parseFloat(style.fontSize));
  }
  return {
    verdict: document.querySelector('#hero').dataset.verdict,
    scrollY: window.scrollY, keybarShown: shown, keybarTop: floor,
    rows: [...document.querySelectorAll('.btn-demo')].map(row => [row.dataset.service, box(row)]),
    primary: box(document.querySelector('[data-testid="primary-hero-action"]')),
    stamp: box(document.querySelector('#heroSource .tag-fixture')),
    stampText: document.querySelector('#heroSource .tag-fixture').textContent,
    overflow: document.documentElement.scrollWidth > innerWidth + 1,
    smallestFont: smallest,
  };
}"""


@pytest.mark.parametrize(
    "width, height, host, floor_px",
    [
        # The board at television resolution in a browser. 24px is the 10-foot floor
        # scripts/measure_legibility.py holds the whole page to.
        (1920, 1080, False, 24.0),
        # The Fire TV app's WebView: a 1080p Fire TV reports 960x540 CSS pixels at
        # two device pixels each (an assumption about the device class, not a
        # measurement of one), so 12 CSS pixels is the same 24 on the panel.
        (960, 540, True, 12.0),
    ],
    ids=["tv-browser-1920x1080", "firetv-webview-960x540"],
)
def test_every_board_row_stays_above_the_key_bar_in_every_verdict(
        browser, base_url, width, height, host, floor_px):
    """A refusal's longer answer used to push the last departures behind the key bar.

    Each state is reached the way the remote reaches it: the cursor is put on the row
    and SELECT is sent through window.navigateDpad, the entry point the Android app
    calls. The navigator scrolls whenever the focused row is not wholly visible, so a
    regression shows up as a scrolled page as well as a covered row.
    """
    context, page, errors, _ = open_board(browser, base_url, width=width, height=height, host=host)
    try:
        wait_for_board(page)
        for service, verdict in EXPECTED_VERDICTS.items():
            if service != "checkout-api":
                page.evaluate(
                    """s => { const row = document.querySelector('.btn-demo[data-service="' + s + '"]');
                              window.mercuryNav.setFocus(row);
                              return window.navigateDpad('SELECT'); }""",
                    service,
                )
                wait_for_board(page, service)
            geometry = page.evaluate(BOARD_GEOMETRY)
            where = f"{service} at {width}x{height}"
            assert geometry["verdict"] == verdict, f"{where}: reached {geometry['verdict']}"
            assert geometry["keybarShown"], f"{where}: the remote's key bar is not shown"
            assert geometry["scrollY"] == 0, f"{where}: the page scrolled to {geometry['scrollY']}"
            bar = geometry["keybarTop"]
            covered = [name for name, box in geometry["rows"] if box["top"] < 0 or box["bottom"] > bar]
            assert covered == [], f"{where}: rows behind the key bar at y={bar}: {covered}"
            for label in ("primary", "stamp"):
                box = geometry[label]
                assert box["top"] >= 0 and box["bottom"] <= bar and box["right"] <= width, (
                    f"{where}: the {label} is not wholly on the first screen: {box}"
                )
            assert geometry["stampText"] == "OFFLINE FIXTURE"
            assert geometry["overflow"] is False, f"{where}: the page scrolls sideways"
            assert geometry["smallestFont"] >= floor_px, (
                f"{where}: text renders at {geometry['smallestFont']}px, under {floor_px}px"
            )
        assert errors == [], errors
    finally:
        context.close()
