"""Unit tests for the AWS Cost Explorer and CloudWatch adapters.

The boto3 clients are replaced by stubs that return the response shapes AWS
documents, so the adapters' parsing and reduction run for real.
"""
import json
from datetime import date, datetime, timedelta, timezone

import pytest

from src.domain.provenance import DataSource
from src.infrastructure.aws_cost_adapter import FIXTURE_PATH, AWSCostAdapter
from src.infrastructure.cloudwatch_adapter import CloudWatchMetricAdapter


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


def test_empty_cloudwatch_response_falls_back_and_says_why():
    stub = StubCloudWatch([])
    series = CloudWatchMetricAdapter(client=stub).get_error_series("checkout-api")
    assert series.provenance.is_live is False
    assert "returned no datapoints" in series.provenance.detail


def test_cloudwatch_failure_falls_back_and_names_the_error():
    stub = StubCloudWatch(None, error=RuntimeError("ThrottlingException"))
    series = CloudWatchMetricAdapter(client=stub).get_error_series("checkout-api")
    assert series.provenance.is_live is False
    assert "ThrottlingException" in series.provenance.detail


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
    assert "flat and healthy" in series.provenance.detail


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
