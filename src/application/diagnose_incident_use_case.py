"""Use Case: answer 'what changed?' by correlating a metric anomaly with commits.

This is the use case behind the Fire TV war room's headline question. It gathers
a metric series and recent commits, hands both to the domain correlator, and
returns the verdict unchanged. It never substitutes a result when a provider
returns nothing.

Commits come from the GitHub API when a token is present. When they do not, it
falls back to the local git checkout rather than to invented commits, and the
provenance says which of the two happened.

When the metric series is simulated (no CloudWatch), the simulation is anchored
to the newest known commit so the correlation is demonstrable end to end without
an AWS account. That anchoring is stated in the provenance the cockpit renders:
the commits are real, the metric is not, and the screen says so.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Protocol

from src.domain.incident_correlation import (
    CommitRef,
    IncidentCorrelation,
    IncidentCorrelator,
    MetricSeries,
)
from src.domain.provenance import DataSource, Provenance


class MetricSeriesProvider(Protocol):
    def get_error_series(
        self, service_name: str, window_minutes: int = 60, anchor_at: datetime | None = None
    ) -> MetricSeries:
        ...


class CommitHistoryProvider(Protocol):
    def list_recent_commits(self, limit: int = 10) -> list[dict[str, Any]]:
        ...


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso_now() -> str:
    return _now().strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_commit_time(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


class DiagnoseIncidentUseCase:
    """Correlates an error metric anomaly with the deployment that preceded it."""

    def __init__(
        self,
        metric_provider: MetricSeriesProvider,
        commit_provider: CommitHistoryProvider,
        local_commit_provider: CommitHistoryProvider | None = None,
        correlator: IncidentCorrelator | None = None,
    ) -> None:
        self._metrics = metric_provider
        self._commits = commit_provider
        self._local_commits = local_commit_provider
        self._correlator = correlator or IncidentCorrelator()

    def _gather_commits(self) -> tuple[list[CommitRef], Provenance]:
        """Try GitHub, then the local checkout. Never fabricate a commit."""
        raw = self._commits.list_recent_commits(limit=20)
        source = DataSource.GITHUB_API
        detail = "{count} recent default-branch commits read from the GitHub REST API."

        if not raw and self._local_commits is not None:
            raw = self._local_commits.list_recent_commits(limit=20)
            source = DataSource.LOCAL_GIT
            detail = (
                "{count} commits read from the local git checkout with git log, because no "
                "GitHub token is configured. These are real commits from this repository, "
                "not the service being monitored."
            )

        commits: list[CommitRef] = []
        for entry in raw:
            stamp = _parse_commit_time(entry.get("committed_at", ""))
            if stamp is None:
                continue
            commits.append(
                CommitRef(
                    sha=entry.get("sha", ""),
                    message=entry.get("message", ""),
                    author=entry.get("author", "unknown"),
                    committed_at=stamp,
                )
            )

        if not commits:
            return [], Provenance(
                source=DataSource.OFFLINE_FIXTURE,
                detail=(
                    "No commits are available from GitHub or from a local checkout, and this "
                    "use case does not invent commits. Attribution is reported as unavailable."
                ),
                observed_at_utc=_iso_now(),
            )

        return commits, Provenance(
            source=source,
            detail=detail.format(count=len(commits)),
            observed_at_utc=_iso_now(),
        )

    def execute(self, service_name: str, window_minutes: int = 60) -> IncidentCorrelation:
        commits, commit_provenance = self._gather_commits()

        # Anchor a simulated series just after the newest commit, so the demo path
        # produces a coherent correlation instead of an anomaly with nothing near
        # it. Only ever applied to a simulated series; a live CloudWatch reading
        # keeps its own timestamps.
        anchor = max((c.committed_at for c in commits), default=None)
        series = self._metrics.get_error_series(
            service_name, window_minutes=window_minutes, anchor_at=anchor
        )

        return self._correlator.correlate(service_name, series, commits, commit_provenance)
