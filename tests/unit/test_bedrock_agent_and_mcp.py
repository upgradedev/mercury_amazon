"""Unit and integration tests for Amazon Bedrock SRE Agent & MCP 2025-11-25 routes in Mercury."""
from __future__ import annotations

import json
from typing import Any

from fastapi.testclient import TestClient

from src.infrastructure.bedrock_incident_agent import (
    BedrockIncidentAgentAdapter,
    public_model_label,
)
from src.interfaces.mcp_server import app


class _FakeMessages:
    def __init__(self, text_response: str, should_raise: bool = False) -> None:
        self._text = text_response
        self._should_raise = should_raise
        self.calls = 0

    def create(self, **kwargs: Any) -> dict[str, Any]:
        self.calls += 1
        if self._should_raise:
            raise RuntimeError("Simulated Bedrock throttling")
        return {"content": [{"type": "text", "text": self._text}], "stop_reason": "end_turn"}


class _FakeBedrockClient:
    def __init__(self, text_response: str, should_raise: bool = False) -> None:
        self.messages = _FakeMessages(text_response, should_raise=should_raise)


def test_public_model_label_strips_account_arn():
    assert public_model_label("anthropic.claude-sonnet-5") == "anthropic.claude-sonnet-5"
    arn = "arn:aws:bedrock:eu-west-1:123456789012:inference-profile/eu.anthropic.claude-sonnet-5"
    assert public_model_label(arn) == "eu.anthropic.claude-sonnet-5"


def test_bedrock_incident_agent_synthesizes_and_caches_with_injected_client():
    fake_json = (
        "```json\n"
        + json.dumps(
            {
                "incident_severity": "SEV-1_ROLLBACK_READY",
                "commander_brief_10ft": "checkout-api 5xx spiked after commit 4812b17. Governed rollback to 3d90a01 is ready.",
                "root_cause_hypothesis": "Sole runtime commit 4812b17 modified checkout handler inside the 60m window.",
                "responder_handoff_draft": {
                    "current_action": "Stage and confirm rollback to 3d90a01.",
                    "confirmed_facts": ["5xx spiked 15.1x."],
                    "next_step": "Verify post-rollback health readback.",
                },
            }
        )
        + "\n```"
    )
    fake_client = _FakeBedrockClient(fake_json)
    adapter = BedrockIncidentAgentAdapter(
        region_name="eu-west-1",
        model_id="anthropic.claude-sonnet-5",
        client_factory=lambda region: fake_client,
    )
    assert adapter.health_summary()["model_id"] == "anthropic.claude-sonnet-5"
    assert adapter.model_path_capability()["model_id"] == "anthropic.claude-sonnet-5"

    sample_payload = {
        "service": "checkout-api",
        "verdict": "ANOMALY_ATTRIBUTED",
        "metric": {"name": "5xx", "baseline": 12.0, "current": 181.2, "anomaly_factor": 15.1},
        "attribution": {"commits_in_window": 1, "nothing_to_revert": False},
        "offending_commit": {"sha": "4812b17abc", "message": "Update checkout", "runtime_files": ["src/app.py"]},
        "recommended_action": {"target_commit_sha": "3d90a01def"},
    }
    res1 = adapter.synthesize_incident_brief(what_changed_payload=sample_payload)
    assert res1["synthesis_mode"] == "bedrock"
    assert res1["model_answered"] == "anthropic.claude-sonnet-5"
    assert res1["cached"] is False
    assert res1["incident_severity"] == "SEV-1_ROLLBACK_READY"
    assert fake_client.messages.calls == 1

    res2 = adapter.synthesize_incident_brief(what_changed_payload=sample_payload)
    assert res2["cached"] is True
    assert fake_client.messages.calls == 1


def test_bedrock_incident_agent_falls_back_cleanly_on_error_and_nominal_services():
    plain_client = _FakeBedrockClient("Plain prose without JSON braces", should_raise=False)
    plain_adapter = BedrockIncidentAgentAdapter(client_factory=lambda region: plain_client)
    res_plain = plain_adapter.synthesize_incident_brief(
        what_changed_payload={
            "service": "quiet-service",
            "verdict": "NO_ANOMALY",
            "metric": {"name": "5xx", "baseline": 10.0, "current": 10.2, "anomaly_factor": 1.02},
            "attribution": {"nothing_to_revert": True},
        }
    )
    assert res_plain["synthesis_mode"] == "bedrock"
    assert "Plain prose" in res_plain["commander_brief_10ft"]

    err_client = _FakeBedrockClient("{}", should_raise=True)
    err_adapter = BedrockIncidentAgentAdapter(client_factory=lambda region: err_client)
    res_err = err_adapter.synthesize_incident_brief(
        what_changed_payload={
            "service": "search-indexer",
            "verdict": "ATTRIBUTION_REFUSED",
            "metric": {"name": "5xx", "baseline": 10.0, "current": 95.0, "anomaly_factor": 9.5},
            "attribution": {"nothing_to_revert": False, "refusal_reason": "WINDOW_TOO_CROWDED"},
        }
    )
    assert res_err["synthesis_mode"] == "deterministic"
    assert res_err["fallback_reason"] == "RuntimeError"
    assert res_err["incident_severity"] == "SEV-2_ATTRIBUTION_REFUSED"

    res_disabled = err_adapter.synthesize_incident_brief(
        what_changed_payload={
            "service": "quiet-service",
            "verdict": "NO_ANOMALY",
            "metric": {"name": "5xx", "baseline": 10.0, "current": 10.0, "anomaly_factor": 1.0},
            "attribution": {"nothing_to_revert": True},
        },
        prefer_bedrock=False,
    )
    assert res_disabled["fallback_reason"] == "prefer_bedrock_false"
    assert res_disabled["incident_severity"] == "NOMINAL_NO_ANOMALY"


def test_health_and_agent_endpoints_expose_bedrock_and_mcp_2025_11_25():
    from src.infrastructure.demo_evidence import seed_recorded_demo_evidence
    from src.interfaces.mcp_server import deployment_evidence, incident_use_case

    seed_recorded_demo_evidence(incident_use_case, deployment_evidence)
    client = TestClient(app)
    h_resp = client.get("/health")
    assert h_resp.status_code == 200
    h_body = h_resp.json()
    assert h_body["mcp_protocol"] == "2025-11-25"
    assert h_body["bedrock_agent"]["model_id"] == "anthropic.claude-sonnet-5"

    s_resp = client.get("/mcp/tools/agent_status")
    assert s_resp.status_code == 200
    s_body = s_resp.json()
    assert s_body["mcp_protocol"]["version"] == "2025-11-25"
    assert s_body["mcp_protocol"]["tools_published"] == 10

    b_resp = client.post("/mcp/tools/agent_incident_brief", json={"service_name": "checkout-api"})
    assert b_resp.status_code == 200
    b_body = b_resp.json()
    assert b_body["service"] == "checkout-api"
    assert "agent_synthesis" in b_body
    assert b_body["agent_synthesis"]["incident_severity"] == "SEV-1_ROLLBACK_READY"

    deck_resp = client.get("/mcp/agent-deck.js")
    assert deck_resp.status_code == 200
    assert "application/javascript" in deck_resp.headers.get("content-type", "")
    assert "btnAgentBrief" in deck_resp.text
    assert "btnAgentPublishHandoff" in deck_resp.text
    assert "btnAgentMcpHandshake" in deck_resp.text

    root_default = client.get("/")
    assert root_default.status_code == 200
    assert "/mcp/agent-deck.js" not in root_default.text

    root_agent = client.get("/?agent=1")
    assert root_agent.status_code == 200
    assert '<script src="/mcp/agent-deck.js" defer></script>' in root_agent.text



def test_mcp_2025_11_25_streamable_http_lifecycle_and_all_tools():
    from src.infrastructure.demo_evidence import seed_recorded_demo_evidence
    from src.interfaces.mcp_server import deployment_evidence, incident_use_case

    seed_recorded_demo_evidence(incident_use_case, deployment_evidence)
    client = TestClient(app)
    get_resp = client.get("/mcp")
    assert get_resp.status_code == 405
    assert get_resp.headers.get("Allow") == "POST"

    bad_json = client.post("/mcp", content=b"{invalid")
    assert bad_json.json()["error"]["code"] == -32700

    batch_json = client.post("/mcp", json=[{"jsonrpc": "2.0", "id": 1, "method": "ping"}])
    assert batch_json.json()["error"]["code"] == -32600

    init_resp = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-11-25"},
        },
    )
    assert init_resp.status_code == 200
    assert init_resp.headers.get("MCP-Session-Id")
    assert init_resp.json()["result"]["protocolVersion"] == "2025-11-25"

    notif_resp = client.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert notif_resp.status_code == 202

    ping_resp = client.post("/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "ping"})
    assert ping_resp.json()["result"] == {}

    unknown_method = client.post("/mcp", json={"jsonrpc": "2.0", "id": 3, "method": "prompts/list"})
    assert unknown_method.json()["error"]["code"] == -32601

    list_resp = client.post("/mcp", json={"jsonrpc": "2.0", "id": 4, "method": "tools/list"})
    tools = list_resp.json()["result"]["tools"]
    assert len(tools) == 10

    for idx, (tool_name, args) in enumerate(
        [
            ("agent_incident_brief", {"service_name": "checkout-api"}),
            ("agent_status", {"refresh": False}),
            ("what_changed", {"service_name": "checkout-api"}),
            ("get_dora_velocity_report", {}),
            ("get_pr_bottlenecks", {}),
            ("get_aws_cost_anomalies", {}),
            ("audit_observability", {"service_name": "checkout-api", "received_signals": ["ErrorCount"]}),
            ("deployment_timeline", {"service": "checkout-api", "environment": "production"}),
            ("demo_update_handoff", {"service_name": "checkout-api"}),
        ],
        start=20,
    ):
        call_resp = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": idx, "method": "tools/call", "params": {"name": tool_name, "arguments": args}},
        )
        assert call_resp.status_code == 200
        assert call_resp.json()["result"]["isError"] is False

    bad_tool = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 99, "method": "tools/call", "params": {"name": "unknown_tool", "arguments": {}}},
    )
    assert bad_tool.json()["error"]["code"] == -32602
