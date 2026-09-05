"""Unit tests for governed rollback: the happy path and every way it refuses.

The refusals matter more than the success. A control that cannot say no is not a
control, so each denial reason has a test that proves it fires.
"""
import time

import pytest

from src.application.governed_rollback_use_case import (
    GovernedRollbackUseCase,
    RecordOnlyDispatcher,
)
from src.domain.governed_rollback import (
    GovernanceTokenError,
    RollbackDenialReason,
    RollbackState,
    compute_payload_hash,
    mint_governance_token,
    verify_governance_token,
)

SECRET = "unit-test-secret"


def _staged(use_case: GovernedRollbackUseCase, action_id: str = "rb-101", **overrides):
    payload = {
        "action_id": action_id,
        "target_service": "auth-service",
        "target_commit_sha": "c9d8e7f6a",
        "reason": "Elevated error rates on OAuth callbacks",
    }
    payload.update(overrides)
    return use_case.stage_rollback(**payload)


def test_rollback_lifecycle_and_execution():
    use_case = GovernedRollbackUseCase(SECRET)
    action, token = _staged(use_case)

    assert action.state == RollbackState.PENDING_CONFIRMATION
    assert len(action.payload_hash) == 64

    confirmed, output = use_case.confirm_and_execute("rb-101", token)
    assert confirmed.state == RollbackState.EXECUTED
    assert "auth-service" in output
    assert "No deployment pipeline was contacted" in output


def test_use_case_refuses_to_construct_without_a_secret():
    with pytest.raises(ValueError, match="non-empty signing secret"):
        GovernedRollbackUseCase("")


def test_expired_lease_is_refused():
    use_case = GovernedRollbackUseCase(SECRET)
    action, token = _staged(use_case, action_id="rb-expired", lease_sec=0.01)
    action.created_at_epoch = time.time() - 10.0

    with pytest.raises(GovernanceTokenError) as exc:
        use_case.confirm_and_execute("rb-expired", token)

    assert exc.value.reason is RollbackDenialReason.LEASE_EXPIRED
    assert action.state == RollbackState.EXPIRED


def test_unknown_action_is_refused():
    use_case = GovernedRollbackUseCase(SECRET)
    with pytest.raises(GovernanceTokenError) as exc:
        use_case.confirm_and_execute("never-staged", "v1.a.b.c.d")
    assert exc.value.reason is RollbackDenialReason.UNKNOWN_ACTION


def test_token_is_single_use():
    use_case = GovernedRollbackUseCase(SECRET)
    _, token = _staged(use_case, action_id="rb-replay")
    use_case.confirm_and_execute("rb-replay", token)

    # Re-stage the same id so the action is pending again, then replay the token.
    action, _fresh_token = _staged(use_case, action_id="rb-replay")
    with pytest.raises(GovernanceTokenError) as exc:
        use_case.confirm_and_execute("rb-replay", token)

    assert exc.value.reason is RollbackDenialReason.TOKEN_ALREADY_USED
    assert action.state == RollbackState.REJECTED


def test_token_minted_for_another_action_is_refused():
    use_case = GovernedRollbackUseCase(SECRET)
    _, token_a = _staged(use_case, action_id="rb-a")
    _staged(use_case, action_id="rb-b")

    with pytest.raises(GovernanceTokenError) as exc:
        use_case.confirm_and_execute("rb-b", token_a)
    assert exc.value.reason is RollbackDenialReason.TOKEN_ACTION_MISMATCH


def test_token_stops_applying_when_the_rollback_content_changes():
    """The core of content binding: mutate the target, the token dies."""
    use_case = GovernedRollbackUseCase(SECRET)
    action, token = _staged(use_case, action_id="rb-tamper")

    action.target_commit_sha = "deadbeef"  # someone edits what will be deployed

    with pytest.raises(GovernanceTokenError) as exc:
        use_case.confirm_and_execute("rb-tamper", token)
    assert exc.value.reason is RollbackDenialReason.TOKEN_CONTENT_MISMATCH
    assert action.state == RollbackState.REJECTED


def test_token_signed_with_a_different_secret_is_refused():
    use_case = GovernedRollbackUseCase(SECRET)
    action, _ = _staged(use_case, action_id="rb-forged")
    forged = mint_governance_token("attacker-secret", "rb-forged", action.payload_hash)

    with pytest.raises(GovernanceTokenError) as exc:
        use_case.confirm_and_execute("rb-forged", forged)
    assert exc.value.reason is RollbackDenialReason.BAD_SIGNATURE


@pytest.mark.parametrize(
    "bad_token",
    ["", "not-a-token", "v1.a.b.c", "v9.a.b.c.d", "v1.a.b.c.d.e"],
)
def test_malformed_tokens_are_refused(bad_token):
    use_case = GovernedRollbackUseCase(SECRET)
    _staged(use_case, action_id="rb-malformed")
    with pytest.raises(GovernanceTokenError) as exc:
        use_case.confirm_and_execute("rb-malformed", bad_token)
    assert exc.value.reason in (
        RollbackDenialReason.MALFORMED_TOKEN,
        RollbackDenialReason.BAD_SIGNATURE,
    )


def test_confirming_an_already_executed_action_is_refused():
    use_case = GovernedRollbackUseCase(SECRET)
    _, token = _staged(use_case, action_id="rb-twice")
    use_case.confirm_and_execute("rb-twice", token)

    with pytest.raises(GovernanceTokenError) as exc:
        use_case.confirm_and_execute("rb-twice", token)
    assert exc.value.reason is RollbackDenialReason.NOT_PENDING


def test_payload_hash_changes_with_every_field():
    base = compute_payload_hash("a", "svc", "sha", "why")
    assert base != compute_payload_hash("b", "svc", "sha", "why")
    assert base != compute_payload_hash("a", "other", "sha", "why")
    assert base != compute_payload_hash("a", "svc", "other", "why")
    assert base != compute_payload_hash("a", "svc", "sha", "other")
    assert base == compute_payload_hash("a", "svc", "sha", "why")


@pytest.mark.parametrize("separator", [":", "\x1f", "|", "\n"])
def test_payload_hash_is_not_confusable_across_field_boundaries(separator):
    """A value containing the joining character must not forge another tuple's hash."""
    shifted_left = compute_payload_hash(f"a{separator}b", "c", "d", "e")
    shifted_right = compute_payload_hash("a", f"b{separator}c", "d", "e")
    assert shifted_left != shifted_right


def test_verify_returns_the_nonce_it_was_minted_with():
    payload_hash = compute_payload_hash("x", "svc", "sha", "why")
    token = mint_governance_token(SECRET, "x", payload_hash, nonce="fixed-nonce")
    assert verify_governance_token(SECRET, token, "x", payload_hash) == "fixed-nonce"


def test_minting_without_a_secret_is_refused():
    with pytest.raises(GovernanceTokenError):
        mint_governance_token("", "x", "hash")


def test_seconds_remaining_decays_to_zero():
    use_case = GovernedRollbackUseCase(SECRET)
    action, _ = _staged(use_case, action_id="rb-lease", lease_sec=60.0)
    assert action.seconds_remaining(current_time=action.created_at_epoch) == pytest.approx(60.0)
    assert action.seconds_remaining(current_time=action.created_at_epoch + 90) == 0.0


def test_record_only_dispatcher_states_that_nothing_was_deployed():
    dispatcher = RecordOnlyDispatcher()
    use_case = GovernedRollbackUseCase(SECRET, dispatcher=dispatcher)
    action, token = _staged(use_case, action_id="rb-dispatch")
    _, output = use_case.confirm_and_execute("rb-dispatch", token)
    assert "No deployment pipeline was contacted" in output
    assert action.target_service in output
