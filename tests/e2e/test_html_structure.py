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
    for computed in ["Incident attributed", "Incident, nothing to blame", "Steady",
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
    assert "checkConnection().then(loadWhatChanged)" in script
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
    """Every region a fetch rewrites must be a live region."""
    assert html.count('aria-live="polite"') >= 4
    for region in ["heroLive", "incidentOutput", "doraOutput", "costOutput"]:
        assert region in html


def test_reduced_motion_is_honoured(html):
    assert "@media (prefers-reduced-motion: reduce)" in html


def test_light_and_dark_are_both_defined(html):
    assert "@media (prefers-color-scheme: light)" in html
    assert "color-scheme:" in html


def test_every_disabled_control_states_its_reason_in_visible_text(html):
    """A title attribute is a hover affordance, and a television has no pointer."""
    for reason_id in ["stageReason", "confirmReason"]:
        assert f'id="{reason_id}"' in html, f"{reason_id} carries the on-screen reason"
        assert f'aria-describedby="{reason_id}"' in html, (
            f"the disabled control is not described by {reason_id}"
        )
    assert "Staging is off until" in html
    assert "Confirming is off until" in html


def test_a_web_font_has_a_real_fallback_stack(html):
    """Fire TV hardware may never reach fonts.googleapis.com."""
    if "fonts.googleapis.com" not in html:
        return
    families = re.search(r"--sans:\s*([^;]+);", html)
    assert families, "no --sans stack is declared"
    assert families.group(1).count(",") >= 3, "the display font needs real fallbacks behind it"
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
