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
