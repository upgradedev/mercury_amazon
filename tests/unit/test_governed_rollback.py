"""Unit tests for Governed Rollback domain model and use case."""
import time
from src.application.governed_rollback_use_case import GovernedRollbackUseCase
from src.domain.governed_rollback import GovernedRollbackAction, RollbackState


def test_rollback_lifecycle_and_execution():
    use_case = GovernedRollbackUseCase()
    action = use_case.stage_rollback(
        action_id="rb-101",
        target_service="auth-service",
        target_commit_sha="c9d8e7f6a",
        reason="Elevated error rates on OAuth callbacks"
    )
    assert action.state == RollbackState.PENDING_CONFIRMATION
    assert len(action.payload_hash) == 64

    # Confirm
    output = use_case.confirm_and_execute("rb-101", "CTO_VOICE_SIG_441")
    assert output is not None
    assert "Successfully rolled back service 'auth-service'" in output
    assert action.state == RollbackState.EXECUTED


def test_expired_rollback_cannot_be_confirmed():
    use_case = GovernedRollbackUseCase()
    action = use_case.stage_rollback(
        action_id="rb-expired",
        target_service="payments",
        target_commit_sha="11223344",
        reason="Testing timeout",
        lease_sec=0.01
    )
    action.created_at_epoch = time.time() - 10.0
    res = use_case.confirm_and_execute("rb-expired", "TOKEN")
    assert res is None
    assert action.state == RollbackState.EXPIRED
