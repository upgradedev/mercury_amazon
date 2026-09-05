"""Integration tests for the Mercury HTTP tool server.

Every telemetry endpoint must return provenance, because the cockpit renders it
and a judge reads it. These tests assert that contract as hard as they assert the
numbers.
"""


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
    if data["offending_commit"] is not None:
        detail = data["metric_provenance"]["detail"]
        assert "placed" in detail and "after the newest known commit" in detail
        assert "the commits are real, this metric is not" in detail


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
