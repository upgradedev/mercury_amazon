"""Use Case: answer 'what changed?' by correlating a metric anomaly with commits.

This is the use case behind the Fire TV war room's headline question. It gathers
a metric series and recent commits, hands both to the domain correlator, and
returns the verdict unchanged. It never substitutes a result when a provider
returns nothing.

Commits come from the GitHub API when a token is present. When they do not, it
falls back to the local git checkout and finally to the checked-in recording used
by the published trial. The provenance distinguishes all three paths.

When the metric series is simulated (no CloudWatch), the simulation is anchored
to the newest known commit so the correlation is demonstrable end to end without
an AWS account. That anchoring is stated in the provenance the cockpit renders:
the commits are real, the metric is not, and the screen says so.

Each commit carries its file list when the source has one (local git and the recording
do; the GitHub commits API used here does not). With a runtime filter on the correlator,
a commit whose files are all outside what the server is built from is not a deploy
candidate, and the simulated reading is placed after a candidate, never after a commit
the filter sets aside.
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
        self,
        service_name: str,
        window_minutes: int = 60,
        anchor_at: datetime | None = None,
        commit_times: list[datetime] | None = None,
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


def _commit_ref_from_entry(entry: dict) -> CommitRef | None:
    """One provider dict into a CommitRef, or None when its time is unreadable."""
    stamp = _parse_commit_time(entry.get("committed_at", ""))
    if stamp is None:
        return None
    listed = entry.get("paths")
    paths = tuple(str(p) for p in listed) if isinstance(listed, (list, tuple)) and listed else None
    return CommitRef(
        sha=entry.get("sha", ""),
        message=entry.get("message", ""),
        author=entry.get("author", "unknown"),
        committed_at=stamp,
        paths=paths,
    )


class DiagnoseIncidentUseCase:
    """Correlates an error metric anomaly with the deployment that preceded it."""

    def __init__(
        self,
        metric_provider: MetricSeriesProvider,
        commit_provider: CommitHistoryProvider,
        local_commit_provider: CommitHistoryProvider | None = None,
        recorded_commit_provider: CommitHistoryProvider | None = None,
        correlator: IncidentCorrelator | None = None,
    ) -> None:
        self._metrics = metric_provider
        self._commits = commit_provider
        self._local_commits = local_commit_provider
        self._recorded_commits = recorded_commit_provider
        self._correlator = correlator or IncidentCorrelator()

    def _gather_commits(self) -> tuple[list[CommitRef], Provenance]:
        """Try GitHub, local git, then an explicitly labelled recording."""
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

        if not raw and self._recorded_commits is not None:
            raw = self._recorded_commits.list_recent_commits(limit=20)
            source = DataSource.OFFLINE_FIXTURE
            detail = getattr(
                self._recorded_commits,
                "detail",
                (
                    "{count} commits read from a checked-in recording. They are real recorded "
                    "repository commits, not live service deployments."
                ),
            )

        commits: list[CommitRef] = []
        for entry in raw:
            ref = _commit_ref_from_entry(entry)
            if ref is not None:
                commits.append(ref)

        if not commits:
            return [], Provenance(
                source=DataSource.OFFLINE_FIXTURE,
                detail=(
                    "No commits are available from GitHub, local git or the checked-in recording, "
                    "and this use case does not invent commits. Attribution is unavailable."
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

        # The local checkout can name a parent the fetch window cannot see
        # (9885eac: the offending commit's parent fell out of the 20). Offer
        # that lookup to the correlator; providers without parent_of simply
        # leave the fallback off.
        def _resolve_parent(sha: str, _local=self._local_commits):
            entry = _local.parent_of(sha)
            return _commit_ref_from_entry(entry) if entry else None

        local = self._local_commits
        parent_resolver = _resolve_parent if (
            local is not None and hasattr(local, "parent_of")) else None

        # Anchor a simulated series just after a real commit, so the demo path produces
        # a coherent correlation instead of an anomaly with nothing near it. The whole
        # log goes with it, because which commit a shape should sit after depends on how
        # crowded that commit's attribution window is, and only the fixture knows which
        # shape it is building. Only ever applied to a simulated series; a live
        # CloudWatch reading keeps its own timestamps.
        #
        # Only candidates are handed over as commit times: with the runtime filter on, a
        # reading placed after a README edit would ask the correlator about a commit it
        # does not count, and the attributing row would turn into a refusal.
        anchor = max((c.committed_at for c in commits), default=None)
        scope = getattr(self._correlator, "service_scope", None)
        candidates = [c for c in commits if scope is None or scope.touches(c.paths) is not False]
        series = self._metrics.get_error_series(
            service_name,
            window_minutes=window_minutes,
            anchor_at=anchor,
            commit_times=[c.committed_at for c in candidates],
        )

        return self._correlator.correlate(service_name, series, commits, commit_provenance,
                                            parent_resolver=parent_resolver)
