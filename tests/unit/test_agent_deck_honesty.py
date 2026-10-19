"""The agent deck and its brief have to say what they are.

The deck sits on the page judges open. These tests hold its server side to the
same rules the rest of the board follows: the data is an offline fixture, dispatch
is record-only, a named commit is a temporal candidate and not a cause, and the
engine label names a model only when a model answered.
"""
from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from src.infrastructure.bedrock_incident_agent import BedrockIncidentAgentAdapter
from src.interfaces.agent_mcp_routes import AGENT_DECK_JS
from src.interfaces.mcp_server import app

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_SERVICES = ("checkout-api", "payments-worker", "search-indexer", "release-train", "quiet-service")
STAGED_CLAIM = re.compile(r"\b(is|was|has been) staged\b|awaiting authori|ready for two-step", re.IGNORECASE)


class _CapturingClient:
    def __init__(self, text: str) -> None:
        self.prompts: list[str] = []
        outer = self

        class _Messages:
            def create(self, **kwargs: Any) -> dict[str, Any]:
                outer.prompts.append(kwargs["messages"][0]["content"])
                return {"content": [{"type": "text", "text": text}]}

        self.messages = _Messages()


def _brief(client: TestClient, service: str) -> dict[str, Any]:
    response = client.post(
        "/mcp/tools/agent_incident_brief",
        json={"service_name": service, "prefer_bedrock": False},
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture
def seeded_client() -> TestClient:
    from src.infrastructure.demo_evidence import seed_recorded_demo_evidence
    from src.interfaces.mcp_server import deployment_evidence, incident_use_case

    seed_recorded_demo_evidence(incident_use_case, deployment_evidence)
    return TestClient(app)


def test_root_serves_the_page_with_the_deck_judges_get(seeded_client):
    """Tests used to get the page without the deck while judges got it with."""
    body = seeded_client.get("/").text
    assert '<script src="/mcp/agent-deck.js" defer></script>' in body


@pytest.mark.parametrize("service", FIXTURE_SERVICES)
def test_every_fixture_brief_carries_the_stamps_and_claims_no_staging(seeded_client, service):
    body = _brief(seeded_client, service)
    assert body["data_label"] == "OFFLINE FIXTURE"
    assert body["rollback_dispatch"] == "record-only"
    synthesis = body["agent_synthesis"]
    assert synthesis["synthesis_mode"] == "deterministic"
    assert synthesis["model_answered"] is None
    text = json.dumps(synthesis)
    assert not STAGED_CLAIM.search(text), text


def test_insufficient_data_is_reported_as_missing_data_not_as_an_elevated_reading(seeded_client):
    body = _brief(seeded_client, "quiet-service")
    assert body["verdict"] == "INSUFFICIENT_DATA"
    synthesis = body["agent_synthesis"]
    text = json.dumps(synthesis).lower()
    assert "elevated" not in text and "spiked" not in text, text
    assert "0.0x" not in text, text
    assert "missing data" in text or "no readings" in text, text
    assert synthesis["incident_severity"] == "INSUFFICIENT_DATA"


def test_no_anomaly_is_not_called_elevated(seeded_client):
    body = _brief(seeded_client, "payments-worker")
    assert body["verdict"] == "NO_ANOMALY"
    text = json.dumps(body["agent_synthesis"]).lower()
    assert "elevated" not in text and "spiked" not in text, text
    assert body["agent_synthesis"]["incident_severity"] == "NOMINAL_NO_ANOMALY"


def test_a_named_commit_is_a_temporal_candidate_with_its_measured_precision(seeded_client):
    body = _brief(seeded_client, "checkout-api")
    assert body["verdict"] == "ANOMALY_ATTRIBUTED"
    synthesis = body["agent_synthesis"]
    text = json.dumps(synthesis)
    assert "not proof" in text.lower() or "does not prove" in text.lower(), text
    assert "0.5" in synthesis["commander_brief_10ft"] + synthesis["root_cause_hypothesis"], text


def _payload_for(client: TestClient, service: str) -> dict[str, Any]:
    response = client.post("/mcp/tools/what_changed", json={"service_name": service})
    assert response.status_code == 200
    return response.json()


def test_the_prompt_says_fixture_and_record_only_and_forbids_cause_and_staging(seeded_client):
    capture = _CapturingClient(json.dumps({"commander_brief_10ft": "Candidate only."}))
    adapter = BedrockIncidentAgentAdapter(client_factory=lambda region: capture)
    adapter.synthesize_incident_brief(
        what_changed_payload=_payload_for(seeded_client, "checkout-api"),
        data_label="OFFLINE FIXTURE",
        rollback_dispatch="record-only",
    )
    prompt = capture.prompts[0]
    assert "OFFLINE FIXTURE" in prompt
    assert "record-only" in prompt
    assert "Do not claim a cause" in prompt
    assert "Do not say a rollback is staged" in prompt


@pytest.mark.parametrize("claim", [
    "checkout-api errors rose after commit 4812b17. A governed rollback is staged and awaiting authorization.",
    "The spike was caused by commit 4812b17 shrinking the connection pool.",
    "Rollback to 3d90a01 was executed and the service recovered.",
])
def test_a_model_answer_that_claims_a_cause_or_a_rollback_is_replaced(seeded_client, claim):
    reply = json.dumps({"commander_brief_10ft": claim, "root_cause_hypothesis": "x"})
    adapter = BedrockIncidentAgentAdapter(client_factory=lambda region: _CapturingClient(reply))
    result = adapter.synthesize_incident_brief(
        what_changed_payload=_payload_for(seeded_client, "checkout-api"),
        data_label="OFFLINE FIXTURE",
        rollback_dispatch="record-only",
    )
    assert result["synthesis_mode"] == "deterministic"
    assert result["model_answered"] is None
    assert result["fallback_reason"] == "model_claim_rejected"
    assert claim not in json.dumps(result)


def test_insufficient_data_never_reaches_the_model(seeded_client):
    capture = _CapturingClient("{}")
    adapter = BedrockIncidentAgentAdapter(client_factory=lambda region: capture)
    result = adapter.synthesize_incident_brief(
        what_changed_payload=_payload_for(seeded_client, "quiet-service"),
    )
    assert capture.prompts == []
    assert result["synthesis_mode"] == "deterministic"
    assert result["fallback_reason"] == "insufficient_data"


def test_agent_status_does_not_claim_pii_redaction_for_the_agent_path(seeded_client):
    body = seeded_client.get("/mcp/tools/agent_status").json()
    observability = body["observability"]
    assert observability.get("pii_redaction_active") is not True
    assert observability["agent_prompt_pii_redaction"] is False
    # The request audit log does mask, and the flag says so only because a probe passed.
    assert observability["audit_log_pii_masking"] is True


def test_the_anthropic_sdk_is_declared_where_pyproject_and_the_lambda_package_read_it():
    from scripts.build_lambda_package import RUNTIME_REQUIREMENTS

    project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    declared = [d for d in project["dependencies"] if d.replace(" ", "").startswith("anthropic")]
    assert declared == ["anthropic==1.8.0"], declared
    assert "anthropic==1.8.0" in RUNTIME_REQUIREMENTS


def test_the_deck_script_makes_no_call_of_its_own_accord():
    """A source check that backs up the browser test, which CI requires."""
    assert not re.search(r"setTimeout\(\s*function\s*\(\)\s*\{\s*runBrief", AGENT_DECK_JS)
    assert "setTimeout(runMcp" not in AGENT_DECK_JS
    assert ".btn-demo[data-service]" not in AGENT_DECK_JS
    assert "'bedrock')" not in AGENT_DECK_JS
    assert "Claude Sonnet 5 + MCP" not in AGENT_DECK_JS
    assert chr(0x2014) not in AGENT_DECK_JS  # no em dash in on-screen copy
