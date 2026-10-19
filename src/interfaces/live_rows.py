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
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from src.domain.incident_correlation import MetricSeries
from src.domain.provenance import DataSource
from src.infrastructure.cloudwatch_adapter import (
    LIVE_LAMBDA_CONTEXT_METRIC,
    LIVE_LAMBDA_METRIC,
    LIVE_LAMBDA_NAMESPACE,
    LIVE_PRODUCTION_FUNCTIONS,
    SIMULATED_SERVICES,
)
from src.infrastructure.offline_mode import (
    live_cloudwatch_enabled,
    live_github_enabled,
    offline_mode_enabled,
)

#: The row the live rows are placed after: the last of the five static rows.
ROWS_ANCHOR = 'data-service="quiet-service"'
FIXTURE_ROW_NAMES: tuple[str, ...] = (*SIMULATED_SERVICES, "quiet-service")

#: Added to the served page only with the switch on. Eight rows have to fit where five
#: did, above the remote's key bar, without dropping any text under the 24px floor at
#: 1920x1080 (or its 960x540 Fire TV equivalent), so the rows lose most of their
#: vertical padding and some line height, the verdict gives up the fourth column to a
#: per-row stamp, and the long function names drop to 0.8em on one line.
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
  </style>
"""


def live_rows_enabled() -> bool:
    """True when the served page carries the live production rows."""
    return live_cloudwatch_enabled()


def _clock(observed_at_utc: str) -> str:
    """``2026-10-19T12:03:07Z`` as ``12:03Z``; the full stamp stays in the title."""
    if "T" in observed_at_utc and len(observed_at_utc) >= 16:
        return observed_at_utc[11:16] + "Z"
    return observed_at_utc


def _stamp(series: MetricSeries) -> tuple[str, str]:
    """The stamp class and words for one production row's reading."""
    provenance = series.provenance
    if provenance.source is DataSource.AWS_CLOUDWATCH:
        return "tag tag-live", f"Live {_clock(provenance.observed_at_utc)}"
    if provenance.source is DataSource.NO_LIVE_DATA:
        return "tag", "No live data"
    return "tag", "Not read"


def _stamp_markup(css: str, words: str) -> str:
    return f'<span class="row-stamp"><span class="{css}">{html.escape(words)}</span></span>'


FIXTURE_STAMP = _stamp_markup("tag tag-fixture", "Fixture")


def _live_row(function_name: str, series: MetricSeries) -> str:
    css, words = _stamp(series)
    read = series.provenance.observed_at_utc or "not read"
    name = html.escape(function_name)
    title = html.escape(
        f"{words}: {LIVE_LAMBDA_NAMESPACE} {LIVE_LAMBDA_METRIC} with {LIVE_LAMBDA_CONTEXT_METRIC} "
        f"for {function_name}, one of the hackathon's own production functions, from CloudWatch "
        f"at {read}. Not a simulated service, and never attributed to a commit.",
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


def read_production_rows(cloudwatch_adapter: Any) -> list[tuple[str, MetricSeries]]:
    """Read every production function, through the adapter's cache, in parallel."""
    with ThreadPoolExecutor(max_workers=len(LIVE_PRODUCTION_FUNCTIONS)) as pool:
        series = list(pool.map(cloudwatch_adapter.get_production_series, LIVE_PRODUCTION_FUNCTIONS))
    return list(zip(LIVE_PRODUCTION_FUNCTIONS, series))


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

    return page.replace("</head>", ROW_STYLE + "</head>", 1)


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
