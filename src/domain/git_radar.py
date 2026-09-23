"""Domain model for PR Review Radar and Bottleneck Detection."""
from dataclasses import dataclass, field

from src.domain.provenance import UNKNOWN_PROVENANCE, Provenance

STALE_REVIEW_SLA_HOURS = 36.0


@dataclass(frozen=True)
class PullRequestDigest:
    pr_id: int
    repository: str
    title: str
    author: str
    hours_open: float
    is_blocked: bool

    @property
    def is_stale(self) -> bool:
        return self.hours_open > STALE_REVIEW_SLA_HOURS


@dataclass(frozen=True)
class PRRadarReport:
    total_open_prs: int
    stale_prs_over_36h: list[PullRequestDigest]
    provenance: Provenance = field(default=UNKNOWN_PROVENANCE)

    def to_voice_summary(self) -> str:
        count = len(self.stale_prs_over_36h)
        if count == 0:
            return f"All {self.total_open_prs} pull requests are moving smoothly within review SLA."
        return f"Found {count} pull requests stuck in code review for over 36 hours."
