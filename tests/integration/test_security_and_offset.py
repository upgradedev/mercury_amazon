"""Security DAST and Parameterized Offset Tests for Mercury."""
import pytest
from fastapi.testclient import TestClient
from src.interfaces.mcp_server import app


client = TestClient(app)


# --- DAST / Malicious Payload Handling ---

def test_dast_invalid_rollback_confirmation():
    res = client.post("/mcp/tools/confirm_rollback", json={
        "action_id": "non_existent_rollback_999",
        "voice_token": "FAKE_TOKEN"
    })
    assert res.status_code == 400


def test_dast_command_injection_in_service_name():
    res = client.post("/mcp/tools/stage_rollback", json={
        "action_id": "rb-inject-01",
        "target_service": "billing; rm -rf /; echo hacked",
        "target_commit_sha": "12345678",
        "reason": "Test"
    })
    assert res.status_code == 200
    assert res.json()["state"] == "PENDING_CONFIRMATION"


# --- Parameterized Offset Fixtures ---

@pytest.mark.parametrize("lease_time", [1.0, 60.0, 300.0, 1200.0])
def test_parameterized_lease_durations(lease_time):
    res = client.post("/mcp/tools/stage_rollback", json={
        "action_id": f"rb-lease-{int(lease_time)}",
        "target_service": "gateway",
        "target_commit_sha": "abcdef01",
        "reason": "Param test",
        "lease_sec": lease_time
    })
    assert res.status_code == 200
    assert res.json()["state"] == "PENDING_CONFIRMATION"
