"""Infrastructure Adapter: GitHub REST API telemetry provider.

Computes the four DORA metrics from real GitHub data when a token is present,
and falls back to a recorded offline fixture otherwise. Every report it returns
carries a :class:`~src.domain.provenance.Provenance` stamp saying which of the
two happened, and the cockpit renders that stamp on screen.

Metric definitions used here (proxies, stated plainly because GitHub does not
expose DORA directly):

deployment_frequency_per_day
    Successful GitHub Actions workflow runs on the default branch inside the
    window, divided by the window length in days.

lead_time_for_changes_hours
    Mean hours between pull request creation and merge, over pull requests
    merged inside the window.

change_failure_rate_percentage
    Failed default-branch workflow runs divided by all completed default-branch
    runs inside the window, as a percentage.

mean_time_to_recovery_hours
    Mean hours from a failed default-branch run to the next successful
    default-branch run.

A repository with no GitHub Actions workflow runs cannot produce a deployment
frequency or a change failure rate by this definition. The adapter reports that
condition in the provenance detail rather than substituting a number.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

import httpx

from src.domain.dora_metrics import DORAMetricsReport
from src.domain.git_radar import STALE_REVIEW_SLA_HOURS, PRRadarReport, PullRequestDigest
from src.domain.provenance import DataSource, Provenance
from src.infrastructure.offline_mode import offline_mode_enabled

GITHUB_API_ROOT = "https://api.github.com"
DEFAULT_REPO = "upgradedev/mercury_amazon"
DEFAULT_WINDOW_DAYS = 30
PER_PAGE = 100
MAX_PAGES = 5
# The single-commit endpoint caps the files it returns. A full page may hide a
# runtime file past the cap, so a capped read is unknown, not a clean bill.
COMMIT_FILES_CAP = 300
FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "github_telemetry_fixture.json"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_gh_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


class GitHubTelemetryAdapter:
    """Reads engineering velocity telemetry from the GitHub REST API.

    Args:
        token: GitHub token. Defaults to the ``GITHUB_TOKEN`` environment
            variable. Without a token the adapter serves the offline fixture.
        repository: ``owner/name`` to measure. Defaults to
            ``MERCURY_GITHUB_REPO`` then to :data:`DEFAULT_REPO`.
        window_days: measurement window. Defaults to ``MERCURY_DORA_WINDOW_DAYS``.
        client: injected ``httpx.Client``, used by the test suite to drive the
            adapter through a mock transport without touching the network.
        allow_unauthenticated: issue anonymous requests when no token is set.
            Anonymous GitHub requests are limited to 60 per hour and cannot read
            private repositories, so this is off by default.
    """

    def __init__(
        self,
        token: str | None = None,
        repository: str | None = None,
        window_days: int | None = None,
        client: httpx.Client | None = None,
        timeout: float = 10.0,
        allow_unauthenticated: bool = False,
    ) -> None:
        self.token = token if token is not None else os.environ.get("GITHUB_TOKEN", "")
        self.repository = repository or os.environ.get("MERCURY_GITHUB_REPO", DEFAULT_REPO)
        self.window_days = window_days or int(os.environ.get("MERCURY_DORA_WINDOW_DAYS", DEFAULT_WINDOW_DAYS))
        self.region = os.environ.get("AWS_REGION", "eu-west-1")
        self._client = client
        self._timeout = timeout
        self._allow_unauthenticated = allow_unauthenticated or bool(client)

    # ------------------------------------------------------------------ HTTP

    @property
    def can_call_live(self) -> bool:
        if offline_mode_enabled() and self._client is None:
            return False
        return bool(self.token) or self._allow_unauthenticated

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "mercury-firetv-cockpit",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """Issue one GET against the GitHub REST API and return parsed JSON."""
        url = f"{GITHUB_API_ROOT}{path}"
        if self._client is not None:
            response = self._client.get(url, params=params, headers=self._headers())
        else:
            with httpx.Client(timeout=self._timeout) as client:
                response = client.get(url, params=params, headers=self._headers())
        response.raise_for_status()
        return response.json()

    def _get_paged(
        self,
        path: str,
        params: dict[str, Any],
        collect: str | None = None,
    ) -> tuple[list[Any], bool]:
        """Page through a GitHub list endpoint up to :data:`MAX_PAGES`.

        Returns the accumulated items and a flag saying whether the page cap was
        reached, which means the result is incomplete. Callers must surface that
        flag rather than presenting a truncated count as a full one.
        """
        items: list[Any] = []
        for page in range(1, MAX_PAGES + 1):
            payload = self._get(path, params={**params, "per_page": PER_PAGE, "page": page})
            batch = payload.get(collect, []) if collect else payload
            if not isinstance(batch, list):
                break
            items.extend(batch)
            if len(batch) < PER_PAGE:
                return items, False
        return items, True

    # -------------------------------------------------------------- Fixtures

    @staticmethod
    @lru_cache(maxsize=1)
    def _load_fixture() -> dict[str, Any]:
        """Read the recorded fixture. Cached, so editing it needs a restart."""
        with open(FIXTURE_PATH, "r", encoding="utf-8") as handle:
            return json.load(handle)

    def _fixture_provenance(self, reason: str) -> Provenance:
        fixture = self._load_fixture()
        return Provenance(
            source=DataSource.OFFLINE_FIXTURE,
            detail=(
                f"{reason} Serving {FIXTURE_PATH.name}, recorded from "
                f"{fixture['recorded_from_repository']} on {fixture['recorded_at_utc']} by "
                f"{fixture['recorded_by_command']}."
            ),
            observed_at_utc=fixture["recorded_at_utc"],
        )

    def _fixture_dora(self, reason: str) -> DORAMetricsReport:
        fixture = self._load_fixture()
        metrics = fixture["dora"]
        return DORAMetricsReport(
            deployment_frequency_per_day=metrics["deployment_frequency_per_day"],
            lead_time_for_changes_hours=metrics["lead_time_for_changes_hours"],
            change_failure_rate_percentage=metrics["change_failure_rate_percentage"],
            mean_time_to_recovery_hours=metrics["mean_time_to_recovery_hours"],
            provenance=self._fixture_provenance(reason),
            sample_size=metrics["sample_size"],
            window_days=metrics["window_days"],
        )

    def _fixture_pr_radar(self, reason: str) -> PRRadarReport:
        fixture = self._load_fixture()
        radar = fixture["pull_requests"]
        return PRRadarReport(
            total_open_prs=radar["total_open_prs"],
            stale_prs_over_36h=[
                PullRequestDigest(
                    pr_id=item["pr_id"],
                    repository=item["repository"],
                    title=item["title"],
                    author=item["author"],
                    hours_open=item["hours_open"],
                    is_blocked=item["is_blocked"],
                )
                for item in radar["stale_prs_over_36h"]
            ],
            provenance=self._fixture_provenance(reason),
        )

    # ------------------------------------------------------------ Computation

    @staticmethod
    def compute_dora_from_runs_and_prs(
        runs: list[dict[str, Any]],
        merged_prs: list[dict[str, Any]],
        window_days: int,
    ) -> tuple[dict[str, float], int]:
        """Pure computation of the four DORA metrics from GitHub payloads.

        Separated from the HTTP layer so it can be tested exhaustively without a
        transport. Returns the metric dict and the number of source records used.
        """
        completed = [r for r in runs if r.get("status") == "completed"]
        successes = [r for r in completed if r.get("conclusion") == "success"]
        failures = [r for r in completed if r.get("conclusion") == "failure"]

        deployment_frequency = len(successes) / window_days if window_days else 0.0

        change_failure_rate = (len(failures) / len(completed) * 100.0) if completed else 0.0

        lead_times: list[float] = []
        for pull in merged_prs:
            created = _parse_gh_time(pull.get("created_at"))
            merged = _parse_gh_time(pull.get("merged_at"))
            if created and merged and merged >= created:
                lead_times.append((merged - created).total_seconds() / 3600.0)
        lead_time_hours = sum(lead_times) / len(lead_times) if lead_times else 0.0

        # MTTR: for each failure, hours until the next success that started later.
        ordered = sorted(
            (r for r in completed if _parse_gh_time(r.get("created_at"))),
            key=lambda r: _parse_gh_time(r.get("created_at")),  # type: ignore[arg-type,return-value]
        )
        recovery_hours: list[float] = []
        pending_failure: datetime | None = None
        for run in ordered:
            stamp = _parse_gh_time(run.get("created_at"))
            if stamp is None:
                continue
            if run.get("conclusion") == "failure" and pending_failure is None:
                pending_failure = stamp
            elif run.get("conclusion") == "success" and pending_failure is not None:
                recovery_hours.append((stamp - pending_failure).total_seconds() / 3600.0)
                pending_failure = None
        mttr_hours = sum(recovery_hours) / len(recovery_hours) if recovery_hours else 0.0

        metrics = {
            "deployment_frequency_per_day": round(deployment_frequency, 3),
            "lead_time_for_changes_hours": round(lead_time_hours, 2),
            "change_failure_rate_percentage": round(change_failure_rate, 2),
            "mean_time_to_recovery_hours": round(mttr_hours, 2),
        }
        return metrics, len(completed) + len(merged_prs)

    # ------------------------------------------------------------- Public API

    def get_metrics_raw(self) -> DORAMetricsReport:
        """Return a DORA report, live from GitHub when possible, fixture otherwise."""
        if not self.can_call_live:
            return self._fixture_dora("GITHUB_TOKEN is not set, so no live call was attempted.")

        try:
            since = _utc_now() - timedelta(days=self.window_days)
            repo_meta = self._get(f"/repos/{self.repository}")
            default_branch = repo_meta.get("default_branch", "main")

            raw_runs, runs_truncated = self._get_paged(
                f"/repos/{self.repository}/actions/runs",
                params={"branch": default_branch, "created": f">={_iso(since)[:10]}"},
                collect="workflow_runs",
            )
            runs = [
                run for run in raw_runs
                if (stamp := _parse_gh_time(run.get("created_at"))) and stamp >= since
            ]

            # Closed pull requests are paged newest-updated first and the walk stops
            # at the first page that falls entirely outside the window. A merge
            # always bumps updated_at, so every pull request merged inside the
            # window is guaranteed to be seen before the walk stops.
            merged: list[dict[str, Any]] = []
            prs_truncated = False
            for page in range(1, MAX_PAGES + 1):
                batch = self._get(
                    f"/repos/{self.repository}/pulls",
                    params={
                        "state": "closed", "sort": "updated", "direction": "desc",
                        "per_page": PER_PAGE, "page": page,
                    },
                )
                if not isinstance(batch, list) or not batch:
                    break
                merged.extend(
                    pull for pull in batch
                    if (stamp := _parse_gh_time(pull.get("merged_at"))) and stamp >= since
                )
                oldest_update = _parse_gh_time(batch[-1].get("updated_at"))
                if oldest_update is not None and oldest_update < since:
                    break
                if len(batch) < PER_PAGE:
                    break
                if page == MAX_PAGES:
                    prs_truncated = True

            metrics, sample_size = self.compute_dora_from_runs_and_prs(runs, merged, self.window_days)
            detail = (
                f"GitHub REST API for {self.repository} over the last {self.window_days} days: "
                f"{len(runs)} default-branch workflow runs, {len(merged)} merged pull requests."
            )
            if not runs:
                detail += (
                    " That repository reported no workflow runs in the window, so deployment"
                    " frequency and change failure rate are both computed as zero rather than estimated."
                )
            if runs_truncated:
                detail += (
                    f" Workflow run paging stopped at the {MAX_PAGES}-page cap, so the deployment"
                    " frequency and change failure rate are lower bounds, not complete counts."
                )
            if prs_truncated:
                detail += (
                    f" Closed pull request paging stopped at the {MAX_PAGES}-page cap before reaching"
                    " the window edge, so the lead time sample may be incomplete."
                )
            return DORAMetricsReport(
                **metrics,
                provenance=Provenance(
                    source=DataSource.GITHUB_API,
                    detail=detail,
                    observed_at_utc=_iso(_utc_now()),
                ),
                sample_size=sample_size,
                window_days=self.window_days,
            )
        except Exception as exc:
            return self._fixture_dora(f"Live GitHub call failed ({type(exc).__name__}: {exc}).")

    def get_pr_radar(self) -> PRRadarReport:
        """Return open pull requests and those past the 36 hour review SLA."""
        if not self.can_call_live:
            return self._fixture_pr_radar("GITHUB_TOKEN is not set, so no live call was attempted.")

        try:
            open_prs, truncated = self._get_paged(
                f"/repos/{self.repository}/pulls",
                params={"state": "open", "sort": "created", "direction": "asc"},
            )
            now = _utc_now()
            stale: list[PullRequestDigest] = []
            for pull in open_prs:
                created = _parse_gh_time(pull.get("created_at"))
                if created is None:
                    continue
                hours_open = round((now - created).total_seconds() / 3600.0, 1)
                if hours_open <= STALE_REVIEW_SLA_HOURS:
                    continue
                stale.append(
                    PullRequestDigest(
                        pr_id=pull.get("number", 0),
                        repository=self.repository,
                        title=pull.get("title", "(no title)"),
                        author=(pull.get("user") or {}).get("login", "unknown"),
                        hours_open=hours_open,
                        is_blocked=bool(pull.get("draft")) or bool(pull.get("requested_reviewers")),
                    )
                )
            detail = (
                f"GitHub REST API for {self.repository}: {len(open_prs)} open pull requests, "
                f"{len(stale)} past the {STALE_REVIEW_SLA_HOURS:.0f} hour review SLA."
            )
            if truncated:
                detail += (
                    f" Paging stopped at the {MAX_PAGES}-page cap, so the open count is a lower bound."
                )
            return PRRadarReport(
                total_open_prs=len(open_prs),
                stale_prs_over_36h=stale,
                provenance=Provenance(
                    source=DataSource.GITHUB_API,
                    detail=detail,
                    observed_at_utc=_iso(now),
                ),
            )
        except Exception as exc:
            return self._fixture_pr_radar(f"Live GitHub call failed ({type(exc).__name__}: {exc}).")

    def _commit_paths(self, full_sha: str) -> list[str] | None:
        """Filenames changed by one commit, or None when the API does not say.

        The commits list carries no file lists, so each commit costs one extra
        read. A failed read leaves the list unknown and the commit a candidate;
        missing data never sets a change aside.
        """
        if not full_sha:
            return None
        try:
            detail = self._get(f"/repos/{self.repository}/commits/{full_sha}")
        except Exception:
            return None
        files = detail.get("files") if isinstance(detail, dict) else None
        if not isinstance(files, list):
            return None
        if len(files) >= COMMIT_FILES_CAP:
            return None
        return [
            str(item.get("filename", ""))
            for item in files
            if isinstance(item, dict) and item.get("filename")
        ]

    def list_recent_commits(self, limit: int = 10) -> list[dict[str, Any]]:
        """Return recent default-branch commits, used by the incident correlator.

        Returns an empty list when no live call is possible. The caller decides
        what to display; this adapter never invents a commit. Each commit counts
        one list read plus one files read, so a call costs at most ``limit + 2``
        requests against the token's rate limit.
        """
        if not self.can_call_live:
            return []
        try:
            repo_meta = self._get(f"/repos/{self.repository}")
            default_branch = repo_meta.get("default_branch", "main")
            payload = self._get(
                f"/repos/{self.repository}/commits",
                params={"sha": default_branch, "per_page": min(limit, 100)},
            )
            commits = []
            for entry in payload[:limit]:
                commit = entry.get("commit", {})
                full_sha = entry.get("sha", "")
                commits.append({
                    "sha": full_sha[:7],
                    "full_sha": full_sha,
                    "message": (commit.get("message") or "").splitlines()[0] if commit.get("message") else "",
                    "author": (commit.get("author") or {}).get("name", "unknown"),
                    "committed_at": (commit.get("author") or {}).get("date", ""),
                    "paths": self._commit_paths(full_sha),
                })
            return commits
        except Exception:
            return []
