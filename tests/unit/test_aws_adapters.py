"""Unit tests for the AWS Cost Explorer and CloudWatch adapters.

The boto3 clients are replaced by stubs that return the response shapes AWS
documents, so the adapters' parsing and reduction run for real.
"""
import json
from datetime import date, datetime, timedelta, timezone

import pytest

from src.domain.provenance import DataSource
from src.infrastructure.aws_cost_adapter import FIXTURE_PATH, AWSCostAdapter
from src.infrastructure.cloudwatch_adapter import (
    SHAPE_INSIDE_BASELINE,
    SHAPE_UNATTRIBUTED,
    SIMULATED_SERVICES,
    UNATTRIBUTED_ANCHOR_OFFSET_MINUTES,
    CloudWatchMetricAdapter,
    simulated_baseline_for,
    simulated_multiplier_for,
)


class StubCostExplorer:
    def __init__(self, payload, error=None):
        self.payload = payload
        self.error = error
        self.calls = []

    def get_cost_and_usage(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.payload


@pytest.fixture(autouse=True)
def live_paths_enabled(monkeypatch):
    """conftest forces MERCURY_OFFLINE on for the suite; these tests exercise both
    sides of that switch, so the default here is off and the offline cases opt in."""
    monkeypatch.delenv("MERCURY_OFFLINE", raising=False)


def cost_bucket(day: str, entries: dict[str, str]):
    return {
        "TimePeriod": {"Start": day, "End": day},
        "Groups": [
            {"Keys": [service], "Metrics": {"UnblendedCost": {"Amount": amount, "Unit": "USD"}}}
            for service, amount in entries.items()
        ],
    }


# ----------------------------------------------------------------- Cost Explorer

def test_summarize_totals_and_projects_from_elapsed_days():
    buckets = [
        cost_bucket("2026-09-01", {"AmazonEC2": "10.00"}),
        cost_bucket("2026-09-02", {"AmazonEC2": "10.00"}),
    ]
    total, projected, anomalies = AWSCostAdapter.summarize(buckets, elapsed_days=2, days_in_month=30)
    assert total == 20.0
    assert projected == 300.0
    assert anomalies == []


def test_summarize_flags_a_service_whose_latest_day_jumps():
    buckets = [
        cost_bucket("2026-09-01", {"AmazonECS": "10.00"}),
        cost_bucket("2026-09-02", {"AmazonECS": "10.00"}),
        cost_bucket("2026-09-03", {"AmazonECS": "40.00"}),
    ]
    _, _, anomalies = AWSCostAdapter.summarize(buckets, elapsed_days=3, days_in_month=30)
    assert len(anomalies) == 1
    assert anomalies[0].service_name == "AmazonECS"
    assert anomalies[0].previous_daily_avg_usd == 10.0
    assert anomalies[0].current_daily_usd == 40.0
    assert anomalies[0].percentage_increase == pytest.approx(300.0)
    assert "does not report a cause" in anomalies[0].root_cause_explanation


def test_summarize_ignores_a_rise_below_the_threshold():
    buckets = [
        cost_bucket("2026-09-01", {"AmazonS3": "10.00"}),
        cost_bucket("2026-09-02", {"AmazonS3": "11.00"}),
    ]
    _, _, anomalies = AWSCostAdapter.summarize(buckets, elapsed_days=2, days_in_month=30)
    assert anomalies == []


def test_summarize_survives_a_malformed_amount():
    buckets = [cost_bucket("2026-09-01", {"AmazonRDS": "not-a-number"})]
    total, _, _ = AWSCostAdapter.summarize(buckets, elapsed_days=1, days_in_month=30)
    assert total == 0.0


def test_single_day_of_data_cannot_produce_an_anomaly():
    buckets = [cost_bucket("2026-09-01", {"AmazonECS": "500.00"})]
    _, _, anomalies = AWSCostAdapter.summarize(buckets, elapsed_days=1, days_in_month=30)
    assert anomalies == []


def test_month_to_date_window_starts_on_the_first():
    start, end, elapsed = AWSCostAdapter.month_to_date_window(date(2026, 9, 17))
    assert start == "2026-09-01"
    assert end == "2026-09-17"
    assert elapsed == 16


def test_month_to_date_window_never_reports_zero_elapsed_days():
    _, _, elapsed = AWSCostAdapter.month_to_date_window(date(2026, 9, 1))
    assert elapsed == 1


def test_live_cost_call_is_labelled_live_and_names_its_limitation():
    stub = StubCostExplorer({
        "ResultsByTime": [
            cost_bucket("2026-09-01", {"AmazonECS": "10.00"}),
            cost_bucket("2026-09-02", {"AmazonECS": "45.00"}),
        ]
    })
    report = AWSCostAdapter(client=stub).fetch_cost_report()

    assert report.provenance.source is DataSource.AWS_COST_EXPLORER
    assert report.provenance.is_live is True
    assert "lags by up to 24 hours" in report.provenance.detail
    assert stub.calls[0]["Granularity"] == "DAILY"
    assert stub.calls[0]["Metrics"] == ["UnblendedCost"]
    assert len(report.anomalies) == 1


def test_cost_call_failure_falls_back_and_names_the_error():
    stub = StubCostExplorer(None, error=RuntimeError("AccessDeniedException"))
    report = AWSCostAdapter(client=stub).fetch_cost_report()
    assert report.provenance.source is DataSource.OFFLINE_FIXTURE
    assert "AccessDeniedException" in report.provenance.detail


def test_no_credentials_serves_the_fixture_labelled_as_synthetic():
    adapter = AWSCostAdapter()
    adapter._resolve_client = lambda: None  # simulate unresolvable credentials
    report = adapter.fetch_cost_report()
    assert report.provenance.is_live is False
    assert "No AWS credentials resolved" in report.provenance.detail
    assert "SYNTHETIC" in report.provenance.detail


def test_the_cost_fixture_admits_it_is_synthetic():
    """This fixture is not a recording, and it must say so where a reader sees it."""
    with open(FIXTURE_PATH, "r", encoding="utf-8") as handle:
        fixture = json.load(handle)
    assert "SYNTHETIC" in fixture["note"]
    assert "never read from an AWS account" in fixture["note"]


# -------------------------------------------------------------------- CloudWatch

class StubCloudWatch:
    def __init__(self, datapoints, error=None):
        self.datapoints = datapoints
        self.error = error
        self.calls = []

    def get_metric_statistics(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return {"Datapoints": self.datapoints}


def test_live_cloudwatch_series_is_labelled_live():
    now = datetime.now(timezone.utc)
    stub = StubCloudWatch([
        {"Timestamp": now - timedelta(minutes=20), "Sum": 3.0},
        {"Timestamp": now - timedelta(minutes=10), "Sum": 2.0},
    ])
    series = CloudWatchMetricAdapter(client=stub).get_error_series("checkout-api")

    assert series.provenance.source is DataSource.AWS_CLOUDWATCH
    assert series.provenance.is_live is True
    assert len(series.points) == 2
    assert series.latest.value == 2.0
    assert stub.calls[0]["Statistics"] == ["Sum"]


def test_cloudwatch_datapoints_are_sorted_oldest_first():
    now = datetime.now(timezone.utc)
    stub = StubCloudWatch([
        {"Timestamp": now, "Sum": 9.0},
        {"Timestamp": now - timedelta(minutes=30), "Sum": 1.0},
    ])
    series = CloudWatchMetricAdapter(client=stub).get_error_series("checkout-api")
    assert [p.value for p in series.points] == [1.0, 9.0]


def test_empty_cloudwatch_response_fails_closed_and_says_why():
    """An empty live read shows NO LIVE DATA, never the simulated spike."""
    stub = StubCloudWatch([])
    anchor = datetime.now(timezone.utc) - timedelta(minutes=30)
    series = CloudWatchMetricAdapter(client=stub).get_error_series(
        "checkout-api", anchor_at=anchor, commit_times=[anchor])
    assert series.points == [], "an empty live read must not be replaced with generated points"
    assert series.provenance.source is DataSource.NO_LIVE_DATA
    assert series.provenance.is_live is False
    assert series.provenance.display_label == "NO LIVE DATA"
    assert "returned no datapoints" in series.provenance.detail
    assert "shape '" not in series.provenance.detail, "the simulated series leaked into a live read"


def test_cloudwatch_failure_fails_closed_and_names_the_error():
    stub = StubCloudWatch(None, error=RuntimeError("ThrottlingException"))
    anchor = datetime.now(timezone.utc) - timedelta(minutes=30)
    series = CloudWatchMetricAdapter(client=stub).get_error_series(
        "checkout-api", anchor_at=anchor, commit_times=[anchor])
    assert series.points == [], "a failed live read must not be replaced with generated points"
    assert series.provenance.source is DataSource.NO_LIVE_DATA
    assert series.provenance.display_label == "NO LIVE DATA"
    assert "ThrottlingException" in series.provenance.detail


@pytest.mark.parametrize("stub", [
    StubCloudWatch([]),
    StubCloudWatch(None, error=RuntimeError("AccessDenied")),
], ids=["empty", "error"])
def test_a_failed_live_read_can_never_yield_a_candidate_commit(stub):
    """The trust-breaker this replaces: a real commit and a generated spike behind it.

    Real commits sit right before the reading. Before the fix, the empty and the failed
    read both returned the simulated series anchored to those commits, so the use case
    named one of them as the change behind an incident nobody measured. Now the answer
    is INSUFFICIENT_DATA, no commit is named, and the metric stamp reads NO LIVE DATA.
    """
    from src.application.diagnose_incident_use_case import DiagnoseIncidentUseCase
    from src.domain.incident_correlation import CorrelationVerdict, IncidentCorrelator

    now = datetime.now(timezone.utc)

    class Commits:
        def list_recent_commits(self, limit=10):
            return [{"sha": f"abc{i}", "message": "real change", "author": "dev",
                     "committed_at": (now - timedelta(minutes=minutes)).isoformat()}
                    for i, minutes in enumerate((8, 240))]

    use_case = DiagnoseIncidentUseCase(CloudWatchMetricAdapter(client=stub), Commits(),
                                       correlator=IncidentCorrelator())
    answer = use_case.execute("checkout-api", 60)

    assert stub.calls, "the live read must have been attempted"
    assert answer.verdict is CorrelationVerdict.INSUFFICIENT_DATA
    assert answer.offending_commit is None
    assert answer.can_attribute is False
    assert answer.metric_provenance.display_label == "NO LIVE DATA"


def test_no_live_data_is_never_rendered_as_live():
    from src.domain.provenance import Provenance

    stamp = Provenance(source=DataSource.NO_LIVE_DATA, detail="d", observed_at_utc="")
    assert DataSource.NO_LIVE_DATA.is_live is False
    assert stamp.to_dict()["is_live"] is False
    assert stamp.to_dict()["display_label"] == "NO LIVE DATA"


def test_simulated_series_says_it_was_generated_not_read():
    adapter = CloudWatchMetricAdapter(simulate_incident=True)
    adapter._resolve_client = lambda: None
    series = adapter.get_error_series("checkout-api")

    assert series.provenance.source is DataSource.OFFLINE_FIXTURE
    assert series.provenance.display_label == "OFFLINE FIXTURE"
    assert "generated" in series.provenance.detail
    assert "never read from" in series.provenance.detail
    assert series.latest.value > series.baseline_mean()


def test_simulation_can_be_switched_to_a_healthy_series():
    adapter = CloudWatchMetricAdapter(simulate_incident=False)
    adapter._resolve_client = lambda: None
    series = adapter.get_error_series("checkout-api")
    assert series.latest.value == pytest.approx(series.baseline_mean())
    # The named shape, not the trailing sentence about the switch: that sentence
    # is printed for every series and would make this assertion unfailable.
    assert "shape 'flat_and_healthy'" in series.provenance.detail


# ----------------------------------------------------------------- Offline mode

def test_offline_mode_suppresses_the_cost_call_even_with_a_client(monkeypatch):
    """MERCURY_OFFLINE must win over a working client, or the tests spend money."""
    monkeypatch.setenv("MERCURY_OFFLINE", "1")
    stub = StubCostExplorer({"ResultsByTime": [cost_bucket("2026-09-01", {"AmazonEC2": "1.00"})]})
    report = AWSCostAdapter(client=stub).fetch_cost_report()
    assert report.provenance.is_live is False
    assert "MERCURY_OFFLINE is set" in report.provenance.detail
    assert stub.calls == [], "no Cost Explorer request may be issued in offline mode"


def test_offline_mode_suppresses_the_cloudwatch_call(monkeypatch):
    monkeypatch.setenv("MERCURY_OFFLINE", "1")
    stub = StubCloudWatch([{"Timestamp": datetime.now(timezone.utc), "Sum": 5.0}])
    series = CloudWatchMetricAdapter(client=stub).get_error_series("checkout-api")
    assert series.provenance.is_live is False
    assert stub.calls == []


def test_offline_mode_can_never_make_a_fixture_look_live(monkeypatch):
    monkeypatch.setenv("MERCURY_OFFLINE", "1")
    report = AWSCostAdapter(client=StubCostExplorer({"ResultsByTime": []})).fetch_cost_report()
    assert report.provenance.display_label == "OFFLINE FIXTURE"


@pytest.mark.parametrize("value,expected", [
    ("1", True), ("true", True), ("TRUE", True), ("yes", True), ("on", True),
    ("0", False), ("false", False), ("", False), ("no", False),
])
def test_offline_flag_parsing(monkeypatch, value, expected):
    from src.infrastructure.offline_mode import offline_mode_enabled

    monkeypatch.setenv("MERCURY_OFFLINE", value)
    assert offline_mode_enabled() is expected


def test_offline_flag_defaults_to_off(monkeypatch):
    from src.infrastructure.offline_mode import offline_mode_enabled

    monkeypatch.delenv("MERCURY_OFFLINE", raising=False)
    assert offline_mode_enabled() is False


# ----------------------------------------------------------------- Cost caching

def test_a_successful_cost_report_is_cached_so_aws_is_not_billed_per_refresh(monkeypatch):
    stub = StubCostExplorer({"ResultsByTime": [
        cost_bucket("2026-09-01", {"AmazonEC2": "10.00"}),
        cost_bucket("2026-09-02", {"AmazonEC2": "10.00"}),
    ]})
    adapter = AWSCostAdapter(client=stub)

    first = adapter.fetch_cost_report()
    second = adapter.fetch_cost_report()

    assert len(stub.calls) == 1, "the second refresh must be served from cache"
    assert first.total_month_to_date_usd == second.total_month_to_date_usd
    assert "Cached for" in first.provenance.detail


def test_the_cost_cache_expires(monkeypatch):
    import src.infrastructure.aws_cost_adapter as module

    monkeypatch.setattr(module, "CACHE_TTL_SECONDS", -1.0)
    stub = StubCostExplorer({"ResultsByTime": [cost_bucket("2026-09-01", {"AmazonEC2": "10.00"})]})
    adapter = module.AWSCostAdapter(client=stub)

    adapter.fetch_cost_report()
    adapter.fetch_cost_report()
    assert len(stub.calls) == 2


def test_the_cost_cache_can_be_invalidated(monkeypatch):
    stub = StubCostExplorer({"ResultsByTime": [cost_bucket("2026-09-01", {"AmazonEC2": "10.00"})]})
    adapter = AWSCostAdapter(client=stub)
    adapter.fetch_cost_report()
    adapter.invalidate_cache()
    adapter.fetch_cost_report()
    assert len(stub.calls) == 2


def test_a_failed_cost_call_is_not_cached(monkeypatch):
    """A transient AWS failure must not pin the wallboard to the fixture."""
    stub = StubCostExplorer(None, error=RuntimeError("ThrottlingException"))
    adapter = AWSCostAdapter(client=stub)
    adapter.fetch_cost_report()
    adapter.fetch_cost_report()
    assert len(stub.calls) == 2


# ------------------------------------- The simulated series depends on the service
#
# The defect these replace: SIMULATED_BASELINE and SIMULATED_SPIKE were module
# constants, so every service name a caller supplied returned the same numbers.
# An invented name got the same spike as the demo service, and the correlator's
# two refusal verdicts were unreachable from any input.

def offline_adapter(**kwargs) -> CloudWatchMetricAdapter:
    adapter = CloudWatchMetricAdapter(**kwargs)
    adapter._resolve_client = lambda: None
    return adapter


def test_two_services_never_return_the_same_series():
    adapter = offline_adapter()
    readings = {
        name: (adapter.get_error_series(name).baseline_mean(), adapter.get_error_series(name).latest.value)
        for name in SIMULATED_SERVICES
    }
    assert len(set(readings.values())) == len(readings), f"services share a reading: {readings}"


def test_the_same_service_reads_the_same_on_every_call():
    """Derived from SHA-256, not from the randomised builtin hash."""
    first = offline_adapter().get_error_series("checkout-api")
    second = offline_adapter().get_error_series("checkout-api")
    assert [p.value for p in first.points] == [p.value for p in second.points]


def test_the_derived_values_are_pinned_to_the_recorded_digest():
    """A change to the derivation must be a deliberate one, not a silent one.

    These are the values the derivation prints today, read from:
        python -c "from src.infrastructure.cloudwatch_adapter import *; \
                   print(simulated_baseline_for('checkout-api'))"
    """
    assert (simulated_baseline_for("checkout-api"), simulated_multiplier_for(
        "checkout-api", SIMULATED_SERVICES["checkout-api"].shape)) == (2.95, 12.9)
    assert (simulated_baseline_for("payments-worker"), simulated_multiplier_for(
        "payments-worker", SIMULATED_SERVICES["payments-worker"].shape)) == (5.9, 1.6)
    assert (simulated_baseline_for("search-indexer"), simulated_multiplier_for(
        "search-indexer", SIMULATED_SERVICES["search-indexer"].shape)) == (4.59, 9.29)


def test_an_inside_baseline_service_stays_under_the_anomaly_threshold():
    """1.20x to 1.89x, against a 3.0x threshold. The margin is the point."""
    for name, service in SIMULATED_SERVICES.items():
        if service.shape != SHAPE_INSIDE_BASELINE:
            continue
        multiplier = simulated_multiplier_for(name, service.shape)
        assert 1.2 <= multiplier < 2.0, f"{name} multiplier {multiplier} is not inside its baseline"
        assert multiplier > 1.0, "a flat line does not show a threshold refusing"
        series = offline_adapter().get_error_series(name)
        assert series.latest.value / series.baseline_mean() < 3.0


def test_a_spiking_service_clears_the_anomaly_threshold_by_a_margin():
    for name, service in SIMULATED_SERVICES.items():
        if service.shape == SHAPE_INSIDE_BASELINE:
            continue
        series = offline_adapter().get_error_series(name)
        assert series.latest.value / series.baseline_mean() >= 6.0, name


def test_the_unattributed_service_is_anchored_outside_the_attribution_window():
    from src.domain.incident_correlation import DEFAULT_ATTRIBUTION_WINDOW_MINUTES

    assert UNATTRIBUTED_ANCHOR_OFFSET_MINUTES > DEFAULT_ATTRIBUTION_WINDOW_MINUTES

    anchor = datetime.now(timezone.utc) - timedelta(hours=12)
    name = next(n for n, s in SIMULATED_SERVICES.items() if s.shape == SHAPE_UNATTRIBUTED)
    series = offline_adapter().get_error_series(name, anchor_at=anchor)

    gap_minutes = (series.latest.at - anchor).total_seconds() / 60
    assert gap_minutes > DEFAULT_ATTRIBUTION_WINDOW_MINUTES
    assert "deliberately outside" in series.provenance.detail


def test_an_unknown_service_is_refused_rather_than_given_an_invented_spike():
    series = offline_adapter().get_error_series("quiet-service")
    assert series.points == [], "a name the fixture does not know must produce no data"
    assert series.provenance.source is DataSource.OFFLINE_FIXTURE
    assert "does not invent a reading" in series.provenance.detail
    assert "quiet-service" in series.provenance.detail


def test_an_unknown_service_is_still_refused_with_the_incident_switch_off():
    series = offline_adapter(simulate_incident=False).get_error_series("quiet-service")
    assert series.points == []


def test_an_unknown_service_is_refused_when_cloudwatch_returns_nothing():
    """The live path's empty read must not invent a series either.

    It used to fall through to the fixture's refusal for an unknown name; an empty
    live read now fails closed for every name, known or not, so the stamp is NO LIVE
    DATA rather than the fixture's wording.
    """
    stub = StubCloudWatch([])
    series = CloudWatchMetricAdapter(client=stub).get_error_series("quiet-service")
    assert series.points == []
    assert "returned no datapoints" in series.provenance.detail
    assert series.provenance.source is DataSource.NO_LIVE_DATA


def test_a_live_reading_for_an_unknown_service_is_returned_unchanged():
    """The refusal is about inventing data, not about which names may be read."""
    now = datetime.now(timezone.utc)
    stub = StubCloudWatch([
        {"Timestamp": now - timedelta(minutes=10), "Sum": 1.0},
        {"Timestamp": now, "Sum": 4.0},
    ])
    series = CloudWatchMetricAdapter(client=stub).get_error_series("quiet-service")
    assert series.provenance.is_live is True
    assert [p.value for p in series.points] == [1.0, 4.0]


def test_the_provenance_reports_the_shape_and_the_numbers_it_generated():
    series = offline_adapter().get_error_series("payments-worker")
    detail = series.provenance.detail
    assert f"shape '{SHAPE_INSIDE_BASELINE}'" in detail
    assert f"baseline {series.baseline_mean()}" in detail
    assert f"rising to {series.latest.value}" in detail
    assert "SHA-256 of the service name" in detail


# ------------------------------------------- Which commit a simulated reading sits after

def _log(*offsets_minutes: float) -> list[datetime]:
    """A commit log, given as minutes before a fixed instant, oldest last."""
    base = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    return [base - timedelta(minutes=offset) for offset in offsets_minutes]


def test_the_attributing_shape_is_anchored_to_a_commit_that_is_alone_in_its_window():
    """A demo whose verdict moves with somebody's commit cadence is not a demo.

    Anchoring at the newest commit was fine while the correlator named the closest
    change whatever else was in the window. Once it refuses a crowded window, whether
    checkout-api attributed or refused depended on how many commits landed in the hour
    before HEAD, so the same checkout showed different verdicts on different days.
    """
    from src.infrastructure.cloudwatch_adapter import SHAPE_ATTRIBUTED, choose_anchor

    # A burst of four at the head, one commit twenty minutes before the burst, and one
    # six hours before that. The newest commit with nothing else in its own window is
    # the one twenty minutes back, so that is the one an attributing demo sits after.
    times = _log(400, 20, 15, 10, 5)
    alone, burst_head = _log(20)[0], _log(5)[0]
    chosen = choose_anchor(SHAPE_ATTRIBUTED, max(times), times)
    assert chosen == alone, "the anchor is not the newest commit that is alone in its window"
    assert chosen != burst_head, "anchoring at the newest commit puts three others in the window"


def test_the_crowded_shape_is_anchored_to_the_commit_with_the_most_company():
    from src.infrastructure.cloudwatch_adapter import SHAPE_CROWDED, choose_anchor

    times = _log(400, 20, 15, 10, 5)
    chosen = choose_anchor(SHAPE_CROWDED, max(times), times)
    assert chosen == max(times), "the crowded anchor must be the end of the burst"


def test_choosing_an_anchor_without_a_log_changes_nothing():
    from src.infrastructure.cloudwatch_adapter import SHAPE_ATTRIBUTED, choose_anchor

    newest = _log(5)[0]
    assert choose_anchor(SHAPE_ATTRIBUTED, newest, None) == newest
    assert choose_anchor(SHAPE_ATTRIBUTED, newest, []) == newest
    assert choose_anchor(SHAPE_ATTRIBUTED, None, None) is None


def test_the_attributing_shape_falls_back_when_no_commit_is_ever_alone():
    """A log with no isolated commit anywhere. The demo then honestly refuses.

    Every commit here has company inside its own window, including the oldest, so there
    is nothing to anchor an attribution to. The chooser returns the newest rather than
    inventing a gap, and what the screen then shows is the crowded-window refusal, which
    is the true answer for a service that ships like that.
    """
    from src.infrastructure.cloudwatch_adapter import SHAPE_ATTRIBUTED, choose_anchor

    times = _log(6, 4, 2, 0)
    assert choose_anchor(SHAPE_ATTRIBUTED, max(times), times) == max(times)


def test_the_crowded_shape_discloses_how_it_was_staged():
    from src.infrastructure.cloudwatch_adapter import SHAPE_CROWDED

    times = _log(400, 20, 15, 10, 5)
    name = next(n for n, s in SIMULATED_SERVICES.items() if s.shape == SHAPE_CROWDED)
    series = offline_adapter().get_error_series(name, anchor_at=max(times), commit_times=times)
    assert "the commit with the most company" in series.provenance.detail
    assert "the commit stamp beside this answer says they are, and this metric is generated" in series.provenance.detail


def test_every_verdict_the_correlator_can_reach_is_reachable_from_the_fixture():
    """One named service per answer, driven through the real correlator.

    The fourth and fifth verdicts are refusals, and the refusals are what this product
    is now built around, so a reviewer has to be able to press each of them.
    """
    from src.domain.incident_correlation import (
        AttributionRefusal,
        CommitRef,
        CorrelationVerdict,
        IncidentCorrelator,
    )

    times = _log(600, 400, 20, 15, 10, 5)
    commits = [CommitRef(f"sha{i:04d}", "m", "dev", at) for i, at in enumerate(times)]
    correlator = IncidentCorrelator()
    adapter = offline_adapter()

    def verdict_for(name):
        series = adapter.get_error_series(name, anchor_at=max(times), commit_times=times)
        return correlator.correlate(name, series, commits)

    assert verdict_for("checkout-api").verdict is CorrelationVerdict.ANOMALY_ATTRIBUTED
    assert verdict_for("payments-worker").verdict is CorrelationVerdict.NO_ANOMALY
    assert verdict_for("quiet-service").verdict is CorrelationVerdict.INSUFFICIENT_DATA

    unattributed = verdict_for("search-indexer")
    assert unattributed.verdict is CorrelationVerdict.ANOMALY_WITHOUT_ATTRIBUTION
    assert unattributed.attribution_refusal is AttributionRefusal.NO_CANDIDATE_IN_WINDOW

    crowded = verdict_for("release-train")
    assert crowded.verdict is CorrelationVerdict.ANOMALY_WITHOUT_ATTRIBUTION
    assert crowded.attribution_refusal is AttributionRefusal.WINDOW_TOO_CROWDED
