"""Domain entity for Governed CI Pipeline & Production Rollbacks.

A rollback is the one irreversible thing Mercury can do from a TV remote, so it
is guarded by three independent conditions, all enforced here:

Authorization
    The caller must present the deployment's shared secret. Staging and
    confirming are separate authorized calls.

Content binding
    Staging mints a governance token that is an HMAC over the action id, the
    SHA-256 hash of the rollback payload, and a random nonce. Changing the target
    service, the target commit or the reason changes the payload hash, which
    invalidates every token already minted for that action.

Single use
    Each token carries a nonce that is consumed on the first successful confirm.
    A replayed token is refused even when it is otherwise valid.

Plus the lease: a staged action expires after ``lease_sec`` seconds.

This module imports only the standard library so the domain stays free of SDKs.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass, field
from enum import Enum

TOKEN_VERSION = "v1"


class RollbackState(str, Enum):
    PENDING_CONFIRMATION = "PENDING_CONFIRMATION"
    CONFIRMED = "CONFIRMED"
    EXECUTED = "EXECUTED"
    EXPIRED = "EXPIRED"
    REJECTED = "REJECTED"


class RollbackDenialReason(str, Enum):
    """Why a confirm was refused. Returned to the caller so a refusal is legible."""

    UNKNOWN_ACTION = "UNKNOWN_ACTION"
    NOT_PENDING = "NOT_PENDING"
    LEASE_EXPIRED = "LEASE_EXPIRED"
    MALFORMED_TOKEN = "MALFORMED_TOKEN"
    TOKEN_ACTION_MISMATCH = "TOKEN_ACTION_MISMATCH"
    TOKEN_CONTENT_MISMATCH = "TOKEN_CONTENT_MISMATCH"
    BAD_SIGNATURE = "BAD_SIGNATURE"
    TOKEN_ALREADY_USED = "TOKEN_ALREADY_USED"


class GovernanceTokenError(ValueError):
    """Raised when a governance token cannot be parsed or verified."""

    def __init__(self, reason: RollbackDenialReason, message: str) -> None:
        super().__init__(message)
        self.reason = reason


def compute_payload_hash(action_id: str, target_service: str, target_commit_sha: str, reason: str) -> str:
    """SHA-256 over the fields that define what the rollback will actually do.

    Each field is length-prefixed before hashing, so no combination of field
    values can be rearranged into a different tuple with the same hash. A plain
    separator would let a value containing that separator forge a collision.
    """
    digest = hashlib.sha256()
    for field_value in (action_id, target_service, target_commit_sha, reason):
        encoded = field_value.encode("utf-8")
        digest.update(str(len(encoded)).encode("ascii"))
        digest.update(b":")
        digest.update(encoded)
    return digest.hexdigest()


def mint_governance_token(secret: str, action_id: str, payload_hash: str, nonce: str | None = None) -> str:
    """Mint a token bound to one action id and one payload hash.

    Format: ``v1.<action_id>.<payload_hash>.<nonce>.<hmac>``. The signature covers
    the first four fields, so neither the bound action nor the bound content can
    be swapped without invalidating it.
    """
    if not secret:
        raise GovernanceTokenError(
            RollbackDenialReason.BAD_SIGNATURE,
            "Cannot mint a governance token without a signing secret.",
        )
    nonce = nonce or secrets.token_hex(16)
    body = f"{TOKEN_VERSION}.{action_id}.{payload_hash}.{nonce}"
    signature = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{signature}"


def verify_governance_token(secret: str, token: str, action_id: str, payload_hash: str) -> str:
    """Verify a token against an action and its current payload hash.

    Returns the token's nonce so the caller can enforce single use. Raises
    :class:`GovernanceTokenError` carrying a specific denial reason otherwise.
    """
    if not secret:
        raise GovernanceTokenError(
            RollbackDenialReason.BAD_SIGNATURE,
            "No signing secret is configured, so no token can be verified.",
        )
    if not token or token.count(".") != 4:
        raise GovernanceTokenError(
            RollbackDenialReason.MALFORMED_TOKEN,
            "Governance token is not in the expected v1.action.hash.nonce.signature form.",
        )

    version, token_action_id, token_payload_hash, nonce, signature = token.split(".")
    if version != TOKEN_VERSION:
        raise GovernanceTokenError(
            RollbackDenialReason.MALFORMED_TOKEN,
            f"Unsupported governance token version '{version}'.",
        )

    body = f"{version}.{token_action_id}.{token_payload_hash}.{nonce}"
    expected = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise GovernanceTokenError(
            RollbackDenialReason.BAD_SIGNATURE,
            "Governance token signature does not verify against the configured secret.",
        )

    # Signature is valid, so the bound fields are trustworthy. Compare them last
    # to give the caller a precise reason rather than a generic rejection.
    if not hmac.compare_digest(token_action_id, action_id):
        raise GovernanceTokenError(
            RollbackDenialReason.TOKEN_ACTION_MISMATCH,
            f"Token was minted for action '{token_action_id}', not '{action_id}'.",
        )
    if not hmac.compare_digest(token_payload_hash, payload_hash):
        raise GovernanceTokenError(
            RollbackDenialReason.TOKEN_CONTENT_MISMATCH,
            "Rollback content changed after this token was minted, so the token no longer applies.",
        )
    return nonce


@dataclass
class GovernedRollbackAction:
    action_id: str
    target_service: str
    target_commit_sha: str
    reason: str
    state: RollbackState = RollbackState.PENDING_CONFIRMATION
    created_at_epoch: float = field(default_factory=time.time)
    lease_sec: float = 300.0
    payload_hash: str = ""
    confirmed_with_nonce: str | None = None
    execution_output: str | None = None
    denial_reason: RollbackDenialReason | None = None

    @classmethod
    def create(
        cls,
        action_id: str,
        target_service: str,
        target_commit_sha: str,
        reason: str,
        lease_sec: float = 300.0,
    ) -> "GovernedRollbackAction":
        return cls(
            action_id=action_id,
            target_service=target_service,
            target_commit_sha=target_commit_sha,
            reason=reason,
            lease_sec=lease_sec,
            payload_hash=compute_payload_hash(action_id, target_service, target_commit_sha, reason),
            created_at_epoch=time.time(),
        )

    def current_payload_hash(self) -> str:
        """Recompute the hash from the live fields, so tampering is detectable."""
        return compute_payload_hash(self.action_id, self.target_service, self.target_commit_sha, self.reason)

    def is_expired(self, current_time: float | None = None) -> bool:
        now = current_time if current_time is not None else time.time()
        return (now - self.created_at_epoch) > self.lease_sec

    def seconds_remaining(self, current_time: float | None = None) -> float:
        now = current_time if current_time is not None else time.time()
        return max(0.0, self.lease_sec - (now - self.created_at_epoch))

    def confirm(
        self,
        secret: str,
        governance_token: str,
        spent_nonces: set[str],
        current_time: float | None = None,
    ) -> str:
        """Confirm this action, returning the nonce that was consumed.

        Raises :class:`GovernanceTokenError` when any of the four conditions
        (state, lease, token validity, single use) is not met.
        """
        if self.state != RollbackState.PENDING_CONFIRMATION:
            raise GovernanceTokenError(
                RollbackDenialReason.NOT_PENDING,
                f"Action '{self.action_id}' is in state {self.state.value}, not PENDING_CONFIRMATION.",
            )
        if self.is_expired(current_time):
            self.state = RollbackState.EXPIRED
            self.denial_reason = RollbackDenialReason.LEASE_EXPIRED
            raise GovernanceTokenError(
                RollbackDenialReason.LEASE_EXPIRED,
                f"The {self.lease_sec:.0f} second confirmation lease on '{self.action_id}' has expired.",
            )

        try:
            nonce = verify_governance_token(
                secret, governance_token, self.action_id, self.current_payload_hash()
            )
        except GovernanceTokenError as exc:
            self.state = RollbackState.REJECTED
            self.denial_reason = exc.reason
            raise

        if nonce in spent_nonces:
            self.state = RollbackState.REJECTED
            self.denial_reason = RollbackDenialReason.TOKEN_ALREADY_USED
            raise GovernanceTokenError(
                RollbackDenialReason.TOKEN_ALREADY_USED,
                "This governance token has already been used. Stage the rollback again for a new token.",
            )

        self.state = RollbackState.CONFIRMED
        self.confirmed_with_nonce = nonce
        return nonce
