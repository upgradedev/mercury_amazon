"""The correlation trial has to be a measurement, not a demonstration.

A corpus that was built to be got right proves nothing, so these tests hold the trial to
the properties that make its published figures mean something:

* the corpus is a function of its seed alone, so a run reproduces;
* the reading times of every case with no cause are drawn without reference to the commit
  log, which is the whole difference between this and the cockpit's demo fixture;
* the truth labels come from the generator and never from the correlator, so retuning the
  correlator moves the verdicts and not one label;
* the scorer counts a right verdict on the wrong commit as a false attribution rather than
  as a hit, and it recognises each of the three refusals as correct where they are correct;
* the README quotes the summary the committed script actually wrote.

Two tests here run the detector this repository shipped until 2026-09-08, whose baseline
contained the spike, so the before half of the README's before-and-after is a run of
committed code rather than a memory of one. That mode is still selectable for exactly
that reason, and the test that shows it swallowing a tenfold regression sits next to the
test that shows the current detector catching the identical series.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

import correlation_trial as trial  # noqa: E402

from src.domain.incident_correlation import (  # noqa: E402
    AttributionRefusal,
    BaselineMode,
    CommitRef,
    CorrelationVerdict,
    IncidentCorrelator,
    MetricPoint,
    MetricSeries,
    WindowAnchor,
)

SUMMARY_PATH = REPO_ROOT / "correlation_trial_summary.json"
README = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
#: Where the trial's figures and their history are published in full.
EVIDENCE = (REPO_ROOT / "docs" / "EVIDENCE.md").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def commits() -> list[CommitRef]:
    stream, _ = trial.load_commit_stream()
    return stream


@pytest.fixture(scope="module")
def scored(commits):
    """The default corpus, scored once. Small enough to run in the unit suite."""
    cases = trial.build_corpus(commits, regression_fresh=40, regression_late=40,
                               exogenous=40, healthy=30, sparse=10)
    return cases, trial.run_corpus(cases, commits)


# ------------------------------------------------------------ The commit stream


def test_the_commit_stream_is_a_recording_that_says_where_it_came_from():
    payload = json.loads(trial.COMMIT_STREAM_PATH.read_text(encoding="utf-8"))
    assert payload["commit_count"] == len(payload["commits"]) >= 2
    assert payload["recorded_by"] == "python scripts/correlation_trial.py --record"
    assert "git log" in payload["source"]
    assert re.fullmatch(r"[0-9a-f]{7,40}", payload["recorded_at_head"])


def test_the_recorded_commits_are_real_commits_in_this_repository():
    """The corpus claims real commits. Ask git whether they exist.

    Skipped where there is no checkout to ask, which is the case in a source tarball.
    """
    if not (REPO_ROOT / ".git").exists():
        pytest.skip("no git checkout to verify the recorded commits against")
    payload = json.loads(trial.COMMIT_STREAM_PATH.read_text(encoding="utf-8"))
    sample = payload["commits"][:5] + payload["commits"][-5:]
    for entry in sample:
        result = subprocess.run(
            ["git", "cat-file", "-e", f"{entry['sha']}^{{commit}}"],
            cwd=str(REPO_ROOT), capture_output=True, timeout=10,
        )
        assert result.returncode == 0, f"{entry['sha']} is not a commit in this repository"


def test_thinning_keeps_every_kth_commit(commits):
    assert trial.thin(commits, 1) == commits
    assert trial.thin(commits, 2) == commits[::2]
    assert len(trial.thin(commits, 4)) == len(commits[::4])
    with pytest.raises(ValueError):
        trial.thin(commits, 0)


# ----------------------------------------------------------------- The corpus


def test_the_corpus_is_reproducible_from_its_seed(commits):
    first = trial.build_corpus(commits, seed=99, regression_fresh=20, regression_late=20,
                               exogenous=20, healthy=10, sparse=5)
    second = trial.build_corpus(commits, seed=99, regression_fresh=20, regression_late=20,
                                exogenous=20, healthy=10, sparse=5)
    assert [trial.asdict(c) for c in first] == [trial.asdict(c) for c in second]


def test_a_different_seed_produces_a_different_corpus(commits):
    first = trial.build_corpus(commits, seed=1, regression_fresh=20, regression_late=0,
                               exogenous=0, healthy=0, sparse=0)
    second = trial.build_corpus(commits, seed=2, regression_fresh=20, regression_late=0,
                                exogenous=0, healthy=0, sparse=0)
    assert [c.point_values for c in first] != [c.point_values for c in second]


def test_the_reading_times_of_uncaused_cases_ignore_where_the_commits_fall(commits):
    """The claim the trial rests on, checked rather than asserted in prose.

    The same span, a completely different arrangement of commits inside it. If any reading
    time in a stratum with no cause moved, the generator would be peeking at the commit log
    and the false-attribution rate would be a number about the corpus rather than about the
    correlator.
    """
    span = (commits[0].committed_at, commits[-1].committed_at)
    scrambled = [commits[0]] + [
        CommitRef(sha=c.sha, message=c.message, author=c.author,
                  committed_at=span[0] + timedelta(minutes=17 * index))
        for index, c in enumerate(commits[1:-1], start=1)
    ] + [commits[-1]]

    original = trial.build_corpus(commits, regression_fresh=0, regression_late=0,
                                  exogenous=50, healthy=50, sparse=20)
    against_scrambled = trial.build_corpus(scrambled, regression_fresh=0, regression_late=0,
                                           exogenous=50, healthy=50, sparse=20)

    assert [c.observed_at for c in original] == [c.observed_at for c in against_scrambled]
    assert [c.point_values for c in original] == [c.point_values for c in against_scrambled]
    assert all(c.causing_sha is None for c in original)


def test_every_regression_case_records_the_commit_that_caused_it(commits):
    cases = trial.build_corpus(commits, regression_fresh=30, regression_late=30,
                               exogenous=0, healthy=0, sparse=0)
    known = {c.sha for c in commits}
    assert cases, "no regression cases were generated"
    for case in cases:
        assert case.causing_sha in known
        assert case.truth == trial.TRUTH_REGRESSION
        assert case.onset_at is not None and case.onset_at <= case.observed_at


def test_the_late_look_stratum_really_does_look_later(commits):
    fresh = trial.build_corpus(commits, regression_fresh=40, regression_late=0,
                               exogenous=0, healthy=0, sparse=0)
    late = trial.build_corpus(commits, regression_fresh=0, regression_late=40,
                              exogenous=0, healthy=0, sparse=0)
    assert {c.polls_since_onset for c in fresh} == {0}
    assert {c.polls_since_onset for c in late} <= set(range(1, 5))
    assert min(c.polls_since_onset for c in late) >= 1


# ----------------------------------------------------------------- The scoring


def test_the_truth_labels_do_not_move_when_the_correlator_is_retuned(commits):
    """Ground truth comes from the generator. Retuning the correlator must not touch it."""
    cases = trial.build_corpus(commits, regression_fresh=40, regression_late=40,
                               exogenous=40, healthy=20, sparse=5)
    shipped = trial.run_corpus(cases, commits)
    retuned = trial.run_corpus(cases, commits, IncidentCorrelator(anomaly_factor=1.05))

    assert [v.truth for v in shipped] == [v.truth for v in retuned]
    assert [v.causing_sha for v in shipped] == [v.causing_sha for v in retuned]
    assert [v.verdict for v in shipped] != [v.verdict for v in retuned], (
        "a correlator that calls almost everything an anomaly reached the same verdicts, "
        "so this test is not exercising what it claims to"
    )


def _correlation(values, commits, minutes_between=10, correlator=None):
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    points = [
        MetricPoint(at=now - timedelta(minutes=minutes_between * (len(values) - 1 - i)), value=v)
        for i, v in enumerate(values)
    ]
    series = MetricSeries("HTTPCode_Target_5XX_Count", "AWS/ApplicationELB", points)
    return now, (correlator or IncidentCorrelator()).correlate("svc", series, commits)


#: The correlator without its crowding gate, which is what it was before 2026-09-08.
#: The scorer has to keep telling a wrong name apart from a right one, and after the gate
#: the shipped settings refuse a crowded window instead of naming anything, so the tests
#: that exercise the naming path build this one explicitly rather than by accident.
def _ungated() -> IncidentCorrelator:
    return IncidentCorrelator(max_commits_in_window=None)


def test_a_right_verdict_on_the_wrong_commit_is_a_false_attribution_not_a_hit():
    """The failure this scorer exists to catch: the correct verdict, the wrong name."""
    now, _ = _correlation([1.0], [])
    innocent = CommitRef("bbbbbbb", "unrelated", "someone", now - timedelta(minutes=5))
    culprit = CommitRef("aaaaaaa", "the one that did it", "someone", now - timedelta(minutes=40))
    _, correlation = _correlation([3, 3, 3, 3, 3, 40], [culprit, innocent], correlator=_ungated())

    case = trial.TrialCase(
        index=0, stratum=trial.STRATUM_FRESH, truth=trial.TRUTH_REGRESSION,
        observed_at=now, point_values=(3, 3, 3, 3, 3, 40), point_times=(),
        causing_sha="aaaaaaa",
    )
    verdict = trial.score_case(case, correlation)

    assert correlation.verdict is CorrelationVerdict.ANOMALY_ATTRIBUTED
    assert verdict.named_sha == "bbbbbbb"
    assert verdict.outcome == trial.WRONG_COMMIT
    assert verdict.outcome != trial.HIT


def test_naming_the_commit_that_caused_it_is_a_hit():
    now, _ = _correlation([1.0], [])
    culprit = CommitRef("aaaaaaa", "the one that did it", "someone", now - timedelta(minutes=6))
    _, correlation = _correlation([3, 3, 3, 3, 3, 40], [culprit])
    case = trial.TrialCase(
        index=0, stratum=trial.STRATUM_FRESH, truth=trial.TRUTH_REGRESSION,
        observed_at=now, point_values=(), point_times=(), causing_sha="aaaaaaa",
    )
    assert trial.score_case(case, correlation).outcome == trial.HIT


def test_the_scorer_credits_each_of_the_three_refusals():
    """Negative cases: the verdicts where a correct answer is a refusal."""
    now, _ = _correlation([1.0], [])
    far_away = CommitRef("ccccccc", "hours earlier", "someone", now - timedelta(hours=9))

    _, exogenous = _correlation([3, 3, 3, 3, 3, 40], [far_away])
    case = trial.TrialCase(index=1, stratum=trial.STRATUM_EXOGENOUS, truth=trial.TRUTH_EXOGENOUS,
                           observed_at=now, point_values=(), point_times=())
    assert exogenous.verdict is CorrelationVerdict.ANOMALY_WITHOUT_ATTRIBUTION
    assert trial.score_case(case, exogenous).outcome == trial.CORRECT_REFUSAL

    _, healthy = _correlation([3, 3.1, 2.9, 3, 3.2, 3.1], [far_away])
    case = trial.TrialCase(index=2, stratum=trial.STRATUM_HEALTHY, truth=trial.TRUTH_HEALTHY,
                           observed_at=now, point_values=(), point_times=())
    assert trial.score_case(case, healthy).outcome == trial.CORRECT_QUIET

    _, sparse = _correlation([3], [far_away])
    case = trial.TrialCase(index=3, stratum=trial.STRATUM_SPARSE, truth=trial.TRUTH_NO_DATA,
                           observed_at=now, point_values=(), point_times=())
    assert sparse.verdict is CorrelationVerdict.INSUFFICIENT_DATA
    assert trial.score_case(case, sparse).outcome == trial.CORRECT_NO_DATA


def test_blaming_a_commit_for_an_anomaly_nothing_caused_is_a_false_attribution():
    now, _ = _correlation([1.0], [])
    bystander = CommitRef("ddddddd", "landed nearby", "someone", now - timedelta(minutes=12))
    _, correlation = _correlation([3, 3, 3, 3, 3, 40], [bystander])
    case = trial.TrialCase(index=4, stratum=trial.STRATUM_EXOGENOUS, truth=trial.TRUTH_EXOGENOUS,
                           observed_at=now, point_values=(), point_times=())
    assert trial.score_case(case, correlation).outcome == trial.FALSE_ATTRIBUTION


def test_the_trailing_baseline_still_swallows_a_spike_running_for_three_polls():
    """The before state, kept runnable rather than remembered.

    ``MetricSeries.baseline_mean`` drops only the newest point, so by the third poll after
    onset the spike is most of its own baseline and the factor falls under the threshold.
    A tenfold regression then reads as healthy. That was the shipped detector until
    2026-09-08 and it is the defect the late-look stratum measured at a 3.3% hit rate. The
    mode is still selectable, so the README's before-and-after is two runs of committed
    code rather than a memory of one.
    """
    now, _ = _correlation([1.0], [])
    culprit = CommitRef("eeeeeee", "the one that did it", "someone", now - timedelta(minutes=35))
    trailing = IncidentCorrelator(
        baseline_mode=BaselineMode.TRAILING,
        window_anchor=WindowAnchor.READING,
        max_commits_in_window=None,
    )

    _, fresh = _correlation([3, 3, 3, 3, 3, 30], [culprit], correlator=trailing)
    _, third_poll = _correlation([3, 3, 3, 30, 30, 30], [culprit], correlator=trailing)

    assert fresh.verdict is CorrelationVerdict.ANOMALY_ATTRIBUTED
    assert fresh.anomaly_factor == pytest.approx(10.0, abs=0.01)
    assert third_poll.verdict is CorrelationVerdict.NO_ANOMALY
    assert third_poll.anomaly_factor < 3.0


def test_the_pre_onset_baseline_sees_the_same_spike_the_trailing_one_swallowed():
    """The after state, on the identical series the test above calls healthy."""
    now, _ = _correlation([1.0], [])
    culprit = CommitRef("eeeeeee", "the one that did it", "someone", now - timedelta(minutes=35))

    _, third_poll = _correlation([3, 3, 3, 30, 30, 30], [culprit])

    assert third_poll.verdict is CorrelationVerdict.ANOMALY_ATTRIBUTED
    assert third_poll.anomaly_factor == pytest.approx(10.0, abs=0.01)
    # The baseline is the three readings before the onset, not the five before the newest.
    assert third_poll.baseline_points == 3
    assert third_poll.onset_at == now - timedelta(minutes=20)
    # And the window ends at the onset, so a commit 35 minutes before the reading is 15
    # minutes before the onset and still reachable.
    assert third_poll.offending_commit.sha == "eeeeeee"


def test_a_crowded_window_is_refused_rather_than_named():
    """The gate that carries the naming precision, and the case where it lets one through."""
    now, _ = _correlation([1.0], [])
    burst = [
        CommitRef("1111111", "first of a burst", "someone", now - timedelta(minutes=40)),
        CommitRef("2222222", "second of a burst", "someone", now - timedelta(minutes=38)),
        CommitRef("3333333", "third of a burst", "someone", now - timedelta(minutes=36)),
    ]
    _, crowded = _correlation([3, 3, 3, 3, 3, 40], burst)
    assert crowded.verdict is CorrelationVerdict.ANOMALY_WITHOUT_ATTRIBUTION
    assert crowded.attribution_refusal is AttributionRefusal.WINDOW_TOO_CROWDED
    assert crowded.commits_in_window == 3
    assert crowded.offending_commit is None
    assert crowded.rollback_is_available is False
    assert "3 changes landed" in crowded.explanation
    assert "cannot attribute it to any one of them" in crowded.to_voice_summary()
    assert "rolling back on this answer would be a guess" in crowded.to_voice_summary()

    _, single = _correlation([3, 3, 3, 3, 3, 40], [burst[0]])
    assert single.verdict is CorrelationVerdict.ANOMALY_ATTRIBUTED
    assert single.commits_in_window == 1
    assert single.attribution_is_ambiguous is False
    assert single.attribution_refusal is None


def test_the_two_refusals_are_told_apart_rather_than_pooled():
    """A crowded window and an empty one are different claims, and score differently."""
    now, _ = _correlation([1.0], [])
    burst = [
        CommitRef("1111111", "first", "someone", now - timedelta(minutes=40)),
        CommitRef("2222222", "second", "someone", now - timedelta(minutes=38)),
    ]
    far_away = CommitRef("ccccccc", "hours earlier", "someone", now - timedelta(hours=9))

    _, crowded = _correlation([3, 3, 3, 3, 3, 40], burst)
    _, empty = _correlation([3, 3, 3, 3, 3, 40], [far_away])
    assert empty.attribution_refusal is AttributionRefusal.NO_CANDIDATE_IN_WINDOW

    case = trial.TrialCase(index=0, stratum=trial.STRATUM_EXOGENOUS, truth=trial.TRUTH_EXOGENOUS,
                           observed_at=now, point_values=(), point_times=())
    assert trial.score_case(case, crowded).outcome == trial.CORRECT_REFUSAL_CROWDED
    assert trial.score_case(case, empty).outcome == trial.CORRECT_REFUSAL

    regression = trial.TrialCase(index=1, stratum=trial.STRATUM_FRESH, truth=trial.TRUTH_REGRESSION,
                                 observed_at=now, point_values=(), point_times=(),
                                 causing_sha="1111111")
    assert trial.score_case(regression, crowded).outcome == trial.REFUSED_CROWDED_ON_REGRESSION
    assert trial.score_case(regression, empty).outcome == trial.REFUSED_ON_REGRESSION


def test_the_answer_says_when_the_named_commit_was_one_of_several():
    """The disclosure is still there for anyone who turns the crowding gate off."""
    now, _ = _correlation([1.0], [])
    burst = [
        CommitRef("1111111", "first of a burst", "someone", now - timedelta(minutes=40)),
        CommitRef("2222222", "second of a burst", "someone", now - timedelta(minutes=38)),
        CommitRef("3333333", "third of a burst", "someone", now - timedelta(minutes=36)),
    ]
    _, ambiguous = _correlation([3, 3, 3, 3, 3, 40], burst, correlator=_ungated())
    assert ambiguous.commits_in_window == 3
    assert ambiguous.attribution_is_ambiguous is True
    assert "3 changes landed inside that window" in ambiguous.explanation
    assert "may not be the one that did it" in ambiguous.to_voice_summary()

    _, single = _correlation([3, 3, 3, 3, 3, 40], [burst[0]], correlator=_ungated())
    assert single.commits_in_window == 1
    assert single.attribution_is_ambiguous is False
    assert "changes landed inside that window" not in single.explanation


def test_a_verdict_that_names_nobody_reports_no_candidates():
    now, _ = _correlation([1.0], [])
    far_away = CommitRef("fffffff", "hours earlier", "someone", now - timedelta(hours=9))
    _, unattributed = _correlation([3, 3, 3, 3, 3, 40], [far_away])
    _, quiet = _correlation([3, 3, 3, 3, 3, 3.1], [far_away])
    assert unattributed.commits_in_window == 0
    assert unattributed.attribution_is_ambiguous is False
    assert quiet.commits_in_window == 0


# ------------------------------------------------- The choice of the crowding gate


def test_the_crowding_gate_holds_up_on_corpora_it_was_not_chosen_on(commits):
    """The gate was picked from a sweep on one seed. This is the out-of-sample check.

    Choosing a threshold on the corpus it is then reported on is fitting, and a
    precision figure chosen that way is worth less than it looks. These seeds took no
    part in the choice. The claim under test is the direction, not a number: refusing a
    crowded window has to buy precision on a corpus nobody tuned against, and it has to
    buy it by naming less rather than by naming better, which is why the namings count
    is asserted to fall as well.
    """
    for seed in (19850717, 20261231):
        cases = trial.build_corpus(commits, seed=seed)
        gated = trial.aggregate(cases, trial.run_corpus(cases, commits))["headline"]
        ungated = trial.aggregate(
            cases, trial.run_corpus(cases, commits, _ungated()))["headline"]

        assert gated["naming_precision"] > ungated["naming_precision"], (
            f"seed {seed}: the gate did not improve precision "
            f"({gated['naming_precision']} against {ungated['naming_precision']})"
        )
        assert gated["times_a_commit_was_named"] < ungated["times_a_commit_was_named"]
        assert gated["naming_recall_on_regressions"] < ungated["naming_recall_on_regressions"], (
            "the gate bought precision without costing recall, which would mean it is not "
            "refusing anything and this test is measuring nothing"
        )
        assert gated["times_a_commit_was_named"] > 50, (
            f"seed {seed}: only {gated['times_a_commit_was_named']} namings, too few to carry "
            "a precision claim"
        )


def test_the_sweep_the_gate_was_chosen_from_is_published(commits):
    """The choice has to be legible: every setting considered, with what it cost."""
    summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    sweep = summary["crowding_gate_sweep"]
    gates = [row["names_when_candidates_at_most"] for row in sweep]
    assert None in gates, "the sweep does not include the ungated setting it is measured against"
    assert summary["correlator"]["max_commits_in_window"] in gates, (
        "the shipped setting is not one of the rows in its own sweep"
    )
    for row in sweep:
        assert row["times_a_commit_was_named"] > 0
        assert row["naming_precision"] is not None
        assert row["naming_recall_on_regressions"] is not None


def test_the_detectability_ceiling_is_arithmetic_on_the_corpus_not_a_claim(commits):
    """A six point series cannot show a spike that started five polls ago.

    The pre-onset baseline needs at least two readings before the onset, and a look four
    polls late leaves one. Those cases are unreachable whatever the detector does, so the
    hit rate has to be read against the ceiling rather than against 100%. This recomputes
    the ceiling from the cases' own timestamps.
    """
    cases = trial.build_corpus(commits)
    ceiling = trial.detectability_ceiling(cases, 2)
    regressions = [c for c in cases if c.truth == trial.TRUTH_REGRESSION]
    unreachable = [c for c in regressions if (c.pre_onset_points or 0) < 2]

    assert ceiling["regressions"] == len(regressions)
    assert ceiling["too_few_readings_before_the_onset"] == len(unreachable)
    assert ceiling["by_stratum"][trial.STRATUM_FRESH]["too_few_readings_before_the_onset"] == 0, (
        "a fresh look always has five readings before the onset, so none can be out of reach"
    )
    assert ceiling["by_stratum"][trial.STRATUM_LATE]["too_few_readings_before_the_onset"] > 0
    # Every unreachable case is a late look four polls after the onset, by construction.
    assert all(c.polls_since_onset == 4 for c in unreachable)

    verdicts = trial.run_corpus(cases, commits)
    head = trial.aggregate(cases, verdicts)["headline"]
    assert head["hit_rate_all_regressions"] <= ceiling["ceiling_on_hit_rate"]


def test_a_crowded_refusal_is_never_counted_as_a_correct_refusal_for_the_right_reason(scored):
    """The two refusals must not be pooled into one flattering figure."""
    cases, verdicts = scored
    summary = trial.aggregate(cases, verdicts)
    head, why = summary["headline"], summary["why_it_named_nobody"]

    combined = head["correct_refusal_rate_on_exogenous_spikes"]
    empty = head["correct_refusal_on_exogenous_spikes_no_candidate"]
    crowded = head["correct_refusal_on_exogenous_spikes_window_too_crowded"]
    assert combined == pytest.approx(empty + crowded, abs=0.0005), (
        "the published refusal rate is not the sum of its two reasons"
    )
    assert why["window_too_crowded"] == sum(
        1 for v in verdicts if v.refusal == "WINDOW_TOO_CROWDED")
    assert why["no_candidate_in_window"] == sum(
        1 for v in verdicts if v.refusal == "NO_CANDIDATE_IN_WINDOW")


# --------------------------------------------------------------- The aggregate


def test_no_case_in_the_corpus_scores_as_unexpected(scored):
    cases, verdicts = scored
    summary = trial.aggregate(cases, verdicts)
    assert summary["unexpected_outcomes"] == 0
    assert summary["cases"] == len(cases)


def test_the_rates_are_computed_over_the_right_denominators(scored):
    cases, verdicts = scored
    summary = trial.aggregate(cases, verdicts)
    head = summary["headline"]
    named = [v for v in verdicts if v.outcome in trial.NAMED_A_COMMIT]
    hits = [v for v in verdicts if v.outcome == trial.HIT]

    assert head["times_a_commit_was_named"] == len(named)
    assert head["naming_precision"] == pytest.approx(len(hits) / len(named), abs=1e-4)
    for rate in (head["hit_rate_fresh_look"], head["hit_rate_late_look"],
                 head["false_attribution_rate_on_uncaused_anomalies"]):
        assert 0.0 <= rate <= 1.0


def test_a_reachable_cause_is_only_missed_when_the_window_held_several_changes(scored):
    """The finding the ambiguity disclosure was actually added for.

    An earlier version of this test asserted that a later commit landed between the cause
    and the reading, which is true of every wrong attribution by construction: the rule
    names the newest commit at or before the reading, so a wrong name is a later commit.
    It looked like a finding and was arithmetic, and the README quoted it as one.

    The real property is this: when the cause was inside the attribution window, so the
    rule could have named it, every miss was a window holding more than one change. A
    wrong name with the cause in the window and a single candidate would mean the rule
    fails for some other reason, which nothing here would explain.
    """
    cases, verdicts = scored
    block = trial.aggregate(cases, verdicts)["why_the_wrong_commit_was_named"]

    assert block["cause_inside_the_window_with_a_single_candidate"] == 0
    assert (
        block["cause_inside_the_window_and_more_than_one_candidate"]
        + block["cause_outside_the_attribution_window"]
        == block["wrong_commit_attributions"]
    )
    assert block["of_which_the_answer_said_it_was_one_of_several"] >= (
        block["cause_inside_the_window_and_more_than_one_candidate"]
    ), "the disclosure must cover at least the cases it was added for"


def test_the_readme_quotes_the_recorded_split_of_the_wrong_names():
    """The claim about what still goes wrong, pinned to the file rather than to memory.

    The split moved when the crowding gate landed. Wrong names used to be dominated by
    "the cause was inside the window and it picked a different change from that same
    window"; those are refused now, so that count is zero, and what is left is almost
    entirely causes that fell outside the window, which no rule with this window could
    have reached. The residual, the cases where the rule had the culprit alone in front
    of it and still named the wrong thing, is published rather than rounded away.
    """
    block = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))["why_the_wrong_commit_was_named"]
    section = EVIDENCE.split("## How often it is right")[1].split("\n## ")[0]

    assert f"the {block['wrong_commit_attributions']} attributions that" in section
    assert f"**{block['cause_outside_the_attribution_window']}** had the real cause" in section
    assert f"**{block['cause_inside_the_window_and_more_than_one_candidate']}** had the cause" in section
    assert block["cause_inside_the_window_and_more_than_one_candidate"] == 0, (
        "the gate is letting a crowded window through, so the README's claim is now false"
    )
    assert f"**{block['cause_inside_the_window_with_a_single_candidate']}** had the cause inside" in section, (
        "the README no longer publishes the residual: the cases where the rule had the "
        "culprit alone in front of it and still named the wrong thing"
    )


def test_the_readme_burstiness_figures_come_from_the_recorded_stream():
    """The explanation for the wrong names quotes the shape of the commit stream.

    Those four figures are the reason the split above is what it is, so they are held to
    the recording rather than to a shell one-liner nobody committed.
    """
    burst = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))["commit_stream"]["burstiness"]
    # Normalised, because any of these can be split across a line wrap.
    section = " ".join(EVIDENCE.split("## How often it is right")[1].split("\n## ")[0].split())

    assert f"is {burst['median_gap_minutes']} minutes" in section
    assert f"{burst['gaps_under_the_attribution_window']} of its {burst['gaps']} gaps" in section
    assert f"{burst['mean_commits_in_a_window_ending_at_a_commit']} commits on average" in section
    assert f"and {burst['max_commits_in_a_window_ending_at_a_commit']} at the worst" in section


# ------------------------------------------------------------------ The README


def test_the_recorded_summary_still_matches_a_fresh_run():
    """The third side of the triangle: README to file, file to a re-run.

    A test comparing the README to a recorded file only proves they agree with each
    other. This re-scores the corpus with the committed correlator and fails if the
    recorded figures are stale, which is what happens the day the detector changes and
    the README does not. The same command runs in CI.
    """
    result = subprocess.run(
        [sys.executable, "scripts/correlation_trial.py", "--check"],
        capture_output=True, text=True, cwd=str(REPO_ROOT), timeout=300,
    )
    assert result.returncode == 0, (
        f"the recorded correlation trial no longer matches a fresh run:\n{result.stdout[-1500:]}"
    )


def test_the_check_mode_fails_when_the_figures_move():
    """A check that cannot fail is not a check. Move the corpus and watch it refuse."""
    result = subprocess.run(
        [sys.executable, "scripts/correlation_trial.py", "--check", "--seed", "7"],
        capture_output=True, text=True, cwd=str(REPO_ROOT), timeout=300,
    )
    assert result.returncode == 1
    assert "no longer matches a fresh run" in result.stdout


def test_the_summary_file_was_written_by_the_committed_command():
    summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    assert summary["measured_by_command"] == "python scripts/correlation_trial.py"
    assert summary["correlator"]["anomaly_factor"] == 3.0
    assert summary["correlator"]["attribution_window_minutes"] == 60
    assert summary["unexpected_outcomes"] == 0


def test_the_readme_quotes_the_recorded_correlation_trial():
    """Same pin as the coverage and legibility numbers: prose against the recording."""
    summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    head = summary["headline"]

    def quoted(label: str) -> float:
        match = re.search(rf"\| {re.escape(label)} \| \*\*([\d.]+)%?\*\*", EVIDENCE)
        assert match, f"the README no longer quotes {label!r} from the correlation trial"
        return float(match.group(1))

    assert quoted("Hit rate, fresh look") == round(head["hit_rate_fresh_look"] * 100, 1)
    assert quoted("Hit rate, late look") == round(head["hit_rate_late_look"] * 100, 1)
    assert quoted("False attribution, exogenous spikes") == round(
        head["false_attribution_rate_on_exogenous_spikes"] * 100, 1)
    assert quoted("Correct refusal, exogenous spikes") == round(
        head["correct_refusal_rate_on_exogenous_spikes"] * 100, 1)

    for name, text in (("README.md", README), ("docs/EVIDENCE.md", EVIDENCE)):
        cases = re.search(r"(\d+) labelled cases", text)
        assert cases and int(cases.group(1)) == summary["cases"], (
            f"{name} quotes {cases.group(1) if cases else 'no'} cases, the recorded run scored "
            f"{summary['cases']}"
        )
