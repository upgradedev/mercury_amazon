"""
Unit tests for Mercury Fire TV Incident Commander workflow.
"""

import pytest
from fastapi.testclient import TestClient
from src.interfaces.mcp_server import app


@pytest.fixture
def client():
    return TestClient(app)


def test_what_changed_root_cause_query(client):
    """Verifies 'Alexa, what changed?' returns offending commit and CloudWatch anomaly."""
    res = client.post("/mcp/tools/what_changed", json={"service_name": "checkout-api", "time_window_minutes": 45})
    assert res.status_code == 200
    data = res.json()
    assert data["incident_detected"] is True
    assert data["service"] == "checkout-api"
    assert "7c8f2a1" in data["offending_commit"]["sha"]
    assert "340%" in data["voice_summary"] or "34.2x" in data["cloudwatch_signal"]["anomaly_factor"]
    assert data["recommended_action"]["type"] == "GOVERNED_ROLLBACK"
    assert data["recommended_action"]["target_commit_sha"] == "3e9d10c"
    assert data["recommended_action"]["status"] == "AWAITING_HUMAN_CONFIRMATION"


def test_incident_commander_rollback_execution(client):
    """Verifies staging and executing a governed rollback via Incident Commander."""
    stage_res = client.post(
        "/mcp/tools/stage_rollback",
        json={
            "action_id": "INCIDENT-4021",
            "target_service": "checkout-api",
            "target_commit_sha": "3e9d10c",
            "reason": "Reverting PR #412 due to CloudWatch 5xx spike",
            "lease_sec": 300.0,
        },
    )
    assert stage_res.status_code == 200
    stage_data = stage_res.json()
    assert stage_data["action_id"] == "INCIDENT-4021"
    assert stage_data["state"] in ["STAGED", "PENDING_CONFIRMATION"]

    confirm_res = client.post(
        "/mcp/tools/confirm_rollback",
        json={
            "action_id": "INCIDENT-4021",
            "voice_token": "ALPHA-77",
        },
    )
    assert confirm_res.status_code == 200
    assert confirm_res.json()["status"] == "EXECUTED"
