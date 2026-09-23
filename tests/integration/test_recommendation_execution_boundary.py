"""M-INVALIDATION: revoked/stale advice cannot dispatch the same staged rollback."""
import time

import pytest

from src.application.governed_rollback_use_case import DispatchResult, GovernedRollbackUseCase
from src.domain.governed_rollback import GovernanceTokenError, RollbackState
from src.domain.recommendation_invalidator import DynamicRecommendationEngine, EvidenceContract
from tests.integration.test_rollback_authorization import (
    CONFIRM,
    STAGE,
    deployment_markers,
    stage_payload,
)

_deployment_markers_fixture = deployment_markers
pytestmark = pytest.mark.usefixtures("_deployment_markers_fixture")

LIVENESS = "/mcp/tools/recommendation_liveness"


def test_recovery_withdrawal_blocks_the_exact_token(client, auth_headers):
    action_id = "invalidate-recovered"
    staged = client.post(STAGE, headers=auth_headers, json=stage_payload(action_id)).json()
    withdrawn = client.post(LIVENESS, headers=auth_headers, params={
        "action_id": action_id, "current_metric_value": 0,
    })
    assert withdrawn.status_code == 200
    assert withdrawn.json()["status"] == "WITHDRAWN"
    assert withdrawn.json()["source"] == "OPERATOR_SUPPLIED_METRIC_NO_LIVE_REFRESH"
    refused = client.post(CONFIRM, headers=auth_headers, json={
        "action_id": action_id, "governance_token": staged["governance_token"],
    })
    assert refused.status_code == 409
    assert refused.json()["detail"]["denial_reason"] == "RECOMMENDATION_WITHDRAWN"


def test_withdrawn_recommendation_does_not_reactivate_with_an_unsafe_reading(client, auth_headers):
    action_id = "invalidate-terminal"
    staged = client.post(STAGE, headers=auth_headers, json=stage_payload(action_id)).json()
    for value in (0, 999):
        result = client.post(LIVENESS, headers=auth_headers, params={
            "action_id": action_id, "current_metric_value": value,
        })
        assert result.json()["status"] == "WITHDRAWN"
    refused = client.post(CONFIRM, headers=auth_headers, json={
        "action_id": action_id, "governance_token": staged["governance_token"],
    })
    assert refused.status_code == 409


def test_anonymous_caller_cannot_withdraw_a_valid_action(client, auth_headers):
    action_id = "invalidate-auth"
    staged = client.post(STAGE, headers=auth_headers, json=stage_payload(action_id)).json()
    assert client.post(LIVENESS, params={
        "action_id": action_id, "current_metric_value": 0,
    }).status_code == 401
    done = client.post(CONFIRM, headers=auth_headers, json={
        "action_id": action_id, "governance_token": staged["governance_token"],
    })
    assert done.status_code == 200
    assert "Recorded locally. No deployment pipeline was contacted" in done.json()["output"]


@pytest.mark.parametrize("value", ["nan", "inf", "-inf"])
def test_nonfinite_readings_are_refused_without_withdrawing(client, auth_headers, value):
    action_id = "invalidate-finite-" + value
    staged = client.post(STAGE, headers=auth_headers, json=stage_payload(action_id)).json()
    assert client.post(LIVENESS, headers=auth_headers, params={
        "action_id": action_id, "current_metric_value": value,
    }).status_code == 422
    assert client.post(CONFIRM, headers=auth_headers, json={
        "action_id": action_id, "governance_token": staged["governance_token"],
    }).status_code == 200


class CountingDispatcher:
    def __init__(self):
        self.calls = []

    def dispatch(self, action):
        self.calls.append(action.action_id)
        return DispatchResult(RollbackState.RECORDED_ONLY, "test-only dispatch recorded")


@pytest.mark.parametrize("condition,reason", [
    ("recovered", "RECOMMENDATION_WITHDRAWN"),
    ("stale", "RECOMMENDATION_STALE"),
    ("missing", "RECOMMENDATION_UNAVAILABLE"),
])
def test_application_boundary_refuses_before_any_dispatch(condition, reason):
    dispatcher = CountingDispatcher()
    use_case = GovernedRollbackUseCase("test-secret", dispatcher)
    action, token = use_case.stage_rollback("direct", "checkout-api", "abc123", "test")
    if condition == "recovered":
        use_case.recommendation_liveness("direct", 0)
    elif condition == "stale":
        # Recommendation evidence can predate the action lease. The confirm
        # boundary must inspect both, even while this action is still pending.
        use_case._recommendations._recommendations["direct"]["created_at"] = time.time() - 301
        assert not action.is_expired()
    else:
        use_case._recommendations._recommendations.clear()
    with pytest.raises(GovernanceTokenError) as caught:
        use_case.confirm_and_execute("direct", token)
    assert caught.value.reason.value == reason
    assert dispatcher.calls == []


def test_unused_token_from_withdrawn_staging_cannot_approve_restage():
    dispatcher = CountingDispatcher()
    use_case = GovernedRollbackUseCase("test-secret", dispatcher)
    _action, old = use_case.stage_rollback("same", "checkout-api", "abc123", "test")
    use_case.recommendation_liveness("same", 0)
    _fresh, _new = use_case.stage_rollback("same", "checkout-api", "abc123", "test")
    with pytest.raises(GovernanceTokenError) as caught:
        use_case.confirm_and_execute("same", old)
    assert caught.value.reason.value == "TOKEN_SUPERSEDED"
    assert dispatcher.calls == []


def test_fresh_restage_requires_its_new_grant_and_dispatches_once():
    dispatcher = CountingDispatcher()
    use_case = GovernedRollbackUseCase("test-secret", dispatcher)
    use_case.stage_rollback("same", "checkout-api", "abc123", "test")
    use_case.recommendation_liveness("same", 0)
    _fresh, new = use_case.stage_rollback("same", "checkout-api", "abc123", "test")
    assert use_case.recommendation_liveness("same", 9)["status"] == "ACTIVE"
    use_case.confirm_and_execute("same", new)
    with pytest.raises(GovernanceTokenError):
        use_case.confirm_and_execute("same", new)
    assert dispatcher.calls == ["same"]


def test_stale_recommendation_cannot_be_refreshed_by_a_later_reading(monkeypatch):
    now = [100.0]
    monkeypatch.setattr("src.domain.recommendation_invalidator.time.time", lambda: now[0])
    engine = DynamicRecommendationEngine()
    engine.register_recommendation("r", "rollback", EvidenceContract("errors", 5, "less_than", 30))
    now[0] = 130.0
    assert engine.evaluate_liveness("r", 100)["status"] == "STALE"
    now[0] = 131.0
    assert engine.evaluate_liveness("r", 0)["status"] == "STALE"


def test_other_action_is_not_withdrawn():
    dispatcher = CountingDispatcher()
    use_case = GovernedRollbackUseCase("test-secret", dispatcher)
    use_case.stage_rollback("first", "checkout-api", "abc123", "test")
    _second, token = use_case.stage_rollback("second", "checkout-api", "def456", "test")
    use_case.recommendation_liveness("first", 0)
    use_case.confirm_and_execute("second", token)
    assert dispatcher.calls == ["second"]


@pytest.mark.parametrize("comparison", ["less_than", "greater_than"])
def test_invalid_threshold_contract_cannot_create_active_recommendation(comparison):
    engine = DynamicRecommendationEngine()
    with pytest.raises(ValueError):
        engine.register_recommendation("r", "rollback", EvidenceContract("errors", float("nan"), comparison))
    assert engine.status("r")["status"] == "UNKNOWN_RECOMMENDATION"
