"""Domain model for the 'what changed?' root cause correlation.

The war room question is always the same during an outage: an error metric moved,
and somebody wants to know which deployment moved it. This module answers that
from two inputs, a metric series and a list of commits, using explicit rules:

1. Find the onset: the first reading of an elevation that is still going on, and
   take the baseline from the readings strictly before it.
2. Call it an anomaly when such an onset exists, which means the newest reading is
   at least ``anomaly_factor`` times a baseline that does not contain the spike.
3. Look for commits in the ``attribution_window_minutes`` before the **onset**, not
   before the reading, because a change that landed after a spike started cannot
   have caused it.
4. Name one only when exactly ``max_commits_in_window`` or fewer landed there.
   Otherwise say how many landed and name none of them.
5. Recommend rolling back to the commit immediately preceding the named one.

Every step reports what it did, and the answer it gives most often is a refusal.
Against the labelled corpus in ``scripts/correlation_trial.py``, this class sees an
anomaly and names nobody 81.1% of the time: 225 times because nothing landed in the
window and 261 times because too much did. Those two are counted apart, in the trial
and on the wire, because a refusal for want of a candidate is the data being empty
while a refusal for a crowded window is a decision.

Rule 4 is what naming precision rests on and it was chosen from a published sweep.
Naming the closest of several changes is where the wrong names came from: of the 36
regressions where this class now names the wrong commit, 35 had the real cause outside
the window entirely, where no rule with this window could have reached it, and 0 had
the cause inside the window with more than one candidate. A further 18 wrong namings
blamed a commit for an exogenous spike no commit caused, 54 wrong of 113 in all. When
it does name a commit, the
commit it names is the one that caused the reading 52.2% of the time over 113
namings, which is close enough to a coin toss that the figure travels with the
answer: see ``src/infrastructure/trial_summary.py``.

Every figure above is written by ``python scripts/correlation_trial.py`` into
``correlation_trial_summary.json`` and a test compares the two.

**A refusal is a refusal, not an acquittal.** The three verdicts that name nothing
(``NO_CANDIDATE_IN_WINDOW``, ``WINDOW_TOO_CROWDED``, ``INSUFFICIENT_DATA``) say that
Mercury cannot attribute the anomaly to a change, and why. None of them is a finding
that no deploy caused it: an empty window says nothing about changes outside it, a
crowded window says nothing about which of its changes did it, and a missing baseline
says nothing at all. The only verdict that may say nothing needs reverting is
``NO_ANOMALY``, where the reading is inside its own baseline. That contract is carried
by :attr:`IncidentCorrelation.nothing_to_revert`, worded by
:attr:`IncidentCorrelation.refusal_statement`, and enforced on every surface by
:data:`REFUSAL_MUST_NOT_CLAIM`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum

from src.domain.provenance import UNKNOWN_PROVENANCE, Provenance

DEFAULT_ANOMALY_FACTOR = 3.0
DEFAULT_ATTRIBUTION_WINDOW_MINUTES = 60

#: How many readings must sit strictly before an onset for the mean of them to be
#: called a baseline. Two is the smallest number that is a mean of more than one
#: sample. It is also a hard cap on what this detector can see: with a six point
#: series polled every ten minutes, a spike that has been running for four polls
#: leaves one pre-onset point and cannot be detected at all. That cap is measured
#: rather than reasoned about, in ``correlation_trial_summary.json`` under
#: ``detectability_ceiling``.
DEFAULT_MIN_BASELINE_POINTS = 2

#: Refuse to name a commit when more than this many changes landed inside the
#: attribution window. Chosen from the sweep printed by
#: ``python scripts/correlation_trial.py --gate-sweep``, and the sweep is published
#: beside the choice so a reader can see what the other settings cost.
DEFAULT_MAX_COMMITS_IN_WINDOW = 1

#: What a refusal may never be rendered as, on the wire, on the screen, or in a
#: document a judge reads. Each is a regular expression matched case-insensitively over
#: whitespace-normalised text. A refusal says Mercury cannot attribute the anomaly to a
#: change and why; it has no way to rule a deploy out, so it never says it has, and it
#: never tells an operator that nothing needs reverting unless the reading is inside its
#: baseline. ``tests/unit/test_incident_correlation.py`` holds every refusal's wording to
#: this list and ``tests/e2e/test_refusal_wording.py`` holds the README, the Devpost
#: text, the cockpit and the video plan to it.
REFUSAL_MUST_NOT_CLAIM: tuple[str, ...] = (
    r"\bis not a deploy\b",
    r"\bnot caused by a deploy",
    r"\bno deploy caused\b",
    r"\bdo not revert anything\b",
    r"\bdo not revert on this\b",
    r"\bdo not roll back on this\b",
    r"\bnothing to blame\b",
    r"\bnot to blame a deploy",
    r"\brule[sd]? out (?:a|the|any) deploy",
    r"\blook elsewhere\b",
)


class CorrelationVerdict(str, Enum):
    """What the correlator concluded."""

    NO_ANOMALY = "NO_ANOMALY"
    ANOMALY_WITHOUT_ATTRIBUTION = "ANOMALY_WITHOUT_ATTRIBUTION"
    ANOMALY_ATTRIBUTED = "ANOMALY_ATTRIBUTED"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class BaselineMode(str, Enum):
    """Which points the current reading is compared against.

    ``TRAILING`` is what this correlator shipped with until 2026-09-08: the mean of
    every point but the newest. It is kept, and reachable from the trial's
    ``--baseline-mode trailing``, so the numbers this repository published before the
    change can be reproduced by running something rather than remembered.
    """

    TRAILING = "trailing"
    PRE_ONSET = "pre_onset"


class WindowAnchor(str, Enum):
    """Which instant the attribution window ends at.

    ``READING`` is the shipped behaviour before 2026-09-08: the window is the hour
    before the operator happened to look. ``ONSET`` ends it at the first elevated
    reading instead, so walking up to the screen half an hour late does not move the
    window off the change that caused the spike. It needs an onset, so it falls back
    to ``READING`` whenever the baseline mode did not find one.
    """

    READING = "reading"
    ONSET = "onset"


class AttributionRefusal(str, Enum):
    """Why an anomaly was left unattributed. Two different things, counted apart."""

    #: Nothing landed inside the window. No rule with this window could name anything.
    NO_CANDIDATE_IN_WINDOW = "NO_CANDIDATE_IN_WINDOW"
    #: Changes landed, but too many of them to point at one. This is a choice, not a
    #: gap in the data, and it is the refusal that carries the product.
    WINDOW_TOO_CROWDED = "WINDOW_TOO_CROWDED"


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

    def ordered_points(self) -> list[MetricPoint]:
        return sorted(self.points, key=lambda p: p.at)

    def baseline_mean(self, exclude_latest: bool = True) -> float:
        """The mean of every point but the newest.

        This is the baseline this correlator used until 2026-09-08, and it is the
        defect the labelled corpus found: a spike that has been running for three
        polls is inside this mean, so the factor collapses and a real regression reads
        as NO_ANOMALY. It is kept because :class:`BaselineMode` can still select it,
        which is how the before-and-after in the README is reproduced rather than
        remembered.
        """
        points = self.ordered_points()
        if exclude_latest:
            points = points[:-1]
        if not points:
            return 0.0
        return sum(p.value for p in points) / len(points)

    def find_onset(
        self,
        anomaly_factor: float,
        min_baseline_points: int = DEFAULT_MIN_BASELINE_POINTS,
    ) -> int | None:
        """Index of the first reading of an elevation that is still going on.

        The earliest index from which **every** later reading, the newest included, is
        at least ``anomaly_factor`` times the mean of everything strictly before that
        index. Returns None when no index qualifies, which is this mode's way of
        saying there is no anomaly.

        Two properties are worth stating because the published figures rest on them.

        The last index is always a candidate, and testing it is arithmetically the
        same test :meth:`baseline_mean` gives. So this detector fires on every series
        the trailing baseline fired on, and on some it did not: it is strictly more
        sensitive, never less. Whatever it costs on healthy series is a cost this
        change introduced, and ``correlation_trial_summary.json`` carries both sides.

        Requiring the elevation to persist to the newest reading is an assumption, not
        a result. It suppresses a single noisy sample, which is why moving the baseline
        earlier does not flood the healthy stratum with false alarms. It also matches
        how the trial's corpus generates a regression, which applies its multiplier
        from onset through to the end, so part of that suppression is fitted to the
        generator rather than earned against a real metric. A production spike that
        has already half recovered is not detected here, and that is the price.
        """
        points = self.ordered_points()
        if len(points) < 2:
            return None
        # Never start past the last index: that keeps the "at least as sensitive as
        # the trailing baseline" property true even for a two point series.
        start = min(max(min_baseline_points, 1), len(points) - 1)
        for index in range(start, len(points)):
            prior = points[:index]
            prior_mean = sum(p.value for p in prior) / len(prior)
            if prior_mean <= 0:
                continue
            threshold = anomaly_factor * prior_mean
            if all(point.value >= threshold for point in points[index:]):
                return index
        return None

    def mean_before(self, index: int) -> float:
        """Mean of the readings strictly before ``index``. Zero when there are none."""
        prior = self.ordered_points()[:index]
        if not prior:
            return 0.0
        return sum(p.value for p in prior) / len(prior)


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
    #: How many commits landed inside the attribution window. Zero when no anomaly was
    #: found and when nothing landed at all. More than one on an attribution means the
    #: newest of several was named; more than one on a WINDOW_TOO_CROWDED refusal is
    #: the reason for the refusal.
    commits_in_window: int = 0
    #: Why nothing was named, on the verdicts that name nothing. None otherwise.
    attribution_refusal: AttributionRefusal | None = None
    #: The first elevated reading, when the detector found one. This is what the
    #: attribution window is measured back from, so a late look does not drag the
    #: window off the change that caused the spike.
    onset_at: datetime | None = None
    #: How many readings the baseline was taken over. Under the pre-onset baseline
    #: this is the count strictly before the onset, which is smaller than the series.
    baseline_points: int = 0
    #: The attribution window this answer was reached with, so a refusal can say how
    #: wide the window it refused over was.
    attribution_window_minutes: int = DEFAULT_ATTRIBUTION_WINDOW_MINUTES

    @property
    def can_attribute(self) -> bool:
        """True only when exactly one change was named. Every other verdict cannot."""
        return self.verdict is CorrelationVerdict.ANOMALY_ATTRIBUTED and self.offending_commit is not None

    @property
    def nothing_to_revert(self) -> bool:
        """True only when the reading is inside its own baseline.

        This is the one verdict that may say nothing needs reverting, because it is the
        one where nothing is wrong. A refusal to attribute is not it: an empty window, a
        crowded window and a missing baseline each leave open whether a deploy caused the
        anomaly, so each is rendered as "cannot attribute" and never as "nothing to
        revert". Every refusal is driven through this property by a test that asserts it
        stays False.
        """
        return self.verdict is CorrelationVerdict.NO_ANOMALY

    @property
    def refusal_statement(self) -> str | None:
        """What a refusal is, and what it is not, in words an operator can act on.

        ``None`` on the two verdicts that are not refusals. On the three that are, the
        statement names the reason and says in the same breath that the reason is not a
        finding about the deploys: Mercury has no way to rule a deploy out, so it never
        says it has.
        """
        window = self.attribution_window_minutes
        ends_at = "the onset" if self.onset_at else "the reading"
        if self.verdict is CorrelationVerdict.INSUFFICIENT_DATA:
            plural = "s" if self.sample_size != 1 else ""
            return (
                f"Mercury cannot attribute anything for {self.service_name}: it has "
                f"{self.sample_size} reading{plural} of {self.metric_name} and a baseline needs at "
                "least two. That is missing data, not a finding about any deploy."
            )
        if self.attribution_refusal is AttributionRefusal.NO_CANDIDATE_IN_WINDOW:
            return (
                f"Mercury cannot attribute this anomaly to a change: no commit landed in the "
                f"{window} minutes before {ends_at}. That is an empty window, not evidence that "
                "no change caused it; a change outside the window, or a cause that is not a "
                "change at all, are both still open."
            )
        if self.attribution_refusal is AttributionRefusal.WINDOW_TOO_CROWDED:
            return (
                f"Mercury cannot attribute this anomaly to any one change: "
                f"{self.commits_in_window} landed in the {window} minutes before {ends_at}, and "
                "nothing in the metric says which of them did it. That is a refusal to guess, "
                "not a finding that none of them caused it; rolling back on this answer would "
                "be a guess."
            )
        return None

    @property
    def attribution_is_ambiguous(self) -> bool:
        """True when a commit was named but it was not the only candidate.

        Unreachable at the shipped settings, and deliberately kept. With
        ``max_commits_in_window = 1`` a crowded window is refused rather than named, so
        this is false on every attribution the default correlator makes and
        ``correlation_trial_summary.json`` records 0 of 54 wrong namings disclosed this
        way. It is what an answer owes an operator when somebody widens the gate, which
        ``--max-commits-in-window`` in the trial does, and the disclosure is measured
        there rather than removed on the assumption nobody will.
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
            if self.attribution_refusal is AttributionRefusal.WINDOW_TOO_CROWDED:
                return (
                    f"{self.metric_name} on {self.service_name} is {self.anomaly_factor:.1f} times its "
                    f"baseline, and {self.commits_in_window} changes landed in the window before it. "
                    "Mercury cannot attribute it to any one of them and will not guess. That is not "
                    "a finding that none of them caused it; rolling back on this answer would be a "
                    "guess."
                )
            return (
                f"{self.metric_name} on {self.service_name} is {self.anomaly_factor:.1f} times its "
                "baseline, and no change landed in the window before it. Mercury cannot attribute "
                "it to a deploy. That is an empty window, not a verdict on what caused it. "
                "Investigate manually."
            )
        commit = self.offending_commit
        spoken = (
            f"{self.metric_name} on {self.service_name} is {self.anomaly_factor:.1f} times its baseline. "
            f"The closest preceding change is commit {commit.sha} by {commit.author}."
        )
        if self.attribution_is_ambiguous:
            spoken += (
                f" {self.commits_in_window} changes landed inside the attribution window, so this is "
                "the closest of several and may not be the one that did it."
            )
        spoken += (
            " This is a temporal candidate, not proof of cause. A rollback target requires separate "
            "deployment and health evidence."
        )
        return spoken


class IncidentCorrelator:
    """Correlates a metric anomaly with the deployment that preceded it."""

    def __init__(
        self,
        anomaly_factor: float = DEFAULT_ANOMALY_FACTOR,
        attribution_window_minutes: int = DEFAULT_ATTRIBUTION_WINDOW_MINUTES,
        baseline_mode: BaselineMode = BaselineMode.PRE_ONSET,
        window_anchor: WindowAnchor = WindowAnchor.ONSET,
        min_baseline_points: int = DEFAULT_MIN_BASELINE_POINTS,
        max_commits_in_window: int | None = DEFAULT_MAX_COMMITS_IN_WINDOW,
    ) -> None:
        self.anomaly_factor = anomaly_factor
        self.attribution_window_minutes = attribution_window_minutes
        self.baseline_mode = baseline_mode
        self.window_anchor = window_anchor
        self.min_baseline_points = min_baseline_points
        #: None means name the closest candidate however many there were, which is what
        #: this correlator did until 2026-09-08.
        self.max_commits_in_window = max_commits_in_window

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
                    f"received {len(series.points)}. With no baseline Mercury cannot attribute "
                    "anything, and says nothing about whether a deploy is involved."
                ),
                metric_provenance=series.provenance,
                commit_provenance=commit_provenance,
                sample_size=len(series.points),
                attribution_window_minutes=self.attribution_window_minutes,
            )

        onset_index = (
            series.find_onset(self.anomaly_factor, self.min_baseline_points)
            if self.baseline_mode is BaselineMode.PRE_ONSET
            else None
        )
        ordered = series.ordered_points()

        if onset_index is not None:
            # The spike is not allowed into its own baseline. This is the whole of the
            # fix the corpus asked for: with the trailing mean, a regression running
            # for three polls was most of the mean it was compared against.
            baseline = series.mean_before(onset_index)
            baseline_points = onset_index
            onset_at = ordered[onset_index].at
            is_anomaly = True
        else:
            baseline = series.baseline_mean()
            baseline_points = max(len(ordered) - 1, 0)
            onset_at = None
            is_anomaly = (
                self.baseline_mode is BaselineMode.TRAILING
                and baseline > 0
                and (latest.value / baseline) >= self.anomaly_factor
            )

        factor = (latest.value / baseline) if baseline > 0 else 0.0

        if not is_anomaly:
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
                baseline_points=baseline_points,
                attribution_window_minutes=self.attribution_window_minutes,
            )

        # The window ends at the onset when there is one, not at the moment somebody
        # looked. A commit that landed after the spike started cannot have caused it,
        # and on the corpus's late-look stratum that single change is most of the
        # difference between naming the cause and naming whatever shipped since.
        window_end = onset_at if (self.window_anchor is WindowAnchor.ONSET and onset_at) else latest.at
        window_start = window_end - timedelta(minutes=self.attribution_window_minutes)
        candidates = sorted(
            (c for c in commits if window_start <= c.committed_at <= window_end),
            key=lambda c: c.committed_at,
        )

        def unattributed(refusal: AttributionRefusal, explanation: str) -> IncidentCorrelation:
            return IncidentCorrelation(
                verdict=CorrelationVerdict.ANOMALY_WITHOUT_ATTRIBUTION,
                service_name=service_name,
                metric_name=series.metric_name,
                baseline_value=round(baseline, 3),
                current_value=round(latest.value, 3),
                anomaly_factor=round(factor, 2),
                offending_commit=None,
                rollback_target=None,
                explanation=explanation,
                metric_provenance=series.provenance,
                commit_provenance=commit_provenance,
                sample_size=len(series.points),
                commits_in_window=len(candidates),
                attribution_refusal=refusal,
                onset_at=onset_at,
                baseline_points=baseline_points,
                attribution_window_minutes=self.attribution_window_minutes,
            )

        if not candidates:
            return unattributed(
                AttributionRefusal.NO_CANDIDATE_IN_WINDOW,
                f"{series.metric_name} is {factor:.2f} times baseline, but no commit landed in the "
                f"{self.attribution_window_minutes} minutes before "
                f"{'the onset' if onset_at else 'the reading'}, so Mercury cannot attribute it to "
                "a change. An empty window is not evidence that no change caused it: a change "
                "outside the window, or a cause that is not a change at all, are both still open.",
            )

        if self.max_commits_in_window is not None and len(candidates) > self.max_commits_in_window:
            # Naming the closest of a crowded window is what produced most of the wrong
            # names in scripts/correlation_trial.py. Refusing is the honest answer, and
            # the refusal is stated as what it is: Mercury cannot attribute this, not
            # Mercury has cleared the changes.
            return unattributed(
                AttributionRefusal.WINDOW_TOO_CROWDED,
                f"{series.metric_name} is {factor:.2f} times baseline and {len(candidates)} changes "
                f"landed in the {self.attribution_window_minutes} minutes before "
                f"{'the onset' if onset_at else 'the reading'}. That is more than the "
                f"{self.max_commits_in_window} this correlator will name from, so it names none of "
                "them. Nothing here says which of those changes did it, and rolling back the closest "
                "one is as likely to revert an innocent change as the guilty one. This is a refusal "
                "to attribute, not a finding that none of them did it.",
            )

        offending = candidates[-1]
        ordered_all = sorted(commits, key=lambda c: c.committed_at)
        offending_index = ordered_all.index(offending)
        rollback_target = ordered_all[offending_index - 1] if offending_index > 0 else None

        explanation = (
            f"{series.metric_name} is {factor:.2f} times the baseline mean of {baseline:.2f}, taken over "
            f"the {baseline_points} readings before "
            f"{'the onset' if onset_at else 'the newest one'}. Commit {offending.sha} landed "
            f"{(window_end - offending.committed_at).total_seconds() / 60:.0f} minutes before "
            f"{'the onset' if onset_at else 'the reading'}, "
            f"the closest change inside the {self.attribution_window_minutes} minute attribution window."
        )
        if len(candidates) > 1:
            explanation += (
                f" It is not the only candidate: {len(candidates)} changes landed inside that window, "
                "and this rule names the closest one. Every wrong attribution in "
                "scripts/correlation_trial.py whose real cause was inside the window looked like this."
            )
        explanation += (
            " Git order is not deployment evidence and does not by itself define a rollback target."
        )

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
            onset_at=onset_at,
            baseline_points=baseline_points,
            attribution_window_minutes=self.attribution_window_minutes,
        )
