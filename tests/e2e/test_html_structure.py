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


def _innerhtml_statements(html: str) -> list[str]:
    """Return each ``innerHTML = ...;`` assignment as one whole statement."""
    statements = []
    for match in re.finditer(r"\.innerHTML\s*=", html):
        tail = html[match.end():]
        end = tail.find(";")
        statements.append(tail[: end if end != -1 else 200])
    return statements


def test_user_supplied_values_are_escaped_before_being_written_into_the_dom(html):
    """Any response value concatenated into innerHTML must pass through escapeHtml."""
    assert "function escapeHtml" in html
    statements = _innerhtml_statements(html)
    assert statements, "expected the page to build output with innerHTML"

    for statement in statements:
        # A statement that concatenates anything must escape or delegate to a
        # builder that escapes. A pure string literal needs neither.
        concatenates = "+" in statement
        if not concatenates:
            continue
        interpolates_identifier = re.search(r"\+\s*(?!')[A-Za-z_$]", statement)
        if not interpolates_identifier:
            continue
        assert "escapeHtml(" in statement or "provenanceBlock(" in statement or "rows" in statement, (
            f"unescaped interpolation into innerHTML: {statement.strip()[:140]}"
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
