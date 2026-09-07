"""Domain model for the 'what changed?' root cause correlation.

The war room question is always the same during an outage: an error metric moved,
and somebody wants to know which deployment moved it. This module answers that
from two inputs, a metric series and a list of commits, using explicit rules:

1. Split the series into a baseline (everything but the newest points) and a
   current reading (the newest point).
2. Call it an anomaly when the current reading is at least ``anomaly_factor``
   times the baseline mean and the baseline mean is above zero.
3. Attribute it to the newest commit that landed before the anomaly onset and
   within ``attribution_window_minutes`` of it.
4. Recommend rolling back to the commit immediately preceding that one.

Every step reports what it did. When there is no anomaly, or no commit inside the
attribution window, the correlator says so rather than naming a commit anyway.

Rule 3 is a heuristic and it has a measured failure mode. ``scripts/correlation_trial.py``
scores this class against a labelled corpus, and every attribution it got wrong was a case
where more than one change had landed inside the window: naming the newest of several is
right only when the newest is the culprit. The correlator therefore counts the candidates
and says how many there were, so an operator is told when the name it gave is one of
several rather than the only one. It does not silently pick differently, because there is
nothing in a metric series that says which of two changes in the same window did it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum

from src.domain.provenance import UNKNOWN_PROVENANCE, Provenance

DEFAULT_ANOMALY_FACTOR = 3.0
DEFAULT_ATTRIBUTION_WINDOW_MINUTES = 60


class CorrelationVerdict(str, Enum):
    """What the correlator concluded."""

    NO_ANOMALY = "NO_ANOMALY"
    ANOMALY_WITHOUT_ATTRIBUTION = "ANOMALY_WITHOUT_ATTRIBUTION"
    ANOMALY_ATTRIBUTED = "ANOMALY_ATTRIBUTED"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


@dataclass(frozen=True)
class MetricPoint:
    at: datetime
    value: float


@dataclass(frozen=True)
class MetricSeries:
    """A time series of one metric, with the provenance of where it came from."""

    metric_name: str
    namespace: str
    points: list[MetricPoint]
    provenance: Provenance = field(default=UNKNOWN_PROVENANCE)

    @property
    def latest(self) -> MetricPoint | None:
        return max(self.points, key=lambda p: p.at) if self.points else None

    def baseline_mean(self, exclude_latest: bool = True) -> float:
        points = sorted(self.points, key=lambda p: p.at)
        if exclude_latest:
            points = points[:-1]
        if not points:
            return 0.0
        return sum(p.value for p in points) / len(points)


@dataclass(frozen=True)
class CommitRef:
    sha: str
    message: str
    author: str
    committed_at: datetime


@dataclass(frozen=True)
class IncidentCorrelation:
    """The correlator's answer, including the case where it has no answer."""

    verdict: CorrelationVerdict
    service_name: str
    metric_name: str
    baseline_value: float
    current_value: float
    anomaly_factor: float
    offending_commit: CommitRef | None
    rollback_target: CommitRef | None
    explanation: str
    metric_provenance: Provenance
    commit_provenance: Provenance
    sample_size: int
    #: How many commits landed inside the attribution window before the reading.
    #: Zero on every verdict that names nobody. One means the attribution had a
    #: single candidate; more than one means it named the newest of several.
    commits_in_window: int = 0

    @property
    def attribution_is_ambiguous(self) -> bool:
        """True when a commit was named but it was not the only candidate.

        Measured, not asserted: in ``correlation_trial_summary.json`` every
        attribution that named the wrong commit is a case where this is true.
        """
        return self.verdict is CorrelationVerdict.ANOMALY_ATTRIBUTED and self.commits_in_window > 1

    @property
    def incident_detected(self) -> bool:
        return self.verdict in (
            CorrelationVerdict.ANOMALY_ATTRIBUTED,
            CorrelationVerdict.ANOMALY_WITHOUT_ATTRIBUTION,
        )

    @property
    def rollback_is_available(self) -> bool:
        return self.verdict is CorrelationVerdict.ANOMALY_ATTRIBUTED and self.rollback_target is not None

    def to_voice_summary(self) -> str:
        """One sentence short enough to be read aloud in a room.

        The cockpit speaks it with the browser's speech synthesis. Nothing in
        this repository integrates a voice assistant.
        """
        if self.verdict is CorrelationVerdict.INSUFFICIENT_DATA:
            return f"I do not have enough {self.metric_name} data for {self.service_name} to answer that."
        if self.verdict is CorrelationVerdict.NO_ANOMALY:
            return (
                f"{self.service_name} looks normal. {self.metric_name} is at "
                f"{self.current_value:.2f} against a baseline of {self.baseline_value:.2f}."
            )
        if self.verdict is CorrelationVerdict.ANOMALY_WITHOUT_ATTRIBUTION:
            return (
                f"{self.metric_name} on {self.service_name} is {self.anomaly_factor:.1f} times its "
                f"baseline, but no deployment landed close enough to blame. Investigate manually."
            )
        commit = self.offending_commit
        target = self.rollback_target
        spoken = (
            f"{self.metric_name} on {self.service_name} is {self.anomaly_factor:.1f} times its baseline. "
            f"The closest preceding change is commit {commit.sha} by {commit.author}."
        )
        if self.attribution_is_ambiguous:
            spoken += (
                f" {self.commits_in_window} changes landed inside the attribution window, so this is "
                "the closest of several and may not be the one that did it."
            )
        if target is not None:
            spoken += f" Rolling back to {target.sha} is staged and waiting for your confirmation."
        return spoken


class IncidentCorrelator:
    """Correlates a metric anomaly with the deployment that preceded it."""

    def __init__(
        self,
        anomaly_factor: float = DEFAULT_ANOMALY_FACTOR,
        attribution_window_minutes: int = DEFAULT_ATTRIBUTION_WINDOW_MINUTES,
    ) -> None:
        self.anomaly_factor = anomaly_factor
        self.attribution_window_minutes = attribution_window_minutes

    def correlate(
        self,
        service_name: str,
        series: MetricSeries,
        commits: list[CommitRef],
        commit_provenance: Provenance = UNKNOWN_PROVENANCE,
    ) -> IncidentCorrelation:
        latest = series.latest
        if latest is None or len(series.points) < 2:
            return IncidentCorrelation(
                verdict=CorrelationVerdict.INSUFFICIENT_DATA,
                service_name=service_name,
                metric_name=series.metric_name,
                baseline_value=0.0,
                current_value=latest.value if latest else 0.0,
                anomaly_factor=0.0,
                offending_commit=None,
                rollback_target=None,
                explanation=(
                    f"Need at least two {series.metric_name} data points to establish a baseline; "
                    f"received {len(series.points)}."
                ),
                metric_provenance=series.provenance,
                commit_provenance=commit_provenance,
                sample_size=len(series.points),
            )

        baseline = series.baseline_mean()
        factor = (latest.value / baseline) if baseline > 0 else 0.0

        if baseline <= 0 or factor < self.anomaly_factor:
            return IncidentCorrelation(
                verdict=CorrelationVerdict.NO_ANOMALY,
                service_name=service_name,
                metric_name=series.metric_name,
                baseline_value=round(baseline, 3),
                current_value=round(latest.value, 3),
                anomaly_factor=round(factor, 2),
                offending_commit=None,
                rollback_target=None,
                explanation=(
                    f"Current {series.metric_name} of {latest.value:.2f} is {factor:.2f} times the "
                    f"baseline mean of {baseline:.2f}, below the {self.anomaly_factor:.1f}x threshold."
                ),
                metric_provenance=series.provenance,
                commit_provenance=commit_provenance,
                sample_size=len(series.points),
            )

        window_start = latest.at - timedelta(minutes=self.attribution_window_minutes)
        candidates = sorted(
            (c for c in commits if window_start <= c.committed_at <= latest.at),
            key=lambda c: c.committed_at,
        )

        if not candidates:
            return IncidentCorrelation(
                verdict=CorrelationVerdict.ANOMALY_WITHOUT_ATTRIBUTION,
                service_name=service_name,
                metric_name=series.metric_name,
                baseline_value=round(baseline, 3),
                current_value=round(latest.value, 3),
                anomaly_factor=round(factor, 2),
                offending_commit=None,
                rollback_target=None,
                explanation=(
                    f"{series.metric_name} is {factor:.2f} times baseline, but no commit landed in the "
                    f"{self.attribution_window_minutes} minutes before the reading, so nothing is blamed."
                ),
                metric_provenance=series.provenance,
                commit_provenance=commit_provenance,
                sample_size=len(series.points),
            )

        offending = candidates[-1]
        ordered_all = sorted(commits, key=lambda c: c.committed_at)
        offending_index = ordered_all.index(offending)
        rollback_target = ordered_all[offending_index - 1] if offending_index > 0 else None

        explanation = (
            f"{series.metric_name} is {factor:.2f} times the baseline mean of {baseline:.2f}. "
            f"Commit {offending.sha} landed "
            f"{(latest.at - offending.committed_at).total_seconds() / 60:.0f} minutes before the reading, "
            f"the closest change inside the {self.attribution_window_minutes} minute attribution window."
        )
        if len(candidates) > 1:
            explanation += (
                f" It is not the only candidate: {len(candidates)} changes landed inside that window, "
                "and this rule names the closest one. Every attribution this correlator got wrong in "
                "scripts/correlation_trial.py was a window with more than one change in it."
            )
        if rollback_target is None:
            explanation += " No earlier commit is known, so no rollback target can be offered."
        else:
            explanation += f" The preceding commit {rollback_target.sha} is the rollback target."

        return IncidentCorrelation(
            verdict=CorrelationVerdict.ANOMALY_ATTRIBUTED,
            service_name=service_name,
            metric_name=series.metric_name,
            baseline_value=round(baseline, 3),
            current_value=round(latest.value, 3),
            anomaly_factor=round(factor, 2),
            offending_commit=offending,
            rollback_target=rollback_target,
            explanation=explanation,
            metric_provenance=series.provenance,
            commit_provenance=commit_provenance,
            sample_size=len(series.points),
            commits_in_window=len(candidates),
        )
