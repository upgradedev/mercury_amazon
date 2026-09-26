"""Structural assertions over the cockpit page and its scripts.

Two things this suite is deliberately strict about, because both were previously
wrong in ways a screenshot could not reveal:

1. Every panel action must reach the API. A dashboard that paints its numbers
   from literals in the page is a picture of a product, not a product.
2. There must be exactly one focus system. Two competing key handlers with two
   independent indices fight each other on a real remote.

The spatial navigation behaviour itself is exercised by ``spatial_nav_spec.js``,
which runs the real navigator in Node; ``test_spatial_navigation_spec_passes``
below is the bridge that runs it inside pytest.
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DOCS = REPO_ROOT / "docs"
INDEX = DOCS / "index.html"
NAV = DOCS / "firetv_nav.js"
SPEC = REPO_ROOT / "tests" / "e2e" / "spatial_nav_spec.js"

ENDPOINTS = [
    "/health",
    "/mcp/tools/get_dora_velocity_report",
    "/mcp/tools/get_pr_bottlenecks",
    "/mcp/tools/get_aws_cost_anomalies",
    "/mcp/tools/what_changed",
    "/mcp/tools/audit_observability",
    "/mcp/tools/stage_rollback",
    "/mcp/tools/confirm_rollback",
    "/mcp/tools/update_handoff",
    "/mcp/handoffs/",
]


@pytest.fixture(scope="module")
def html() -> str:
    return INDEX.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def nav_js() -> str:
    return NAV.read_text(encoding="utf-8")


# ------------------------------------------------------- The page calls its API

def test_the_page_actually_calls_fetch(html):
    assert "fetch(" in html, "the cockpit must call its own API, not paint literals"


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_every_backend_endpoint_is_referenced_by_the_page(html, endpoint):
    assert endpoint in html, f"the cockpit never calls {endpoint}"


def test_the_page_measures_its_own_latency(html):
    assert "performance.now()" in html
    assert "elapsed" in html


def test_incident_panel_shows_complete_shared_handoff_state(html):
    for field in ("Responder", "Current action", "Confirmed facts", "Next step"):
        assert field in html
    assert "expected_revision" in html
    assert "Publish handoff" in html
    assert "Refresh handoff" in html


def test_the_page_renders_loading_and_error_states(html):
    assert "loading-card" in html
    assert "error-card" in html
    assert "showError" in html
    assert "showLoading" in html


def test_the_page_renders_data_provenance(html):
    """A viewer must be able to tell a live reading from a fixture on the screen."""
    assert "provenanceBlock" in html
    assert "tag-fixture" in html
    assert "tag-live" in html
    assert "OFFLINE FIXTURE" in html


def test_the_provenance_badge_sits_inside_the_hero_card(html):
    """Structure half of the fold fix. The pixel half is tests/ux.

    The badge used to render in ``.hero-foot``, below the demo buttons, which puts it
    at y=1144 on a 1080 tall screen. It now renders in ``#heroSource`` inside
    ``.hero-figure``, next to the anomaly factor it qualifies. This asserts the badge
    goes into that container rather than asserting a pixel, so the layout can move as
    long as the provenance stays with the number; ``tests/ux`` measures where it
    actually lands.
    """
    hero = html.split('<section id="hero"', 1)[1].split("</section>", 1)[0]
    figure = hero.split('class="hero-figure"', 1)[1].split("</div>\n            </div>", 1)[0]
    assert 'id="heroSource"' in figure, (
        "the provenance container is no longer inside the hero figure block"
    )
    assert "el('heroSource')" in html
    # The badge renders the words, not the machine slug: "offline-fixture" is a value,
    # "OFFLINE FIXTURE" is what somebody across a room reads.
    # The words come from stampFor, which every badge and provenance block uses since
    # this repository's own commits got a STAND-IN stamp of their own.
    badge = html.split("function sourceBadge(", 1)[1].split("\n    }", 1)[0]
    assert "stampFor(provenance)" in badge
    stamp = html.split("function stampFor(", 1)[1].split("\n    }", 1)[0]
    assert "display_label" in stamp
    assert "OFFLINE FIXTURE" in stamp


def test_the_page_renders_the_crowded_window_refusal(html):
    """The verdict the product is now built around has to have a branch on the screen."""
    assert "WINDOW_TOO_CROWDED" in html
    assert "too many changes to name one" in html
    assert 'data-service="release-train"' in html
    # A refusal is rendered as a refusal. The headline says Mercury cannot attribute,
    # and the cause line is the server's own refusal statement when it ships one.
    assert "Cannot attribute this" in html
    assert "refusal_statement" in html
    assert "Do not revert on this" not in html


def test_the_page_prints_the_measured_worth_of_a_naming(html):
    """The precision travels with the answer, and is never computed in the page."""
    assert "measured_accuracy" in html
    assert "accuracyLine" in html
    assert "hero-accuracy" in html
    accuracy = html.split("function accuracyLine(", 1)[1].split("\n    }", 1)[0]
    assert "precision_when_it_names_a_commit" in accuracy
    assert "measured_by_command" in accuracy


def test_no_hardcoded_telemetry_numbers_remain_in_the_markup(html):
    """The old page hardcoded these next to an API it never called."""
    markup = html.split("<script>")[0]
    for fabricated in ["2.4 / day", "14.5 h", "3.2%", "0.8 h", "+340%", "7c8f2a1", "3e9d10c", "ALPHA-77"]:
        assert fabricated not in markup, f"{fabricated!r} is painted into the markup"


def test_the_page_never_asserts_a_connection_it_has_not_made(html):
    """No 'Connected' badge may exist that is not computed from a fetch result."""
    assert "state-unknown" in html
    assert "API not checked" in html
    # The reachable state is only ever set from inside a fetch handler.
    for match in re.finditer(r"setConnection\('reachable'", html):
        preceding = html[: match.start()]
        assert "await fetch" in preceding or "response.status" in preceding


def test_the_page_has_no_random_pairing_code(html, nav_js):
    for token in ["Math.random", "pairingCode", "generatePairingCode", "TV-"]:
        assert token not in nav_js, f"{token} generates a fake device pairing state"
    assert "Math.random" not in html


def test_the_page_carries_no_multi_product_suite_or_pricing(html):
    for token in ["suite_companion_enhancements", "Ambient Suite", "Stripe", "pricing", "Plans"]:
        assert token not in html, f"{token} belongs to a different product story"


def test_the_governance_secret_field_is_a_password_input_and_not_persisted(html):
    assert 'id="opSecret" type="password"' in html
    assert "localStorage" not in html
    assert "Never stored" in html


def test_the_setup_fields_are_off_the_first_screen(html):
    """A television's first screen must be the incident, not a form.

    Both text fields used to sit in the top bar, where they are a D-pad hostile setup
    step in front of the answer. They now live in a row that starts ``hidden`` behind a
    focusable toggle, and the D-pad ring skips hidden controls, so the remote never
    lands in a text field it cannot type into comfortably.
    """
    setup_row = re.search(r'<div class="setup-row" id="setupRow"([^>]*)>', html)
    assert setup_row, "the setup fields are no longer in a row of their own"
    assert "hidden" in setup_row.group(1), "the setup row is not hidden on load"

    for field in ('id="apiBase"', 'id="opSecret"'):
        position = html.index(field)
        assert position > html.index('id="setupRow"'), f"{field} is outside the setup row"
        assert position < html.index('id="connDetail"'), f"{field} escaped the setup row"

    toggle = re.search(r'<button id="btnSetup"(.*?)</button>', html, re.S)
    assert toggle, "there is no control that reveals the setup fields"
    assert 'aria-controls="setupRow"' in toggle.group(1)
    assert 'aria-expanded="false"' in toggle.group(1)
    assert "data-tv-focusable" in toggle.group(1), "the toggle is not reachable from the D-pad"


def test_the_hero_holds_no_text_input_at_all(html):
    """The hero is the answer. Nothing in it may ask the viewer to type."""
    hero = html[html.index('<section id="hero"'):html.index('<section id="wall"')]
    assert "<input" not in hero
    assert "<textarea" not in hero


def test_an_action_that_needs_the_secret_opens_the_field_it_needs(html):
    """Hiding a field is only kind if the refusal that needs it points at it."""
    script = html.split("<script>")[-1]
    assert "function requireSecret" in script
    assert script.count("requireSecret()") >= 2, (
        "both rollback actions must go through the helper that reveals the secret field"
    )
    assert "setSetupVisible(true)" in script


def test_the_secret_is_sent_as_a_bearer_header(html):
    assert "'Authorization'] = 'Bearer '" in html or "Authorization" in html
    assert "Bearer " in html


def test_response_values_reach_the_dom_as_text_and_never_as_markup(html, nav_js):
    """No markup sink exists in the cockpit at all.

    The page used to concatenate API responses into ``innerHTML`` and rely on an
    escaping helper being called at every site. It now builds nodes with
    ``createElement`` and writes values with ``textContent``, which removes the
    class of defect rather than guarding each instance of it. This test asserts
    the absence of the sink, which is the stronger property.
    """
    for source, name in ((html, "index.html"), (nav_js, "firetv_nav.js")):
        assert not re.search(r"\.innerHTML\s*=", source), f"{name} assigns innerHTML"
        assert not re.search(r"\.outerHTML\s*=", source), f"{name} assigns outerHTML"
        assert "insertAdjacentHTML" not in source, f"{name} calls insertAdjacentHTML"
        assert "document.write" not in source, f"{name} calls document.write"
    assert "createElement(" in html and "textContent" in html, (
        "the page must build its output as DOM nodes"
    )


# ----------------------------------------------------------- One focus system

def test_there_is_exactly_one_keydown_handler_in_the_cockpit(html, nav_js):
    page_handlers = len(re.findall(r"addEventListener\(\s*'keydown'", html))
    nav_handlers = len(re.findall(r"addEventListener\(\s*'keydown'", nav_js))
    assert page_handlers == 0, "the page must not register a second competing key handler"
    assert nav_handlers == 1, "firetv_nav.js owns the single keydown handler"


def test_the_page_holds_no_focus_index_of_its_own(html):
    for token in ["currentFocus", "navElements", "focusableElements"]:
        assert token not in html, f"{token} is a second focus system inside the page"


def test_navigation_is_geometric_rather_than_a_list_walk(nav_js):
    assert "getBoundingClientRect" in nav_js
    assert "scoreCandidate" in nav_js
    assert "PERPENDICULAR_PENALTY" in nav_js
    assert "% this.focusableElements.length" not in nav_js, "modulo cycling is a list walk"


def test_the_native_bridge_entry_point_exists_for_the_leanback_activity(nav_js):
    assert "window.navigateDpad" in nav_js
    for direction in ["UP", "DOWN", "LEFT", "RIGHT", "SELECT", "BACK"]:
        assert direction in nav_js


def test_focus_ring_is_dimensioned_for_ten_foot_viewing(html):
    ring = re.search(r"\.tv-focused\s*\{(.+?)\}", html, re.DOTALL)
    assert ring, "a .tv-focused rule must exist"
    body = ring.group(1)
    width = re.search(r"outline:\s*(\d+)px", body)
    assert width and int(width.group(1)) >= 3, "the focus ring must be at least 3px to read from a sofa"
    assert "box-shadow" in body


# ---------------------------------------------------------------- UX and shape

def test_responsive_and_ten_foot_breakpoints_are_present(html):
    assert 'name="viewport"' in html
    assert "@media (max-width: 600px)" in html
    assert "@media (min-width: 1400px)" in html, "a TV-sized breakpoint must scale type up"


def test_hero_action_is_marked_and_every_control_explains_itself(html):
    assert 'data-testid="primary-hero-action"' in html
    disabled_controls = re.findall(r"<button[^>]*\bdisabled\b[^>]*>", html)
    assert disabled_controls, "the staged-rollback buttons start disabled"
    for control in disabled_controls:
        assert 'title="' in control, f"a disabled control gives no reason: {control[:90]}"
        assert "Disabled until" in control


def test_empty_states_explain_themselves_instead_of_rendering_nothing(html):
    assert "empty-state-card" in html
    assert html.count("empty-state-card") >= 3


def test_static_hosting_is_declared_honestly(html):
    """Opened from GitHub Pages there is no API, and the page must say so."""
    assert "This page is static unless a Mercury API is running" in html


# ------------------------------------------------------- The five second read

def test_the_hero_answer_is_empty_until_the_api_answers(html):
    """The hero states an incident. None of those states may be in the markup."""
    markup = html.split("<script>")[0]
    for computed in ["Incident attributed", "Incident, cannot attribute", "Steady",
                     "Rollback staged", "ANOMALY_ATTRIBUTED"]:
        assert computed not in markup, f"{computed!r} is painted into the markup"
    # What the markup may say is that nothing has been asked yet.
    assert 'id="heroHeadline"' in markup
    assert "No answer yet" in markup
    assert 'data-state="idle"' in markup


def test_the_hero_headline_and_figure_are_written_from_the_response(html):
    script = html.split("<script>")[-1]
    assert "function heroFromCorrelation" in script
    for field in ["data.offending_commit.sha", "metric.anomaly_factor", "data.verdict"]:
        assert field in script, f"the hero never reads {field} from the response"


def test_the_page_asks_what_changed_on_load_rather_than_waiting_for_a_click(html):
    """A wallboard that says nothing until someone clicks cannot be read at all."""
    script = html.split("<script>")[-1]
    # Still asked on load; the flag says nobody pressed anything, so it is painted
    # and not announced to a screen reader.
    assert "checkConnection().then(function () { return loadWhatChanged(false); })" in script
    assert "if (apiBase())" in script, "the load-time call must be conditional on there being an API"


def test_the_key_hint_bar_names_the_remote_keys(html):
    assert 'class="keybar"' in html
    for key in ["CENTER", "BACK"]:
        assert f">{key}<" in html, f"the key hint bar does not name {key}"
    assert 'id="hintFocus"' in html, "the hint bar must show which control the cursor is on"


def test_the_hint_bar_is_fed_by_the_navigator_not_by_a_second_key_handler(html, nav_js):
    assert "mercury:focuschange" in nav_js, "the navigator must announce focus changes"
    assert "mercury:focuschange" in html, "the page must subscribe to the announcement"
    assert "announceFocus" in nav_js


def test_back_returns_from_a_panel_before_it_leaves_the_application(html):
    script = html.split("<script>")[-1]
    assert "window.mercuryOnBack" in script
    assert "showWall()" in script and "function showPanel" in script


# ------------------------------------------------------------- Accessibility

def test_the_page_has_landmarks_a_skip_link_and_one_h1(html):
    assert 'class="skip-link"' in html
    for landmark in ["<header", "<main>", "<footer"]:
        assert landmark in html, f"missing landmark {landmark}"
    assert html.count("<h1") == 1, "a 10-foot page has exactly one headline"
    assert 'aria-labelledby="heroHeadline"' in html


def test_async_regions_announce_themselves_to_assistive_technology(html):
    """Results are announced, briefly, and only after somebody asked for them.

    This used to require the whole answer row (#heroLive) to be a live region. It was,
    and a screen reader read the board out on page load, then read the full answer
    again when the flap settled, refusal paragraphs included. The answer row is now
    not live; one visually hidden status line carries a short sentence after a user
    action. The panel consoles stay live: they are hidden until opened, and only a
    press inside them rewrites them.
    """
    assert html.count('aria-live="polite"') >= 4
    for region in ["boardStatus", "incidentOutput", "doraOutput", "costOutput"]:
        assert region in html
    hero_live = re.search(r'<div id="heroLive"[^>]*>', html).group(0)
    assert "aria-live" not in hero_live, "the answer row must not announce itself on load"
    status = re.search(r'<p id="boardStatus"[^>]*>', html).group(0)
    assert 'role="status"' in status and "sr-only" in status
    script = html.split("<script>")[-1]
    assert "loadWhatChanged(false)" in script, "the answer fetched on load is not announced"


def test_reduced_motion_is_honoured(html):
    assert "@media (prefers-reduced-motion: reduce)" in html


def test_the_board_commits_to_one_dark_theme_and_paints_it_explicitly(html):
    """The departures board is dark on purpose, and says so rather than inheriting it.

    This used to assert a light variant. The redesign commits to one dark board: the
    page's first home is a television in a dim room, most TV browsers report no
    colour-scheme preference, and a board that turned white on a phone would stop being
    the same object. What must hold instead is that the choice is declared to the
    browser and that nothing is left to a user-agent default: the page ground is
    painted, and the colours come from named tokens.
    """
    style = html.split("<style>", 1)[1].split("</style>", 1)[0]
    assert "color-scheme: dark;" in style, "the dark commitment is not declared to the browser"
    assert "@media (prefers-color-scheme: light)" not in style, (
        "a light variant exists, so the one-theme rationale above is no longer true"
    )
    body = re.search(r"\n\s*body\s*\{(.+?)\}", style, re.DOTALL)
    assert body and "background-color: var(--board)" in body.group(1), (
        "the body does not paint its own background"
    )
    for token in ("--board:", "--flap:", "--ink:", "--amber:",
                  "--v-attributed:", "--v-cannot:", "--v-nothing:", "--v-insufficient:"):
        assert token in style, f"the palette token {token} is missing"


def test_every_disabled_control_states_its_reason_in_visible_text(html):
    """A title attribute is a hover affordance, and a television has no pointer."""
    for reason_id in ["stageReason", "confirmReason"]:
        assert f'id="{reason_id}"' in html, f"{reason_id} carries the on-screen reason"
        assert f'aria-describedby="{reason_id}"' in html, (
            f"the disabled control is not described by {reason_id}"
        )
    assert "Staging is off until" in html
    assert "Confirming is off until" in html


SHIPPED_PAGE_FILES = ("index.html", "firetv_nav.js", "webmcp_bridge.js", "manifest.json")

# Every way a page, a script or a manifest can make the browser load something:
# attributes that fetch, CSS url() and @import, manifest members, and script calls.
_LOADING_TARGETS = [
    re.compile(r"""\b(?:href|src|srcset|poster|action|formaction|data)\s*=\s*["']?\s*([^"'\s>]+)""", re.I),
    re.compile(r"""url\(\s*["']?([^"')\s]+)""", re.I),
    re.compile(r"""@import\s+(?:url\()?\s*["']([^"']+)""", re.I),
    re.compile(r"""["'](?:src|href|start_url|scope|action)["']\s*:\s*["']([^"']+)""", re.I),
]
_SCRIPT_REQUEST_TO_A_HOST = re.compile(
    r"""\b(?:fetch|importScripts|EventSource|WebSocket|sendBeacon|open)\s*\([^)]*?["'`](?:[a-z]+:)?//""", re.I)
_ANOTHER_ORIGIN = re.compile(r"^(?:[a-z][a-z0-9+.-]*:)?//", re.I)


def _external_references(text: str) -> list[str]:
    found = [
        match.group(0).strip()
        for pattern in _LOADING_TARGETS
        for match in pattern.finditer(text)
        if _ANOTHER_ORIGIN.match(match.group(1))
    ]
    found.extend(match.group(0) for match in _SCRIPT_REQUEST_TO_A_HOST.finditer(text))
    return found


def test_the_page_loads_nothing_from_another_origin():
    """Fire TV hardware may never reach a font CDN, or any other host.

    This replaces a test that checked only the fallback stack, and only when the page
    linked fonts.googleapis.com, so it passed whether or not the fonts could load. The
    page, both scripts and the manifest ship together from one origin; none of them may
    name another one anywhere the browser would fetch it. The API base the page calls is
    its own origin, read at runtime, and the example in the Setup field is a placeholder
    attribute, which is text, not a load.
    """
    for name in SHIPPED_PAGE_FILES:
        text = (DOCS / name).read_text(encoding="utf-8")
        assert _external_references(text) == [], (
            f"{name} loads from another origin: {_external_references(text)}"
        )
        for host in ("fonts.googleapis.com", "fonts.gstatic.com", "cdn.", "unpkg.com", "cdnjs"):
            assert host not in text, f"{name} names {host}"


def test_the_matcher_above_catches_what_it_is_for():
    """A forbid-list that matches nothing passes by not looking."""
    caught = [
        '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Barlow">',
        '<link rel="preconnect" href="//fonts.gstatic.com" crossorigin>',
        "<script src='https://cdn.example/x.js'></script>",
        "@font-face { src: url(https://fonts.gstatic.com/s/a.woff2) format('woff2'); }",
        '@import url("https://example.com/a.css");',
        "fetch('https://api.example.com/x')",
        '{"src": "https://example.com/icon.png"}',
    ]
    for sample in caught:
        assert _external_references(sample), f"the matcher let through: {sample}"
    allowed = [
        '<input placeholder="http://127.0.0.1:8002">',
        "src: url(barlow-latin-400.woff2) format('woff2');",
        '<script src="firetv_nav.js"></script>',
        "fetch(url, options || {})",
    ]
    for sample in allowed:
        assert not _external_references(sample), f"the matcher refused a local reference: {sample}"


def test_every_web_font_is_committed_beside_the_page_and_swaps_in(html):
    """Each @font-face names a file that ships next to the page, with its licence."""
    style = html.split("<style>", 1)[1].split("</style>", 1)[0]
    faces = re.findall(r"@font-face\s*\{(.+?)\}", style, re.DOTALL)
    assert len(faces) >= 3, "the page no longer declares its own font faces"
    families = set()
    for face in faces:
        assert "font-display: swap" in face, f"a face blocks text while it loads: {face[:80]}"
        family = re.search(r"font-family:\s*'([^']+)'", face).group(1)
        families.add(family)
        for source in re.findall(r"url\(\s*([^)\s]+)\s*\)", face):
            assert "/" not in source and source.endswith(".woff2"), f"{source} is not a sibling woff2"
            assert (DOCS / source).is_file(), f"{source} is named by the page but not committed"
    assert families == {"Barlow", "Barlow Condensed", "JetBrains Mono"}
    for licence in ("OFL-Barlow.txt", "OFL-BarlowCondensed.txt", "OFL-JetBrainsMono.txt"):
        text = (DOCS / licence).read_text(encoding="utf-8")
        assert "SIL Open Font License, Version 1.1" in text, f"{licence} is not the OFL"


def test_a_web_font_has_a_real_fallback_stack(html):
    """The faces are local now, but a first paint with font-display: swap uses these."""
    families = re.search(r"--sans:\s*([^;]+);", html)
    assert families, "no --sans stack is declared"
    assert families.group(1).count(",") >= 3, "the body font needs real fallbacks behind it"
    display = re.search(r"--display:\s*([^;]+);", html)
    assert display and display.group(1).count(",") >= 3, "the display font needs real fallbacks behind it"
    mono = re.search(r"--mono:\s*([^;]+);", html)
    assert mono and "monospace" in mono.group(1)


def test_the_manifest_names_no_file_that_is_not_committed():
    """A manifest that lists absent icons 404s on every load."""
    manifest = json.loads((DOCS / "manifest.json").read_text(encoding="utf-8"))
    for icon in manifest.get("icons", []):
        assert (DOCS / icon["src"]).exists(), f"manifest names {icon['src']}, which is not committed"
    start_url = manifest.get("start_url", "").lstrip("./")
    assert (DOCS / start_url).exists()


def test_no_service_worker_claims_an_offline_cache_that_is_never_filled():
    """The previous worker cached nothing and named another product's cache."""
    assert not (DOCS / "sw.js").exists()
    assert "serviceWorker" not in INDEX.read_text(encoding="utf-8")


# -------------------------------------------------- The real navigator spec run

@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_spatial_navigation_spec_passes():
    """Run the real navigator in Node against a synthetic grid."""
    result = subprocess.run(
        [shutil.which("node"), str(SPEC)],
        capture_output=True, text=True, cwd=str(REPO_ROOT), timeout=120,
    )
    assert result.returncode == 0, f"spatial navigation spec failed:\n{result.stdout}\n{result.stderr}"
    assert "spatial navigation assertions passed" in result.stdout
