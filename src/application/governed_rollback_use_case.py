"""Use Case: Stage and Execute Governed Production Rollbacks.

Holds the staged actions and the set of spent governance nonces. The domain
decides whether a confirmation is legitimate; this layer holds the state that
decision needs and performs the dispatch once it passes.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Protocol

from src.domain.governed_rollback import (
    GovernanceTokenError,
    GovernedRollbackAction,
    RollbackState,
    mint_governance_token,
)
from src.domain.recommendation_invalidator import DynamicRecommendationEngine, EvidenceContract


@dataclass(frozen=True)
class DispatchResult:
    """The strongest result the dispatcher actually proved."""

    state: RollbackState
    output: str


class RollbackDispatcher(Protocol):
    """Whatever actually performs the rollback once governance has passed."""

    def dispatch(self, action: GovernedRollbackAction) -> DispatchResult:
        ...


class RecordOnlyDispatcher:
    """Default dispatcher. Records the decision and performs no cloud call.

    This is what a deployment reaches unless it has selected another dispatcher,
    and it says plainly in its own output that no deployment system was
    contacted. A real one exists in
    ``src/infrastructure/github_actions_dispatcher.py``; it is selected by
    ``MERCURY_ROLLBACK_DISPATCH`` and is not reachable by accident.
    """

    def dispatch(self, action: GovernedRollbackAction) -> DispatchResult:
        return DispatchResult(
            state=RollbackState.RECORDED_ONLY,
            output=(
                f"Governance passed for '{action.target_service}' to commit {action.target_commit_sha[:8]}. "
                "Recorded locally. No deployment pipeline was contacted: this deployment is running the "
                "record-only dispatcher. Set MERCURY_ROLLBACK_DISPATCH=github_actions to reach one that "
                "does, and MERCURY_ROLLBACK_DISPATCH_ARMED=1 for it to send anything."
            ),
        )


class GovernedRollbackUseCase:
    """Stages rollbacks, mints governance tokens, and confirms exactly once."""

    def __init__(self, secret: str, dispatcher: RollbackDispatcher | None = None) -> None:
        if not secret:
            raise ValueError("GovernedRollbackUseCase requires a non-empty signing secret.")
        self._secret = secret
        self._actions: dict[str, GovernedRollbackAction] = {}
        self._spent_nonces: set[str] = set()
        self._dispatcher = dispatcher or RecordOnlyDispatcher()
        self._recommendations = DynamicRecommendationEngine()
        self._issued_tokens: dict[str, str] = {}

    def stage_rollback(
        self,
        action_id: str,
        target_service: str,
        target_commit_sha: str,
        reason: str,
        lease_sec: float = 300.0,
        environment: str = "",
        target_artifact_sha256: str = "",
        target_deployment_marker_id: str = "",
        offending_deployment_marker_id: str = "",
    ) -> tuple[GovernedRollbackAction, str]:
        """Stage an action and mint the single-use token that can confirm it."""
        action = GovernedRollbackAction.create(
            action_id,
            target_service,
            target_commit_sha,
            reason,
            lease_sec,
            environment,
            target_artifact_sha256,
            target_deployment_marker_id,
            offending_deployment_marker_id,
        )
        self._actions[action_id] = action
        token = mint_governance_token(self._secret, action_id, action.payload_hash)
        self._issued_tokens[action_id] = token
        self._recommendations.register_recommendation(
            rec_id=action.action_id,
            action=f"Roll back {action.target_service} to {action.target_commit_sha}",
            evidence=EvidenceContract(
                metric_name="HTTPCode_Target_5XX_Count", safe_threshold=5.0,
                comparison="less_than", ttl_seconds=action.lease_sec,
            ),
        )
        return action, token

    def get(self, action_id: str) -> GovernedRollbackAction | None:
        return self._actions.get(action_id)

    def recommendation_liveness(self, action_id: str, metric_value: float) -> dict:
        return self._recommendations.evaluate_liveness(action_id, metric_value)

    def confirm_and_execute(self, action_id: str, governance_token: str) -> tuple[GovernedRollbackAction, str]:
        """Confirm and dispatch, or raise :class:`GovernanceTokenError`."""
        from src.domain.governed_rollback import RollbackDenialReason

        action = self._actions.get(action_id)
        if action is None:
            raise GovernanceTokenError(
                RollbackDenialReason.UNKNOWN_ACTION,
                f"No staged rollback with id '{action_id}'.",
            )

        nonce = action.confirm(self._secret, governance_token, self._spent_nonces, current_time=time.time())
        # A fresh staging of the same payload must not revive an unused old grant.
        if governance_token != self._issued_tokens.get(action_id):
            action.state = RollbackState.REJECTED
            action.denial_reason = RollbackDenialReason.TOKEN_SUPERSEDED
            raise GovernanceTokenError(
                action.denial_reason, "This token belongs to an earlier staging; review the fresh proposal."
            )
        recommendation = self._recommendations.status(action_id)
        if recommendation["status"] != "ACTIVE":
            action.state = RollbackState.REJECTED
            action.denial_reason = {
                "WITHDRAWN": RollbackDenialReason.RECOMMENDATION_WITHDRAWN,
                "STALE": RollbackDenialReason.RECOMMENDATION_STALE,
            }.get(recommendation["status"], RollbackDenialReason.RECOMMENDATION_UNAVAILABLE)
            raise GovernanceTokenError(
                action.denial_reason,
                f"Recommendation is {recommendation['status']}; nothing dispatched. Stage and review again.",
            )
        self._spent_nonces.add(nonce)

        result = self._dispatcher.dispatch(action)
        action.state = result.state
        action.execution_output = result.output
        return action, result.output
