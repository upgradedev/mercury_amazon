"""Interfaces Layer: the hybrid board's live production rows, added server-side.

The board's service rows are static ``.btn-demo[data-service]`` buttons in
``docs/index.html``, and the page script asks ``what_changed`` once per button it
finds. So a row added to the served HTML is asked, rendered and selectable exactly
like the others, with no change to ``docs/index.html`` or to the Fire TV navigation
script.

With ``MERCURY_LIVE_CLOUDWATCH=1`` the served page gains one row per allow-listed
production function, each stamped LIVE with the time CloudWatch was read, and the
five fixture rows gain an explicit FIXTURE stamp, so the two kinds can never be
mistaken for each other on the board. With the switch off the page is served byte
for byte as before.

This does change what the TV renders when the switch is on: three more rows. The
Android TV runtime receipt was taken on the five-row page, so a deployment that sets
the switch needs a fresh emulator run before that receipt describes it.
"""
from __future__ import annotations

import html
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import wait as wait_for
from typing import Any

from src.application.diagnose_incident_use_case import (
    LIVE_ROW_CLAIM_STRENGTH,
    LIVE_ROW_REFUSAL_REASON,
    LiveRowCorrelation,
)
from src.domain.incident_correlation import IncidentCorrelation, MetricSeries
from src.domain.provenance import DataSource
from src.infrastructure.cloudwatch_adapter import (
    LIVE_LAMBDA_CONTEXT_METRIC,
    LIVE_LAMBDA_METRIC,
    LIVE_LAMBDA_NAMESPACE,
    LIVE_PRODUCTION_FUNCTIONS,
    NOT_CALLED_REASON_PREFIX,
    SIMULATED_SERVICES,
    UNREAD_REASON_PREFIX,
)
from src.infrastructure.offline_mode import (
    live_cloudwatch_enabled,
    live_github_enabled,
    offline_mode_enabled,
)

#: The row the live rows are placed after: the last of the five static rows.
ROWS_ANCHOR = 'data-service="quiet-service"'
FIXTURE_ROW_NAMES: tuple[str, ...] = (*SIMULATED_SERVICES, "quiet-service")
#: The longest the page waits for the production rows. The Lambda's own timeout is 30 s
#: and the page must render well inside it; a row that has not answered by then is
#: drawn "Not read" and its read carries on in the background.
PAGE_READ_DEADLINE_SECONDS = 4.0

#: Added to the served page only with the switch on. Eight rows have to fit where five
#: did, above the remote's key bar, without dropping any text under the 24px floor at
#: 1920x1080 (or its 960x540 Fire TV equivalent), so the rows lose most of their
#: vertical padding and some line height, the verdict gives up the fourth column to a
#: per-row stamp, and the long function names drop to 0.8em on one line. On a laptop
#: (601 to 1399 px, not the TV host) the page caps the board at 21rem and shares it out
#: in equal rows; eight rows overflowed that box onto the next section's heading, so
#: there the cap is lifted and each row takes its own height.
ROW_STYLE = """  <style id="mercury-live-rows">
    .departures-rows .btn-demo {
      padding-top: 0.08rem; padding-bottom: 0.08rem; line-height: 1.1; align-items: center;
    }
    .btn-demo .row-stamp { justify-self: end; white-space: nowrap; }
    /* rem, not px, borders: the stamp's own 4px plate edge is not scaled by the Fire TV
       host's 1.25vw root, and at 960x540 it alone made each fixture row taller. */
    .btn-demo .row-stamp .tag {
      font-size: 0.8em; line-height: 1; padding: 0.05rem 0.4rem; border-width: 0.08rem;
    }
    .btn-demo[data-row-source] .row-service { font-size: 0.8em; white-space: nowrap; }
    @media (min-width: 601px) {
      .btn-demo .row-verdict { grid-column: 3; }
      .btn-demo .row-stamp { grid-column: 4; }
    }
    @media (max-width: 600px) {
      .btn-demo .row-stamp { grid-column: 1 / -1; justify-self: start; }
    }
    @media (min-width: 601px) and (max-width: 1399.98px) {
      html:not(.tv-host) .departures { max-height: none; }
      html:not(.tv-host) .departures-rows { grid-auto-rows: auto; }
    }
  </style>
"""


#: Added to the served page only with the switch on, before ``</body>``. The board's
#: frozen script (docs/index.html) words every cannot-attribute answer that is not
#: WINDOW_TOO_CROWDED as an empty deploy window: eyebrow "window empty", headline "no
#: change in the window". For a live production row that is false (no deploy feed is
#: connected, so no window was read), and those two lines are the largest text on the
#: TV. The server cannot change that branch, so this rewrites the two lines, and only
#: them, whenever the hero holds a live row's cannot-attribute answer. It also rewrites
#: a zero-baseline factor ("0×", which reads as zero times the baseline beside an
#: incident) as "from 0" on the hero and on that row. The cause line under the headline
#: is the server's own refusal statement and is left alone. It keys on the service
#: name the hero shows, never on which row has focus, and changes nothing else.
LIVE_HERO_TEXT = {
    "window_eyebrow": "Incident, cannot attribute: window empty",
    "eyebrow": "Incident, cannot attribute: no deploy feed",
    "headline": "Cannot attribute this: no deploy feed connected",
    "zero_factor": "from 0",
}

LIVE_HERO_SCRIPT = """  <script id="mercury-live-hero">
  (function () {
    var LIVE = __LIVE_ROWS__;
    var TEXT = __LIVE_TEXT__;
    var ZERO = /^0(?:\\.0+)?\\u00d7$/;
    function node(id) { return document.getElementById(id); }
    function isLive(service) { return LIVE.indexOf((service || '').trim()) >= 0; }
    function fixHero() {
      var hero = node('hero');
      if (!hero || hero.getAttribute('data-verdict') !== 'cannot') return;
      if (!isLive(node('heroService') && node('heroService').textContent)) return;
      // A live row never reaches the crowded-window branch (its refusal is
      // NO_DEPLOY_FEED), so every cannot-attribute headline it gets is the
      // empty-window one, whether settled or still flipping in.
      var eyebrow = node('heroEyebrow');
      if (eyebrow && eyebrow.textContent !== TEXT.eyebrow) eyebrow.textContent = TEXT.eyebrow;
      var headline = node('heroHeadline');
      if (headline && headline.textContent !== TEXT.headline) headline.textContent = TEXT.headline;
      var figure = node('heroFigure');
      if (figure && ZERO.test(figure.textContent)) figure.textContent = TEXT.zero_factor;
    }
    function fixRows() {
      var rows = document.querySelectorAll('.btn-demo[data-row-source]');
      for (var i = 0; i < rows.length; i++) {
        if (!isLive(rows[i].getAttribute('data-service'))) continue;
        var verdict = rows[i].querySelector('[data-row-verdict]');
        var reading = rows[i].querySelector('[data-row-reading]');
        if (verdict && reading && verdict.getAttribute('data-verdict') === 'cannot'
            && ZERO.test(reading.textContent)) {
          reading.textContent = TEXT.zero_factor;
        }
      }
    }
    function fix() {
      try { fixHero(); fixRows(); } catch (e) { /* never break the board */ }
    }
    if (typeof MutationObserver !== 'function') return;
    var watch = { subtree: true, childList: true, characterData: true, attributes: true,
                  attributeFilter: ['data-verdict'] };
    var hero = node('hero');
    if (hero) new MutationObserver(fix).observe(hero, watch);
    var rows = document.querySelector('.departures-rows');
    if (rows) new MutationObserver(fix).observe(rows, watch);
    fix();
  })();
  </script>
"""


def live_hero_script() -> str:
    """The hero rewrite above, with the production function names filled in."""
    import json

    return (
        LIVE_HERO_SCRIPT
        .replace("__LIVE_ROWS__", json.dumps(list(LIVE_PRODUCTION_FUNCTIONS)))
        .replace("__LIVE_TEXT__", json.dumps({k: v for k, v in LIVE_HERO_TEXT.items()
                                              if k != "window_eyebrow"}))
    )


def live_rows_enabled() -> bool:
    """True when the served page carries the live production rows."""
    return live_cloudwatch_enabled()


def _clock(observed_at_utc: str) -> str:
    """``2026-10-19T12:03:07Z`` as ``12:03Z``; the full stamp stays in the title."""
    if "T" in observed_at_utc and len(observed_at_utc) >= 16:
        return observed_at_utc[11:16] + "Z"
    return observed_at_utc


def _not_read(series: MetricSeries) -> bool:
    """True when CloudWatch gave this row no answer, or was never asked (no credentials)."""
    provenance = series.provenance
    if provenance.source is DataSource.AWS_CLOUDWATCH:
        return False
    if provenance.source is DataSource.NO_LIVE_DATA:
        return provenance.detail.startswith((UNREAD_REASON_PREFIX, NOT_CALLED_REASON_PREFIX))
    return True


def _stamp(series: MetricSeries) -> tuple[str, str]:
    """The stamp class and words for one production row's reading.

    "No live data" is CloudWatch answering with nothing or refusing; "Not read" is no
    answer at all (a deadline, a timeout, a dropped connection) or no call (no
    credentials).
    """
    provenance = series.provenance
    if provenance.source is DataSource.AWS_CLOUDWATCH:
        return "tag tag-live", f"Live {_clock(provenance.observed_at_utc)}"
    if not _not_read(series):
        return "tag", "No live data"
    return "tag", "Not read"


def _stamp_markup(css: str, words: str) -> str:
    return f'<span class="row-stamp"><span class="{css}">{html.escape(words)}</span></span>'


FIXTURE_STAMP = _stamp_markup("tag tag-fixture", "Fixture")


def _live_row(function_name: str, series: MetricSeries) -> str:
    css, words = _stamp(series)
    name = html.escape(function_name)
    # The title is also the button's accessible description, so it names a CloudWatch
    # time only when CloudWatch answered at that time.
    if series.provenance.source is DataSource.AWS_CLOUDWATCH:
        read = f"from CloudWatch at {series.provenance.observed_at_utc or 'an unrecorded time'}"
    elif _not_read(series):
        read = "not read from CloudWatch for this view"
    else:
        read = f"asked of CloudWatch at {series.provenance.observed_at_utc}, which gave no usable reading"
    title = html.escape(
        f"{words}: {LIVE_LAMBDA_NAMESPACE} {LIVE_LAMBDA_METRIC} with {LIVE_LAMBDA_CONTEXT_METRIC} "
        f"for {function_name}, one of the hackathon's own production functions, {read}. Not a "
        "simulated service, and never attributed to a commit.",
        quote=True,
    )
    return (
        f'\n            <button class="btn btn-demo board-grid" data-service="{name}" '
        f'data-row-source="{html.escape(series.provenance.source.value)}" aria-pressed="false" '
        f'data-tv-focusable\n'
        f'                    data-tv-label="Ask about live production function {name}"\n'
        f'                    title="{title}">\n'
        f'              <span class="row-service">{name}</span>\n'
        f'              <span class="row-reading" data-row-reading></span>\n'
        f'              <span class="row-verdict" data-row-verdict>Not asked</span>\n'
        f'              {_stamp_markup(css, words)}\n'
        f'            </button>'
    )


def read_production_rows(
    cloudwatch_adapter: Any, deadline_seconds: float | None = None
) -> list[tuple[str, MetricSeries]]:
    """Read every production function in parallel, through the adapter's cache.

    The page waits at most ``deadline_seconds`` (default
    :data:`PAGE_READ_DEADLINE_SECONDS`). A function that has not answered by then is
    recorded as not read (``mark_unread``) and drawn that way; the pool is not joined,
    so a slow read cannot hold the page.
    """
    deadline = PAGE_READ_DEADLINE_SECONDS if deadline_seconds is None else deadline_seconds
    started = time.monotonic()
    pool = ThreadPoolExecutor(max_workers=len(LIVE_PRODUCTION_FUNCTIONS))
    try:
        futures = {
            name: pool.submit(cloudwatch_adapter.get_production_series, name)
            for name in LIVE_PRODUCTION_FUNCTIONS
        }
        wait_for(list(futures.values()), timeout=deadline)
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    waited = round(time.monotonic() - started, 1)
    rows = []
    for name, future in futures.items():
        series = future.result() if future.done() and not future.cancelled() else None
        if series is None:
            series = cloudwatch_adapter.mark_unread(name, max(waited, deadline))
        rows.append((name, series))
    return rows


def _row_end(page: str, service_name: str) -> int:
    """Index of the ``</button>`` that closes one static row, or -1."""
    anchor = page.find(f'data-service="{service_name}"')
    if anchor < 0:
        return -1
    return page.find("</button>", anchor)


def inject_live_rows(page: str, rows: list[tuple[str, MetricSeries]]) -> str:
    """Return ``page`` with the live rows after the last static row, and fixture stamps.

    Returns the page unchanged when any static row is not found, so a future edit to
    the board degrades to the five-row page rather than to broken markup;
    ``tests/unit/test_live_rows.py`` fails the build if a row goes missing.
    """
    if any(_row_end(page, name) < 0 for name in FIXTURE_ROW_NAMES):
        return page

    # Stamp every fixture row inside its own button, then add the live rows after
    # the last one. Each insertion re-finds its row, so the offsets never go stale.
    for name in FIXTURE_ROW_NAMES:
        close = _row_end(page, name)
        page = page[:close] + "  " + FIXTURE_STAMP + "\n            " + page[close:]

    close = _row_end(page, ROWS_ANCHOR.split('"')[1])
    insert_at = close + len("</button>")
    markup = "".join(_live_row(name, series) for name, series in rows)
    page = page[:insert_at] + markup + page[insert_at:]

    page = page.replace("</head>", ROW_STYLE + "</head>", 1)
    body_end = page.rfind("</body>")
    if body_end >= 0:
        page = page[:body_end] + live_hero_script() + page[body_end:]
    return page


def withdraw_window_fields(payload: dict[str, Any], correlation: IncidentCorrelation) -> None:
    """Withdraw a live production row's window fields from a ``what_changed`` payload.

    No commit feed was read for a live row and no candidate was looked for, so the
    window fields describe a check that never happened: a count of 0 reads as "the
    window was empty", NO_CANDIDATE_IN_WINDOW as "nothing landed inside the window".
    They are withdrawn (null), not zeroed, the refusal and the claim strength name what
    did happen, and the rollback block says why no target can exist. Any other answer
    is left untouched.
    """
    if not isinstance(correlation, LiveRowCorrelation):
        return
    payload["attribution"].update({
        "commits_in_window": None,
        "commits_set_aside": None,
        "candidate_filter": None,
        "refusal_reason": (
            LIVE_ROW_REFUSAL_REASON if correlation.attribution_refusal is not None else None
        ),
        "claim_strength": LIVE_ROW_CLAIM_STRENGTH,
        "causality_statement": correlation.causality_statement,
    })
    payload["deployment_evidence"]["blocked_reason"] = correlation.rollback_blocked_reason


def live_sources_summary(cloudwatch_adapter: Any, github_adapter: Any) -> dict[str, Any]:
    """Which data sources this process may read live, for ``/health``."""
    return {
        "offline_mode": offline_mode_enabled(),
        "cloudwatch_production_rows": (
            list(LIVE_PRODUCTION_FUNCTIONS) if live_rows_enabled() else []
        ),
        "cloudwatch_production_reads_allowed": cloudwatch_adapter.live_read_allowed(),
        "cloudwatch_simulated_services": "offline-fixture" if offline_mode_enabled() else "live-read",
        "github_dora_and_pr_radar": bool(github_adapter.can_call_live),
        "github_commit_feed": bool(github_adapter.can_list_commits_live),
        # No per-adapter switch exists for Cost Explorer: it reports the whole account's
        # bill, so under MERCURY_OFFLINE it is always the fixture.
        "cost_explorer": "offline-fixture" if offline_mode_enabled() else "live-read",
    }


def data_sources_sentence() -> str:
    """The MCP ``initialize`` instructions' sentence about where the data comes from."""
    if offline_mode_enabled() and not (live_cloudwatch_enabled() or live_github_enabled()):
        return "The public data is an offline fixture and rollback dispatch is record-only."
    if not offline_mode_enabled():
        return (
            "Adapters read live where credentials allow and every response's provenance says "
            "which. Rollback dispatch is record-only unless the deployment arms it."
        )
    live = []
    if live_cloudwatch_enabled():
        live.append("the production Lambda rows are read live from CloudWatch")
    if live_github_enabled():
        live.append("DORA and the pull request radar are read live from GitHub when it answers")
    return (
        "The simulated incident services and the cost report are offline fixtures; "
        + " and ".join(live)
        + ". Every response's provenance says which. Rollback dispatch is record-only."
    )
