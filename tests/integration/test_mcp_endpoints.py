"""Integration tests for the Mercury HTTP tool server.

Every telemetry endpoint must return provenance, because the cockpit renders it
and a judge reads it. These tests assert that contract as hard as they assert the
numbers.
"""
import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def test_health_reports_the_build_sha_field():
    from fastapi.testclient import TestClient

    from src.interfaces.mcp_server import app

    res = TestClient(app).get("/health")
    assert res.status_code == 200
    body = res.json()
    assert body["service"] == "mercury-firetv-cockpit"
    # build_sha may be empty outside a git checkout, but the field must exist so
    # scripts/probe_deployment.py can compare a deployment against a commit.
    assert "build_sha" in body
    assert "github_live" in body


def test_root_serves_the_cockpit_page(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "Mercury" in res.text
    assert "Fire TV Incident Commander" in res.text


def test_cockpit_scripts_are_served_next_to_the_page(client):
    res = client.get("/firetv_nav.js")
    assert res.status_code == 200
    assert "mercuryNav" in res.text


def test_cockpit_script_route_refuses_path_traversal(client):
    res = client.get("/..%2f..%2fREADME.js")
    assert res.status_code in (404, 400)


def test_dora_endpoint_returns_metrics_and_provenance(client):
    res = client.post("/mcp/tools/get_dora_velocity_report")
    assert res.status_code == 200
    data = res.json()
    assert data["tier"] in ["ELITE", "HIGH", "MEDIUM", "LOW"]
    assert set(data["metrics"]) == {
        "deployment_frequency_per_day", "lead_time_hours",
        "change_failure_rate_pct", "mttr_hours",
    }
    prov = data["provenance"]
    assert prov["data_source"] in ("github-api", "offline-fixture")
    assert prov["detail"]
    assert isinstance(prov["is_live"], bool)


def test_dora_endpoint_is_honest_about_fixture_mode(client):
    """With no GITHUB_TOKEN in the environment the response must say fixture."""
    data = client.post("/mcp/tools/get_dora_velocity_report").json()
    assert data["provenance"]["data_source"] == "offline-fixture"
    assert data["provenance"]["display_label"] == "OFFLINE FIXTURE"
    assert data["provenance"]["is_live"] is False


def test_pr_bottlenecks_endpoint_returns_counts_and_provenance(client):
    data = client.post("/mcp/tools/get_pr_bottlenecks").json()
    assert data["total_open"] >= 0
    assert data["stale_count"] >= len(data["stale_prs"])
    assert "provenance" in data


def test_cost_endpoint_returns_spend_and_provenance(client):
    data = client.post("/mcp/tools/get_aws_cost_anomalies").json()
    assert data["month_to_date_usd"] >= 0
    assert data["provenance"]["data_source"] in ("aws-cost-explorer", "offline-fixture")


def test_what_changed_returns_a_verdict_and_both_provenances(client):
    res = client.post("/mcp/tools/what_changed", json={"service_name": "checkout-api"})
    assert res.status_code == 200
    data = res.json()
    assert data["verdict"] in (
        "NO_ANOMALY", "ANOMALY_ATTRIBUTED", "ANOMALY_WITHOUT_ATTRIBUTION", "INSUFFICIENT_DATA",
    )
    assert data["explanation"]
    assert "metric_provenance" in data
    assert "commit_provenance" in data


def test_what_changed_falls_back_to_real_local_commits_not_invented_ones(client):
    """Without a GitHub token the commits come from git log, and say so."""
    data = client.post("/mcp/tools/what_changed", json={"service_name": "checkout-api"}).json()

    assert data["commit_provenance"]["data_source"] in ("local-git", "offline-fixture")
    if data["commit_provenance"]["data_source"] == "local-git":
        assert "git log" in data["commit_provenance"]["detail"]
        assert "not the service being monitored" in data["commit_provenance"]["detail"]
        assert data["offending_commit"]["sha"]
    else:
        # No checkout available: nothing may be blamed.
        assert data["offending_commit"] is None
        assert data["recommended_action"] is None


def test_the_metric_behind_a_correlation_is_never_claimed_to_be_live_offline(client):
    """The commits may be real while the metric is simulated. The split must show."""
    data = client.post("/mcp/tools/what_changed", json={"service_name": "checkout-api"}).json()
    assert data["metric_provenance"]["is_live"] is False
    assert data["metric_provenance"]["display_label"] == "OFFLINE FIXTURE"
    assert "never read from" in data["metric_provenance"]["detail"]


def test_an_anchored_simulation_says_it_was_anchored(client):
    """Moving a simulated point to fit a commit must be disclosed, not hidden."""
    data = client.post("/mcp/tools/what_changed", json={"service_name": "checkout-api"}).json()
    assert data["offending_commit"] is not None
    detail = data["metric_provenance"]["detail"]
    # Which commit the reading is placed after is itself a choice, so the sentence
    # has to name the rule that chose it, not merely admit that something moved.
    assert "placed" in detail
    assert "alone in its 60 minute attribution window" in detail
    assert "the commits are real, this metric is not" in detail


def test_the_five_demo_services_reach_the_five_verdicts_the_readme_promises(client):
    """The README's demo table, driven against this checkout's real git log.

    This used to be conditional: the anchored-simulation test above only asserted
    anything ``if data["offending_commit"] is not None``, so the day checkout-api
    stopped attributing, the table in the README would have gone stale with the suite
    still green. It can stop attributing: which commit the fixture anchors to is chosen
    from the real log, and the log grows every time somebody commits.

    So the verdicts are asserted, not conditioned on. If a burst of commits ever makes
    the attributing demo unreachable, this fails and the README is corrected rather
    than quietly wrong.
    """
    expected = {
        "checkout-api": ("ANOMALY_ATTRIBUTED", None),
        "release-train": ("ANOMALY_WITHOUT_ATTRIBUTION", "WINDOW_TOO_CROWDED"),
        "search-indexer": ("ANOMALY_WITHOUT_ATTRIBUTION", "NO_CANDIDATE_IN_WINDOW"),
        "payments-worker": ("NO_ANOMALY", None),
        "quiet-service": ("INSUFFICIENT_DATA", None),
    }
    for service, (verdict, refusal) in expected.items():
        data = client.post("/mcp/tools/what_changed", json={"service_name": service}).json()
        assert data["verdict"] == verdict, (
            f"{service} returned {data['verdict']}, not the {verdict} the README's demo "
            f"table promises. The fixture anchors to this checkout's real git log, so a "
            f"burst of commits can move this: fix the anchoring or the table, not this test."
        )
        assert data["attribution"]["refusal_reason"] == refusal, service
        # Only the attributed row may offer a rollback. The refusals must not.
        assert (data["recommended_action"] is not None) == (verdict == "ANOMALY_ATTRIBUTED"), service


def test_the_crowded_refusal_says_which_commit_it_was_anchored_to_and_why(client):
    """The demo that shows the refusal has to disclose its own staging too."""
    data = client.post("/mcp/tools/what_changed", json={"service_name": "release-train"}).json()
    assert data["verdict"] == "ANOMALY_WITHOUT_ATTRIBUTION"
    assert data["attribution"]["refusal_reason"] == "WINDOW_TOO_CROWDED"
    assert data["attribution"]["commits_in_window"] > 1
    assert data["offending_commit"] is None
    assert data["recommended_action"] is None
    detail = data["metric_provenance"]["detail"]
    assert "the commit with the most company" in detail
    assert "the commits are real, this metric is not" in detail
    assert "Do not roll back on this answer" in data["voice_summary"]


def test_every_answer_carries_the_measured_worth_of_naming_a_commit(client):
    """An attribution ships the precision it was measured at, next to the name.

    The figure comes from correlation_trial_summary.json, which
    ``python scripts/correlation_trial.py`` writes, so the number on the wire is the
    number in the README rather than one recomputed per request.
    """
    data = client.post("/mcp/tools/what_changed", json={"service_name": "checkout-api"}).json()
    accuracy = data["attribution"]["measured_accuracy"]
    assert accuracy["measured_by_command"] == "python scripts/correlation_trial.py"
    if accuracy["measured"]:
        summary = json.loads((REPO_ROOT / "correlation_trial_summary.json").read_text(encoding="utf-8"))
        assert accuracy["precision_when_it_names_a_commit"] == summary["headline"]["naming_precision"]
        assert accuracy["namings_measured"] == summary["headline"]["times_a_commit_was_named"]
        assert accuracy["corpus_cases"] == summary["cases"]
    else:
        assert accuracy["precision_when_it_names_a_commit"] is None
        assert "no measured accuracy" in accuracy["note"]


def test_what_changed_reports_how_many_changes_were_candidates(client):
    """The count the correlation trial argued for has to reach the wire.

    Against the labelled corpus in ``scripts/correlation_trial.py`` every wrong attribution
    whose real cause was inside the attribution window was a window holding more than one
    change, so the number of candidates is part of the answer rather than a log line.
    """
    data = client.post("/mcp/tools/what_changed", json={"service_name": "checkout-api"}).json()
    attribution = data["attribution"]
    assert isinstance(attribution["commits_in_window"], int)
    assert attribution["commits_in_window"] >= 0

    if data["verdict"] == "ANOMALY_ATTRIBUTED":
        assert attribution["commits_in_window"] >= 1
        assert attribution["is_ambiguous"] == (attribution["commits_in_window"] > 1)
        if attribution["is_ambiguous"]:
            assert "It is not the only candidate" in data["explanation"]
    else:
        # Nothing was named, so there is nothing to be ambiguous about.
        assert attribution["is_ambiguous"] is False


def test_a_verdict_that_names_nobody_claims_no_candidates(client):
    """The two refusals must not report a candidate they did not act on."""
    for service in ("payments-worker", "search-indexer", "quiet-service"):
        data = _what_changed(client, service)
        assert data["offending_commit"] is None
        assert data["attribution"]["commits_in_window"] == 0
        assert data["attribution"]["is_ambiguous"] is False


def test_what_changed_rejects_an_out_of_range_window(client):
    assert client.post("/mcp/tools/what_changed", json={"time_window_minutes": 99999}).status_code == 422
    assert client.post("/mcp/tools/what_changed", json={"time_window_minutes": 1}).status_code == 422


def test_observability_audit_reports_missing_signals(client):
    res = client.post("/mcp/tools/audit_observability", json={
        "service_name": "checkout-api",
        "received_signals": ["error_rate", "emf_logs"],
    })
    assert res.status_code == 200
    data = res.json()
    assert data["is_fully_observable"] is False
    assert "p95_latency" in data["missing_signals"]
    assert 0 < data["observability_gap_score"] <= 1


def test_every_response_carries_a_request_id_header(client):
    res = client.get("/health")
    assert res.headers.get("X-Mercury-Request-Id")


def test_devops_event_feed_starts_empty_and_accepts_authorized_events(client, auth_headers):
    res = client.post("/webhooks/github/workflow_run", headers=auth_headers, json={
        "repository": "acme/widgets", "workflow_name": "ci.yml", "conclusion": "failure",
    })
    assert res.status_code == 200
    assert res.json()["status"] == "FAILURE"

    feed = client.get("/mcp/events/devops").json()
    assert feed["total"] >= 1
    assert feed["events"][0]["source"] == "GitHub_Actions"


def test_webhook_ingest_requires_authorization(client):
    res = client.post("/webhooks/github/workflow_run", json={
        "repository": "acme/widgets", "workflow_name": "ci.yml", "conclusion": "success",
    })
    assert res.status_code == 401


# -------------------------------------- Every verdict is reachable from the API
#
# The defect these close: the simulated metric series came from two module
# constants, so every service name returned the same 34x factor. The correlator's
# NO_ANOMALY and ANOMALY_WITHOUT_ATTRIBUTION verdicts had unit tests but no input
# a reviewer could supply ever reached them over HTTP. These drive the four
# verdicts through the endpoint the cockpit calls.

DEMO_SERVICES = ["checkout-api", "payments-worker", "search-indexer"]


def _what_changed(client, service_name):
    res = client.post("/mcp/tools/what_changed", json={"service_name": service_name})
    assert res.status_code == 200
    return res.json()


def test_the_metric_series_is_not_the_same_for_every_service(client):
    readings = {
        name: (_what_changed(client, name)["metric"]["baseline"],
               _what_changed(client, name)["metric"]["current"])
        for name in DEMO_SERVICES
    }
    assert len(set(readings.values())) == len(DEMO_SERVICES), (
        f"the simulated series does not depend on the service: {readings}"
    )


def test_the_demo_services_reach_three_different_verdicts(client):
    verdicts = {name: _what_changed(client, name)["verdict"] for name in DEMO_SERVICES}
    commits_available = (
        _what_changed(client, "checkout-api")["commit_provenance"]["data_source"]
        in ("local-git", "github-api")
    )

    assert verdicts["payments-worker"] == "NO_ANOMALY"
    assert verdicts["search-indexer"] == "ANOMALY_WITHOUT_ATTRIBUTION"
    if commits_available:
        assert verdicts["checkout-api"] == "ANOMALY_ATTRIBUTED"
        assert len(set(verdicts.values())) == 3
    else:
        # No checkout and no token: nothing can be attributed, and the correlator
        # must say so rather than blaming something.
        assert verdicts["checkout-api"] == "ANOMALY_WITHOUT_ATTRIBUTION"


def test_the_steady_service_is_refused_on_the_factor_not_on_missing_data(client):
    """A zero baseline would also produce NO_ANOMALY. Prove it is the threshold."""
    data = _what_changed(client, "payments-worker")
    metric = data["metric"]
    assert metric["baseline"] > 0
    assert metric["sample_size"] >= 2
    assert 1.0 < metric["anomaly_factor"] < 3.0
    assert "below the 3.0x threshold" in data["explanation"]
    assert data["recommended_action"] is None
    assert data["offending_commit"] is None


def test_the_unattributed_service_had_commits_available_and_still_blamed_nothing(client):
    """The refusal must come from the attribution window, not from an empty history."""
    data = _what_changed(client, "search-indexer")
    if data["commit_provenance"]["data_source"] not in ("local-git", "github-api"):
        pytest.skip("no commit history is reachable here, so the window cannot be the reason")

    assert data["verdict"] == "ANOMALY_WITHOUT_ATTRIBUTION"
    assert data["metric"]["anomaly_factor"] >= 3.0
    assert data["offending_commit"] is None
    assert data["recommended_action"] is None
    assert "no commit landed in the" in data["explanation"]
    assert "deliberately outside" in data["metric_provenance"]["detail"]


def test_an_unknown_service_is_refused_rather_than_given_an_invented_incident(client):
    data = _what_changed(client, "quiet-service")
    assert data["verdict"] == "INSUFFICIENT_DATA"
    assert data["incident_detected"] is False
    assert data["metric"]["sample_size"] == 0
    assert data["metric"]["current"] == 0.0
    assert data["recommended_action"] is None
    assert "does not invent a reading" in data["metric_provenance"]["detail"]


def test_the_cockpit_offers_exactly_the_services_the_fixture_knows():
    """The demo buttons on the page and the fixture must not drift apart."""
    from pathlib import Path

    from src.infrastructure.cloudwatch_adapter import SIMULATED_SERVICES

    page = (Path(__file__).resolve().parent.parent.parent / "docs" / "index.html").read_text(
        encoding="utf-8"
    )
    offered = set(re.findall(r'data-service="([^"]+)"', page))
    assert set(SIMULATED_SERVICES) < offered, (
        f"the cockpit does not offer every known service: {set(SIMULATED_SERVICES) - offered}"
    )
    unknown = offered - set(SIMULATED_SERVICES)
    assert len(unknown) == 1, (
        f"the cockpit must offer exactly one name the fixture refuses, found {sorted(unknown)}"
    )
