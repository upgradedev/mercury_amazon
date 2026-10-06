from datetime import datetime, timedelta, timezone


def marker_payload(marker_id, revision, digest, deployed_at):
    return {
        "marker_id": marker_id,
        "service": "checkout-api",
        "environment": "production",
        "revision": revision,
        "artifact_sha256": digest,
        "deployed_at": deployed_at.isoformat(),
        "health_checked_at": (deployed_at + timedelta(minutes=2)).isoformat(),
        "health_status": "HEALTHY",
        "health_observed_revision": revision,
        "health_observed_artifact_sha256": digest,
        "health_url": "https://test.invalid/health",
    }


def test_unverified_client_chosen_sha_cannot_be_staged(client, auth_headers):
    res = client.post("/mcp/tools/stage_rollback", headers=auth_headers, json={
        "action_id": "forged-target",
        "target_service": "checkout-api",
        "target_commit_sha": "attacker-sha",
        "environment": "production",
        "target_artifact_sha256": "1" * 64,
        "target_deployment_marker_id": "missing-good",
        "offending_deployment_marker_id": "missing-current",
        "reason": "try arbitrary target",
        "lease_sec": 300,
    })
    assert res.status_code == 409
    assert res.json()["detail"]["denial_reason"] == "UNVERIFIED_DEPLOYMENT_TARGET"


def test_what_changed_selects_a_target_only_from_verified_deployment_timeline(client, auth_headers):
    first = client.post("/mcp/tools/what_changed", json={"service_name": "checkout-api"}).json()
    offending_revision = first["offending_commit"]["sha"]
    assert first["recommended_action"] is None
    assert "Git order alone is not a target" in first["deployment_evidence"]["blocked_reason"]

    now = datetime(2026, 9, 23, 8, tzinfo=timezone.utc)
    for payload in (
        marker_payload("good-17", "release-17", "1" * 64, now),
        marker_payload("incident-release", offending_revision, "2" * 64, now + timedelta(hours=1)),
    ):
        recorded = client.post(
            "/mcp/tools/record_deployment_evidence", headers=auth_headers, json=payload
        )
        assert recorded.status_code == 200, recorded.text

    second = client.post("/mcp/tools/what_changed", json={"service_name": "checkout-api"}).json()
    action = second["recommended_action"]
    assert action["target_commit_sha"] == "release-17"
    assert action["target_artifact_sha256"] == "1" * 64
    assert action["target_deployment_marker_id"] == "good-17"
    assert action["offending_deployment_marker_id"] == "incident-release"


def test_handoff_requires_auth_and_rejects_stale_overwrite(client, auth_headers):
    payload = {
        "incident_id": "inc-17",
        "responder": "Maya",
        "current_action": "Checking the deployment timeline",
        "confirmed_facts": ["5xx spike verified", "release marker matched health readback"],
        "next_step": "Stage the verified last-known-good target",
        "expected_revision": 0,
    }
    assert client.post("/mcp/tools/update_handoff", json=payload).status_code == 401
    created = client.post("/mcp/tools/update_handoff", headers=auth_headers, json=payload)
    assert created.status_code == 200
    assert created.json()["revision"] == 1

    read = client.get("/mcp/handoffs/inc-17", headers=auth_headers)
    assert read.status_code == 200
    assert read.json()["next_step"] == payload["next_step"]

    stale = dict(payload, responder="Noah", expected_revision=0)
    refused = client.post("/mcp/tools/update_handoff", headers=auth_headers, json=stale)
    assert refused.status_code == 409
    assert "stale handoff revision" in refused.json()["detail"]


def test_no_handoff_path_exports_the_cause_code_as_a_confirmed_fact(client, auth_headers):
    """Both handoff paths hand over the candidate wording, never ANOMALY_ATTRIBUTED.

    The demo handoff stopped writing the raw verdict code first. The operator path
    built its facts in the page as ``data.verdict + ': ' + data.explanation`` and so
    still sent "ANOMALY_ATTRIBUTED: ..." as a confirmed fact. It now sends the
    server's ``attribution.handoff_fact``, which this test drives through the operator
    route exactly as the page does, and the store refuses the code from any client.
    """
    answer = client.post("/mcp/tools/what_changed", json={"service_name": "checkout-api"}).json()
    assert answer["verdict"] == "ANOMALY_ATTRIBUTED", "the fixture no longer names a change"
    fact = answer["attribution"]["handoff_fact"]
    commit = answer["offending_commit"]
    assert fact.startswith("Temporal candidate, not proof of cause: commit " + commit["sha"])
    assert "ANOMALY_ATTRIBUTED" not in fact

    # The operator path, with the facts the page builds in publishHandoff().
    metric = answer["metric"]
    published = client.post("/mcp/tools/update_handoff", headers=auth_headers, json={
        "incident_id": "checkout-api-operator",
        "responder": "Primary responder",
        "current_action": "Gathering evidence",
        "confirmed_facts": [
            f"{metric['name']} is {metric['current']} against baseline {metric['baseline']}",
            fact,
        ],
        "next_step": "Keep investigating",
        "expected_revision": 0,
    })
    assert published.status_code == 200, published.text
    facts = published.json()["confirmed_facts"]
    assert facts[1] == fact
    assert not any("ANOMALY_ATTRIBUTED" in item for item in facts)

    # Any other client that still writes the old fact is refused, not stored.
    old_fact = "ANOMALY_ATTRIBUTED: " + answer["explanation"]
    refused = client.post("/mcp/tools/update_handoff", headers=auth_headers, json={
        "incident_id": "checkout-api-operator", "responder": "Script",
        "current_action": "Gathering evidence", "confirmed_facts": [old_fact],
        "next_step": "Keep investigating", "expected_revision": 1,
    })
    assert refused.status_code == 409
    assert "temporal candidate, not proof of cause" in refused.json()["detail"]
    assert client.get("/mcp/handoffs/checkout-api-operator", headers=auth_headers).json()[
        "confirmed_facts"] == facts


def test_every_refusal_hands_over_its_refusal_statement_not_its_code(client):
    for service in ("search-indexer", "release-train", "quiet-service"):
        answer = client.post("/mcp/tools/what_changed", json={"service_name": service}).json()
        assert answer["verdict"] != "ANOMALY_ATTRIBUTED", service
        assert answer["attribution"]["handoff_fact"] == answer["attribution"]["refusal_statement"]
        assert answer["verdict"] not in answer["attribution"]["handoff_fact"]
