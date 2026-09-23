from datetime import datetime, timezone

import pytest

from src.application.governed_rollback_use_case import GovernedRollbackUseCase
from src.domain.deployment_evidence import DeploymentEvidenceLedger, DeploymentMarker
from src.domain.governed_rollback import GovernanceTokenError, RollbackDenialReason
from src.domain.incident_handoff import HandoffConflict, IncidentHandoffStore
from src.infrastructure.dynamodb_state import DynamoStateStore, StateConflict


class ConditionalFailure(Exception):
    response = {"Error": {"Code": "ConditionalCheckFailedException"}}


class FakeTable:
    def __init__(self):
        self.items = {}

    def put_item(self, Item, ConditionExpression=None, ExpressionAttributeNames=None,
                 ExpressionAttributeValues=None):
        key = (Item["pk"], Item["sk"])
        old = self.items.get(key)
        if ConditionExpression == "attribute_not_exists(pk)" and old is not None:
            raise ConditionalFailure()
        if ConditionExpression == "#revision = :expected":
            expected = ExpressionAttributeValues[":expected"]
            if old is None or old.get("revision") != expected:
                raise ConditionalFailure()
        self.items[key] = dict(Item)

    def get_item(self, Key, ConsistentRead=False):
        item = self.items.get((Key["pk"], Key["sk"]))
        return {"Item": dict(item)} if item else {}

    def query(self, KeyConditionExpression, ScanIndexForward=True):
        # boto3's condition object keeps the compared value in its second slot.
        wanted = KeyConditionExpression.get_expression()["values"][1]
        values = [dict(item) for (pk, _), item in self.items.items() if pk == wanted]
        return {"Items": sorted(values, key=lambda item: item["sk"])}


def store():
    return DynamoStateStore("test-table", table=FakeTable())


def marker(marker_id, revision, minute):
    digest = ("a" if minute == 1 else "b") * 64
    return DeploymentMarker.from_values(
        marker_id=marker_id, service="checkout-api", environment="production",
        revision=revision, artifact_sha256=digest,
        deployed_at=f"2026-09-01T00:0{minute}:00Z",
        health_checked_at=f"2026-09-01T00:0{minute}:30Z", health_status="HEALTHY",
        health_observed_revision=revision, health_observed_artifact_sha256=digest,
        source="authenticated-deployment-marker",
    )


def test_deployment_markers_survive_a_fresh_ledger():
    durable = store()
    first = DeploymentEvidenceLedger(storage=durable)
    first.record(marker("old", "abc", 1))
    first.record(marker("new", "def", 2))
    fresh = DeploymentEvidenceLedger(storage=durable)
    assert [item.marker_id for item in fresh.timeline("checkout-api", "production")] == ["new", "old"]
    assert fresh.rollback_pair("checkout-api", "production", "def")[1].revision == "abc"


def test_handoff_uses_durable_optimistic_revision():
    durable = store()
    first = IncidentHandoffStore(storage=durable)
    item = first.update(
        incident_id="inc", responder="Maya", current_action="Inspecting",
        confirmed_facts=["errors rose"], next_step="Compare deployments", expected_revision=0,
    )
    assert item.revision == 1
    fresh = IncidentHandoffStore(storage=durable)
    assert fresh.get("inc").responder == "Maya"
    with pytest.raises(HandoffConflict, match="revision"):
        fresh.update(
            incident_id="inc", responder="Niko", current_action="Taking over",
            confirmed_facts=["errors rose"], next_step="Rollback", expected_revision=0,
        )


def test_rollback_confirmation_survives_cold_start_and_nonce_is_global():
    durable = store()
    first = GovernedRollbackUseCase("secret", storage=durable)
    action, token = first.stage_rollback(
        "demo", "checkout-api", "abc", "fixture", 300, "production", "a" * 64, "old", "new"
    )
    fresh = GovernedRollbackUseCase("secret", storage=durable)
    restored, output = fresh.confirm_and_execute(action.action_id, token)
    assert restored.state.value == "RECORDED_ONLY"
    assert "No deployment pipeline was contacted" in output
    replay = GovernedRollbackUseCase("secret", storage=durable)
    with pytest.raises(GovernanceTokenError) as caught:
        replay.confirm_and_execute(action.action_id, token)
    assert caught.value.reason in {
        RollbackDenialReason.NOT_PENDING, RollbackDenialReason.TOKEN_ALREADY_USED,
    }


def test_rejected_token_state_survives_cold_start():
    durable = store()
    first = GovernedRollbackUseCase("secret", storage=durable)
    action, _ = first.stage_rollback(
        "reject-me", "checkout-api", "abc", "fixture", 300,
        "production", "a" * 64, "old", "new",
    )
    with pytest.raises(GovernanceTokenError) as caught:
        first.confirm_and_execute(action.action_id, "not-a-token")
    assert caught.value.reason == RollbackDenialReason.MALFORMED_TOKEN

    restored = GovernedRollbackUseCase("secret", storage=durable).get(action.action_id)
    assert restored.state.value == "REJECTED"
    assert restored.denial_reason == RollbackDenialReason.MALFORMED_TOKEN


def test_dispatch_failure_cannot_be_replayed_after_cold_start():
    class FailedDispatcher:
        def dispatch(self, action):
            raise RuntimeError("accepted then connection dropped")

    durable = store()
    first = GovernedRollbackUseCase("secret", dispatcher=FailedDispatcher(), storage=durable)
    action, token = first.stage_rollback(
        "effect-boundary", "checkout-api", "abc", "fixture", 300,
        "production", "a" * 64, "old", "new",
    )
    with pytest.raises(RuntimeError, match="connection dropped"):
        first.confirm_and_execute(action.action_id, token)

    restored = GovernedRollbackUseCase("secret", storage=durable).get(action.action_id)
    assert restored.state.value == "CONFIRMED"
    with pytest.raises(GovernanceTokenError) as caught:
        GovernedRollbackUseCase("secret", storage=durable).confirm_and_execute(action.action_id, token)
    assert caught.value.reason == RollbackDenialReason.NOT_PENDING


def test_store_reports_conditional_conflicts():
    durable = store()
    payload = {
        "incident_id": "inc", "responder": "A", "current_action": "x",
        "confirmed_facts": ["y"], "next_step": "z", "revision": 1,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    durable.put_handoff(payload, expected_revision=0)
    with pytest.raises(StateConflict):
        durable.put_handoff(payload, expected_revision=0)
