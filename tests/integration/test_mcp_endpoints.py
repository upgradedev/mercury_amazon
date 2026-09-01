"""Integration tests for Mercury FastMCP Endpoints."""
from fastapi.testclient import TestClient
from src.interfaces.mcp_server import app


client = TestClient(app)


def test_health_endpoint():
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json()["service"] == "mercury-voice-cto"


def test_demo_ui_endpoint():
    res = client.get("/demo")
    assert res.status_code == 200
    assert "Mercury: Voice CTO Cockpit" in res.text


def test_dora_velocity_tool():
    res = client.post("/mcp/tools/get_dora_velocity_report")
    assert res.status_code == 200
    data = res.json()
    assert "voice_summary" in data
    assert data["tier"] in ["ELITE", "HIGH", "MEDIUM", "LOW"]


def test_pr_bottlenecks_tool():
    res = client.post("/mcp/tools/get_pr_bottlenecks")
    assert res.status_code == 200
    data = res.json()
    assert data["total_open"] > 0
    assert len(data["stale_prs"]) >= 1


def test_aws_cost_anomalies_tool():
    res = client.post("/mcp/tools/get_aws_cost_anomalies")
    assert res.status_code == 200
    data = res.json()
    assert data["month_to_date_usd"] > 0
    assert len(data["anomalies"]) >= 1


def test_governed_rollback_flow():
    stage_res = client.post("/mcp/tools/stage_rollback", json={
        "action_id": "mcp-rb-01",
        "target_service": "billing-api",
        "target_commit_sha": "abc12345",
        "reason": "Database connection pool exhaustion"
    })
    assert stage_res.status_code == 200
    assert stage_res.json()["state"] == "PENDING_CONFIRMATION"

    confirm_res = client.post("/mcp/tools/confirm_rollback", json={
        "action_id": "mcp-rb-01",
        "voice_token": "CTO_VOICE_VERIFIED"
    })
    assert confirm_res.status_code == 200
    assert confirm_res.json()["status"] == "EXECUTED"
