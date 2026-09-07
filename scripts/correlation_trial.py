#!/usr/bin/env python3
"""Correlation trial: how often does Mercury blame the right commit, and how often does it blame an innocent one.

WHAT THIS IS. A labelled corpus of incidents, scored against the committed
:class:`~src.domain.incident_correlation.IncidentCorrelator` with its shipped defaults
(3.0x anomaly threshold, 60 minute attribution window, 6 point series). Each case carries
the truth its generator recorded when it built the case: which commit, if any, caused the
reading. The correlator never sees that truth, and the truth is never derived from what
the correlator said. Two figures come out of it and both are published whatever they are:

* the **hit rate**, the share of genuine regressions where the commit Mercury named is the
  commit that caused them;
* the **false-attribution rate**, the share of anomalies no commit caused where Mercury
  named a commit anyway.

The dotted branches of the README diagram are the second figure. They are the reason the
corpus contains more cases with no cause than with one.

WHERE THE TIMESTAMPS COME FROM, WHICH IS THE POINT. The deployment stream is this
repository's own ``git log``, recorded once into
``src/infrastructure/fixtures/commit_stream_fixture.json`` so a published number does not
move every time somebody commits. The reading times of every case with **no** cause are
drawn uniformly over the span of that log and snapped to a fixed 10 minute polling grid,
with no reference whatsoever to where individual commits fall: the generator for those
strata is handed two dates and never the commits. That is the difference between this and
the cockpit's demo fixture, which places its one reading four minutes after the newest
commit so the correlation cannot fail. ``tests/unit/test_correlation_trial.py`` proves the
independence by regenerating those strata against a commit log whose times have been
shuffled and asserting the reading times do not move.

For a regression the reading time necessarily follows its cause, because that is what
causing something means. What is not chosen to flatter the correlator is the delay: the
propagation delay is drawn from a distribution that reaches past the 60 minute attribution
window, and the operator's look at the screen is drawn from a distribution that reaches
several polls past the onset. Both draws are made without looking at where the neighbouring
commits are.

WHAT THE NUMBERS ARE WORTH, WHICH IS NOT THE SAME THING.

* The **hit rate on a fresh look** mostly re-derives an arithmetic rule, and the
  interesting part of it is only how often the *newest* commit before the reading is not
  the one that caused it. This repository commits in bursts, so that happens.
* The **hit rate on a late look** is the figure that carries information, and it is bad.
  ``MetricSeries.baseline_mean`` drops only the newest point, so a spike that has been
  running for three polls is inside its own baseline and the factor collapses below the
  threshold. Nobody designed that; the corpus found it.
* The **false-attribution rate** is a joint property of the correlator's 60 minute window
  and the density of the commit stream it is given, and it is close to meaningless without
  the second half of that sentence. ``--commit-stride`` thins the recorded log to every
  k-th commit, and the report prints the sweep, so a reader can see how much of the figure
  is the window and how much is this repository's commit cadence.

WHAT THIS IS NOT. Not a field trial. No production incident, no real error metric and no
deployment pipeline appears anywhere in it: the metric values are generated here from the
parameters below, all of which are assumptions written by the authors rather than
observations of a real service. The commits are real, and they are development commits
from this repository, not deployments of the service being monitored.

Run command::

    python scripts/correlation_trial.py                 # score and report
    python scripts/correlation_trial.py --json          # machine readable
    python scripts/correlation_trial.py --record        # re-record the commit stream from git log

``--check`` re-scores the corpus and compares it to the recorded summary, which is what CI
runs. The draws come from ``random.Random`` seeded with a string, so they are identical on
every platform, but the rates are floating point and a case sitting exactly on the 3.0x
threshold could in principle fall the other way on a different libm. If that ever happens
the check will say which figure moved, and the answer is to re-record on the machine that
publishes, not to loosen the comparison.

Every figure it prints is a property of this corpus on the machine that ran it, and the
seed that produced it is printed beside it so the run can be repeated exactly.
"""
from __future__ import annotations

import argparse
import json
import math
import platform
import random
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.domain.incident_correlation import (  # noqa: E402
    DEFAULT_ANOMALY_FACTOR,
    DEFAULT_ATTRIBUTION_WINDOW_MINUTES,
    CommitRef,
    CorrelationVerdict,
    IncidentCorrelator,
    MetricPoint,
    MetricSeries,
)
from src.domain.provenance import DataSource, Provenance  # noqa: E402
from src.infrastructure.cloudwatch_adapter import (  # noqa: E402
    DEFAULT_METRIC,
    DEFAULT_NAMESPACE,
    SERIES_POINTS,
)
from src.infrastructure.local_git_adapter import LocalGitCommitProvider  # noqa: E402

#: Where the recorded deployment stream lives. Real commits, recorded once.
COMMIT_STREAM_PATH = REPO_ROOT / "src" / "infrastructure" / "fixtures" / "commit_stream_fixture.json"

#: Where the scored summary is written. The README quotes it and a test compares them.
SUMMARY_PATH = REPO_ROOT / "correlation_trial_summary.json"

#: Minutes between metric samples. ``CloudWatchMetricAdapter`` asks CloudWatch for
#: ``window_minutes // SERIES_POINTS`` minute periods over a 60 minute window, so 10.
POLL_CADENCE_MINUTES = 60 // SERIES_POINTS

#: Fixed so the published figures can be reproduced. ``--seed`` changes the corpus.
DEFAULT_SEED = 20260908

#: Cohort sizes. There are deliberately more cases with no cause than with one: the
#: refusals are what the README diagram promises and what a war room tool is judged on.
DEFAULT_REGRESSION_FRESH = 300
DEFAULT_REGRESSION_LATE = 300
DEFAULT_EXOGENOUS = 300
DEFAULT_HEALTHY = 200
DEFAULT_SPARSE = 60

#: Authored assumptions about the shape of an error metric. None was measured.
#: ``--noise-sigma`` exists so a reader can see how much of the healthy-day false alarm
#: figure is the correlator's threshold and how much is this guess about burstiness.
DEFAULT_NOISE_SIGMA = 0.40
BASELINE_RATE_RANGE = (1.0, 60.0)          # errors per 10 minute sample, log-uniform
SPIKE_MULTIPLIER_RANGE = (1.5, 20.0)       # how hard a regression bites, log-uniform
PROPAGATION_DELAY_MINUTES = (1.0, 75.0)    # commit lands to error rate moves
LATE_LOOK_POLLS = (1, 4)                   # how many polls after onset somebody looks

#: Truth labels. What a perfect answer would be, recorded by the generator.
TRUTH_REGRESSION = "REGRESSION_CAUSED_BY_A_COMMIT"
TRUTH_EXOGENOUS = "ANOMALY_NO_COMMIT_CAUSED"
TRUTH_HEALTHY = "NO_ANOMALY"
TRUTH_NO_DATA = "NOT_ENOUGH_DATA"

STRATUM_FRESH = "regression_fresh_look"
STRATUM_LATE = "regression_late_look"
STRATUM_EXOGENOUS = "exogenous_spike"
STRATUM_HEALTHY = "healthy"
STRATUM_SPARSE = "telemetry_gap"

#: Outcomes. Every case scores as exactly one of these.
HIT = "HIT_named_the_commit_that_caused_it"
WRONG_COMMIT = "FALSE_ATTRIBUTION_named_an_innocent_commit"
REFUSED_ON_REGRESSION = "REFUSED_saw_the_anomaly_and_blamed_nothing"
MISSED_REGRESSION = "MISS_never_called_it_an_anomaly"
FALSE_ATTRIBUTION = "FALSE_ATTRIBUTION_blamed_a_commit_for_an_anomaly_it_did_not_cause"
CORRECT_REFUSAL = "CORRECT_REFUSAL_anomaly_with_nothing_blamed"
MISSED_EXOGENOUS = "MISS_never_called_the_exogenous_spike_an_anomaly"
CORRECT_QUIET = "CORRECT_stayed_quiet_on_a_healthy_series"
FALSE_ANOMALY = "FALSE_ALARM_called_a_healthy_series_an_anomaly"
CORRECT_NO_DATA = "CORRECT_refused_for_want_of_data"
UNEXPECTED = "UNEXPECTED"

#: Outcomes in which the correlator named a commit. Used for the naming precision figure.
NAMED_A_COMMIT = (HIT, WRONG_COMMIT, FALSE_ATTRIBUTION)


# --------------------------------------------------------------- The commit stream


def record_commit_stream(path: Path = COMMIT_STREAM_PATH, limit: int = 100) -> dict:
    """Record this checkout's ``git log`` as the corpus deployment stream.

    Same idea as ``scripts/record_github_fixture.py``: the data is real, it is recorded
    once, and the recording says where it came from. Reading ``git log`` live on every run
    would move every published figure on every commit, including the commit that publishes
    the figure.
    """
    commits = LocalGitCommitProvider().list_recent_commits(limit=limit)
    if len(commits) < 2:
        raise SystemExit(f"git log returned {len(commits)} commits; a corpus needs a stream")
    head = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        capture_output=True, text=True, cwd=str(REPO_ROOT), timeout=10,
    ).stdout.strip()
    payload = {
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "recorded_by": "python scripts/correlation_trial.py --record",
        "recorded_at_head": head,
        "source": (
            "git log in this checkout. These are real development commits from this "
            "repository, not deployments of any monitored service, and they are recorded "
            "rather than read live so a published measurement does not move on every commit."
        ),
        "commit_count": len(commits),
        "commits": commits,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def load_commit_stream(path: Path = COMMIT_STREAM_PATH) -> tuple[list[CommitRef], dict]:
    """Load the recorded stream, oldest first, with the recording's own metadata."""
    if not path.exists():
        raise SystemExit(
            f"no recorded commit stream at {path}. Record one with:\n"
            "  python scripts/correlation_trial.py --record"
        )
    payload = json.loads(path.read_text(encoding="utf-8"))
    commits = [
        CommitRef(
            sha=entry["sha"],
            message=entry.get("message", ""),
            author=entry.get("author", "unknown"),
            committed_at=datetime.fromisoformat(entry["committed_at"]).astimezone(timezone.utc),
        )
        for entry in payload["commits"]
    ]
    commits.sort(key=lambda c: c.committed_at)
    return commits, payload


def thin(commits: list[CommitRef], stride: int) -> list[CommitRef]:
    """Keep every ``stride``-th commit, so commit density can be varied on purpose.

    Density is the other half of any false-attribution figure: an anomaly with no cause is
    attributed exactly when some commit happens to fall in the 60 minute window before the
    reading, and how often that happens is a property of the stream, not of the correlator.
    """
    if stride < 1:
        raise ValueError("stride must be at least 1")
    return commits[::stride]


def commit_density_per_hour(commits: list[CommitRef]) -> float:
    """Commits per hour over the span of the stream. Measured from the stream itself."""
    if len(commits) < 2:
        return 0.0
    span_hours = (commits[-1].committed_at - commits[0].committed_at).total_seconds() / 3600.0
    return round(len(commits) / span_hours, 3) if span_hours > 0 else 0.0


# ------------------------------------------------------------------- The corpus


@dataclass(frozen=True)
class TrialCase:
    """One labelled incident: what the correlator is shown, and what is true about it."""

    index: int
    stratum: str
    truth: str
    observed_at: datetime
    point_values: tuple[float, ...]
    point_times: tuple[datetime, ...]
    causing_sha: str | None = None
    onset_at: datetime | None = None
    polls_since_onset: int | None = None
    spike_multiplier: float | None = None
    #: Computed from the case's own timestamps, never from anything the correlator said.
    cause_inside_attribution_window: bool | None = None
    #: Commits that landed after the cause and before the reading. A burst of them is how
    #: a correct rule ("the closest change before the reading") names an innocent commit.
    commits_between_cause_and_reading: int | None = None

    def to_series(self) -> MetricSeries:
        return MetricSeries(
            metric_name=DEFAULT_METRIC,
            namespace=DEFAULT_NAMESPACE,
            points=[
                MetricPoint(at=at, value=value)
                for at, value in zip(self.point_times, self.point_values)
            ],
            provenance=Provenance(
                source=DataSource.OFFLINE_FIXTURE,
                detail=(
                    f"Corpus case {self.index} ({self.stratum}), generated by "
                    "scripts/correlation_trial.py. Never read from CloudWatch."
                ),
                observed_at_utc=self.observed_at.isoformat(),
            ),
        )


def _log_uniform(rng: random.Random, low: float, high: float) -> float:
    return math.exp(rng.uniform(math.log(low), math.log(high)))


def _grid_ceiling(moment: datetime, cadence_minutes: int = POLL_CADENCE_MINUTES) -> datetime:
    """The first polling instant at or after ``moment``.

    The poll grid is absolute and fixed, the way a metric pipeline's is. It is not aligned
    to anything in the commit log, so where a commit falls inside a poll interval is an
    accident rather than a choice.
    """
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    minutes = (moment - epoch).total_seconds() / 60.0
    return epoch + timedelta(minutes=math.ceil(minutes / cadence_minutes) * cadence_minutes)


def _stratum_rng(seed: int, stratum: str) -> random.Random:
    """One independent stream per stratum.

    Seeding per stratum is what lets the independence test mean something: the reading
    times of a stratum that never touches the commits are then a function of the seed and
    the span alone, so regenerating them against a different commit log must reproduce
    them exactly.
    """
    return random.Random(f"{seed}:{stratum}")


def _series_values(
    rng: random.Random,
    baseline_rate: float,
    multiplier: float | None,
    elevated_from_index: int | None,
    noise_sigma: float,
    points: int = SERIES_POINTS,
) -> tuple[float, ...]:
    """Sample the series. Every point is noisy; the elevated ones are also multiplied."""
    values = []
    for index in range(points):
        noise = rng.lognormvariate(0.0, noise_sigma)
        value = baseline_rate * noise
        if multiplier is not None and elevated_from_index is not None and index >= elevated_from_index:
            value *= multiplier
        values.append(round(value, 3))
    return tuple(values)


def _point_times(observed_at: datetime, points: int = SERIES_POINTS) -> tuple[datetime, ...]:
    return tuple(
        observed_at - timedelta(minutes=POLL_CADENCE_MINUTES * (points - 1 - index))
        for index in range(points)
    )


def _regression_cases(
    count: int,
    commits: list[CommitRef],
    seed: int,
    stratum: str,
    noise_sigma: float,
    start_index: int,
) -> list[TrialCase]:
    """Cases where one recorded commit really did cause the reading.

    The cause is drawn uniformly from the stream. The propagation delay reaches past the
    correlator's own 60 minute window on purpose, and on the late-look stratum the operator
    arrives one to four polls after the onset, which is what a person walking into a room
    does. Neither draw looks at where the neighbouring commits are.
    """
    rng = _stratum_rng(seed, stratum)
    late = stratum == STRATUM_LATE
    cases: list[TrialCase] = []

    for offset in range(count):
        cause = rng.choice(commits)
        multiplier = _log_uniform(rng, *SPIKE_MULTIPLIER_RANGE)
        baseline_rate = _log_uniform(rng, *BASELINE_RATE_RANGE)
        propagation = rng.uniform(*PROPAGATION_DELAY_MINUTES)
        polls_late = rng.randint(*LATE_LOOK_POLLS) if late else 0

        onset = cause.committed_at + timedelta(minutes=propagation)
        first_poll = _grid_ceiling(onset)
        observed_at = first_poll + timedelta(minutes=POLL_CADENCE_MINUTES * polls_late)
        times = _point_times(observed_at)
        elevated_from = next((i for i, at in enumerate(times) if at >= onset), None)

        window_start = observed_at - timedelta(minutes=DEFAULT_ATTRIBUTION_WINDOW_MINUTES)
        between = sum(
            1 for c in commits if cause.committed_at < c.committed_at <= observed_at
        )

        cases.append(TrialCase(
            index=start_index + offset,
            stratum=stratum,
            truth=TRUTH_REGRESSION,
            observed_at=observed_at,
            point_values=_series_values(rng, baseline_rate, multiplier, elevated_from, noise_sigma),
            point_times=times,
            causing_sha=cause.sha,
            onset_at=onset,
            polls_since_onset=polls_late,
            spike_multiplier=round(multiplier, 3),
            cause_inside_attribution_window=window_start <= cause.committed_at <= observed_at,
            commits_between_cause_and_reading=between,
        ))
    return cases


def _uncaused_cases(
    count: int,
    span: tuple[datetime, datetime],
    seed: int,
    stratum: str,
    noise_sigma: float,
    start_index: int,
) -> list[TrialCase]:
    """Cases no commit caused. This generator is handed the span and never the commits.

    ``exogenous_spike`` is a real anomaly with a cause outside the deployment stream: a
    traffic surge, an upstream dependency, a bad cache. The right answer is to call it an
    anomaly and blame nothing. ``healthy`` is an ordinary series with nothing wrong, where
    the right answer is silence. ``telemetry_gap`` is a service that reported one sample,
    where the right answer is to refuse for want of data.

    The exogenous spike is always looked at on the first poll after onset. Scoring
    attribution on cases the detector never flagged would dilute the false-attribution rate
    with detector misses, and those are measured on their own stratum.
    """
    rng = _stratum_rng(seed, stratum)
    span_start, span_end = span
    span_minutes = (span_end - span_start).total_seconds() / 60.0
    cases: list[TrialCase] = []

    for offset in range(count):
        # Drawn from the span alone. Nothing here reads a commit time.
        observed_at = _grid_ceiling(span_start + timedelta(minutes=rng.uniform(0.0, span_minutes)))
        times = _point_times(observed_at)
        baseline_rate = _log_uniform(rng, *BASELINE_RATE_RANGE)

        if stratum == STRATUM_EXOGENOUS:
            multiplier = _log_uniform(rng, *SPIKE_MULTIPLIER_RANGE)
            values = _series_values(rng, baseline_rate, multiplier, SERIES_POINTS - 1, noise_sigma)
            cases.append(TrialCase(
                index=start_index + offset, stratum=stratum, truth=TRUTH_EXOGENOUS,
                observed_at=observed_at, point_values=values, point_times=times,
                onset_at=times[-1], polls_since_onset=0, spike_multiplier=round(multiplier, 3),
            ))
        elif stratum == STRATUM_HEALTHY:
            values = _series_values(rng, baseline_rate, None, None, noise_sigma)
            cases.append(TrialCase(
                index=start_index + offset, stratum=stratum, truth=TRUTH_HEALTHY,
                observed_at=observed_at, point_values=values, point_times=times,
            ))
        else:
            values = _series_values(rng, baseline_rate, None, None, noise_sigma, points=1)
            cases.append(TrialCase(
                index=start_index + offset, stratum=stratum, truth=TRUTH_NO_DATA,
                observed_at=observed_at, point_values=values, point_times=(observed_at,),
            ))
    return cases


def build_corpus(
    commits: list[CommitRef],
    seed: int = DEFAULT_SEED,
    noise_sigma: float = DEFAULT_NOISE_SIGMA,
    regression_fresh: int = DEFAULT_REGRESSION_FRESH,
    regression_late: int = DEFAULT_REGRESSION_LATE,
    exogenous: int = DEFAULT_EXOGENOUS,
    healthy: int = DEFAULT_HEALTHY,
    sparse: int = DEFAULT_SPARSE,
) -> list[TrialCase]:
    """Build the whole labelled corpus from one seed, so a run reproduces exactly."""
    if len(commits) < 2:
        raise ValueError("a corpus needs at least two commits in the stream")
    span = (commits[0].committed_at, commits[-1].committed_at)

    cases: list[TrialCase] = []
    cases += _regression_cases(regression_fresh, commits, seed, STRATUM_FRESH, noise_sigma, len(cases))
    cases += _regression_cases(regression_late, commits, seed, STRATUM_LATE, noise_sigma, len(cases))
    cases += _uncaused_cases(exogenous, span, seed, STRATUM_EXOGENOUS, noise_sigma, len(cases))
    cases += _uncaused_cases(healthy, span, seed, STRATUM_HEALTHY, noise_sigma, len(cases))
    cases += _uncaused_cases(sparse, span, seed, STRATUM_SPARSE, noise_sigma, len(cases))
    return cases


# ------------------------------------------------------------------- Scoring


@dataclass(frozen=True)
class CaseVerdict:
    """One scored case: what the correlator said, and whether that was right."""

    index: int
    stratum: str
    truth: str
    verdict: str
    named_sha: str | None
    causing_sha: str | None
    outcome: str
    anomaly_factor: float
    #: How many commits the correlator had to choose between, and whether it said so.
    commits_in_window: int = 0
    ambiguity_disclosed: bool = False


def score_case(case: TrialCase, correlation) -> CaseVerdict:
    """Score one case against the truth its generator recorded.

    The truth is read from the case. Nothing in this function looks at the correlator's
    explanation, its provenance or its confidence: only the verdict and the commit it
    named, against what the generator knows happened.
    """
    verdict = correlation.verdict
    named = correlation.offending_commit.sha if correlation.offending_commit else None

    if case.truth == TRUTH_REGRESSION:
        if verdict is CorrelationVerdict.ANOMALY_ATTRIBUTED:
            outcome = HIT if named == case.causing_sha else WRONG_COMMIT
        elif verdict is CorrelationVerdict.ANOMALY_WITHOUT_ATTRIBUTION:
            outcome = REFUSED_ON_REGRESSION
        elif verdict in (CorrelationVerdict.NO_ANOMALY, CorrelationVerdict.INSUFFICIENT_DATA):
            outcome = MISSED_REGRESSION
        else:
            outcome = UNEXPECTED
    elif case.truth == TRUTH_EXOGENOUS:
        if verdict is CorrelationVerdict.ANOMALY_ATTRIBUTED:
            outcome = FALSE_ATTRIBUTION
        elif verdict is CorrelationVerdict.ANOMALY_WITHOUT_ATTRIBUTION:
            outcome = CORRECT_REFUSAL
        elif verdict in (CorrelationVerdict.NO_ANOMALY, CorrelationVerdict.INSUFFICIENT_DATA):
            outcome = MISSED_EXOGENOUS
        else:
            outcome = UNEXPECTED
    elif case.truth == TRUTH_HEALTHY:
        if verdict is CorrelationVerdict.ANOMALY_ATTRIBUTED:
            outcome = FALSE_ATTRIBUTION
        elif verdict is CorrelationVerdict.ANOMALY_WITHOUT_ATTRIBUTION:
            outcome = FALSE_ANOMALY
        elif verdict is CorrelationVerdict.NO_ANOMALY:
            outcome = CORRECT_QUIET
        else:
            outcome = UNEXPECTED
    else:
        outcome = CORRECT_NO_DATA if verdict is CorrelationVerdict.INSUFFICIENT_DATA else UNEXPECTED

    return CaseVerdict(
        index=case.index, stratum=case.stratum, truth=case.truth,
        verdict=verdict.value, named_sha=named, causing_sha=case.causing_sha,
        outcome=outcome, anomaly_factor=correlation.anomaly_factor,
        commits_in_window=correlation.commits_in_window,
        ambiguity_disclosed=correlation.attribution_is_ambiguous,
    )


def run_corpus(
    cases: list[TrialCase],
    commits: list[CommitRef],
    correlator: IncidentCorrelator | None = None,
) -> list[CaseVerdict]:
    """Put every case through the shipped correlator with its shipped defaults.

    ``correlator`` is injectable for one reason only: a test retunes it and asserts that
    the verdicts move while not one truth label does. Every published figure comes from
    the default.
    """
    correlator = correlator or IncidentCorrelator()
    provenance = Provenance(
        source=DataSource.LOCAL_GIT,
        detail=f"{len(commits)} commits recorded from this repository's git log.",
        observed_at_utc=datetime.now(timezone.utc).isoformat(),
    )
    return [
        score_case(case, correlator.correlate("corpus-service", case.to_series(), commits, provenance))
        for case in cases
    ]


def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def aggregate(cases: list[TrialCase], verdicts: list[CaseVerdict]) -> dict:
    """Turn scored cases into the figures the README quotes, plus the breakdown."""
    by_index = {case.index: case for case in cases}
    counts: dict[str, dict[str, int]] = {}
    for verdict in verdicts:
        counts.setdefault(verdict.stratum, {})
        counts[verdict.stratum][verdict.outcome] = counts[verdict.stratum].get(verdict.outcome, 0) + 1

    def stratum(name: str) -> list[CaseVerdict]:
        return [v for v in verdicts if v.stratum == name]

    fresh, late = stratum(STRATUM_FRESH), stratum(STRATUM_LATE)
    regressions = fresh + late
    exogenous, healthy, sparse = stratum(STRATUM_EXOGENOUS), stratum(STRATUM_HEALTHY), stratum(STRATUM_SPARSE)
    uncaused = exogenous + healthy

    hits = sum(1 for v in regressions if v.outcome == HIT)
    named = [v for v in verdicts if v.outcome in NAMED_A_COMMIT]
    false_attributions = sum(1 for v in uncaused if v.outcome == FALSE_ATTRIBUTION)
    wrong_commit = [v for v in regressions if v.outcome == WRONG_COMMIT]

    in_window = [v for v in regressions if by_index[v.index].cause_inside_attribution_window]
    in_window_fresh = [v for v in fresh if by_index[v.index].cause_inside_attribution_window]

    wrong_namings = [v for v in verdicts if v.outcome in (WRONG_COMMIT, FALSE_ATTRIBUTION)]
    disclosed_wrong = sum(1 for v in wrong_namings if v.ambiguity_disclosed)
    disclosed_hits = sum(1 for v in verdicts if v.outcome == HIT and v.ambiguity_disclosed)

    return {
        "cases": len(verdicts),
        "headline": {
            "hit_rate_all_regressions": _rate(hits, len(regressions)),
            "hit_rate_fresh_look": _rate(sum(1 for v in fresh if v.outcome == HIT), len(fresh)),
            "hit_rate_late_look": _rate(sum(1 for v in late if v.outcome == HIT), len(late)),
            "hit_rate_cause_inside_the_attribution_window": _rate(
                sum(1 for v in in_window if v.outcome == HIT), len(in_window)),
            "hit_rate_fresh_look_cause_inside_the_window": _rate(
                sum(1 for v in in_window_fresh if v.outcome == HIT), len(in_window_fresh)),
            "false_attribution_rate_on_uncaused_anomalies": _rate(false_attributions, len(uncaused)),
            "false_attribution_rate_on_exogenous_spikes": _rate(
                sum(1 for v in exogenous if v.outcome == FALSE_ATTRIBUTION), len(exogenous)),
            "correct_refusal_rate_on_exogenous_spikes": _rate(
                sum(1 for v in exogenous if v.outcome == CORRECT_REFUSAL), len(exogenous)),
            "quiet_rate_on_healthy_series": _rate(
                sum(1 for v in healthy if v.outcome == CORRECT_QUIET), len(healthy)),
            "refusal_rate_on_a_telemetry_gap": _rate(
                sum(1 for v in sparse if v.outcome == CORRECT_NO_DATA), len(sparse)),
            "naming_precision": _rate(hits, len(named)),
            "times_a_commit_was_named": len(named),
        },
        "counts_by_stratum": {
            name: {
                "cases": len(stratum(name)),
                "outcomes": dict(sorted(counts.get(name, {}).items(), key=lambda kv: -kv[1])),
            }
            for name in (STRATUM_FRESH, STRATUM_LATE, STRATUM_EXOGENOUS, STRATUM_HEALTHY, STRATUM_SPARSE)
        },
        # Cross-tabulated rather than counted one way, because two different things go
        # wrong and only one of them is the rule's fault. A cause outside the window is
        # unreachable for any rule with that window. A cause inside it that still got the
        # wrong name is the rule choosing badly between candidates it had.
        #
        # The field this replaced counted "a later commit landed before the reading",
        # which was 156 of 156 and meant nothing: the rule names the newest commit at or
        # before the reading, so a wrong name is a later commit by construction.
        "why_the_wrong_commit_was_named": {
            "wrong_commit_attributions": len(wrong_commit),
            "cause_inside_the_window_and_more_than_one_candidate": sum(
                1 for v in wrong_commit
                if by_index[v.index].cause_inside_attribution_window and v.commits_in_window > 1
            ),
            "cause_inside_the_window_with_a_single_candidate": sum(
                1 for v in wrong_commit
                if by_index[v.index].cause_inside_attribution_window and v.commits_in_window <= 1
            ),
            "cause_outside_the_attribution_window": sum(
                1 for v in wrong_commit if not by_index[v.index].cause_inside_attribution_window
            ),
            "of_which_the_answer_said_it_was_one_of_several": sum(
                1 for v in wrong_commit if v.ambiguity_disclosed
            ),
        },
        # Whether the answer told the operator it was one of several. The recall figure is
        # what the disclosure is for; the cost figure is how often it says so when the
        # named commit was in fact the right one, which is the price of saying it.
        "ambiguity_disclosure": {
            "wrong_namings": len(wrong_namings),
            "wrong_namings_disclosed_as_ambiguous": disclosed_wrong,
            "disclosure_recall_on_wrong_namings": _rate(disclosed_wrong, len(wrong_namings)),
            "correct_namings": hits,
            "correct_namings_also_flagged_ambiguous": disclosed_hits,
            "disclosure_cost_on_correct_namings": _rate(disclosed_hits, hits),
        },
        "regressions_whose_cause_was_inside_the_attribution_window": len(in_window),
        "unexpected_outcomes": sum(1 for v in verdicts if v.outcome == UNEXPECTED),
    }


def density_sweep(
    commits: list[CommitRef], strides: tuple[int, ...], seed: int, noise_sigma: float,
    exogenous: int, healthy: int,
) -> list[dict]:
    """Re-score the uncaused strata against thinner commit streams.

    Only the uncaused strata are swept: they are the ones whose figure is a joint property
    of the window and the stream. A regression's cause has to stay in the stream for the
    case to mean anything, so thinning it there would change the corpus rather than the
    density.
    """
    span = (commits[0].committed_at, commits[-1].committed_at)
    rows = []
    for stride in strides:
        thinned = thin(commits, stride)
        if len(thinned) < 2:
            continue
        cases = (
            _uncaused_cases(exogenous, span, seed, STRATUM_EXOGENOUS, noise_sigma, 0)
            + _uncaused_cases(healthy, span, seed, STRATUM_HEALTHY, noise_sigma, exogenous)
        )
        verdicts = run_corpus(cases, thinned)
        false_attributions = sum(1 for v in verdicts if v.outcome == FALSE_ATTRIBUTION)
        rows.append({
            "commit_stride": stride,
            "commits_in_stream": len(thinned),
            "commits_per_hour": commit_density_per_hour(thinned),
            "uncaused_cases": len(cases),
            "false_attributions": false_attributions,
            "false_attribution_rate": _rate(false_attributions, len(cases)),
        })
    return rows


# ---------------------------------------------------------------------- Report


def build_summary(args) -> dict:
    commits, recording = load_commit_stream()
    stream = thin(commits, args.commit_stride)
    cases = build_corpus(
        stream, seed=args.seed, noise_sigma=args.noise_sigma,
        regression_fresh=args.regression_fresh, regression_late=args.regression_late,
        exogenous=args.exogenous, healthy=args.healthy, sparse=args.sparse,
    )
    verdicts = run_corpus(cases, stream)
    summary = aggregate(cases, verdicts)
    summary.update({
        "measured_at_utc": datetime.now(timezone.utc).isoformat(),
        "measured_on": platform.platform(),
        "python_version": platform.python_version(),
        "measured_by_command": "python scripts/correlation_trial.py",
        "seed": args.seed,
        "noise_sigma": args.noise_sigma,
        "correlator": {
            "anomaly_factor": DEFAULT_ANOMALY_FACTOR,
            "attribution_window_minutes": DEFAULT_ATTRIBUTION_WINDOW_MINUTES,
            "series_points": SERIES_POINTS,
            "poll_cadence_minutes": POLL_CADENCE_MINUTES,
        },
        "commit_stream": {
            "recorded_at_head": recording.get("recorded_at_head"),
            "recorded_at_utc": recording.get("recorded_at_utc"),
            "commits_recorded": recording.get("commit_count"),
            "commit_stride": args.commit_stride,
            "commits_in_stream": len(stream),
            "commits_per_hour": commit_density_per_hour(stream),
            "span_start_utc": stream[0].committed_at.isoformat(),
            "span_end_utc": stream[-1].committed_at.isoformat(),
            "source": recording.get("source"),
        },
        "scope": (
            "A labelled corpus generated by scripts/correlation_trial.py and scored against "
            "the committed IncidentCorrelator with its shipped defaults. The commits are real "
            "development commits from this repository; the metric values are generated here "
            "and were never read from a monitored service. The reading times of every case "
            "with no cause are drawn over the span of the commit log without reference to "
            "where any commit falls."
        ),
        "density_sweep": density_sweep(
            commits, tuple(args.sweep), args.seed, args.noise_sigma, args.exogenous, args.healthy,
        ),
    })
    return summary


def print_report(summary: dict) -> None:
    head = summary["headline"]
    stream = summary["commit_stream"]
    print(f"Scored {summary['cases']} labelled cases against IncidentCorrelator "
          f"({summary['correlator']['anomaly_factor']}x threshold, "
          f"{summary['correlator']['attribution_window_minutes']} minute window), seed {summary['seed']}")
    print(f"  commit stream: {stream['commits_in_stream']} real commits, "
          f"{stream['commits_per_hour']} per hour, recorded at {stream['recorded_at_head']}")
    print(f"  hit rate, all regressions:            {head['hit_rate_all_regressions']}")
    print(f"    on a fresh look:                    {head['hit_rate_fresh_look']}")
    print(f"    on a late look:                     {head['hit_rate_late_look']}")
    print(f"    cause inside the 60 minute window:  {head['hit_rate_cause_inside_the_attribution_window']}")
    print(f"  false attribution on uncaused anomalies: {head['false_attribution_rate_on_uncaused_anomalies']}")
    print(f"    on exogenous spikes alone:          {head['false_attribution_rate_on_exogenous_spikes']}")
    print(f"  correct refusal on exogenous spikes:  {head['correct_refusal_rate_on_exogenous_spikes']}")
    print(f"  quiet on healthy series:              {head['quiet_rate_on_healthy_series']}")
    print(f"  refused for want of data:             {head['refusal_rate_on_a_telemetry_gap']}")
    print(f"  naming precision (right commit when it named one): {head['naming_precision']} "
          f"over {head['times_a_commit_was_named']} namings")
    disclosure = summary["ambiguity_disclosure"]
    print(f"  of the {disclosure['wrong_namings']} namings that were wrong, "
          f"{disclosure['wrong_namings_disclosed_as_ambiguous']} were shown as one of several "
          f"({disclosure['disclosure_recall_on_wrong_namings']}); "
          f"{disclosure['correct_namings_also_flagged_ambiguous']} of "
          f"{disclosure['correct_namings']} correct ones were shown that way too "
          f"({disclosure['disclosure_cost_on_correct_namings']})")
    print("  outcomes by stratum:")
    for name, block in summary["counts_by_stratum"].items():
        print(f"    {name} ({block['cases']} cases)")
        for outcome, count in block["outcomes"].items():
            print(f"      {count:>5}  {outcome}")
    print("  density sweep on the uncaused strata:")
    for row in summary["density_sweep"]:
        print(f"    stride {row['commit_stride']}: {row['commits_in_stream']:>3} commits, "
              f"{row['commits_per_hour']:>6} per hour -> false attribution rate "
              f"{row['false_attribution_rate']}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Score the incident correlator against a labelled corpus.")
    parser.add_argument("--record", action="store_true", help="re-record the commit stream from git log")
    parser.add_argument("--json", action="store_true", help="print the summary as JSON")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--noise-sigma", type=float, default=DEFAULT_NOISE_SIGMA)
    parser.add_argument("--commit-stride", type=int, default=1,
                        help="keep every k-th commit, to vary the density of the deployment stream")
    parser.add_argument("--sweep", type=int, nargs="+", default=[1, 2, 4, 8],
                        help="commit strides to sweep the false-attribution rate over")
    parser.add_argument("--regression-fresh", type=int, default=DEFAULT_REGRESSION_FRESH)
    parser.add_argument("--regression-late", type=int, default=DEFAULT_REGRESSION_LATE)
    parser.add_argument("--exogenous", type=int, default=DEFAULT_EXOGENOUS)
    parser.add_argument("--healthy", type=int, default=DEFAULT_HEALTHY)
    parser.add_argument("--sparse", type=int, default=DEFAULT_SPARSE)
    parser.add_argument("--no-write", action="store_true", help="do not write the summary file")
    parser.add_argument("--check", action="store_true",
                        help="re-score and compare against the recorded summary without writing it")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    if args.record:
        payload = record_commit_stream()
        print(f"recorded {payload['commit_count']} commits from git log at "
              f"{payload['recorded_at_head']} into {COMMIT_STREAM_PATH.relative_to(REPO_ROOT)}")
        return 0

    summary = build_summary(args)

    if args.check:
        # The README quotes the recorded file, and a test compares those two. This
        # is the third side of that triangle: it proves the recorded file is still
        # what the committed code produces, the way the coverage recorder does.
        if not SUMMARY_PATH.exists():
            print(f"{SUMMARY_PATH.name} does not exist; run the trial without --check first")
            return 1
        recorded = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
        drifted = {
            key: (recorded["headline"].get(key), value)
            for key, value in summary["headline"].items()
            if recorded["headline"].get(key) != value
        }
        if drifted:
            print("the recorded correlation trial no longer matches a fresh run:")
            for key, (was, now) in drifted.items():
                print(f"  {key}: recorded {was}, this run {now}")
            return 1
        print(f"{SUMMARY_PATH.name} matches a fresh run of the trial on all "
              f"{len(summary['headline'])} published figures")
        return 0

    if not args.no_write:
        SUMMARY_PATH.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print_report(summary)
        if not args.no_write:
            print(f"  written to {SUMMARY_PATH.name}")

    # An unexpected outcome means a verdict the scorer does not know how to judge, which
    # would make every figure above unsafe to quote.
    return 1 if summary["unexpected_outcomes"] else 0


if __name__ == "__main__":
    raise SystemExit(main())


# ``asdict`` is used by the tests to serialise a case for comparison.
__all__ = [
    "TrialCase", "CaseVerdict", "build_corpus", "run_corpus", "score_case", "aggregate",
    "load_commit_stream", "record_commit_stream", "thin", "asdict",
]
