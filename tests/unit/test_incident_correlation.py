"""Unit tests for the 'what changed?' correlator.

Covers the verdict it should reach in each situation, including the two where it
must decline to name a commit.
"""
from datetime import datetime, timedelta, timezone

import pytest

from src.domain.incident_correlation import (
    AttributionRefusal,
    BaselineMode,
    CommitRef,
    CorrelationVerdict,
    IncidentCorrelator,
    MetricPoint,
    MetricSeries,
    WindowAnchor,
)
from src.domain.provenance import DataSource, Provenance

NOW = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)

LIVE = Provenance(DataSource.AWS_CLOUDWATCH, "test series", "2026-09-05T12:00:00Z")
COMMITS_LIVE = Provenance(DataSource.GITHUB_API, "test commits", "2026-09-05T12:00:00Z")


def series(values, provenance=LIVE, step_minutes=10):
    points = [
        MetricPoint(at=NOW - timedelta(minutes=step_minutes * (len(values) - 1 - i)), value=v)
        for i, v in enumerate(values)
    ]
    return MetricSeries("HTTPCode_Target_5XX_Count", "AWS/ApplicationELB", points, provenance)


def commit(sha, minutes_ago, author="dev"):
    return CommitRef(sha=sha, message=f"commit {sha}", author=author,
                     committed_at=NOW - timedelta(minutes=minutes_ago))


def test_flat_series_is_not_an_incident():
    result = IncidentCorrelator().correlate("checkout-api", series([2, 2, 2, 2, 2]), [commit("aaa", 5)])
    assert result.verdict is CorrelationVerdict.NO_ANOMALY
    assert result.incident_detected is False
    assert result.offending_commit is None
    assert "below the" in result.explanation
    assert "looks normal" in result.to_voice_summary()


def test_single_point_cannot_establish_a_baseline():
    result = IncidentCorrelator().correlate("checkout-api", series([50]), [commit("aaa", 5)])
    assert result.verdict is CorrelationVerdict.INSUFFICIENT_DATA
    assert result.sample_size == 1
    assert "not have enough" in result.to_voice_summary()


def test_empty_series_is_insufficient_data():
    empty = MetricSeries("HTTPCode_Target_5XX_Count", "AWS/ApplicationELB", [], LIVE)
    result = IncidentCorrelator().correlate("checkout-api", empty, [])
    assert result.verdict is CorrelationVerdict.INSUFFICIENT_DATA


def test_spike_with_a_recent_commit_is_attributed():
    correlator = IncidentCorrelator(anomaly_factor=3.0, attribution_window_minutes=60)
    commits = [commit("old111", 400), commit("prev22", 90), commit("bad333", 12)]
    result = correlator.correlate("checkout-api", series([2, 2, 2, 2, 70]), commits, COMMITS_LIVE)

    assert result.verdict is CorrelationVerdict.ANOMALY_ATTRIBUTED
    assert result.incident_detected is True
    assert result.offending_commit.sha == "bad333"
    assert result.rollback_target.sha == "prev22"
    assert result.rollback_is_available is True
    assert result.anomaly_factor == pytest.approx(35.0)
    assert "bad333" in result.to_voice_summary()


def test_spike_with_no_commit_in_the_window_is_not_attributed():
    correlator = IncidentCorrelator(anomaly_factor=3.0, attribution_window_minutes=60)
    result = correlator.correlate("checkout-api", series([2, 2, 2, 2, 70]), [commit("old111", 900)])

    assert result.verdict is CorrelationVerdict.ANOMALY_WITHOUT_ATTRIBUTION
    assert result.incident_detected is True
    assert result.offending_commit is None
    assert result.rollback_is_available is False
    assert "cannot attribute it to a deploy" in result.to_voice_summary()
    assert "not a verdict on what caused it" in result.to_voice_summary()


def test_spike_with_no_commits_at_all_is_not_attributed():
    result = IncidentCorrelator().correlate("checkout-api", series([2, 2, 2, 2, 70]), [])
    assert result.verdict is CorrelationVerdict.ANOMALY_WITHOUT_ATTRIBUTION


def test_only_commit_available_offers_no_rollback_target():
    correlator = IncidentCorrelator()
    result = correlator.correlate("checkout-api", series([2, 2, 2, 2, 70]), [commit("only11", 10)])
    assert result.verdict is CorrelationVerdict.ANOMALY_ATTRIBUTED
    assert result.offending_commit.sha == "only11"
    assert result.rollback_target is None
    assert result.rollback_is_available is False


def test_offending_commit_at_fetch_edge_resolves_its_parent():
    correlator = IncidentCorrelator()
    parent = commit("pare99", 200)

    def resolve(sha):
        return parent if sha == "only11" else None

    result = correlator.correlate(
        "checkout-api", series([2, 2, 2, 2, 70]), [commit("only11", 10)],
        COMMITS_LIVE, parent_resolver=resolve)
    assert result.verdict is CorrelationVerdict.ANOMALY_ATTRIBUTED
    assert result.offending_commit.sha == "only11"
    assert result.rollback_target.sha == "pare99"
    assert result.rollback_is_available is True


def test_offending_commit_at_fetch_edge_without_a_parent_stays_unavailable():
    correlator = IncidentCorrelator()

    def resolve(sha):
        return None

    result = correlator.correlate(
        "checkout-api", series([2, 2, 2, 2, 70]), [commit("only11", 10)],
        COMMITS_LIVE, parent_resolver=resolve)
    assert result.verdict is CorrelationVerdict.ANOMALY_ATTRIBUTED
    assert result.rollback_target is None
    assert result.rollback_is_available is False
    assert "Git order is not deployment evidence" in result.explanation


def test_commit_after_the_reading_is_never_blamed():
    """A commit that landed after the metric reading cannot have caused it."""
    correlator = IncidentCorrelator()
    future = CommitRef("future", "later", "dev", NOW + timedelta(minutes=5))
    result = correlator.correlate("checkout-api", series([2, 2, 2, 2, 70]), [commit("prev22", 30), future])
    assert result.offending_commit.sha == "prev22"


def test_threshold_is_respected_exactly():
    correlator = IncidentCorrelator(anomaly_factor=3.0)
    just_under = correlator.correlate("svc", series([2, 2, 2, 2, 5.9]), [commit("a", 5)])
    just_over = correlator.correlate("svc", series([2, 2, 2, 2, 6.1]), [commit("a", 5)])
    assert just_under.verdict is CorrelationVerdict.NO_ANOMALY
    assert just_over.verdict is CorrelationVerdict.ANOMALY_ATTRIBUTED


def test_zero_baseline_is_not_treated_as_an_infinite_spike():
    """Dividing by a zero baseline must not manufacture an incident."""
    result = IncidentCorrelator().correlate("svc", series([0, 0, 0, 0, 4]), [commit("a", 5)])
    assert result.verdict is CorrelationVerdict.NO_ANOMALY
    assert result.anomaly_factor == 0.0


def test_provenance_travels_through_the_correlator():
    fixture = Provenance(DataSource.OFFLINE_FIXTURE, "generated locally", "2026-09-05T12:00:00Z")
    result = IncidentCorrelator().correlate("svc", series([2, 2, 70], provenance=fixture), [], COMMITS_LIVE)
    assert result.metric_provenance.source is DataSource.OFFLINE_FIXTURE
    assert result.metric_provenance.is_live is False
    assert result.commit_provenance.source is DataSource.GITHUB_API
    assert result.commit_provenance.is_live is True


def test_baseline_mean_excludes_the_latest_point():
    assert series([1, 2, 3, 100]).baseline_mean() == pytest.approx(2.0)
    assert series([1, 2, 3, 100]).baseline_mean(exclude_latest=False) == pytest.approx(26.5)


# ------------------------------------------------- The pre-onset baseline (2026-09-08)

def test_the_onset_is_the_first_reading_of_an_elevation_that_is_still_going():
    """Not the first split that flatters the newest reading.

    An earlier-is-better search would put the onset of ``[2,2,2,2,70]`` at index 2,
    because 70 is 35 times the mean of the first two readings. That would move the
    attribution window half an hour off the spike. The onset is the first index from
    which every later reading is elevated, which for that series is the last one.
    """
    assert series([2, 2, 2, 2, 70]).find_onset(3.0) == 4
    assert series([2, 2, 70, 70, 70]).find_onset(3.0) == 2
    assert series([2, 2, 2, 2, 2]).find_onset(3.0) is None
    # A blip that recovered is not an elevation that is still going on.
    assert series([2, 2, 70, 2, 2]).find_onset(3.0) is None


def test_the_pre_onset_detector_is_never_less_sensitive_than_the_trailing_one():
    """The property the published before-and-after rests on.

    The last index is always a candidate onset, and testing it is arithmetically the
    same test the trailing baseline applies. So every series the old detector called an
    anomaly the new one calls an anomaly too, and the healthy-series cost of the change
    is bounded by the cases where the new one fires and the old one did not.
    """
    trailing = IncidentCorrelator(baseline_mode=BaselineMode.TRAILING, max_commits_in_window=None)
    fresh = IncidentCorrelator(max_commits_in_window=None)
    shapes = [
        [2, 2, 2, 2, 70], [2, 2, 70, 70, 70], [2, 2, 2, 2, 2], [5, 5, 5, 5, 6],
        [1, 1, 1, 1, 3.1], [0, 0, 0, 0, 4], [3, 3, 3, 30, 30, 30], [2, 70, 70, 70, 70],
    ]
    for values in shapes:
        old = trailing.correlate("svc", series(values), [])
        new = fresh.correlate("svc", series(values), [])
        if old.incident_detected:
            assert new.incident_detected, f"{values} was an anomaly before and is not now"


def test_the_baseline_stops_at_the_onset_rather_than_at_the_newest_point():
    result = IncidentCorrelator().correlate("svc", series([4, 4, 4, 40, 40, 40]), [])
    assert result.baseline_points == 3
    assert result.baseline_value == pytest.approx(4.0)
    assert result.anomaly_factor == pytest.approx(10.0)


def test_a_two_point_series_still_behaves_like_the_trailing_baseline():
    """The floor case of the sensitivity property: nowhere earlier to put the onset."""
    result = IncidentCorrelator().correlate("svc", series([2, 70]), [])
    assert result.verdict is CorrelationVerdict.ANOMALY_WITHOUT_ATTRIBUTION
    assert result.baseline_value == pytest.approx(2.0)


def test_the_attribution_window_ends_at_the_onset_not_at_the_reading():
    """The half of the change that fixes a late look, isolated.

    The spike started 20 minutes before the reading. A change that landed 55 minutes
    before the reading is 35 minutes before the onset, so it is inside the window; a
    change that landed after the spike started cannot have caused it and is outside.
    """
    before_onset = commit("before1", 55)
    after_onset = commit("after11", 5)
    result = IncidentCorrelator().correlate(
        "svc", series([4, 4, 4, 40, 40, 40]), [commit("older1", 400), before_onset, after_onset])
    assert result.offending_commit.sha == "before1"
    assert result.onset_at == NOW - timedelta(minutes=20)

    anchored_at_the_reading = IncidentCorrelator(window_anchor=WindowAnchor.READING)
    late = anchored_at_the_reading.correlate(
        "svc", series([4, 4, 4, 40, 40, 40]), [commit("older1", 400), before_onset, after_onset])
    # Anchored at the reading, both are candidates, so the gate refuses instead.
    assert late.verdict is CorrelationVerdict.ANOMALY_WITHOUT_ATTRIBUTION
    assert late.attribution_refusal is AttributionRefusal.WINDOW_TOO_CROWDED


def test_a_crowded_window_refuses_and_offers_no_rollback():
    burst = [commit(f"burst{i}", 30 + i) for i in range(4)]
    result = IncidentCorrelator().correlate("svc", series([2, 2, 2, 2, 70]), burst)
    assert result.verdict is CorrelationVerdict.ANOMALY_WITHOUT_ATTRIBUTION
    assert result.attribution_refusal is AttributionRefusal.WINDOW_TOO_CROWDED
    assert result.commits_in_window == 4
    assert result.rollback_is_available is False
    assert result.incident_detected is True


def test_turning_the_crowding_gate_off_restores_the_older_behaviour():
    burst = [commit(f"burst{i}", 30 + i) for i in range(4)]
    result = IncidentCorrelator(max_commits_in_window=None).correlate(
        "svc", series([2, 2, 2, 2, 70]), burst)
    assert result.verdict is CorrelationVerdict.ANOMALY_ATTRIBUTED
    assert result.attribution_is_ambiguous is True


# ------------------------------------------ A refusal is a refusal, not an acquittal
#
# The finding these close: a refusal to attribute was being rendered as proof that no
# deploy caused the incident. The correlator cannot rule a deploy out, so none of its
# refusals may say it has, and only the inside-baseline verdict may say nothing needs
# reverting.

def _certainty_violations(text: str) -> list[str]:
    import re

    from src.domain.incident_correlation import REFUSAL_MUST_NOT_CLAIM

    flat = " ".join(text.split())
    return [pattern for pattern in REFUSAL_MUST_NOT_CLAIM if re.search(pattern, flat, re.IGNORECASE)]


def _empty_window():
    return IncidentCorrelator().correlate("svc", series([2, 2, 2, 2, 70]), [commit("old111", 900)])


def _crowded_window():
    burst = [commit(f"burst{i}", 30 + i) for i in range(4)]
    return IncidentCorrelator().correlate("svc", series([2, 2, 2, 2, 70]), burst)


def _missing_baseline():
    return IncidentCorrelator().correlate("svc", series([50]), [commit("aaa", 5)])


@pytest.mark.parametrize("make, refusal", [
    (_empty_window, AttributionRefusal.NO_CANDIDATE_IN_WINDOW),
    (_crowded_window, AttributionRefusal.WINDOW_TOO_CROWDED),
    (_missing_baseline, None),
], ids=["empty-window", "crowded-window", "missing-baseline"])
def test_a_refusal_is_never_rendered_as_nothing_to_revert(make, refusal):
    result = make()
    assert result.attribution_refusal is refusal
    assert result.can_attribute is False
    assert result.nothing_to_revert is False, (
        f"{result.verdict.value} says nothing needs reverting, which only NO_ANOMALY may say"
    )
    statement = result.refusal_statement
    assert statement is not None and "cannot attribute" in statement
    for surface, text in (
        ("refusal_statement", statement),
        ("voice_summary", result.to_voice_summary()),
        ("explanation", result.explanation),
    ):
        assert not _certainty_violations(text), f"{surface} states the refusal as a certainty: {text!r}"


def test_the_refusal_statement_says_what_the_refusal_is_not():
    """Each reason, and in the same sentence, what it does not establish."""
    empty = _empty_window().refusal_statement
    assert "no commit landed in the 75 minutes" in empty
    assert "not evidence that no change caused it" in empty

    crowded = _crowded_window().refusal_statement
    assert "4 landed in the 75 minutes" in crowded
    assert "not a finding that none of them caused it" in crowded
    assert "would be a guess" in crowded

    missing = _missing_baseline().refusal_statement
    assert "1 reading of" in missing
    assert "not a finding about any deploy" in missing


def test_the_refusal_statement_names_the_window_it_refused_over():
    correlator = IncidentCorrelator(attribution_window_minutes=45)
    result = correlator.correlate("svc", series([2, 2, 2, 2, 70]), [commit("old111", 900)])
    assert result.attribution_window_minutes == 45
    assert "45 minutes" in result.refusal_statement


def test_only_the_inside_baseline_verdict_says_nothing_needs_reverting():
    result = IncidentCorrelator().correlate("svc", series([2, 2, 2, 2, 2]), [commit("aaa", 5)])
    assert result.verdict is CorrelationVerdict.NO_ANOMALY
    assert result.nothing_to_revert is True
    assert result.can_attribute is False
    assert result.refusal_statement is None


def test_an_attribution_is_neither_a_refusal_nor_a_clean_bill():
    commits = [commit("old111", 400), commit("prev22", 90), commit("bad333", 12)]
    result = IncidentCorrelator().correlate("svc", series([2, 2, 2, 2, 70]), commits)
    assert result.verdict is CorrelationVerdict.ANOMALY_ATTRIBUTED
    assert result.can_attribute is True
    assert result.nothing_to_revert is False
    assert result.refusal_statement is None
    assert not _certainty_violations(result.to_voice_summary())


def test_the_forbidden_certainty_list_catches_the_wording_that_was_retired():
    """Negative control on the list itself: the phrases the finding named must all trip it."""
    for retired in (
        "do not revert anything, this is not a deploy.",
        "Do not revert on this. 6 changes landed",
        "Do not roll back on this answer.",
        "no deployment landed close enough to blame, so nothing to blame",
        "told to look elsewhere",
    ):
        assert _certainty_violations(retired), f"the list does not catch {retired!r}"


# ------------------------------------------------- Local git commit provider

def test_local_git_provider_reads_real_commits_from_this_checkout():
    from src.infrastructure.local_git_adapter import LocalGitCommitProvider

    provider = LocalGitCommitProvider()
    if not provider.is_available:
        pytest.skip("not running inside a git checkout")

    commits = provider.list_recent_commits(limit=5)
    assert commits, "git log returned nothing in a repository that has commits"
    for commit in commits:
        assert commit["sha"]
        assert commit["author"]
        assert commit["committed_at"]
        # An ISO-8601 timestamp git actually produced, not a placeholder.
        datetime.fromisoformat(commit["committed_at"])


def test_local_git_provider_returns_nothing_outside_a_checkout(tmp_path):
    from src.infrastructure.local_git_adapter import LocalGitCommitProvider

    provider = LocalGitCommitProvider(repo_root=tmp_path)
    assert provider.is_available is False
    assert provider.list_recent_commits() == []


def test_local_git_provider_respects_the_limit():
    from src.infrastructure.local_git_adapter import LocalGitCommitProvider

    provider = LocalGitCommitProvider()
    if not provider.is_available:
        pytest.skip("not running inside a git checkout")
    assert len(provider.list_recent_commits(limit=2)) <= 2


# ------------------------------------------------------------ Use case wiring

class _NoCommits:
    def list_recent_commits(self, limit=10):
        return []


class _SomeCommits:
    def __init__(self, entries):
        self.entries = entries

    def list_recent_commits(self, limit=10):
        return self.entries[:limit]


class _RecordingMetrics:
    def __init__(self, series_to_return):
        self.series = series_to_return
        self.anchor_seen = "unset"
        self.commit_times_seen = "unset"

    def get_error_series(self, service_name, window_minutes=60, anchor_at=None, commit_times=None):
        self.anchor_seen = anchor_at
        self.commit_times_seen = commit_times
        return self.series


def test_use_case_falls_back_from_github_to_local_git():
    from src.application.diagnose_incident_use_case import DiagnoseIncidentUseCase
    from src.domain.provenance import DataSource as DS

    entries = [{"sha": "abc1234", "message": "real", "author": "Dev",
                "committed_at": (NOW - timedelta(minutes=20)).isoformat()}]
    metrics = _RecordingMetrics(series([2, 2, 2, 2, 70]))
    use_case = DiagnoseIncidentUseCase(metrics, _NoCommits(), _SomeCommits(entries))

    result = use_case.execute("checkout-api")
    assert result.commit_provenance.source is DS.LOCAL_GIT
    assert "git log" in result.commit_provenance.detail


def test_use_case_prefers_github_when_it_returns_commits():
    from src.application.diagnose_incident_use_case import DiagnoseIncidentUseCase
    from src.domain.provenance import DataSource as DS

    entries = [{"sha": "gh12345", "message": "from github", "author": "Dev",
                "committed_at": (NOW - timedelta(minutes=20)).isoformat()}]
    local = _SomeCommits([{"sha": "local11", "message": "local", "author": "Dev",
                           "committed_at": (NOW - timedelta(minutes=5)).isoformat()}])
    metrics = _RecordingMetrics(series([2, 2, 2, 2, 70]))
    use_case = DiagnoseIncidentUseCase(metrics, _SomeCommits(entries), local)

    result = use_case.execute("checkout-api")
    assert result.commit_provenance.source is DS.GITHUB_API


def test_use_case_reports_no_commits_rather_than_inventing_them():
    from src.application.diagnose_incident_use_case import DiagnoseIncidentUseCase
    from src.domain.provenance import DataSource as DS

    metrics = _RecordingMetrics(series([2, 2, 2, 2, 70]))
    use_case = DiagnoseIncidentUseCase(metrics, _NoCommits(), _NoCommits())

    result = use_case.execute("checkout-api")
    assert result.commit_provenance.source is DS.OFFLINE_FIXTURE
    assert "does not invent commits" in result.commit_provenance.detail
    assert result.offending_commit is None


def test_the_newest_commit_time_is_passed_as_the_simulation_anchor():
    from src.application.diagnose_incident_use_case import DiagnoseIncidentUseCase

    newest = NOW - timedelta(minutes=10)
    entries = [
        {"sha": "old1234", "message": "old", "author": "D", "committed_at": (NOW - timedelta(hours=5)).isoformat()},
        {"sha": "new1234", "message": "new", "author": "D", "committed_at": newest.isoformat()},
    ]
    metrics = _RecordingMetrics(series([2, 2, 2, 2, 70]))
    DiagnoseIncidentUseCase(metrics, _SomeCommits(entries)).execute("checkout-api")
    assert metrics.anchor_seen == newest


def test_no_anchor_is_passed_when_there_are_no_commits():
    from src.application.diagnose_incident_use_case import DiagnoseIncidentUseCase

    metrics = _RecordingMetrics(series([2, 2, 2]))
    DiagnoseIncidentUseCase(metrics, _NoCommits()).execute("checkout-api")
    assert metrics.anchor_seen is None
