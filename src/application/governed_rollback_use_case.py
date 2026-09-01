"""Use Case: Stage and Execute Governed Production Rollbacks."""
import time

from src.domain.governed_rollback import GovernedRollbackAction, RollbackState


class GovernedRollbackUseCase:
    def __init__(self):
        self._actions: dict[str, GovernedRollbackAction] = {}

    def stage_rollback(
        self, action_id: str, target_service: str, target_commit_sha: str, reason: str, lease_sec: float = 300.0
    ) -> GovernedRollbackAction:
        action = GovernedRollbackAction.create(action_id, target_service, target_commit_sha, reason, lease_sec)
        self._actions[action_id] = action
        return action

    def confirm_and_execute(self, action_id: str, voice_token: str) -> str | None:
        action = self._actions.get(action_id)
        if not action or action.state != RollbackState.PENDING_CONFIRMATION:
            return None

        confirmed = action.confirm(voice_token, current_time=time.time())
        if not confirmed:
            return None

        action.state = RollbackState.EXECUTED
        output = f"Successfully rolled back service '{action.target_service}' to commit {action.target_commit_sha[:8]}."
        action.execution_output = output
        return output
