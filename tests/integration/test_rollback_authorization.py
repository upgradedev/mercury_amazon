"""Integration tests for the rollback authorization boundary.

These are the tests that prove the control can refuse. Before this boundary
existed, anyone who could reach the deployment could stage and confirm a
production rollback with an arbitrary string as the token.
"""
import time

import pytest

from src.domain.governed_rollback import mint_governance_token

STAGE = "/mcp/tools/stage_rollback"
CONFIRM = "/mcp/tools/confirm_rollback"


def stage_payload(action_id="itest-1", **overrides):
    payload = {
        "action_id": action_id,
        "target_service": "checkout-api",
        "target_commit_sha": "3e9d10c",
        "reason": "Integration test staging",
        "lease_sec": 300.0,
    }
    payload.update(overrides)
    return payload


# ----------------------------------------------------------- Bearer enforcement

def test_staging_without_a_bearer_header_is_unauthorized(client):
    res = client.post(STAGE, json=stage_payload())
    assert res.status_code == 401
    assert "Bearer" in res.json()["detail"]


def test_confirming_without_a_bearer_header_is_unauthorized(client):
    res = client.post(CONFIRM, json={"action_id": "x", "governance_token": "y"})
    assert res.status_code == 401


@pytest.mark.parametrize("header", [
    "Bearer wrong-secret",
    "Bearer ",
    "Basic dXNlcjpwYXNz",
    "test-secret-do-not-use-in-production",  # right value, missing the scheme
])
def test_a_bad_authorization_header_is_unauthorized(client, header):
    res = client.post(STAGE, headers={"Authorization": header}, json=stage_payload())
    assert res.status_code == 401


def test_the_unauthorized_response_does_not_leak_the_secret(client):
    body = client.post(STAGE, headers={"Authorization": "Bearer nope"}, json=stage_payload()).text
    assert "test-secret-do-not-use-in-production" not in body


# ------------------------------------------------------------- Governance token

def test_authorized_staging_returns_a_bound_single_use_token(client, auth_headers):
    res = client.post(STAGE, headers=auth_headers, json=stage_payload("itest-happy"))
    assert res.status_code == 200
    body = res.json()
    assert body["state"] == "PENDING_CONFIRMATION"
    assert len(body["payload_hash"]) == 64
    assert body["governance_token"].startswith("v1.itest-happy.")
    assert body["lease_seconds_remaining"] <= 300.0

    confirmed = client.post(CONFIRM, headers=auth_headers, json={
        "action_id": "itest-happy", "governance_token": body["governance_token"],
    })
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "EXECUTED"


def test_a_replayed_token_is_refused_the_second_time(client, auth_headers):
    staged = client.post(STAGE, headers=auth_headers, json=stage_payload("itest-replay")).json()
    token = staged["governance_token"]

    assert client.post(CONFIRM, headers=auth_headers, json={
        "action_id": "itest-replay", "governance_token": token}).status_code == 200

    # Re-stage the same id so the action is pending again, then replay.
    client.post(STAGE, headers=auth_headers, json=stage_payload("itest-replay"))
    replay = client.post(CONFIRM, headers=auth_headers, json={
        "action_id": "itest-replay", "governance_token": token})
    assert replay.status_code == 409
    assert replay.json()["detail"]["denial_reason"] == "TOKEN_ALREADY_USED"


def test_an_arbitrary_string_is_not_a_governance_token(client, auth_headers):
    client.post(STAGE, headers=auth_headers, json=stage_payload("itest-arbitrary"))
    res = client.post(CONFIRM, headers=auth_headers, json={
        "action_id": "itest-arbitrary", "governance_token": "ALPHA-77"})
    assert res.status_code == 400
    assert res.json()["detail"]["denial_reason"] == "MALFORMED_TOKEN"


def test_a_token_forged_with_another_secret_is_refused(client, auth_headers):
    staged = client.post(STAGE, headers=auth_headers, json=stage_payload("itest-forged")).json()
    forged = mint_governance_token("attacker", "itest-forged", staged["payload_hash"])
    res = client.post(CONFIRM, headers=auth_headers, json={
        "action_id": "itest-forged", "governance_token": forged})
    assert res.status_code == 403
    assert res.json()["detail"]["denial_reason"] == "BAD_SIGNATURE"


def test_a_token_from_another_action_is_refused(client, auth_headers):
    first = client.post(STAGE, headers=auth_headers, json=stage_payload("itest-a")).json()
    client.post(STAGE, headers=auth_headers, json=stage_payload("itest-b"))
    res = client.post(CONFIRM, headers=auth_headers, json={
        "action_id": "itest-b", "governance_token": first["governance_token"]})
    assert res.status_code == 403
    assert res.json()["detail"]["denial_reason"] == "TOKEN_ACTION_MISMATCH"


def test_confirming_an_unknown_action_is_a_404(client, auth_headers):
    res = client.post(CONFIRM, headers=auth_headers, json={
        "action_id": "never-staged-at-all", "governance_token": "v1.a.b.c.d"})
    assert res.status_code == 404
    assert res.json()["detail"]["denial_reason"] == "UNKNOWN_ACTION"


def test_an_expired_lease_is_refused(client, auth_headers):
    from src.interfaces.mcp_server import rollback_use_case

    staged = client.post(STAGE, headers=auth_headers,
                         json=stage_payload("itest-expired", lease_sec=1.0)).json()
    action = rollback_use_case.get("itest-expired")
    action.created_at_epoch = time.time() - 60.0

    res = client.post(CONFIRM, headers=auth_headers, json={
        "action_id": "itest-expired", "governance_token": staged["governance_token"]})
    assert res.status_code == 410
    assert res.json()["detail"]["denial_reason"] == "LEASE_EXPIRED"


def test_editing_the_target_after_staging_invalidates_the_token(client, auth_headers):
    """Content binding, end to end: change what will ship, the token stops working."""
    from src.interfaces.mcp_server import rollback_use_case

    staged = client.post(STAGE, headers=auth_headers, json=stage_payload("itest-tamper")).json()
    rollback_use_case.get("itest-tamper").target_commit_sha = "attacker-chosen-sha"

    res = client.post(CONFIRM, headers=auth_headers, json={
        "action_id": "itest-tamper", "governance_token": staged["governance_token"]})
    assert res.status_code == 403
    assert res.json()["detail"]["denial_reason"] == "TOKEN_CONTENT_MISMATCH"


# ------------------------------------------------------------- Input validation

@pytest.mark.parametrize("lease", [0, -5, 3601])
def test_out_of_range_leases_are_rejected(client, auth_headers, lease):
    res = client.post(STAGE, headers=auth_headers, json=stage_payload("itest-lease", lease_sec=lease))
    assert res.status_code == 422


@pytest.mark.parametrize("lease", [1.0, 60.0, 300.0, 1200.0, 3600.0])
def test_in_range_leases_are_accepted(client, auth_headers, lease):
    res = client.post(STAGE, headers=auth_headers,
                      json=stage_payload(f"itest-lease-{lease}", lease_sec=lease))
    assert res.status_code == 200
    assert res.json()["state"] == "PENDING_CONFIRMATION"


def test_empty_required_fields_are_rejected(client, auth_headers):
    res = client.post(STAGE, headers=auth_headers, json=stage_payload("itest-empty", target_service=""))
    assert res.status_code == 422


def test_an_overlong_reason_is_rejected(client, auth_headers):
    res = client.post(STAGE, headers=auth_headers,
                      json=stage_payload("itest-long", reason="x" * 2000))
    assert res.status_code == 422


def test_a_shell_metacharacter_service_name_is_stored_verbatim_not_executed(client, auth_headers):
    """Nothing shells out, so the string is data. This records that it stays data."""
    hostile = "billing; rm -rf /; echo hacked"
    res = client.post(STAGE, headers=auth_headers,
                      json=stage_payload("itest-inject", target_service=hostile))
    assert res.status_code == 200
    assert res.json()["target_service"] == hostile


def test_a_refused_confirmation_burns_the_staged_action(client, auth_headers):
    """Fail-closed on purpose: a tampering attempt costs the operator a re-stage.

    Documented in the README and in the domain docstring, so this test exists to
    stop the behaviour changing silently in either direction.
    """
    staged = client.post(STAGE, headers=auth_headers, json=stage_payload("itest-burn")).json()

    rejected = client.post(CONFIRM, headers=auth_headers, json={
        "action_id": "itest-burn", "governance_token": "not-a-real-token"})
    assert rejected.status_code == 400

    # The correct token no longer works, because the action is no longer pending.
    followup = client.post(CONFIRM, headers=auth_headers, json={
        "action_id": "itest-burn", "governance_token": staged["governance_token"]})
    assert followup.status_code == 409
    assert followup.json()["detail"]["denial_reason"] == "NOT_PENDING"


def test_the_security_audit_script_passes_against_the_running_app():
    """scripts/security_audit.py is a check, so a green suite must include it."""
    import subprocess
    import sys
    from pathlib import Path

    repo_root = Path(__file__).resolve().parent.parent.parent
    result = subprocess.run(
        [sys.executable, "scripts/security_audit.py"],
        capture_output=True, text=True, cwd=str(repo_root), timeout=300,
    )
    assert result.returncode == 0, f"security audit failed:\n{result.stdout[-2000:]}"
    assert "checks passed" in result.stdout
