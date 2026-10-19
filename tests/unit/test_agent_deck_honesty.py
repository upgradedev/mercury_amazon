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

from src.infrastructure.bedrock_incident_agent import (
    FORBIDDEN_CLAIMS,
    BedrockIncidentAgentAdapter,
    forbidden_claim,
)
from src.interfaces.agent_mcp_routes import AGENT_DECK_JS
from src.interfaces.mcp_server import app

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_SERVICES = ("checkout-api", "payments-worker", "search-indexer", "release-train", "quiet-service")
# The production guard, plus the wording the deterministic brief itself dropped.
TWO_STEP_CLAIM = re.compile(r"ready for two-step", re.IGNORECASE)


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
    assert not forbidden_claim(text), FORBIDDEN_CLAIMS.search(text)
    assert not TWO_STEP_CLAIM.search(text), text


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
    assert "50 percent of cases on a synthetic held-out split" in synthesis["commander_brief_10ft"], text
    assert "0.5 of the time" not in text


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


# ------------------------------------------------ capability branches, without AWS

@pytest.mark.parametrize("creds,sdk,expected", [
    (True, True, "ready_to_attempt"),
    (True, False, "unavailable_sdk_not_installed"),
    (False, True, "unavailable_no_credentials"),
    (False, False, "unavailable_no_sdk_and_no_credentials"),
])
def test_the_capability_label_follows_credentials_and_sdk(monkeypatch, creds, sdk, expected):
    """The label an operator reads must not depend on what this machine happens to have."""
    monkeypatch.setattr(BedrockIncidentAgentAdapter, "_resolve_credentials", staticmethod(lambda: creds))
    monkeypatch.setattr(BedrockIncidentAgentAdapter, "sdk_present", staticmethod(lambda: sdk))
    adapter = BedrockIncidentAgentAdapter()
    assert adapter.resolved_capability(refresh=True) == expected
    # A second read inside the cache window does not resolve credentials again.
    assert adapter.credentials_present() is creds
    assert adapter.model_path_capability()["resolved_capability"] == expected


def test_credentials_from_the_environment_count_without_boto3(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIAEXAMPLEONLY")
    assert BedrockIncidentAgentAdapter._resolve_credentials() is True


def test_under_pytest_the_adapter_never_attempts_a_live_call(monkeypatch):
    monkeypatch.setattr(BedrockIncidentAgentAdapter, "_resolve_credentials", staticmethod(lambda: True))
    monkeypatch.setattr(BedrockIncidentAgentAdapter, "sdk_present", staticmethod(lambda: True))
    monkeypatch.setenv("MERCURY_AGENT_MODEL", "on")
    monkeypatch.delenv("MERCURY_ALLOW_BEDROCK_IN_PYTEST", raising=False)
    adapter = BedrockIncidentAgentAdapter()
    assert adapter._can_attempt_live_call(prefer_bedrock=True) is False
    assert adapter.last_fallback_reason == "pytest_offline_guard"


def test_outside_the_guard_a_missing_capability_is_the_fallback_reason(monkeypatch):
    monkeypatch.setattr(BedrockIncidentAgentAdapter, "_resolve_credentials", staticmethod(lambda: False))
    monkeypatch.setattr(BedrockIncidentAgentAdapter, "sdk_present", staticmethod(lambda: True))
    monkeypatch.setenv("MERCURY_ALLOW_BEDROCK_IN_PYTEST", "1")
    monkeypatch.setenv("MERCURY_AGENT_MODEL", "on")
    adapter = BedrockIncidentAgentAdapter()
    assert adapter._can_attempt_live_call(prefer_bedrock=True) is False
    assert adapter.last_fallback_reason == "unavailable_no_credentials"


def test_an_empty_or_malformed_model_reply_falls_back_or_is_wrapped(seeded_client):
    payload = _payload_for(seeded_client, "search-indexer")
    empty = BedrockIncidentAgentAdapter(client_factory=lambda region: _CapturingClient("   "))
    result = empty.synthesize_incident_brief(what_changed_payload=payload)
    assert result["synthesis_mode"] == "deterministic"
    assert result["fallback_reason"] == "ValueError"

    broken = BedrockIncidentAgentAdapter(
        client_factory=lambda region: _CapturingClient("{not json at all}"))
    wrapped = broken.synthesize_incident_brief(what_changed_payload=payload)
    assert wrapped["synthesis_mode"] == "bedrock"
    assert wrapped["commander_brief_10ft"] == "{not json at all}"
    assert wrapped["incident_severity"] == "SEV-2_ATTRIBUTION_REFUSED"


# ------------------------------------------------ 10-19 review of PR #62

#: Each string passed the guard before the review, or was put in the prompt by it.
@pytest.mark.parametrize("claim", [
    "The rollback is awaiting authorized staging.",
    "Status: AWAITING_AUTHORIZED_STAGING",
    "A governed rollback of checkout-api is ready to stage now.",
    "Errors rose after a4ec9aa shrank the pool.",
    "a4ec9aa introduced the regression.",
])
def test_the_production_guard_rejects_the_wording_the_review_found(seeded_client, claim):
    assert forbidden_claim(claim), claim
    reply = json.dumps({"commander_brief_10ft": claim})
    adapter = BedrockIncidentAgentAdapter(client_factory=lambda region: _CapturingClient(reply))
    result = adapter.synthesize_incident_brief(what_changed_payload=_payload_for(seeded_client, "checkout-api"))
    assert result["fallback_reason"] == "model_claim_rejected"
    assert result["model_call_attempted"] is True and result["model_answered"] is None
    assert claim not in json.dumps(result)


def test_the_prompt_carries_no_staging_status_lease_or_note(seeded_client):
    payload = _payload_for(seeded_client, "checkout-api")
    assert payload["recommended_action"]["status"] == "AWAITING_AUTHORIZED_STAGING"
    capture = _CapturingClient(json.dumps({"commander_brief_10ft": "Candidate only."}))
    BedrockIncidentAgentAdapter(client_factory=lambda region: capture).synthesize_incident_brief(
        what_changed_payload=payload
    )
    prompt = capture.prompts[0]
    assert "AWAITING_AUTHORIZED_STAGING" not in prompt
    assert "lease" not in prompt.lower()
    assert payload["recommended_action"]["note"] not in prompt
    assert payload["recommended_action"]["target_commit_sha"] in prompt


def test_the_deployed_adapter_calls_no_model_unless_the_server_opts_in(monkeypatch):
    monkeypatch.setattr(BedrockIncidentAgentAdapter, "_resolve_credentials", staticmethod(lambda: True))
    monkeypatch.setattr(BedrockIncidentAgentAdapter, "sdk_present", staticmethod(lambda: True))
    monkeypatch.setenv("MERCURY_ALLOW_BEDROCK_IN_PYTEST", "1")
    monkeypatch.delenv("MERCURY_AGENT_MODEL", raising=False)
    adapter = BedrockIncidentAgentAdapter()
    assert adapter._can_attempt_live_call(prefer_bedrock=True) is False
    assert adapter.last_fallback_reason == "model_off_by_default"
    monkeypatch.setenv("MERCURY_AGENT_MODEL", "yes")
    assert adapter._can_attempt_live_call(prefer_bedrock=True) is False
    assert adapter.last_fallback_reason == "model_off_by_default"


def test_model_calls_stop_at_the_per_process_cap(seeded_client, monkeypatch):
    monkeypatch.setenv("MERCURY_AGENT_MODEL_MAX_CALLS", "1")
    capture = _CapturingClient(json.dumps({"commander_brief_10ft": "Candidate only."}))
    adapter = BedrockIncidentAgentAdapter(client_factory=lambda region: capture)
    first = adapter.synthesize_incident_brief(what_changed_payload=_payload_for(seeded_client, "checkout-api"))
    second = adapter.synthesize_incident_brief(what_changed_payload=_payload_for(seeded_client, "search-indexer"))
    assert first["synthesis_mode"] == "bedrock"
    assert second["synthesis_mode"] == "deterministic"
    assert second["fallback_reason"] == "model_call_cap_reached"
    assert len(capture.prompts) == 1


@pytest.mark.parametrize("service", FIXTURE_SERVICES + ("no-such-service",))
def test_a_deterministic_brief_names_no_model_on_the_route_or_through_tools_call(seeded_client, service):
    body = seeded_client.post("/mcp/tools/agent_incident_brief", json={"service_name": service}).json()
    synthesis = body["agent_synthesis"]
    assert synthesis["synthesis_mode"] == "deterministic"
    assert synthesis["model_id"] is None and synthesis["region"] is None
    assert "bedrock_model_path" not in body
    rpc = seeded_client.post("/mcp", json={
        "jsonrpc": "2.0", "id": 5, "method": "tools/call",
        "params": {"name": "agent_incident_brief", "arguments": {"service_name": service}},
    }).json()
    text = rpc["result"]["content"][0]["text"]
    # A fixture commit message may name a claude/ branch, so look for the model id.
    assert "anthropic.claude" not in text and "sonnet" not in text.lower()
    assert "bedrock_model_path" not in text
    assert '"region": "eu-west-1"' not in text


def test_a_partial_model_reply_names_only_the_fields_the_model_wrote(seeded_client):
    reply = json.dumps({"commander_brief_10ft": "Candidate only, from the model."})
    adapter = BedrockIncidentAgentAdapter(client_factory=lambda region: _CapturingClient(reply))
    result = adapter.synthesize_incident_brief(what_changed_payload=_payload_for(seeded_client, "checkout-api"))
    assert result["synthesis_mode"] == "bedrock"
    assert result["model_fields"] == ["commander_brief_10ft"]
    assert result["template_fields"] == ["incident_severity", "root_cause_hypothesis", "responder_handoff_draft"]
    assert "model_fields" in AGENT_DECK_JS and "deterministic template" in AGENT_DECK_JS


def test_the_deck_says_a_rejected_model_answer_was_rejected():
    assert "model answer rejected (claim guard)" in AGENT_DECK_JS
    assert "model_claim_rejected" in AGENT_DECK_JS


def test_an_attributed_commit_without_a_rollback_target_names_the_candidate_and_why(seeded_client):
    payload = _payload_for(seeded_client, "checkout-api")
    payload["recommended_action"] = None
    payload["deployment_evidence"]["blocked_reason"] = "No authenticated deployment marker proves a target."
    result = BedrockIncidentAgentAdapter().synthesize_incident_brief(
        what_changed_payload=payload, prefer_bedrock=False
    )
    sha = payload["offending_commit"]["sha"][:7]
    text = json.dumps(result)
    assert "refused to name a commit" not in text
    assert result["incident_severity"] == "SEV-2_NO_ROLLBACK_TARGET"
    assert sha in result["commander_brief_10ft"]
    assert "No authenticated deployment marker proves a target." in text
