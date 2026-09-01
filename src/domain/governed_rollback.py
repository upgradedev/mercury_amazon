"""Domain entity for Governed CI Pipeline & Production Rollbacks."""
import hashlib
import time
from dataclasses import dataclass, field
from enum import Enum


class RollbackState(str, Enum):
    PENDING_CONFIRMATION = "PENDING_CONFIRMATION"
    CONFIRMED = "CONFIRMED"
    EXECUTED = "EXECUTED"
    EXPIRED = "EXPIRED"
    REJECTED = "REJECTED"


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
    voice_token: str | None = None
    execution_output: str | None = None

    @classmethod
    def create(
        cls,
        action_id: str,
        target_service: str,
        target_commit_sha: str,
        reason: str,
        lease_sec: float = 300.0,
    ) -> "GovernedRollbackAction":
        payload = f"{action_id}:{target_service}:{target_commit_sha}:{reason}".encode()
        h = hashlib.sha256(payload).hexdigest()
        return cls(
            action_id=action_id,
            target_service=target_service,
            target_commit_sha=target_commit_sha,
            reason=reason,
            lease_sec=lease_sec,
            payload_hash=h,
            created_at_epoch=time.time(),
        )

    def is_expired(self, current_time: float | None = None) -> bool:
        now = current_time or time.time()
        return (now - self.created_at_epoch) > self.lease_sec

    def confirm(self, voice_token: str, current_time: float | None = None) -> bool:
        if self.is_expired(current_time):
            self.state = RollbackState.EXPIRED
            return False
        if self.state != RollbackState.PENDING_CONFIRMATION:
            return False
        if not voice_token or not voice_token.strip():
            return False
        self.state = RollbackState.CONFIRMED
        self.voice_token = voice_token
        return True
