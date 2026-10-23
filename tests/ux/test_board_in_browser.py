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
import random
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
        # pytest-asyncio installs a selector policy on Windows, while Playwright's
        # Node driver needs subprocess support from the proactor policy.
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    return factory


@pytest.fixture(scope="module")
def base_url(tmp_path_factory):
    env = os.environ.copy()
    env["MERCURY_OFFLINE"] = "1"
    for name in ("MERCURY_ROLLBACK_DISPATCH", "MERCURY_STATE_TABLE", "GITHUB_TOKEN"):
        env.pop(name, None)
    yield from _serve(tmp_path_factory, env, ["-m", "uvicorn", "src.interfaces.mcp_server:app"])


#: The server for the hybrid page (MERCURY_LIVE_CLOUDWATCH=1). CloudWatch is a stub set
#: on the server's own adapter before it starts, so the three production rows are
#: drawn LIVE without any AWS call; volcan's and aletheia's errors rise, so two rows
#: read as anomalies Mercury cannot attribute.
LIVE_ROWS_SERVER = """
import sys
from datetime import datetime, timedelta, timezone

import uvicorn

from src.interfaces import mcp_server


#: volcan's errors rise against a baseline (an anomaly the board cannot attribute);
#: aletheia's rise from a baseline of zero, which has no ratio; the wallboard is quiet.
ERRORS = {
    "volcan-mcp-euw1-prod": (1, 0, 0, 0, 0, 1),
    "aletheia-provenance-euw1-prod": (0, 0, 0, 0, 0, 4),
}


class CloudWatchStub:
    def get_metric_statistics(self, **kwargs):
        function = kwargs["Dimensions"][0]["Value"]
        if kwargs["MetricName"] == "Errors":
            values = ERRORS.get(function, (0, 0, 0, 0, 0, 0))
        else:
            values = (5, 4, 6, 3, 5, 4)
        end = datetime.now(timezone.utc)
        return {"Datapoints": [
            {"Timestamp": end - timedelta(hours=len(values) - index), "Sum": float(value)}
            for index, value in enumerate(values)
        ]}


mcp_server.cloudwatch_adapter._client = CloudWatchStub()
uvicorn.run(mcp_server.app, host="127.0.0.1", port=int(sys.argv[sys.argv.index("--port") + 1]))
"""


@pytest.fixture(scope="module")
def live_rows_base_url(tmp_path_factory):
    """The page as the hybrid deployment serves it: five fixture rows and three live ones.

    No AWS credential can resolve in this server (the stub answers instead), so nothing
    here reaches AWS whatever the developer's shell holds.
    """
    env = os.environ.copy()
    env.update({
        "MERCURY_OFFLINE": "1",
        "MERCURY_LIVE_CLOUDWATCH": "1",
        "AWS_EC2_METADATA_DISABLED": "true",
        "AWS_SHARED_CREDENTIALS_FILE": str(tmp_path_factory.mktemp("no_aws") / "credentials"),
        "AWS_CONFIG_FILE": str(tmp_path_factory.mktemp("no_aws_config") / "config"),
    })
    for name in ("MERCURY_ROLLBACK_DISPATCH", "MERCURY_STATE_TABLE", "GITHUB_TOKEN",
                 "MERCURY_LIVE_GITHUB", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY",
                 "AWS_SESSION_TOKEN", "AWS_PROFILE", "AWS_DEFAULT_PROFILE",
                 "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI", "AWS_CONTAINER_CREDENTIALS_FULL_URI"):
        env.pop(name, None)
    yield from _serve(tmp_path_factory, env, ["-c", LIVE_ROWS_SERVER])


def _serve(tmp_path_factory, env, args):
    """Start ``python <args> --host 127.0.0.1 --port <port>``, yield its URL once healthy."""
    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    # The server's access log goes to a file, not a pipe: nothing drains a pipe while
    # the browser runs, and a full one stalls the server mid-module.
    log_path = tmp_path_factory.mktemp("server") / "uvicorn.log"
    log = open(log_path, "w", encoding="utf-8")
    process = subprocess.Popen(
        [sys.executable, *args, "--host", "127.0.0.1", "--port", str(port)],
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
               offline=False, init_script=None, routes=()):
    """Open the board and return (context, page, console_errors, refused_requests).

    ``routes`` is a sequence of (url pattern, handler) pairs registered before the
    page loads, for a test that needs to show the board an answer this checkout's
    server does not give (the public Lambda's, which has no git checkout).
    """
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
    for pattern, handler in routes:
        context.route(pattern, handler)
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
        if provenance["data_source"] != "local-git":
            pytest.skip("without a git checkout the stamps merge into one stripe; "
                        "test_matching_stamps_merge_into_one_stripe covers that path")
        badge = page.evaluate(COMMIT_BADGE)
        expected = "Standing in for deploys of checkout-api: " + provenance["detail"]
        assert badge["description"] == expected
        assert badge["title"] == expected
        assert badge["visible"] == "STAND-IN" + "Mercury’s commits"
        assert badge["note"] == ("Without a GitHub token, the commit named under a spike is the newest "
                                 "lone commit in Mercury's own git history, standing in for a deploy.")
        assert errors == [], errors
    finally:
        context.close()


def _as_the_public_lambda_answers(route):
    """Rewrite one what_changed answer the way the public Lambda gives it.

    The Lambda has no git checkout, so its commits come from the display-only deploy
    feed, stamped OFFLINE FIXTURE like the metric. This checkout's server reads local
    git instead, so the stamp is rewritten here and nothing else is.
    """
    from src.infrastructure.deploy_feed_fixture import DeployFeedFixtureProvider

    response = route.fetch()
    body = response.json()
    if body.get("commit_provenance"):
        body["commit_provenance"] = {
            "data_source": "offline-fixture", "is_live": False, "display_label": "OFFLINE FIXTURE",
            "detail": DeployFeedFixtureProvider().detail.format(count=8),
            "observed_at_utc": body["commit_provenance"].get("observed_at_utc", ""),
        }
    route.fulfill(response=response, json=body)


HERO_STAMPS = """() => {
  const source = document.querySelector('#heroSource');
  const badges = [...source.querySelectorAll('.src-badge')];
  const note = document.querySelector('#standInNote');
  return { badges: badges.length, tags: source.querySelectorAll('.tag').length,
           text: source.textContent,
           description: badges[0] && badges[0].getAttribute('aria-description'),
           title: badges[0] && badges[0].title,
           note: note && note.textContent.replace(/\\s+/g, ' ').trim() };
}"""


def test_matching_stamps_merge_into_one_stripe(browser, base_url):
    """The public board stacked two OFFLINE FIXTURE stripes and a stray "commits".

    With no git checkout the metric and the commits are both offline fixtures. The
    hero now prints that stamp once, with no caption, and keeps where the commits came
    from as the stripe's accessible description and hover text.
    """
    context, page, errors, _ = open_board(
        browser, base_url, routes=[("**/mcp/tools/what_changed", _as_the_public_lambda_answers)])
    try:
        wait_for_board(page)
        stamps = page.evaluate(HERO_STAMPS)
        assert stamps["badges"] == 1, stamps
        assert stamps["tags"] == 1, stamps
        assert stamps["text"] == "OFFLINE FIXTURE", stamps
        assert "commits" not in stamps["text"]
        assert "Standing in for deploys of checkout-api: " in stamps["description"]
        assert "written by hand" in stamps["description"]
        assert stamps["title"] == stamps["description"]
        assert stamps["note"].startswith("Without a GitHub token or a git checkout, the deploy named")
        assert "invented, display-only deploy feed" in stamps["note"]
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

    Board and agent status regions stay empty through load, the flap and row
    calls. Pressing a row updates only the board's status in one short sentence.
    """
    context, page, errors, _ = open_board(browser, base_url)
    try:
        wait_for_board(page)
        page.wait_for_timeout(300)
        live = page.evaluate(
            """() => [...document.querySelectorAll('[aria-live], [role="status"], [role="alert"]')]
                   .filter(el => !el.closest('[hidden]'))
                   .map(el => ({ id: el.id, text: el.textContent.trim() }))""")
        assert {entry["id"]: entry["text"] for entry in live} == {
            "boardStatus": "", "bedrockAgentStatus": "",
        }, live
        page.evaluate(
            """() => { window.mercuryNav.setFocus(document.querySelector('.btn-demo[data-service="search-indexer"]'));
                      return window.navigateDpad('SELECT'); }""")
        wait_for_board(page, "search-indexer")
        page.wait_for_function("document.querySelector('#boardStatus').textContent.length > 0")
        said = page.evaluate("document.querySelector('#boardStatus').textContent")
        assert said == "search-indexer: cannot attribute.", said
        assert page.locator("#bedrockAgentStatus").text_content() == ""
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
            # Which tile is nearest the skip link depends on the board's
            # geometry, and the board renders genuine `git log` history, so a
            # new commit can move the ring's landing tile (9885eac proved it:
            # same tree as the green run, ring lands on an id-less tile, not
            # btnStage). Pin the behavior, not the coordinate: ArrowRight must
            # re-engage the ring on a control.
            current = page.evaluate(
                "() => { const c = window.mercuryNav.current;"
                " return c ? c.tagName + '.' + c.className : 'none'; }")
            assert current.startswith("BUTTON."), current
            assert "tv-focused" in current, current
        assert errors == [], errors
    finally:
        context.close()


def test_a_200_character_commit_message_does_not_grow_the_hero_cause(browser, base_url):
    """The board renders genuine git history, so the quoted message is unbounded.

    PR #37's CI failed twice on the merge checkout: it attributed the merge
    commit itself, whose 100-character message grew the hero cause a third line
    and pushed quiet-service behind the key bar at 960x540, while every checkout
    with a short message stayed green. The message is set directly here so the
    test does not depend on which commit the checkout happens to attribute.
    """
    context, page, errors, _ = open_board(browser, base_url, width=960, height=540, host=True)
    try:
        wait_for_board(page)
        height_of = """() => {
            const el = document.querySelector('#heroCause');
            return el.getBoundingClientRect().height;
        }"""
        before = page.evaluate(height_of)
        page.evaluate(
            """() => { document.querySelector('#heroCause .quote').textContent =
                             '"' + 'x'.repeat(200) + '"'; }"""
        )
        after = page.evaluate(height_of)
        assert after <= before + 1.0, (
            f"a 200-character message grew the hero cause {before:.1f}px to {after:.1f}px"
        )
        assert errors == [], errors
    finally:
        context.close()


QUALIFIER = "Proximity is not proof of cause."

QUALIFIER_SHOWN = """q => {
  const cause = document.querySelector('#heroCause');
  cause.scrollIntoView({ block: 'center' });
  const box = cause.getBoundingClientRect();
  const walker = document.createTreeWalker(cause, NodeFilter.SHOW_TEXT);
  while (walker.nextNode()) {
    const node = walker.currentNode;
    const at = node.textContent.indexOf(q);
    if (at < 0) continue;
    const range = document.createRange();
    range.setStart(node, at); range.setEnd(node, at + q.length);
    const rects = [...range.getClientRects()].filter(r => r.width > 0 && r.height > 0);
    if (!rects.length) return { found: true, painted: false };
    const inside = rects.every(r => r.top >= box.top - 0.5 && r.bottom <= box.bottom + 0.5
                                    && r.left >= box.left - 0.5 && r.right <= box.right + 0.5);
    const last = rects[rects.length - 1];
    const hit = document.elementFromPoint(last.left + last.width / 2, last.top + last.height / 2);
    return { found: true, painted: true, inside, hit: !!hit && cause.contains(hit),
             display: getComputedStyle(cause).display, rects: rects.length,
             box: [box.top, box.bottom], last: [last.top, last.bottom] };
  }
  return { found: false };
}"""


def test_the_causality_qualifier_stays_visible_at_phone_width(browser, base_url):
    """The two-line clamp on the hero cause must never clip the qualifier.

    The clamp bounds an unbounded commit message. If it wraps the message and the
    qualifier together, a long message at 375 px pushes "Proximity is not proof of
    cause." below the clamp and the board names a commit with no caveat. This checks
    that the qualifier's own painted box sits inside the clamped block, with the
    message the server sends and with a 200-character one.
    """
    context, page, errors, _ = open_board(browser, base_url, width=375, height=812)
    try:
        wait_for_board(page)
        assert page.evaluate("document.querySelector('#hero').dataset.verdict") == "attributed"
        shown = page.evaluate(QUALIFIER_SHOWN, QUALIFIER)
        assert shown.get("painted") and shown["inside"] and shown["hit"], shown
        page.evaluate(
            """() => { document.querySelector('#heroCause .quote').textContent =
                             '"' + 'x'.repeat(200) + '"'; }"""
        )
        shown = page.evaluate(QUALIFIER_SHOWN, QUALIFIER)
        assert shown.get("painted") and shown["inside"] and shown["hit"], (
            f"a 200-character message clipped the qualifier at 375 px: {shown}")
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


# ------------------------------------------------- The hybrid page, eight rows

LIVE_ROWS_GEOMETRY = """() => {
  const box = el => { const r = el.getBoundingClientRect(); return { top: r.top, bottom: r.bottom }; };
  const rows = [...document.querySelectorAll('.departures-rows .btn-demo')];
  const bar = document.querySelector('.keybar');
  const shown = getComputedStyle(bar).display !== 'none';
  return {
    tvHost: document.documentElement.classList.contains('tv-host'),
    scrollY: window.scrollY,
    keybarTop: shown ? bar.getBoundingClientRect().top : innerHeight,
    services: rows.map(row => row.dataset.service),
    stamps: rows.map(row => { const s = row.querySelector('.row-stamp'); return s ? s.textContent.trim() : ''; }),
    rows: rows.map(row => [row.dataset.service, box(row)]),
    rowsBox: box(document.querySelector('.departures-rows')),
    rollback: box(document.querySelector('#rollback')),
    rollbackTitle: box(document.querySelector('#rollbackTitle')),
  };
}"""


@pytest.mark.parametrize(
    "width, height, host",
    [(1280, 720, False), (1920, 1080, False), (960, 540, True)],
    ids=["laptop-1280x720", "tv-browser-1920x1080", "firetv-webview-960x540"],
)
def test_eight_rows_stay_on_the_board_with_the_live_rows_on(
        browser, live_rows_base_url, width, height, host):
    """With MERCURY_LIVE_CLOUDWATCH=1 the board has eight rows where it had five.

    On a laptop the page caps the board at 21rem and shares it out in equal rows, so at
    1280x720 the last live row used to spill out of the board and cover the next
    section's heading, "Governed rollback and handoff". The live rows' own style lifts
    that cap below 1400px; on the television layouts it never applied, and every row
    still has to clear the remote's key bar there.
    """
    from src.infrastructure.cloudwatch_adapter import LIVE_PRODUCTION_FUNCTIONS

    context, page, errors, _ = open_board(
        browser, live_rows_base_url, width=width, height=height, host=host)
    try:
        wait_for_board(page)
        geometry = page.evaluate(LIVE_ROWS_GEOMETRY)
        where = f"{width}x{height}"
        assert geometry["tvHost"] is host, f"{where}: {geometry}"
        assert geometry["services"][-3:] == list(LIVE_PRODUCTION_FUNCTIONS), geometry["services"]
        assert len(geometry["services"]) == 8, geometry["services"]
        assert all(s.startswith("Live ") for s in geometry["stamps"][-3:]), geometry["stamps"]
        name, last = geometry["rows"][-1]
        # Half a pixel for sub-pixel rounding of fractional rem heights.
        assert last["bottom"] <= geometry["rowsBox"]["bottom"] + 0.5, (
            f"{where}: {name} spills out of the board: {last} vs {geometry['rowsBox']}"
        )
        assert last["bottom"] <= geometry["rollback"]["top"], (
            f"{where}: {name} covers the next section: {last} vs {geometry['rollback']}"
        )
        assert last["bottom"] <= geometry["rollbackTitle"]["top"], (
            f"{where}: {name} covers 'Governed rollback and handoff': {geometry['rollbackTitle']}"
        )
        if host or width >= 1400:
            assert geometry["scrollY"] == 0, f"{where}: the page scrolled to {geometry['scrollY']}"
            bar = geometry["keybarTop"]
            covered = [n for n, b in geometry["rows"] if b["top"] < 0 or b["bottom"] > bar]
            assert covered == [], f"{where}: rows behind the key bar at y={bar}: {covered}"
        assert errors == [], errors
    finally:
        context.close()


LIVE_HERO_STATE = """() => ({
  service: document.querySelector('#heroService').textContent,
  verdict: document.querySelector('#hero').dataset.verdict,
  eyebrow: document.querySelector('#heroEyebrow').textContent,
  headline: document.querySelector('#heroHeadline').textContent,
  figure: document.querySelector('#heroFigure').textContent,
  cause: document.querySelector('#heroCause').textContent,
  rows: Object.fromEntries([...document.querySelectorAll('.btn-demo[data-row-source]')].map(row =>
    [row.dataset.service, row.querySelector('[data-row-reading]').textContent])),
  eyebrowBox: (r => [r.top, r.bottom])(document.querySelector('#heroEyebrow').getBoundingClientRect()),
  headlineBox: (r => [r.top, r.bottom])(document.querySelector('#heroHeadline').getBoundingClientRect()),
})"""


@pytest.mark.parametrize(
    "width, height, host",
    [(1920, 1080, False), (960, 540, True)],
    ids=["tv-browser-1920x1080", "firetv-webview-960x540"],
)
def test_a_live_row_hero_never_describes_a_deploy_window(browser, live_rows_base_url, width, height, host):
    """The largest text on the TV must not say a window was read for a live row.

    docs/index.html (frozen) words every cannot-attribute answer outside a crowded
    window as "Incident, cannot attribute: window empty" / "Cannot attribute this: no
    change in the window". No deploy feed is connected for the production functions, so
    no window was read; the switch-on page rewrites those two lines, and the zero-baseline
    factor "0x", while the server's own refusal statement stays under them.
    """
    import re as _re

    from src.interfaces.live_rows import LIVE_HERO_TEXT

    context, page, errors, _ = open_board(
        browser, live_rows_base_url, width=width, height=height, host=host)
    try:
        wait_for_board(page)
        rows = page.evaluate(LIVE_HERO_STATE)["rows"]
        # aletheia's row is filled by the board's own refresh, never selected yet.
        assert rows["aletheia-provenance-euw1-prod"] == LIVE_HERO_TEXT["zero_factor"], rows
        for service in ("volcan-mcp-euw1-prod", "aletheia-provenance-euw1-prod"):
            page.locator(f'.btn-demo[data-service="{service}"]').click()
            wait_for_board(page, service=service)
            page.wait_for_timeout(200)
            hero = page.evaluate(LIVE_HERO_STATE)
            print(service, json.dumps(hero))
            assert hero["verdict"] == "cannot", hero
            for line in (hero["eyebrow"], hero["headline"]):
                assert not _re.search(r"window|no change", line, _re.IGNORECASE), hero
            assert hero["eyebrow"] == LIVE_HERO_TEXT["eyebrow"], hero
            assert hero["headline"] == LIVE_HERO_TEXT["headline"], hero
            assert "No deploy feed is connected" in hero["cause"], hero
            assert "landed" not in hero["cause"], hero
            assert hero["eyebrowBox"][1] <= hero["headlineBox"][0] + 1, hero
        assert hero["figure"] == LIVE_HERO_TEXT["zero_factor"], hero
        assert hero["rows"]["aletheia-provenance-euw1-prod"] == LIVE_HERO_TEXT["zero_factor"], hero
        # A fixture row's empty-window answer keeps the board's own wording: there the
        # recorded commit window was read and really was empty.
        page.locator('.btn-demo[data-service="search-indexer"]').click()
        wait_for_board(page, service="search-indexer")
        fixture = page.evaluate(LIVE_HERO_STATE)
        assert fixture["eyebrow"] == LIVE_HERO_TEXT["window_eyebrow"], fixture
        # The rewritten lines take no more height than the board's own wording did, so
        # the hero keeps its shape on the TV.
        height = lambda box: box[1] - box[0]  # noqa: E731
        assert height(hero["eyebrowBox"]) <= height(fixture["eyebrowBox"]) + 1, (hero, fixture)
        assert height(hero["headlineBox"]) <= height(fixture["headlineBox"]) + 1, (hero, fixture)
        assert errors == [], errors
    finally:
        context.close()


LIVE_ROW_HANDOFF_STATE = """() => {
  const box = el => { if (!el) return null; const r = el.getBoundingClientRect();
    return { top: Math.round(r.top * 10) / 10, bottom: Math.round(r.bottom * 10) / 10 }; };
  const bar = document.querySelector('.keybar');
  const shown = bar && getComputedStyle(bar).display !== 'none' && bar.getBoundingClientRect().height > 0;
  const out = document.querySelector('#handoffOutput');
  const current = window.mercuryNav.current;
  return {
    tvHost: document.documentElement.classList.contains('tv-host'),
    keybarTop: shown ? bar.getBoundingClientRect().top : innerHeight,
    viewport: innerHeight,
    text: out.textContent,
    card: box(out.querySelector('.error-card')),
    focus: current && current.id,
    focusBox: box(current),
    scrollY: Math.round(scrollY),
  };
}"""


@pytest.mark.parametrize(
    "width, height, host",
    [(1920, 1080, True), (960, 540, True)],
    ids=["firetv-1920x1080", "firetv-webview-960x540"],
)
def test_a_live_row_handoff_refusal_is_shown_above_the_key_bar(
        browser, live_rows_base_url, width, height, host):
    """The board's own Publish handoff on a LIVE row, pressed with the D-pad.

    A live row has no recorded demo handoff, so the server answers 422 with its reason.
    The board's error card used to render behind the remote's key bar with the page not
    scrolled, so a TV viewer saw only "HTTP 422" in the console header and never the
    reason. The card must come up above the bar, with the cursor still on Publish.
    """
    from src.interfaces.handoff_routes import DEMO_HANDOFF_UNAVAILABLE

    context, page, errors, _ = open_board(
        browser, live_rows_base_url, width=width, height=height, host=host)
    calls: list[tuple[str, int]] = []
    page.on("response", lambda response: calls.append((urlsplit(response.url).path, response.status))
            if "handoff" in response.url else None)
    try:
        wait_for_board(page)
        service = "volcan-mcp-euw1-prod"
        page.evaluate(f"window.mercuryNav.setFocus(document.querySelector('.btn-demo[data-service=\"{service}\"]'))")
        assert page.evaluate("window.navigateDpad('SELECT')") is True
        wait_for_board(page, service=service)
        page.locator("#btnHandoff:not([disabled])").wait_for(timeout=10_000)
        # DOWN from the live row, key by key, until the cursor is on Publish handoff.
        path = []
        for _ in range(12):
            if page.evaluate("window.mercuryNav.current && window.mercuryNav.current.id") == "btnHandoff":
                break
            assert page.evaluate("window.navigateDpad('DOWN')") is True
            path.append(page.evaluate(
                "(c => c && (c.id || c.dataset.service))(window.mercuryNav.current)"))
            page.wait_for_timeout(120)
        assert page.evaluate("window.mercuryNav.current.id") == "btnHandoff", path
        page.wait_for_timeout(300)
        assert page.evaluate("window.navigateDpad('SELECT')") is True
        page.locator("#handoffOutput .error-card").wait_for(timeout=10_000)
        page.wait_for_timeout(400)
        state = page.evaluate(LIVE_ROW_HANDOFF_STATE)
        print("live row handoff:", path, json.dumps(state), calls)
        assert state["tvHost"] is host, state
        assert ("/mcp/tools/demo_update_handoff", 422) in calls, calls
        assert DEMO_HANDOFF_UNAVAILABLE in state["text"], state["text"]
        assert "Another screen published" not in state["text"], state["text"]
        assert state["focus"] == "btnHandoff", state
        assert state["card"]["top"] >= 0, state
        assert state["card"]["bottom"] <= state["keybarTop"], (
            f"{width}x{height}: the refusal is behind the key bar: {state}")
        assert state["focusBox"]["top"] >= 0, state
        # The browser logs the refused request itself; nothing else may error.
        assert [e for e in errors if "422" not in e] == [], errors
    finally:
        context.close()
