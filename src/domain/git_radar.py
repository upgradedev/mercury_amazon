"""Domain model for PR Review Radar and Bottleneck Detection."""
from dataclasses import dataclass


@dataclass(frozen=True)
class PullRequestDigest:
    pr_id: int
    repository: str
    title: str
    author: str
    hours_open: float
    is_blocked: bool


@dataclass(frozen=True)
class PRRadarReport:
    total_open_prs: int
    stale_prs_over_36h: list[PullRequestDigest]

    def to_voice_summary(self) -> str:
        count = len(self.stale_prs_over_36h)
        if count == 0:
            return f"All {self.total_open_prs} pull requests are moving smoothly within review SLA."
        return f"Found {count} pull requests stuck in code review for over 36 hours."
