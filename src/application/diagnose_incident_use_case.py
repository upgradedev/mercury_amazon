"""Use Case: answer 'what changed?' by correlating a metric anomaly with commits.

This is the use case behind the Fire TV war room's headline question. It pulls a
metric series from the observability provider and the recent commits from the
version control provider, hands both to the domain correlator, and returns its
verdict unchanged. It never substitutes a result when a provider returns nothing.
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
    def get_error_series(self, service_name: str, window_minutes: int = 60) -> MetricSeries:
        ...


class CommitHistoryProvider(Protocol):
    def list_recent_commits(self, limit: int = 10) -> list[dict[str, Any]]:
        ...


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
        correlator: IncidentCorrelator | None = None,
    ) -> None:
        self._metrics = metric_provider
        self._commits = commit_provider
        self._correlator = correlator or IncidentCorrelator()

    def execute(self, service_name: str, window_minutes: int = 60) -> IncidentCorrelation:
        series = self._metrics.get_error_series(service_name, window_minutes=window_minutes)
        raw_commits = self._commits.list_recent_commits(limit=20)

        commits: list[CommitRef] = []
        for entry in raw_commits:
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

        if commits:
            commit_provenance = Provenance(
                source=DataSource.GITHUB_API,
                detail=f"{len(commits)} recent default-branch commits read from the GitHub REST API.",
                observed_at_utc=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            )
        else:
            commit_provenance = Provenance(
                source=DataSource.OFFLINE_FIXTURE,
                detail=(
                    "No commits are available: GITHUB_TOKEN is unset or the call failed, and this "
                    "use case does not invent commits. Attribution will be reported as unavailable."
                ),
                observed_at_utc=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            )

        return self._correlator.correlate(service_name, series, commits, commit_provenance)
