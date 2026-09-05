"""Unit tests for the 'what changed?' correlator.

Covers the verdict it should reach in each situation, including the two where it
must decline to name a commit.
"""
from datetime import datetime, timedelta, timezone

import pytest

from src.domain.incident_correlation import (
    CommitRef,
    CorrelationVerdict,
    IncidentCorrelator,
    MetricPoint,
    MetricSeries,
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
    assert "no deployment landed close enough" in result.to_voice_summary()


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
    assert "No earlier commit is known" in result.explanation


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
