"""The hybrid board: per-adapter live switches, the production rows, caches, sanitizer.

``MERCURY_OFFLINE=1`` still makes every adapter a fixture. ``MERCURY_LIVE_CLOUDWATCH=1``
re-opens CloudWatch for the three allow-listed production functions only, and
``MERCURY_LIVE_GITHUB=1`` re-opens the DORA report and the pull request radar only.
Nothing here touches the network: CloudWatch is a stub, GitHub is an
``httpx.MockTransport``, and the served page is read through FastAPI's TestClient.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from botocore.exceptions import ClientError

from src.application.diagnose_incident_use_case import DiagnoseIncidentUseCase
from src.domain.incident_correlation import (
    REFUSAL_MUST_NOT_CLAIM,
    CorrelationVerdict,
    IncidentCorrelator,
    MetricPoint,
    MetricSeries,
)
from src.domain.provenance import DataSource, Provenance
from src.infrastructure import cloudwatch_adapter as cloudwatch_module
from src.infrastructure import github_adapter as github_module
from src.infrastructure.aws_cost_adapter import AWSCostAdapter
from src.infrastructure.cloudwatch_adapter import (
    LIVE_LAMBDA_PERIOD_SECONDS,
    LIVE_LAMBDA_WINDOW_MINUTES,
    LIVE_PRODUCTION_FUNCTIONS,
    SIMULATED_SERVICES,
    CloudWatchMetricAdapter,
)
from src.infrastructure.github_adapter import GitHubTelemetryAdapter
from src.infrastructure.offline_mode import live_cloudwatch_enabled, live_github_enabled
from src.infrastructure.safe_errors import describe_exception, scrub
from src.interfaces.live_rows import FIXTURE_ROW_NAMES, inject_live_rows

INDEX_HTML = Path(__file__).resolve().parents[2] / "docs" / "index.html"
ACCOUNT_ID = "123456789012"
# Built at runtime so no secret scanner mistakes the test input for a real key id.
FAKE_KEY_ID = "AKIA" + "EXAMPLE" + "0123456789"[:9]
TWELVE_DIGITS = re.compile(r"(?<!\d)\d{12}(?!\d)")
ACCESS_DENIED = (
    f"User: arn:aws:sts::{ACCOUNT_ID}:assumed-role/mercury-lambda-role-euw1-prod/"
    "mercury-wallboard-euw1-prod is not authorized to perform: cloudwatch:GetMetricStatistics "
    "because no identity-based policy allows the cloudwatch:GetMetricStatistics action"
)
ROW_BUTTON = re.compile(r'<button class="btn btn-demo board-grid" data-service="([^"]+)"')


def access_denied() -> ClientError:
    return ClientError(
        {
            "Error": {"Code": "AccessDenied", "Message": ACCESS_DENIED},
            "ResponseMetadata": {"RequestId": "0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0", "HTTPStatusCode": 403},
        },
        "GetMetricStatistics",
    )


def assert_nothing_identifying(text: str) -> None:
    assert ACCOUNT_ID not in text
    assert not TWELVE_DIGITS.search(text), TWELVE_DIGITS.search(text)
    assert "arn:aws" not in text.lower()
    assert "assumed-role" not in text


class LambdaStub:
    """A CloudWatch client with hourly Errors and Invocations for one function."""

    def __init__(self, errors=(0.0, 0.0, 0.0, 0.0), invocations=(5.0, 4.0, 6.0, 3.0), error=None):
        self.errors = errors
        self.invocations = invocations
        self.error = error
        self.calls: list[dict] = []

    def get_metric_statistics(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        values = self.errors if kwargs["MetricName"] == "Errors" else self.invocations
        end = datetime.now(timezone.utc)
        return {"Datapoints": [
            {"Timestamp": end - timedelta(hours=len(values) - index), "Sum": value}
            for index, value in enumerate(values)
        ]}


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def monotonic(self) -> float:
        return self.now


@pytest.fixture
def hybrid(monkeypatch):
    """The hybrid deployment's environment: offline, plus both live opt-ins."""
    monkeypatch.setenv("MERCURY_OFFLINE", "1")
    monkeypatch.setenv("MERCURY_LIVE_CLOUDWATCH", "1")
    monkeypatch.setenv("MERCURY_LIVE_GITHUB", "1")
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)


# ------------------------------------------------------------------- Switches

@pytest.mark.parametrize("value, expected", [
    ("1", True), ("true", True), ("ON", True), (" yes ", True),
    ("0", False), ("", False), ("off", False), ("live", False),
])
def test_live_switches_parse_like_the_offline_switch(monkeypatch, value, expected):
    monkeypatch.setenv("MERCURY_LIVE_CLOUDWATCH", value)
    monkeypatch.setenv("MERCURY_LIVE_GITHUB", value)
    assert live_cloudwatch_enabled() is expected
    assert live_github_enabled() is expected


def test_the_suite_runs_with_both_live_switches_off():
    assert live_cloudwatch_enabled() is False
    assert live_github_enabled() is False


# ------------------------------------------------------------ CloudWatch rows

def test_a_production_function_is_read_live_from_aws_lambda_under_the_hybrid(hybrid):
    stub = LambdaStub(errors=(0.0, 1.0, 0.0, 0.0), invocations=(10.0, 12.0, 9.0, 11.0))
    series = CloudWatchMetricAdapter(client=stub).get_error_series("volcan-mcp-euw1-prod")

    assert series.provenance.source is DataSource.AWS_CLOUDWATCH
    assert series.provenance.display_label == "LIVE"
    assert series.namespace == "AWS/Lambda" and series.metric_name == "Errors"
    assert [p.value for p in series.points] == [0.0, 1.0, 0.0, 0.0]
    assert [call["MetricName"] for call in stub.calls] == ["Errors", "Invocations"]
    for call in stub.calls:
        assert call["Namespace"] == "AWS/Lambda"
        assert call["Dimensions"] == [{"Name": "FunctionName", "Value": "volcan-mcp-euw1-prod"}]
        assert call["Period"] == LIVE_LAMBDA_PERIOD_SECONDS
        assert call["EndTime"] - call["StartTime"] == timedelta(minutes=LIVE_LAMBDA_WINDOW_MINUTES)
    detail = series.provenance.detail
    assert "1 errors in 42 invocations" in detail
    assert "not a simulated service" in detail
    assert series.provenance.observed_at_utc in detail


@pytest.mark.parametrize("service", sorted(SIMULATED_SERVICES))
def test_the_simulated_services_stay_fixtures_and_make_no_call_under_the_hybrid(hybrid, monkeypatch, service):
    stub = LambdaStub()
    hybrid_series = CloudWatchMetricAdapter(client=stub).get_error_series(service)
    monkeypatch.delenv("MERCURY_LIVE_CLOUDWATCH")
    offline_series = CloudWatchMetricAdapter(client=LambdaStub()).get_error_series(service)

    assert stub.calls == []
    assert hybrid_series.provenance.source is DataSource.OFFLINE_FIXTURE
    assert [p.value for p in hybrid_series.points] == [p.value for p in offline_series.points]


@pytest.mark.parametrize("service", ["quiet-service", "some-other-function", "mercury-wallboard-euw1-dev"])
def test_a_name_off_the_allow_list_is_never_sent_to_cloudwatch(hybrid, service):
    stub = LambdaStub()
    series = CloudWatchMetricAdapter(client=stub).get_error_series(service)
    assert stub.calls == []
    assert series.points == []
    assert series.provenance.source is DataSource.OFFLINE_FIXTURE


def test_offline_without_the_switch_reads_no_production_function(monkeypatch):
    monkeypatch.setenv("MERCURY_OFFLINE", "1")
    stub = LambdaStub()
    for name in LIVE_PRODUCTION_FUNCTIONS:
        series = CloudWatchMetricAdapter(client=stub).get_error_series(name)
        assert series.points == [] and series.provenance.is_live is False
    assert stub.calls == []


def test_a_live_read_is_cached_with_its_original_read_time(hybrid, monkeypatch):
    clock = FakeClock()
    monkeypatch.setattr(cloudwatch_module, "time", clock)
    stub = LambdaStub()
    adapter = CloudWatchMetricAdapter(client=stub)

    first = adapter.get_error_series("aletheia-provenance-euw1-prod")
    clock.now += 30
    second = adapter.get_error_series("aletheia-provenance-euw1-prod")
    assert len(stub.calls) == 2, "the second read inside the window must not call CloudWatch"
    assert second is first
    assert second.provenance.observed_at_utc == first.provenance.observed_at_utc

    clock.now += 61
    adapter.get_error_series("aletheia-provenance-euw1-prod")
    assert len(stub.calls) == 4, "an expired read must go back to CloudWatch"

    adapter.invalidate_live_cache()
    adapter.get_error_series("aletheia-provenance-euw1-prod")
    assert len(stub.calls) == 6


def test_a_failed_live_read_is_cached_too(hybrid, monkeypatch):
    monkeypatch.setattr(cloudwatch_module, "time", FakeClock())
    stub = LambdaStub(error=access_denied())
    adapter = CloudWatchMetricAdapter(client=stub)
    first = adapter.get_error_series("mercury-wallboard-euw1-prod")
    adapter.get_error_series("mercury-wallboard-euw1-prod")
    assert first.provenance.source is DataSource.NO_LIVE_DATA
    assert len(stub.calls) == 1, "a missing IAM grant must not turn every page view into a call"


def test_no_invocations_is_no_live_data_and_says_so(hybrid):
    stub = LambdaStub(errors=(), invocations=())
    series = CloudWatchMetricAdapter(client=stub).get_error_series("volcan-mcp-euw1-prod")
    assert series.provenance.source is DataSource.NO_LIVE_DATA
    assert series.points == []
    assert "0 invocations" in series.provenance.detail


# ------------------------------------------------------------ The live row use case

class NoCommits:
    def list_recent_commits(self, limit=10):
        raise AssertionError("a live production row must never read the commit feed")


def _use_case(stub):
    return DiagnoseIncidentUseCase(
        CloudWatchMetricAdapter(client=stub), NoCommits(), correlator=IncidentCorrelator())


def test_a_live_row_is_never_attributed_to_a_commit(hybrid):
    correlation = _use_case(LambdaStub(errors=(1.0, 1.0, 1.0, 9.0))).execute("volcan-mcp-euw1-prod")
    assert correlation.verdict is CorrelationVerdict.ANOMALY_WITHOUT_ATTRIBUTION
    assert correlation.offending_commit is None
    assert correlation.can_attribute is False
    assert correlation.commit_provenance.source is DataSource.NO_LIVE_DATA
    assert "Attribution is not attempted" in correlation.commit_provenance.detail


def test_a_quiet_live_row_reads_as_no_anomaly(hybrid):
    correlation = _use_case(LambdaStub()).execute("mercury-wallboard-euw1-prod")
    assert correlation.verdict is CorrelationVerdict.NO_ANOMALY
    assert correlation.metric_provenance.display_label == "LIVE"


def test_errors_rising_from_a_zero_baseline_are_never_an_all_clear(hybrid):
    correlation = _use_case(LambdaStub(errors=(0.0, 0.0, 0.0, 4.0))).execute("aletheia-provenance-euw1-prod")
    assert correlation.verdict is CorrelationVerdict.ANOMALY_WITHOUT_ATTRIBUTION
    assert correlation.nothing_to_revert is False
    assert correlation.incident_detected is True
    statement = correlation.refusal_statement
    assert "rose from zero to 4" in statement
    for text in (statement, correlation.to_voice_summary(), correlation.explanation, correlation.handoff_fact):
        for forbidden in REFUSAL_MUST_NOT_CLAIM:
            assert not re.search(forbidden, " ".join(text.split()), re.IGNORECASE), (forbidden, text)


def test_the_zero_baseline_guard_leaves_a_real_baseline_alone(hybrid):
    correlation = _use_case(LambdaStub(errors=(2.0, 2.0, 2.0, 2.0))).execute("volcan-mcp-euw1-prod")
    assert correlation.verdict is CorrelationVerdict.NO_ANOMALY
    assert correlation.baseline_value == 2.0


@pytest.mark.parametrize("errors, run", [
    ((0.0, 5.0, 5.0), 2),
    ((0.0, 5.0, 5.0, 5.0), 3),
    ((0.0, 2.0, 3.0, 2.0, 2.0), 4),
], ids=["zeros-then-two", "zeros-then-three", "zeros-then-four"])
def test_errors_that_left_zero_some_readings_ago_are_never_an_all_clear(hybrid, errors, run):
    """A run of errors after only zeros is inside the correlator's trailing mean.

    Lambda reports Errors only for hours with invocations, so (0, 5, 5) is a real
    shape: the correlator compares 5 with the mean of (0, 5) and calls it normal. The
    readings before the rise were all zero, so the live row reports a zero baseline.
    """
    invocations = tuple(5.0 for _ in errors)
    correlation = _use_case(LambdaStub(errors=errors, invocations=invocations)).execute(
        "aletheia-provenance-euw1-prod")
    assert correlation.verdict is CorrelationVerdict.ANOMALY_WITHOUT_ATTRIBUTION
    assert correlation.nothing_to_revert is False
    assert correlation.incident_detected is True
    assert correlation.baseline_value == 0.0
    assert correlation.anomaly_factor == 0.0
    assert f"above zero for the last {run} readings" in correlation.refusal_statement
    for text in (correlation.refusal_statement, correlation.to_voice_summary(),
                 correlation.explanation, correlation.handoff_fact):
        assert "looks normal" not in text, text
        assert "Nothing to revert" not in text, text
        assert "in the newest reading" not in text, text  # the rise was earlier than that
        assert "No deploy feed is connected" in text, text


@pytest.mark.parametrize("errors", [
    (5.0, 5.0, 5.0),
    (2.0, 0.0, 2.0, 2.0),
    (0.0, 0.0, 0.0, 0.0),
], ids=["steady-errors", "errors-before-the-zeros", "quiet"])
def test_the_zero_run_guard_leaves_other_series_alone(hybrid, errors):
    """Errors with no zeros before them, or with errors among them, are not a zero baseline."""
    invocations = tuple(5.0 for _ in errors)
    correlation = _use_case(LambdaStub(errors=errors, invocations=invocations)).execute(
        "volcan-mcp-euw1-prod")
    assert correlation.verdict is CorrelationVerdict.NO_ANOMALY
    assert correlation.zero_baseline is False
    assert correlation.zero_run == 0


def test_a_zero_run_live_row_reads_as_cannot_attribute_on_every_surface(server, client):
    """The review's (0, 5, 5): route, brief and voice, with no ratio to a baseline of 2.5."""
    mcp_server, stub = server
    stub.errors = (0.0, 5.0, 5.0)
    stub.invocations = (5.0,) * 3
    service = "aletheia-provenance-euw1-prod"
    for body in _what_changed_both_ways(client, service):
        assert body["verdict"] == "ANOMALY_WITHOUT_ATTRIBUTION"
        assert body["attribution"]["nothing_to_revert"] is False
        assert body["attribution"]["refusal_reason"] == "NO_DEPLOY_FEED"
        assert "looks normal" not in body["voice_summary"]
        for text in (body["explanation"], body["voice_summary"],
                     body["attribution"]["refusal_statement"], body["attribution"]["handoff_fact"]):
            assert "2.50" not in text and "2.0x" not in text, text
    brief = client.post("/mcp/tools/agent_incident_brief",
                        json={"service_name": service, "prefer_bedrock": False}).json()
    syn = brief["agent_synthesis"]
    assert syn["incident_severity"] == "SEV-2_ATTRIBUTION_REFUSED"
    assert "Nothing to revert" not in syn["commander_brief_10ft"]
    assert "2.0x" not in syn["commander_brief_10ft"]


# ------------------------------------------------------------- Routes and page

@pytest.fixture
def server(hybrid, monkeypatch):
    """The module-level server with a stub CloudWatch client and fresh caches."""
    from src.interfaces import mcp_server

    stub = LambdaStub()
    monkeypatch.setattr(mcp_server.cloudwatch_adapter, "_client", stub)
    mcp_server.cloudwatch_adapter.invalidate_live_cache()
    mcp_server.github_adapter.invalidate_cache()
    yield mcp_server, stub
    mcp_server.cloudwatch_adapter.invalidate_live_cache()
    mcp_server.github_adapter.invalidate_cache()


def test_the_live_row_route_is_labelled_live_and_offers_no_rollback(server, client):
    body = client.post("/mcp/tools/what_changed", json={"service_name": "volcan-mcp-euw1-prod"}).json()
    assert body["metric_provenance"]["display_label"] == "LIVE"
    assert body["metric_provenance"]["data_source"] == "aws-cloudwatch"
    assert body["commit_provenance"]["display_label"] == "NO LIVE DATA"
    assert body["offending_commit"] is None
    assert body["recommended_action"] is None


def test_the_rollback_demo_survives_the_hybrid(server, client, monkeypatch):
    hybrid_body = client.post("/mcp/tools/what_changed", json={"service_name": "checkout-api"}).json()
    monkeypatch.delenv("MERCURY_LIVE_CLOUDWATCH")
    monkeypatch.delenv("MERCURY_LIVE_GITHUB")
    offline_body = client.post("/mcp/tools/what_changed", json={"service_name": "checkout-api"}).json()

    assert hybrid_body["metric_provenance"]["display_label"] == "OFFLINE FIXTURE"
    assert hybrid_body["verdict"] == offline_body["verdict"]
    assert hybrid_body["offending_commit"] == offline_body["offending_commit"]
    assert hybrid_body["commit_provenance"]["data_source"] == offline_body["commit_provenance"]["data_source"]
    assert (hybrid_body["recommended_action"] is None) is (offline_body["recommended_action"] is None)


def test_the_page_is_unchanged_without_the_switch(client, monkeypatch):
    monkeypatch.setenv("MERCURY_OFFLINE", "1")
    page = client.get("/").text
    assert ROW_BUTTON.findall(page) == ROW_BUTTON.findall(INDEX_HTML.read_text(encoding="utf-8"))
    assert "row-stamp" not in page and "mercury-live-rows" not in page


def test_the_hybrid_page_carries_three_live_rows_beside_five_fixture_rows(server, client):
    page = client.get("/").text
    services = ROW_BUTTON.findall(page)
    assert services == [*FIXTURE_ROW_NAMES, *LIVE_PRODUCTION_FUNCTIONS]
    assert page.count('<span class="tag tag-fixture">Fixture</span>') == len(FIXTURE_ROW_NAMES)
    live_stamps = re.findall(r'<span class="tag tag-live">Live (\d\d:\d\dZ)</span>', page)
    assert len(live_stamps) == len(LIVE_PRODUCTION_FUNCTIONS)
    assert page.count('data-row-source="aws-cloudwatch"') == len(LIVE_PRODUCTION_FUNCTIONS)
    assert 'id="mercury-live-rows"' in page
    # Two reads per function for the page, then the rows' own what_changed reuse them.
    _, stub = server
    assert len(stub.calls) == 2 * len(LIVE_PRODUCTION_FUNCTIONS)
    client.post("/mcp/tools/what_changed", json={"service_name": LIVE_PRODUCTION_FUNCTIONS[0]})
    assert len(stub.calls) == 2 * len(LIVE_PRODUCTION_FUNCTIONS)


def test_every_static_row_the_injection_needs_is_in_the_page():
    page = INDEX_HTML.read_text(encoding="utf-8")
    for name in FIXTURE_ROW_NAMES:
        assert f'data-service="{name}"' in page
        assert f'<span class="row-service">{name}</span>' in page


def test_injection_degrades_to_the_original_page_when_a_row_is_missing():
    page = INDEX_HTML.read_text(encoding="utf-8").replace('data-service="quiet-service"', 'data-service="gone"')
    assert inject_live_rows(page, []) == page


def test_health_reports_each_source(server, client):
    sources = client.get("/health").json()["live_sources"]
    assert sources["offline_mode"] is True
    assert sources["cloudwatch_production_rows"] == list(LIVE_PRODUCTION_FUNCTIONS)
    assert sources["cloudwatch_simulated_services"] == "offline-fixture"
    assert sources["github_dora_and_pr_radar"] is True
    assert sources["github_commit_feed"] is False
    assert sources["cost_explorer"] == "offline-fixture"


def test_the_mcp_instructions_follow_the_switches(server, client):
    body = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}).json()
    instructions = body["result"]["instructions"]
    assert "production Lambda rows are read live from CloudWatch" in instructions
    assert "cost report are offline fixtures" in instructions
    assert "The public data is an offline fixture" not in instructions


# --------------------------------------------------------------- Cost Explorer

class CostStub:
    def __init__(self) -> None:
        self.calls = 0

    def get_cost_and_usage(self, **kwargs):
        self.calls += 1
        return {"ResultsByTime": []}


def test_cost_explorer_stays_a_fixture_with_every_live_switch_on(hybrid):
    stub = CostStub()
    report = AWSCostAdapter(client=stub).fetch_cost_report()
    assert stub.calls == 0
    assert report.provenance.source is DataSource.OFFLINE_FIXTURE


# ---------------------------------------------------------------------- GitHub

def _dora_routes(recorder, status=200):
    def respond(payload):
        return lambda request: httpx.Response(status, json=payload if status == 200 else {"message": "Not Found"})

    handlers = {
        "/repos/acme/widgets": respond({"default_branch": "main"}),
        "/repos/acme/widgets/actions/runs": respond({"workflow_runs": []}),
        "/repos/acme/widgets/pulls": respond([]),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        recorder.append(request)
        return handlers.get(request.url.path, respond({}))(request)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_the_github_switch_opens_dora_but_not_the_commit_feed(hybrid, monkeypatch):
    adapter = GitHubTelemetryAdapter(repository="acme/widgets")
    assert adapter.can_call_live is True
    assert adapter.can_list_commits_live is False
    monkeypatch.setattr(adapter, "_get", lambda *a, **k: pytest.fail("the commit feed called GitHub"))
    assert adapter.list_recent_commits() == []


def test_anonymous_requests_carry_no_authorization_header(hybrid):
    seen: list[httpx.Request] = []
    adapter = GitHubTelemetryAdapter(token="", repository="acme/widgets", client=_dora_routes(seen))
    report = adapter.get_metrics_raw()
    assert report.provenance.source is DataSource.GITHUB_API
    assert seen and all("authorization" not in request.headers for request in seen)


def test_live_github_answers_are_cached(hybrid, monkeypatch):
    clock = FakeClock()
    monkeypatch.setattr(github_module, "time", clock)
    seen: list[httpx.Request] = []
    adapter = GitHubTelemetryAdapter(token="", repository="acme/widgets", client=_dora_routes(seen))

    first = adapter.get_metrics_raw()
    adapter.get_pr_radar()
    calls = len(seen)
    clock.now += 600
    assert adapter.get_metrics_raw() is first
    adapter.get_pr_radar()
    assert len(seen) == calls, "a cached answer must not spend the anonymous rate limit"

    clock.now += 301
    adapter.get_metrics_raw()
    assert len(seen) > calls, "an expired answer must go back to GitHub"


@pytest.mark.parametrize("status, words", [(404, "HTTP 404, not found, or not public"),
                                           (403, "HTTP 403, forbidden, or the anonymous rate limit")])
def test_a_private_or_rate_limited_repo_falls_back_to_the_labelled_fixture(hybrid, monkeypatch, status, words):
    monkeypatch.setattr(github_module, "time", FakeClock())
    seen: list[httpx.Request] = []
    adapter = GitHubTelemetryAdapter(token="", repository="acme/widgets", client=_dora_routes(seen, status))
    report = adapter.get_metrics_raw()
    assert report.provenance.display_label == "OFFLINE FIXTURE"
    assert words in report.provenance.detail
    assert "anonymous request" in report.provenance.detail
    adapter.get_metrics_raw()
    assert len(seen) == 1, "a refused anonymous read is cached, not retried per page view"


# ------------------------------------------------------------------- Sanitizer

def test_an_access_denied_keeps_its_code_and_loses_the_account():
    text = describe_exception(access_denied())
    assert text.startswith("ClientError: AccessDenied")
    assert_nothing_identifying(text)
    assert "0f1e2d3c" not in text


def test_scrub_removes_every_identifier_shape():
    raw = (
        f"arn:aws:iam::{ACCOUNT_ID}:role/x account {ACCOUNT_ID} key {FAKE_KEY_ID} "
        "RequestId: 9f8e7d6c-5b4a-3928-1706-f5e4d3c2b1a0 token ghp_" + "x" * 36 + " "
        "owner someone@example.com"
    )
    assert len(FAKE_KEY_ID) == 20
    cleaned = scrub(raw, limit=1000)
    assert_nothing_identifying(cleaned)
    for leaked in (FAKE_KEY_ID, "9f8e7d6c", "ghp_", "someone@example.com"):
        assert leaked not in cleaned


def test_an_unknown_exception_keeps_its_class_and_a_scrubbed_message():
    assert describe_exception(RuntimeError("ThrottlingException")) == "RuntimeError: ThrottlingException"
    text = describe_exception(RuntimeError(ACCESS_DENIED))
    assert text.startswith("RuntimeError: ")
    assert_nothing_identifying(text)


@pytest.mark.parametrize("error", [access_denied(), RuntimeError(ACCESS_DENIED)], ids=["client-error", "plain"])
def test_an_access_denied_never_reaches_any_response(server, client, error):
    mcp_server, stub = server
    stub.error = error
    responses = [
        client.post("/mcp/tools/what_changed", json={"service_name": name}).text
        for name in LIVE_PRODUCTION_FUNCTIONS
    ]
    responses.append(client.get("/").text)
    responses.append(client.get("/health").text)
    responses.append(client.post("/mcp", json={
        "jsonrpc": "2.0", "id": 2, "method": "tools/call",
        "params": {"name": "what_changed", "arguments": {"service_name": LIVE_PRODUCTION_FUNCTIONS[1]}},
    }).text)
    assert stub.calls, "the failing client was never asked"
    body = json.loads(responses[0])
    assert body["metric_provenance"]["display_label"] == "NO LIVE DATA"
    assert "CloudWatch call failed" in body["metric_provenance"]["detail"]
    for text in responses:
        assert_nothing_identifying(text)


def test_a_github_failure_never_reaches_the_dora_route(server, client, monkeypatch):
    mcp_server, _ = server

    def refuse(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"message": ACCESS_DENIED})

    monkeypatch.setattr(mcp_server.github_adapter, "_client", httpx.Client(transport=httpx.MockTransport(refuse)))
    text = client.post("/mcp/tools/get_dora_velocity_report").text
    assert json.loads(text)["provenance"]["display_label"] == "OFFLINE FIXTURE"
    assert "HTTP 403" in text
    assert_nothing_identifying(text)


def test_a_cost_explorer_failure_is_sanitized(monkeypatch):
    monkeypatch.delenv("MERCURY_OFFLINE", raising=False)

    class Refusing:
        def get_cost_and_usage(self, **kwargs):
            raise ClientError({"Error": {"Code": "AccessDeniedException", "Message": ACCESS_DENIED}},
                              "GetCostAndUsage")

    detail = AWSCostAdapter(client=Refusing()).fetch_cost_report().provenance.detail
    assert "AccessDeniedException" in detail
    assert_nothing_identifying(detail)


def test_a_failing_mcp_tool_call_is_sanitized(client, monkeypatch):
    from src.interfaces import mcp_server

    async def explode():
        raise RuntimeError(ACCESS_DENIED)

    monkeypatch.setattr(mcp_server, "get_dora_velocity_report", explode)
    body = client.post("/mcp", json={
        "jsonrpc": "2.0", "id": 3, "method": "tools/call",
        "params": {"name": "get_dora_velocity_report", "arguments": {}},
    }).json()
    assert body["result"]["isError"] is True
    assert_nothing_identifying(json.dumps(body))


def test_a_live_row_stamp_comes_from_the_read_not_from_the_row(hybrid):
    """The LIVE stamp is chosen from the reading's provenance, so a fixture cannot wear it."""
    series = MetricSeries(
        metric_name="Errors", namespace="AWS/Lambda",
        points=[MetricPoint(at=datetime.now(timezone.utc), value=0.0)],
        provenance=Provenance(DataSource.OFFLINE_FIXTURE, "fixture", ""),
    )
    page = inject_live_rows(INDEX_HTML.read_text(encoding="utf-8"), [("volcan-mcp-euw1-prod", series)])
    assert 'data-row-source="offline-fixture"' in page
    assert '<span class="tag tag-live">Live' not in page
    assert '<span class="tag">Not read</span>' in page


# ------------------------------------------------- Review round, 2026-10-19 (PR #67)

#: Every way a text has described a deploy window Mercury never read for a live row: the
#: server's sentences ("no commit landed"), the board's frozen hero branch ("no change in
#: the window", "window empty"), the agent brief's count ("Commits in window") and the
#: wire's causality statement ("the sole deploy candidate in the configured time window").
DEPLOY_WINDOW_WORDS = re.compile(
    r"no (?:commit|change)s? landed|no change in the window|window empty|empty window"
    r"|commits? in (?:the )?window|sole deploy candidate",
    re.IGNORECASE,
)


def _live_row_texts(correlation) -> dict[str, str | None]:
    return {
        "explanation": correlation.explanation,
        "refusal_statement": correlation.refusal_statement,
        "voice_summary": correlation.to_voice_summary(),
        "handoff_fact": correlation.handoff_fact,
    }


@pytest.mark.parametrize("errors", [
    (1.0, 0.0, 0.0, 0.0, 0.0, 1.0),
    (0.0, 0.0, 0.0, 0.0, 1.0, 1.0),
    (0.0, 0.0, 0.0, 4.0),
    (0.0, 5.0, 5.0),
    (0.0, 5.0, 5.0, 5.0),
    (0.0, 0.0, 0.0, 0.0),
    (2.0,),
], ids=["spike-after-one", "spike-from-zero-onset", "zero-baseline", "zero-run-of-two",
        "zero-run-of-three", "quiet", "one-reading"])
def test_no_live_row_text_describes_a_deploy_window_mercury_never_read(hybrid, errors):
    """Mercury never read these functions' deploys, so no text may say none landed."""
    invocations = tuple(5.0 for _ in errors)
    correlation = _use_case(LambdaStub(errors=errors, invocations=invocations)).execute("volcan-mcp-euw1-prod")
    texts = _live_row_texts(correlation)
    for name, text in texts.items():
        if text is None:
            continue
        assert not DEPLOY_WINDOW_WORDS.search(text), (name, text)
    assert "No deploy feed is connected" in texts["explanation"]
    assert "No deploy feed is connected" in texts["voice_summary"]
    assert "No deploy feed is connected" in texts["handoff_fact"]
    if correlation.verdict is not CorrelationVerdict.NO_ANOMALY:
        assert "No deploy feed is connected" in texts["refusal_statement"]
    for text in texts.values():
        for forbidden in REFUSAL_MUST_NOT_CLAIM:
            assert text is None or not re.search(forbidden, " ".join(text.split()), re.IGNORECASE)


def test_the_anomaly_series_from_the_review_are_anomalies(hybrid):
    """The two review series really reach the anomaly verdict whose wording was wrong."""
    for errors in ((1.0, 0.0, 0.0, 0.0, 0.0, 1.0), (0.0, 0.0, 0.0, 0.0, 1.0, 1.0)):
        correlation = _use_case(LambdaStub(errors=errors, invocations=(5.0,) * 6)).execute("volcan-mcp-euw1-prod")
        assert correlation.verdict is CorrelationVerdict.ANOMALY_WITHOUT_ATTRIBUTION


def test_the_live_row_route_never_says_no_change_landed(server, client):
    mcp_server, stub = server
    stub.errors = (1.0, 0.0, 0.0, 0.0, 0.0, 1.0)
    stub.invocations = (5.0,) * 6
    body = client.post("/mcp/tools/what_changed", json={"service_name": "volcan-mcp-euw1-prod"}).json()
    assert body["verdict"] == "ANOMALY_WITHOUT_ATTRIBUTION"
    for text in (body["explanation"], body["voice_summary"], body["attribution"]["refusal_statement"],
                 body["attribution"]["handoff_fact"]):
        assert not DEPLOY_WINDOW_WORDS.search(text), text
        assert "No deploy feed is connected" in text


def _what_changed_both_ways(client, service: str) -> list[dict]:
    """The same answer over REST and over MCP tools/call, as an agent would read it."""
    rest = client.post("/mcp/tools/what_changed", json={"service_name": service}).json()
    rpc = client.post("/mcp", json={
        "jsonrpc": "2.0", "id": 7, "method": "tools/call",
        "params": {"name": "what_changed", "arguments": {"service_name": service}},
    }).json()
    return [rest, rpc["result"]["structuredContent"]]


@pytest.mark.parametrize("errors", [
    (1.0, 0.0, 0.0, 0.0, 0.0, 1.0),
    (0.0, 0.0, 0.0, 0.0, 1.0, 1.0),
    (0.0, 0.0, 0.0, 0.0, 0.0, 4.0),
    (0.0, 5.0, 5.0),
    (0.0, 5.0, 5.0, 5.0),
], ids=["spike-after-one", "spike-from-zero-onset", "zero-baseline", "zero-run-of-two",
        "zero-run-of-three"])
def test_a_live_row_answer_withdraws_every_window_field(server, client, errors):
    """The wire fields of a live anomaly describe no window check, because none happened.

    Before the fix an MCP client read refusal_reason NO_CANDIDATE_IN_WINDOW ("nothing
    landed inside the window"), commits_in_window 0, claim_strength
    TEMPORAL_CANDIDATE_ONLY with "the sole deploy candidate in the configured time
    window", and no blocked_reason, so the board fell back to "the correlator refusing,
    not a missing feature".
    """
    mcp_server, stub = server
    stub.errors = errors
    stub.invocations = (5.0,) * len(errors)
    for body in _what_changed_both_ways(client, "volcan-mcp-euw1-prod"):
        attribution = body["attribution"]
        assert body["verdict"] == "ANOMALY_WITHOUT_ATTRIBUTION"
        assert attribution["refusal_reason"] == "NO_DEPLOY_FEED"
        assert attribution["commits_in_window"] is None
        assert attribution["commits_set_aside"] is None
        assert attribution["claim_strength"] == "NO_ATTRIBUTION_ATTEMPTED"
        assert "No deploy feed is connected" in attribution["causality_statement"]
        blocked = body["deployment_evidence"]["blocked_reason"]
        assert blocked and "no deploy feed" in blocked.lower()
        for text in (attribution["causality_statement"], blocked, body["explanation"]):
            assert not DEPLOY_WINDOW_WORDS.search(text), text
        assert "NO_CANDIDATE_IN_WINDOW" not in json.dumps(body)
        assert "TEMPORAL_CANDIDATE_ONLY" not in json.dumps(body)


def test_a_quiet_live_row_carries_no_window_fields_either(server, client):
    for body in _what_changed_both_ways(client, "mercury-wallboard-euw1-prod"):
        assert body["verdict"] == "NO_ANOMALY"
        assert body["attribution"]["refusal_reason"] is None
        assert body["attribution"]["commits_in_window"] is None
        assert body["attribution"]["claim_strength"] == "NO_ATTRIBUTION_ATTEMPTED"


def test_a_fixture_row_keeps_its_window_fields(server, client):
    """The live-row withdrawal must not leak onto the simulated services."""
    for body in _what_changed_both_ways(client, "checkout-api"):
        assert body["attribution"]["claim_strength"] == "TEMPORAL_CANDIDATE_ONLY"
        assert isinstance(body["attribution"]["commits_in_window"], int)
        assert "sole deploy candidate" in body["attribution"]["causality_statement"]


@pytest.mark.parametrize("errors", [
    (1.0, 0.0, 0.0, 0.0, 0.0, 1.0),
    (0.0, 0.0, 0.0, 0.0, 1.0, 1.0),
    (0.0, 0.0, 0.0, 0.0, 0.0, 4.0),
    (0.0, 5.0, 5.0),
    (0.0, 5.0, 5.0, 5.0),
], ids=["spike-after-one", "spike-from-zero-onset", "zero-baseline", "zero-run-of-two",
        "zero-run-of-three"])
def test_the_agent_brief_for_a_live_row_counts_no_commits(server, client, errors):
    """No commit was read for a live row, so its brief gives no count and no window code."""
    mcp_server, stub = server
    stub.errors = errors
    stub.invocations = (5.0,) * len(errors)
    body = client.post("/mcp/tools/agent_incident_brief",
                       json={"service_name": "volcan-mcp-euw1-prod", "prefer_bedrock": False}).json()
    assert body["data_label"] == "LIVE"
    syn = body["agent_synthesis"]
    assert syn["incident_severity"] == "SEV-2_ATTRIBUTION_REFUSED"
    draft = syn["responder_handoff_draft"]
    texts = [syn["commander_brief_10ft"], syn["root_cause_hypothesis"], draft["current_action"],
             *draft["confirmed_facts"]]
    for text in texts:
        assert "Commits in window" not in text, text
        assert "NO_CANDIDATE_IN_WINDOW" not in text, text
        assert not DEPLOY_WINDOW_WORDS.search(text), text
        assert "rose 0.0x" not in text, text  # a zero baseline has no ratio
    assert "No deploy feed is connected" in syn["commander_brief_10ft"]


def test_a_demo_handoff_for_a_live_row_is_refused_as_unavailable_not_as_a_race(client):
    from src.interfaces.handoff_routes import DEMO_HANDOFF_UNAVAILABLE

    refused = client.post("/mcp/tools/demo_update_handoff",
                          json={"service_name": "volcan-mcp-euw1-prod", "expected_revision": 0})
    assert refused.status_code == 422, refused.text
    assert refused.json()["detail"] == DEMO_HANDOFF_UNAVAILABLE


def test_the_demo_handoff_race_is_still_a_409(client):
    from src.infrastructure.demo_evidence import seed_recorded_demo_evidence
    from src.interfaces.mcp_server import deployment_evidence, incident_use_case

    seed_recorded_demo_evidence(incident_use_case, deployment_evidence)
    revision = client.get("/mcp/demo-handoff/revision").json()["revision"]
    first = client.post("/mcp/tools/demo_update_handoff", json={"expected_revision": revision})
    assert first.status_code == 200, first.text
    stale = client.post("/mcp/tools/demo_update_handoff", json={"expected_revision": revision})
    assert stale.status_code == 409, stale.text


def test_the_mcp_demo_handoff_for_a_live_row_is_an_honest_tool_error(client):
    from src.interfaces.handoff_routes import DEMO_HANDOFF_UNAVAILABLE

    body = client.post("/mcp", json={
        "jsonrpc": "2.0", "id": 4, "method": "tools/call",
        "params": {"name": "demo_update_handoff", "arguments": {"service_name": "volcan-mcp-euw1-prod"}},
    }).json()
    assert body["result"]["isError"] is True
    assert body["result"]["content"][0]["text"] == DEMO_HANDOFF_UNAVAILABLE
    assert "TypeError" not in json.dumps(body)


class SlowLambdaStub(LambdaStub):
    """A CloudWatch that does not answer until it is released (or ``delay`` passes)."""

    def __init__(self, delay: float) -> None:
        import threading

        super().__init__()
        self.delay = delay
        self.release = threading.Event()

    def get_metric_statistics(self, **kwargs):
        self.release.wait(self.delay)
        return super().get_metric_statistics(**kwargs)


def _wait_for_background_reads(adapter, timeout: float = 10.0) -> None:
    """Block until every production read the page left running has written its answer.

    The page does not join its reads, so without this they finish after the test and
    write into the shared adapter's cache after the next test has reset it.
    """
    import time as _time

    deadline = _time.monotonic() + timeout
    while _time.monotonic() < deadline:
        cached = [adapter.cached_live_series(name) for name in LIVE_PRODUCTION_FUNCTIONS]
        if all(s is not None and s.provenance.source is DataSource.AWS_CLOUDWATCH for s in cached):
            return
        _time.sleep(0.02)
    raise AssertionError("the background CloudWatch reads did not finish")


def test_the_page_does_not_wait_for_a_slow_cloudwatch(server, client, monkeypatch):
    import time as _time

    from src.interfaces import live_rows

    mcp_server, _ = server
    slow = SlowLambdaStub(delay=30.0)
    monkeypatch.setattr(mcp_server.cloudwatch_adapter, "_client", slow)
    monkeypatch.setattr(live_rows, "PAGE_READ_DEADLINE_SECONDS", 0.3)
    try:
        started = _time.monotonic()
        page = client.get("/").text
        elapsed = _time.monotonic() - started
        assert elapsed < 0.3 + 0.6, f"the page waited {elapsed:.2f} s for CloudWatch"
        assert page.count('<span class="tag">Not read</span>') == len(LIVE_PRODUCTION_FUNCTIONS)
        assert 'data-row-source="no-live-data"' in page
        # The not-read rows are remembered, so the board's own question is answered at
        # once from that memory instead of waiting on CloudWatch again.
        started = _time.monotonic()
        body = client.post("/mcp/tools/what_changed", json={"service_name": "volcan-mcp-euw1-prod"}).json()
        assert _time.monotonic() - started < 0.6
        assert body["metric_provenance"]["display_label"] == "NO LIVE DATA"
        assert "did not answer within" in body["metric_provenance"]["detail"]
        assert_nothing_identifying(body["metric_provenance"]["detail"])
    finally:
        slow.release.set()
        _wait_for_background_reads(mcp_server.cloudwatch_adapter)
        mcp_server.cloudwatch_adapter.invalidate_live_cache()


def test_a_read_that_did_not_answer_is_remembered_for_thirty_seconds(hybrid, monkeypatch):
    clock = FakeClock()
    monkeypatch.setattr(cloudwatch_module, "time", clock)
    stub = LambdaStub()
    adapter = CloudWatchMetricAdapter(client=stub)

    unread = adapter.mark_unread("volcan-mcp-euw1-prod", 4.0)
    assert unread.provenance.source is DataSource.NO_LIVE_DATA
    assert unread.provenance.detail.startswith(cloudwatch_module.UNREAD_REASON_PREFIX)
    assert cloudwatch_module.UNREAD_CACHE_SECONDS == 30.0

    clock.now += 29
    assert adapter.get_error_series("volcan-mcp-euw1-prod") is unread
    assert stub.calls == [], "a remembered not-read row must not call CloudWatch"

    # Shorter than a real read's 60 s: a slow CloudWatch is asked again after 30 s.
    clock.now += 2
    again = adapter.get_error_series("volcan-mcp-euw1-prod")
    assert again.provenance.source is DataSource.AWS_CLOUDWATCH
    assert len(stub.calls) == 2


def test_a_read_that_answered_just_after_the_deadline_is_not_hidden(hybrid, monkeypatch):
    """The read finished between the page giving up and the not-read mark."""
    monkeypatch.setattr(cloudwatch_module, "time", FakeClock())
    adapter = CloudWatchMetricAdapter(client=LambdaStub())
    answered = adapter.get_error_series("aletheia-provenance-euw1-prod")

    kept = adapter.mark_unread("aletheia-provenance-euw1-prod", 4.0)
    assert kept is answered
    assert adapter.cached_live_series("aletheia-provenance-euw1-prod") is answered


def test_the_cloudwatch_client_gives_up_quickly(monkeypatch):
    """botocore's 60 s defaults and legacy retries could outlive the Lambda's 30 s."""
    import boto3

    built: dict = {}

    class FakeSession:
        def get_credentials(self):
            return object()

        def client(self, service, **kwargs):
            built.update(kwargs, service=service)
            return object()

    monkeypatch.setattr(boto3.session, "Session", FakeSession)
    CloudWatchMetricAdapter()._resolve_client()
    config = built["config"]
    assert built["service"] == "cloudwatch"
    assert config.connect_timeout == 2
    assert config.read_timeout == 3
    assert config.retries == {"max_attempts": 1}


def test_the_prompt_says_a_live_row_is_a_live_reading(server, client):
    from src.infrastructure.bedrock_incident_agent import BedrockIncidentAgentAdapter

    class Capture:
        def __init__(self) -> None:
            self.prompts: list[str] = []
            outer = self

            class Messages:
                def create(self, **kwargs):
                    outer.prompts.append(kwargs["messages"][0]["content"])
                    return {"content": [{"type": "text", "text": json.dumps({"commander_brief_10ft": "x"})}]}

            self.messages = Messages()

    for label, service in (("LIVE", "volcan-mcp-euw1-prod"), ("OFFLINE FIXTURE", "checkout-api")):
        capture = Capture()
        adapter = BedrockIncidentAgentAdapter(client_factory=lambda region, c=capture: c)
        payload = client.post("/mcp/tools/what_changed", json={"service_name": service}).json()
        assert payload["metric_provenance"]["display_label"] == label
        adapter.synthesize_incident_brief(what_changed_payload=payload, data_label=label,
                                          rollback_dispatch="record-only")
        prompt = capture.prompts[0]
        if label == "LIVE":
            assert "not a reading of a real service" not in prompt
            assert "live CloudWatch reading of the team's own Lambda function volcan-mcp-euw1-prod" in prompt
            assert "No deploy feed is connected" in prompt
        else:
            assert "it is not a reading of a real service" in prompt
        assert "Do not claim a cause" in prompt and "record-only" in prompt


def test_the_deck_note_is_true_for_a_fixture_and_for_a_live_row():
    from src.interfaces.agent_deck import AGENT_DECK_JS

    assert "its data is the board" not in AGENT_DECK_JS
    note = re.search(r"'Nothing here runs until.*?stay in charge\.'", AGENT_DECK_JS, re.DOTALL).group(0)
    assert "OFFLINE FIXTURE for a" in note and "simulated service" in note
    assert "the label says whether CloudWatch was read" in note
    # The deck's static text never says "live": the switch-off page has no live data,
    # and tests/ux/test_agent_deck_in_browser.py holds the rendered deck to the same.
    assert not re.search(r"\blive\b", note, re.IGNORECASE), note


def test_the_deck_scrolls_a_new_card_without_moving_focus():
    """The browser suite measures it; this pins the mechanism where it cannot run."""
    from src.interfaces.agent_deck import AGENT_DECK_JS

    assert "function revealCard(card, upTo)" in AGENT_DECK_JS
    assert "revealCard(card, brief);" in AGENT_DECK_JS
    assert "revealCard(card);" in AGENT_DECK_JS  # the error card
    assert "querySelector('.keybar')" in AGENT_DECK_JS
    assert ".focus(" not in AGENT_DECK_JS


# ------------------------------------------------- Review round 1 repairs, 2026-10-19

class CannedModel:
    """A model client that records the prompt and answers with a fixed brief."""

    def __init__(self, brief: str) -> None:
        self.prompts: list[str] = []
        outer = self

        class Messages:
            def create(self, **kwargs):
                outer.prompts.append(kwargs["messages"][0]["content"])
                return {"content": [{"type": "text", "text": json.dumps({"commander_brief_10ft": brief})}]}

        self.messages = Messages()


def _model_brief(client, service: str, reply: str):
    from src.infrastructure.bedrock_incident_agent import BedrockIncidentAgentAdapter

    model = CannedModel(reply)
    adapter = BedrockIncidentAgentAdapter(client_factory=lambda region: model)
    payload = client.post("/mcp/tools/what_changed", json={"service_name": service}).json()
    result = adapter.synthesize_incident_brief(
        what_changed_payload=payload, data_label=payload["metric_provenance"]["display_label"],
        rollback_dispatch="record-only")
    return model.prompts[0], result


@pytest.mark.parametrize("errors", [
    (1.0, 0.0, 0.0, 0.0, 0.0, 1.0),
    (0.0, 0.0, 0.0, 0.0, 0.0, 4.0),
    (0.0, 0.0, 0.0, 0.0),
], ids=["spike-after-one", "zero-baseline", "quiet"])
def test_the_prompt_for_a_live_row_hands_the_model_no_commit_window(server, client, errors):
    """No commit was read for a live row, so the model is given no count and no window rule."""
    mcp_server, stub = server
    stub.errors = errors
    stub.invocations = (5.0,) * len(errors)
    prompt, _ = _model_brief(client, "volcan-mcp-euw1-prod", "x")
    assert "commits_in_window" not in prompt
    assert "set_aside=" not in prompt
    assert "sole deploy candidate" not in prompt
    assert "A named commit is only a temporal candidate" not in prompt
    assert "no commits were read, because no deploy feed is connected" in prompt
    assert "live CloudWatch reading of the team's own Lambda function volcan-mcp-euw1-prod" in prompt
    # #64's rules stay as they were.
    assert "Do not claim a cause" in prompt
    assert "Do not say a rollback is staged" in prompt
    assert "not even to deny it" in prompt
    assert "'caused by'" in prompt and "'dispatched'" in prompt
    # The rejected phrasings stay word for word; only what to write instead changes,
    # because a live row has no window and no candidate commits to describe.
    assert REJECTED_PHRASINGS in prompt
    assert "only runtime commit in the window" not in prompt
    assert "candidate commits" not in prompt
    assert "Write 'no deploy feed is connected for this function' instead." in prompt


#: #64's list, as the prompt carries it on every row.
REJECTED_PHRASINGS = (
    "Never use these phrasings, which the board rejects even in a negative sentence: 'caused by',"
    " 'root cause is', 'the cause is', 'the cause was', 'introduced the regression', 'after <commit>', 'is staged',"
    " 'has been staged', 'awaiting', 'ready to stage', 'ready to roll back', 'was executed', 'rolled back',"
    " 'reverted', 'dispatched'."
)


def test_a_fixture_prompt_still_carries_its_commit_window(server, client):
    prompt, _ = _model_brief(client, "checkout-api", "x")
    assert "A named commit is only a temporal candidate" in prompt
    assert "commits_in_window=" in prompt
    assert "it is not a reading of a real service" in prompt
    assert REJECTED_PHRASINGS in prompt
    assert "Write 'the only runtime commit in the window was <commit>' or 'a temporal candidate' instead." in prompt
    assert "what the reading and the candidate commits do and do not show" in prompt


WINDOW_CLAIM_REPLY = "No commits landed in the attribution window, so no deploy is implicated."


def test_a_model_brief_that_describes_a_window_on_a_live_row_is_rejected(server, client):
    mcp_server, stub = server
    stub.errors = (1.0, 0.0, 0.0, 0.0, 0.0, 1.0)
    stub.invocations = (5.0,) * 6
    _, result = _model_brief(client, "volcan-mcp-euw1-prod", WINDOW_CLAIM_REPLY)
    assert result["fallback_reason"] == "model_claim_rejected", result
    assert result["synthesis_mode"] == "deterministic"
    assert result["rejected_phrase"].lower().startswith("no commits landed")
    assert WINDOW_CLAIM_REPLY not in json.dumps(result)


def test_the_window_guard_is_only_for_answers_with_no_commits_read(server, client):
    """On a fixture row a commit window was read, so the same words are not a false claim."""
    _, result = _model_brief(client, "checkout-api", WINDOW_CLAIM_REPLY)
    assert result["synthesis_mode"] == "bedrock", result
    assert result["fallback_reason"] is None


@pytest.mark.parametrize("phrase", [
    "No commits landed in the attribution window.",
    "no change landed before the spike",
    "Commits in window: 0.",
    "the window is empty",
    "No deploy is implicated.",
    "nothing was deployed",
    "the only runtime commit in the window was abc1234",
    # Round 2: ordinary deploy-window claims the first guard let through.
    "No changes were deployed in the 75 minutes before the onset.",
    "No runtime commit was in the window.",
    "The window had no runtime commit.",
    "No runtime commits were found in the window.",
    "There was no deploy before the errors began.",
    "No code changes preceded the spike.",
    "No deployment activity was observed before the onset.",
    "No candidate commit was found.",
    "Nothing shipped in the window.",
    "The spike is not deploy-related.",
    "There were no deploys in the last 24 hours, so a code change is unlikely.",
    "The errors are unrelated to any deploy.",
])
def test_the_no_commits_read_guard_catches_window_claims(phrase):
    from src.infrastructure.bedrock_incident_agent import no_commits_read_claim_match

    assert no_commits_read_claim_match(phrase), phrase


@pytest.mark.parametrize("phrase", [
    "No deploy feed is connected for volcan-mcp-euw1-prod, so Mercury did not try to name a commit.",
    "Errors rose from 0.0 to 4.0. Investigate by hand.",
    "This is a live CloudWatch reading of the team's own Lambda function.",
    "No deploy feed is connected for this function.",
    "Errors rose over the 24-hour CloudWatch window; no deploy feed is connected.",
    "Errors rose over the 24-hour CloudWatch window, and no deploy feed is connected for it.",
    "No commits or deploys were read for this service, so attribution was not attempted.",
    "Investigate volcan-mcp-euw1-prod by hand; no deploy feed is connected, so no commit was named.",
    "The error count shows no change in the trend over the last day.",
])
def test_the_no_commits_read_guard_leaves_honest_live_text_alone(phrase):
    from src.infrastructure.bedrock_incident_agent import no_commits_read_claim_match

    assert no_commits_read_claim_match(phrase) is None, phrase


def test_the_label_line_names_the_team_function_only_for_a_production_row():
    from src.infrastructure.bedrock_incident_agent import data_label_line

    simulated = data_label_line("LIVE", "checkout-api")
    assert "live CloudWatch reading" in simulated
    assert "team's own" not in simulated and "No deploy feed" not in simulated
    assert "not a reading of a real service" not in simulated
    production = data_label_line("LIVE", "aletheia-provenance-euw1-prod")
    assert "team's own Lambda function aletheia-provenance-euw1-prod" in production


def test_a_live_row_with_one_reading_is_described_as_one_reading(server, client):
    """A function with traffic in one hour of the 24 has one datapoint, not none."""
    mcp_server, stub = server
    stub.errors = (2.0,)
    stub.invocations = (5.0,)
    body = client.post("/mcp/tools/agent_incident_brief",
                       json={"service_name": "volcan-mcp-euw1-prod", "prefer_bedrock": False}).json()
    assert body["verdict"] == "INSUFFICIENT_DATA"
    syn = body["agent_synthesis"]
    assert "no readings" not in syn["commander_brief_10ft"], syn["commander_brief_10ft"]
    assert "only 1 reading of Errors" in syn["commander_brief_10ft"]
    next_step = syn["responder_handoff_draft"]["next_step"]
    assert "Connect a real metric source" not in next_step, next_step
    assert "CloudWatch was read" in next_step


def test_a_live_row_cloudwatch_refusal_is_not_framed_as_passing(server, client):
    """An AccessDenied is CloudWatch answering, cached 60 s: asking again soon changes nothing."""
    mcp_server, stub = server
    stub.error = access_denied()
    body = client.post("/mcp/tools/agent_incident_brief",
                       json={"service_name": "volcan-mcp-euw1-prod", "prefer_bedrock": False}).json()
    assert body["verdict"] == "INSUFFICIENT_DATA"
    next_step = body["agent_synthesis"]["responder_handoff_draft"]["next_step"]
    assert "Connect a real metric source" not in next_step, next_step
    assert "ask again in a minute" not in next_step, next_step
    assert "asking again will not change that" in next_step, next_step


def test_a_fixture_row_with_no_readings_keeps_its_wording(client):
    body = client.post("/mcp/tools/agent_incident_brief",
                       json={"service_name": "quiet-service", "prefer_bedrock": False}).json()
    assert body["verdict"] == "INSUFFICIENT_DATA"
    assert "Connect a real metric source" in body["agent_synthesis"]["responder_handoff_draft"]["next_step"]


class GatedLambdaStub(LambdaStub):
    """The first call waits for ``release``, then fails with a botocore read timeout.

    Every later call answers at once. It is the late read the review found: begun first,
    finished last, with a failure.
    """

    def __init__(self, **kwargs) -> None:
        import threading

        super().__init__(**kwargs)
        self.entered = threading.Event()
        self.release = threading.Event()
        self._first = True
        self._lock = threading.Lock()

    def get_metric_statistics(self, **kwargs):
        from botocore.exceptions import ReadTimeoutError

        with self._lock:
            first, self._first = self._first, False
        if first:
            self.entered.set()
            self.release.wait(10)
            raise ReadTimeoutError(endpoint_url="https://monitoring.eu-west-1.amazonaws.com/")
        return super().get_metric_statistics(**kwargs)


def test_a_late_failed_read_never_overwrites_a_newer_live_answer(hybrid):
    import threading

    stub = GatedLambdaStub(errors=(0.0, 0.0, 1.0, 0.0))
    adapter = CloudWatchMetricAdapter(client=stub)
    late: dict = {}
    old = threading.Thread(
        target=lambda: late.update(series=adapter.get_production_series("volcan-mcp-euw1-prod")))
    old.start()
    assert stub.entered.wait(5)
    newer = adapter.get_production_series("volcan-mcp-euw1-prod")  # begun later, answers first
    assert newer.provenance.source is DataSource.AWS_CLOUDWATCH
    stub.release.set()
    old.join(5)
    assert not old.is_alive()

    cached = adapter.cached_live_series("volcan-mcp-euw1-prod")
    assert cached is newer, cached.provenance.detail
    # The late caller is handed the newer answer too, not its own stale failure.
    assert late["series"] is newer


def test_a_read_timeout_is_a_row_not_read_and_is_asked_again_after_thirty_seconds(hybrid, monkeypatch):
    from botocore.exceptions import ReadTimeoutError

    from src.interfaces.live_rows import _stamp

    clock = FakeClock()
    monkeypatch.setattr(cloudwatch_module, "time", clock)
    stub = LambdaStub(error=ReadTimeoutError(endpoint_url="https://monitoring.eu-west-1.amazonaws.com/"))
    adapter = CloudWatchMetricAdapter(client=stub)

    series = adapter.get_production_series("volcan-mcp-euw1-prod")
    assert series.provenance.source is DataSource.NO_LIVE_DATA
    assert series.provenance.detail.startswith(cloudwatch_module.UNREAD_REASON_PREFIX)
    assert "ReadTimeoutError" in series.provenance.detail
    assert_nothing_identifying(series.provenance.detail)
    assert _stamp(series) == ("tag", "Not read")

    calls = len(stub.calls)
    clock.now += 29
    assert adapter.get_production_series("volcan-mcp-euw1-prod") is series
    assert len(stub.calls) == calls, "a timed-out row is remembered, not asked again at once"
    stub.error = None
    clock.now += 2  # 31 s: shorter than a real answer's 60 s
    again = adapter.get_production_series("volcan-mcp-euw1-prod")
    assert again.provenance.source is DataSource.AWS_CLOUDWATCH


def test_an_access_denied_is_still_an_answer_cached_for_a_minute(hybrid, monkeypatch):
    """Only a timeout is 'not read': a refusal is CloudWatch answering."""
    from src.interfaces.live_rows import _stamp

    clock = FakeClock()
    monkeypatch.setattr(cloudwatch_module, "time", clock)
    stub = LambdaStub(error=access_denied())
    adapter = CloudWatchMetricAdapter(client=stub)
    series = adapter.get_production_series("volcan-mcp-euw1-prod")
    assert _stamp(series) == ("tag", "No live data")
    calls = len(stub.calls)
    clock.now += 45
    assert adapter.get_production_series("volcan-mcp-euw1-prod") is series
    assert len(stub.calls) == calls


class SlowThenTimeoutStub(LambdaStub):
    """Sleeps past the page's deadline, then fails the way botocore's read timeout does."""

    def __init__(self, delay: float) -> None:
        super().__init__()
        self.delay = delay

    def get_metric_statistics(self, **kwargs):
        import time as _time

        from botocore.exceptions import ReadTimeoutError

        self.calls.append(kwargs)
        _time.sleep(self.delay)
        raise ReadTimeoutError(endpoint_url="https://monitoring.eu-west-1.amazonaws.com/")


def test_a_read_that_times_out_after_the_page_deadline_stays_not_read(server, client, monkeypatch):
    import time as _time

    from src.interfaces import live_rows

    mcp_server, _ = server
    adapter = mcp_server.cloudwatch_adapter
    monkeypatch.setattr(adapter, "_client", SlowThenTimeoutStub(delay=0.4))
    monkeypatch.setattr(live_rows, "PAGE_READ_DEADLINE_SECONDS", 0.1)
    try:
        page = client.get("/").text
        assert page.count('<span class="tag">Not read</span>') == len(LIVE_PRODUCTION_FUNCTIONS)
        deadline = _time.monotonic() + 5
        while _time.monotonic() < deadline:
            done = [adapter.cached_live_series(n) for n in LIVE_PRODUCTION_FUNCTIONS]
            if all(s is not None and "ReadTimeoutError" in s.provenance.detail for s in done):
                break
            _time.sleep(0.05)
        for name in LIVE_PRODUCTION_FUNCTIONS:
            entry = adapter._live_cache[name]
            assert "ReadTimeoutError" in entry[2].provenance.detail, entry[2].provenance.detail
            assert entry[1] == cloudwatch_module.UNREAD_CACHE_SECONDS
        page = client.get("/").text
        assert page.count('<span class="tag">Not read</span>') == len(LIVE_PRODUCTION_FUNCTIONS)
        assert "No live data" not in page
    finally:
        adapter.invalidate_live_cache()


def test_the_live_hero_rewrite_ships_only_with_the_switch_on(server, client, monkeypatch):
    """docs/index.html is frozen; the switch-on page carries the rewrite, the other does not."""
    from src.interfaces.live_rows import LIVE_HERO_TEXT

    page = client.get("/").text
    script = page[page.index('<script id="mercury-live-hero">'):]
    script = script[:script.index("</script>")]
    assert page.index('id="mercury-live-hero"') > page.index('data-service="quiet-service"')
    for name in LIVE_PRODUCTION_FUNCTIONS:
        assert f'"{name}"' in script
    assert json.dumps(LIVE_HERO_TEXT["headline"]) in script
    assert LIVE_HERO_TEXT["window_eyebrow"] not in script
    assert not DEPLOY_WINDOW_WORDS.search(LIVE_HERO_TEXT["eyebrow"] + " " + LIVE_HERO_TEXT["headline"])
    assert page.rstrip().endswith("</html>")

    monkeypatch.delenv("MERCURY_LIVE_CLOUDWATCH")
    assert "mercury-live-hero" not in client.get("/").text


# ------------------------------------------------- Review round 2 repairs, 2026-10-19

@pytest.mark.parametrize("reply", [
    "No runtime commits were found in the window, so Mercury names no temporal candidate.",
    "There were no deploys in the last 24 hours, so a code change is unlikely.",
])
def test_a_paraphrased_window_claim_on_a_live_row_is_rejected(server, client, reply):
    """The model's own words for 'no commit landed' are discarded like the listed ones."""
    mcp_server, stub = server
    stub.errors = (1.0, 0.0, 0.0, 0.0, 0.0, 1.0)
    stub.invocations = (5.0,) * 6
    _, result = _model_brief(client, "volcan-mcp-euw1-prod", reply)
    assert result["fallback_reason"] == "model_claim_rejected", result
    assert result["synthesis_mode"] == "deterministic"
    assert reply not in json.dumps(result)


def _strings(value) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in _strings(v)]
    if isinstance(value, (list, tuple)):
        return [s for v in value for s in _strings(v)]
    return []


@pytest.mark.parametrize("errors", [
    (1.0, 0.0, 0.0, 0.0, 0.0, 1.0),
    (0.0, 0.0, 0.0, 0.0, 1.0, 1.0),
    (0.0, 0.0, 0.0, 0.0, 0.0, 4.0),
    (2.0, 2.0, 2.0, 2.0, 2.0, 40.0),
    (0.0, 5.0, 5.0),
    (0.0, 0.0, 0.0, 0.0),
    (2.0,),
], ids=["spike-after-one", "spike-from-zero-onset", "zero-baseline", "big-spike", "zero-run-of-two",
        "quiet", "one-reading"])
def test_the_widened_guard_leaves_mercurys_own_live_sentences_alone(server, client, errors):
    """A model that quotes Mercury's own live-row sentences back must not be rejected for it."""
    from src.infrastructure.bedrock_incident_agent import no_commits_read_claim_match

    mcp_server, stub = server
    stub.errors = errors
    stub.invocations = (5.0,) * len(errors)
    correlation = _use_case(LambdaStub(errors=errors, invocations=(5.0,) * len(errors))).execute(
        "volcan-mcp-euw1-prod")
    texts = [t for t in _live_row_texts(correlation).values() if t]
    texts += [correlation.causality_statement, correlation.rollback_blocked_reason]
    body = client.post("/mcp/tools/agent_incident_brief",
                       json={"service_name": "volcan-mcp-euw1-prod", "prefer_bedrock": False}).json()
    texts += _strings(body["agent_synthesis"])
    what = client.post("/mcp/tools/what_changed", json={"service_name": "volcan-mcp-euw1-prod"}).json()
    texts += _strings(what["attribution"]) + [what["explanation"], what["voice_summary"],
                                             what["deployment_evidence"]["blocked_reason"] or ""]
    for text in texts:
        assert no_commits_read_claim_match(text) is None, text


def test_a_live_row_names_what_mercury_did_not_what_is_missing(server, client):
    """An operator can record a marker for any service; the reason must stay true then too."""
    from src.domain.deployment_evidence import DeploymentMarker
    from src.interfaces.mcp_server import deployment_evidence

    mcp_server, stub = server
    stub.errors = (1.0, 0.0, 0.0, 0.0, 0.0, 1.0)
    stub.invocations = (5.0,) * 6
    deployed = datetime.now(timezone.utc) - timedelta(hours=3)
    deployment_evidence.record(DeploymentMarker.from_values(
        marker_id="volcan-marker", service="volcan-mcp-euw1-prod", environment="production",
        revision="abc1234", artifact_sha256="a" * 64, deployed_at=deployed,
        health_checked_at=deployed + timedelta(minutes=2), health_status="HEALTHY",
        health_observed_revision="abc1234", health_observed_artifact_sha256="a" * 64,
    ))
    body = client.post("/mcp/tools/what_changed", json={"service_name": "volcan-mcp-euw1-prod"}).json()
    evidence = body["deployment_evidence"]
    assert evidence["markers_seen"] == 1, evidence
    blocked = evidence["blocked_reason"]
    assert "marker" not in blocked.lower(), blocked
    assert "does not attribute" in blocked and "no deploy feed is connected" in blocked, blocked


def test_a_production_row_with_no_credentials_is_never_labelled_a_fixture(hybrid, monkeypatch):
    """A local run with no AWS credentials: CloudWatch is never called, and no row says FIXTURE."""
    from fastapi.testclient import TestClient

    from src.interfaces import mcp_server
    from src.interfaces.live_rows import _stamp

    adapter = mcp_server.cloudwatch_adapter
    monkeypatch.setattr(adapter, "_client", None)
    monkeypatch.setattr(adapter, "_resolve_client", lambda: None)
    adapter.invalidate_live_cache()
    try:
        series = adapter.get_production_series("volcan-mcp-euw1-prod")
        assert series.provenance.source is DataSource.NO_LIVE_DATA
        assert series.provenance.display_label == "NO LIVE DATA"
        assert series.provenance.detail.startswith(cloudwatch_module.NOT_CALLED_REASON_PREFIX)
        assert _stamp(series) == ("tag", "Not read")
        # Never cached: the moment credentials resolve, the next view reads CloudWatch.
        assert adapter.cached_live_series("volcan-mcp-euw1-prod") is None

        with TestClient(mcp_server.app) as http:
            body = http.post("/mcp/tools/agent_incident_brief",
                             json={"service_name": "volcan-mcp-euw1-prod", "prefer_bedrock": False}).json()
            page = http.get("/").text
        assert body["data_label"] == "NO LIVE DATA", body["data_label"]
        next_step = body["agent_synthesis"]["responder_handoff_draft"]["next_step"]
        assert "Connect a real metric source" not in next_step, next_step
        assert "ask again in a minute" not in next_step, next_step
        assert page.count('<span class="tag">Not read</span>') == len(LIVE_PRODUCTION_FUNCTIONS)
        assert 'data-row-source="offline-fixture"' not in page
    finally:
        adapter.invalidate_live_cache()


def test_a_live_row_that_did_not_answer_in_time_asks_again(server, client):
    """Only a row not read in time is a passing condition: it is read again after 30 s."""
    from botocore.exceptions import ReadTimeoutError

    mcp_server, stub = server
    stub.error = ReadTimeoutError(endpoint_url="https://monitoring.eu-west-1.amazonaws.com/")
    body = client.post("/mcp/tools/agent_incident_brief",
                       json={"service_name": "volcan-mcp-euw1-prod", "prefer_bedrock": False}).json()
    assert body["verdict"] == "INSUFFICIENT_DATA"
    next_step = body["agent_synthesis"]["responder_handoff_draft"]["next_step"]
    assert "ask again in a minute" in next_step, next_step


def test_a_live_row_with_no_datapoints_is_not_framed_as_passing(server, client):
    mcp_server, stub = server
    stub.errors = ()
    stub.invocations = ()
    body = client.post("/mcp/tools/agent_incident_brief",
                       json={"service_name": "volcan-mcp-euw1-prod", "prefer_bedrock": False}).json()
    assert body["verdict"] == "INSUFFICIENT_DATA"
    next_step = body["agent_synthesis"]["responder_handoff_draft"]["next_step"]
    assert "ask again in a minute" not in next_step, next_step
    assert "asking again will not change that" in next_step, next_step


class SlowThenAnswerStub(LambdaStub):
    """The first thread's reads block until ``release``, then answer with a real reading.

    Every other thread's read fails at once with a botocore connect timeout: the newer
    read that times out first while the older, slower one is still going to answer.
    """

    def __init__(self, **kwargs) -> None:
        import threading

        super().__init__(**kwargs)
        self.entered = threading.Event()
        self.release = threading.Event()
        self._first_thread = None
        self._lock = threading.Lock()

    def get_metric_statistics(self, **kwargs):
        import threading

        from botocore.exceptions import ConnectTimeoutError

        with self._lock:
            if self._first_thread is None:
                self._first_thread = threading.get_ident()
            first = self._first_thread == threading.get_ident()
        if not first:
            raise ConnectTimeoutError(endpoint_url="https://monitoring.eu-west-1.amazonaws.com/")
        self.entered.set()
        self.release.wait(10)
        return super().get_metric_statistics(**kwargs)


def test_a_late_real_answer_replaces_a_newer_read_that_never_answered(hybrid):
    """The mirror of the late-failure case: a timeout is not an answer, so it never wins."""
    import threading

    stub = SlowThenAnswerStub(errors=(0.0, 0.0, 1.0, 0.0))
    adapter = CloudWatchMetricAdapter(client=stub)
    late: dict = {}
    old = threading.Thread(
        target=lambda: late.update(series=adapter.get_production_series("volcan-mcp-euw1-prod")))
    old.start()
    assert stub.entered.wait(5)
    newer = adapter.get_production_series("volcan-mcp-euw1-prod")  # begun later, timed out first
    assert newer.provenance.detail.startswith(cloudwatch_module.UNREAD_REASON_PREFIX)
    stub.release.set()
    old.join(5)
    assert not old.is_alive()

    assert late["series"].provenance.source is DataSource.AWS_CLOUDWATCH, late["series"].provenance.detail
    cached = adapter.cached_live_series("volcan-mcp-euw1-prod")
    assert cached is late["series"], cached.provenance.detail
    assert adapter._live_cache["volcan-mcp-euw1-prod"][1] == adapter._live_cache_seconds()


def test_the_board_question_about_a_live_row_does_not_wait_for_a_slow_cloudwatch(server, client, monkeypatch):
    """what_changed and the agent brief read a live row under a deadline too, like the page."""
    import time as _time

    mcp_server, _ = server
    adapter = mcp_server.cloudwatch_adapter
    slow = SlowLambdaStub(delay=30.0)
    monkeypatch.setattr(adapter, "_client", slow)
    monkeypatch.setattr(cloudwatch_module, "ROUTE_READ_DEADLINE_SECONDS", 0.3)
    names = ("volcan-mcp-euw1-prod", "aletheia-provenance-euw1-prod")
    try:
        for path, payload in (
            ("/mcp/tools/what_changed", {"service_name": names[0]}),
            ("/mcp/tools/agent_incident_brief", {"service_name": names[1], "prefer_bedrock": False}),
        ):
            started = _time.monotonic()
            body = client.post(path, json=payload).json()
            elapsed = _time.monotonic() - started
            assert elapsed < 0.3 + 0.7, f"{path} waited {elapsed:.2f} s for CloudWatch"
            assert body["metric_provenance"]["display_label"] == "NO LIVE DATA", body
            assert "did not answer within" in body["metric_provenance"]["detail"]
    finally:
        slow.release.set()
        deadline = _time.monotonic() + 10
        while _time.monotonic() < deadline:
            done = [adapter.cached_live_series(n) for n in names]
            if all(s is not None and s.provenance.source is DataSource.AWS_CLOUDWATCH for s in done):
                break
            _time.sleep(0.02)
        adapter.invalidate_live_cache()


def test_the_read_deadlines_stay_short():
    """Both bounds keep a slow CloudWatch inside the Lambda's 30 s timeout.

    The route's deadline comes before a model call that may take its own 25 s.
    """
    from src.infrastructure.bedrock_incident_agent import MODEL_CALL_TIMEOUT_SEC
    from src.interfaces import live_rows

    assert 3.0 <= live_rows.PAGE_READ_DEADLINE_SECONDS <= 5.0
    assert cloudwatch_module.ROUTE_READ_DEADLINE_SECONDS <= 3.0
    assert cloudwatch_module.ROUTE_READ_DEADLINE_SECONDS + MODEL_CALL_TIMEOUT_SEC <= 28.0


def test_a_dropped_connection_is_a_row_not_read(hybrid, monkeypatch):
    """CloudWatch never answered, so the row is 'Not read', not 'No live data'."""
    from botocore.exceptions import ConnectionClosedError

    from src.interfaces.live_rows import _stamp

    monkeypatch.setattr(cloudwatch_module, "time", FakeClock())
    stub = LambdaStub(error=ConnectionClosedError(endpoint_url="https://monitoring.eu-west-1.amazonaws.com/"))
    adapter = CloudWatchMetricAdapter(client=stub)
    series = adapter.get_production_series("volcan-mcp-euw1-prod")
    assert series.provenance.source is DataSource.NO_LIVE_DATA
    assert series.provenance.detail.startswith(cloudwatch_module.UNREAD_REASON_PREFIX)
    assert "ConnectionClosedError" in series.provenance.detail
    assert "in time" not in series.provenance.detail  # it was dropped, not slow
    assert _stamp(series) == ("tag", "Not read")
    assert adapter._live_cache["volcan-mcp-euw1-prod"][1] == cloudwatch_module.UNREAD_CACHE_SECONDS


def test_a_row_title_names_a_read_time_only_for_a_reading(hybrid):
    from src.interfaces.live_rows import _live_row

    def title_of(series) -> str:
        return re.search(r'title="([^"]*)"', _live_row("volcan-mcp-euw1-prod", series)).group(1)

    unread = CloudWatchMetricAdapter(client=LambdaStub()).mark_unread("volcan-mcp-euw1-prod", 4.0)
    title = title_of(unread)
    assert title.startswith("Not read:"), title
    assert "from CloudWatch at" not in title and unread.provenance.observed_at_utc not in title, title
    assert "not read from CloudWatch" in title, title

    refused = CloudWatchMetricAdapter(client=LambdaStub(error=access_denied())).get_production_series(
        "volcan-mcp-euw1-prod")
    title = title_of(refused)
    assert title.startswith("No live data:"), title
    assert "from CloudWatch at" not in title, title
    assert "no usable reading" in title, title

    live = CloudWatchMetricAdapter(client=LambdaStub()).get_production_series("volcan-mcp-euw1-prod")
    assert f"from CloudWatch at {live.provenance.observed_at_utc}" in title_of(live)


def test_the_deck_reveals_the_boards_handoff_refusal_and_returns_keyboard_focus():
    """The browser suites measure both; this pins the mechanisms where they cannot run."""
    from src.interfaces.agent_deck import AGENT_DECK_JS

    # The board's own Publish handoff error card, revealed while the cursor is on Publish.
    assert "function revealBoardError(card)" in AGENT_DECK_JS
    assert "document.getElementById('handoffOutput')" in AGENT_DECK_JS
    assert "cursor() !== publish" in AGENT_DECK_JS
    # Keyboard focus goes back only to the deck control the cursor is still on.
    assert "keepKeyboardFocus(btnBrief, hadFocus);" in AGENT_DECK_JS
    assert "keepKeyboardFocus(btnPublish, hadFocus);" in AGENT_DECK_JS
    assert "nav.current !== control" in AGENT_DECK_JS
    assert ".focus(" not in AGENT_DECK_JS
