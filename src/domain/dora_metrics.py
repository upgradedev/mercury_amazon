"""Domain model for DORA Engineering Velocity Metrics."""
from dataclasses import dataclass
from enum import Enum


class PerformanceTier(str, Enum):
    ELITE = "ELITE"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


@dataclass(frozen=True)
class DORAMetricsReport:
    deployment_frequency_per_day: float
    lead_time_for_changes_hours: float
    change_failure_rate_percentage: float
    mean_time_to_recovery_hours: float

    @property
    def overall_tier(self) -> PerformanceTier:
        if (
            self.deployment_frequency_per_day >= 1.0
            and self.lead_time_for_changes_hours <= 24.0
            and self.change_failure_rate_percentage <= 5.0
        ):
            return PerformanceTier.ELITE
        if (
            self.deployment_frequency_per_day >= 0.2
            and self.lead_time_for_changes_hours <= 72.0
            and self.change_failure_rate_percentage <= 15.0
        ):
            return PerformanceTier.HIGH
        return PerformanceTier.MEDIUM

    def to_voice_summary(self) -> str:
        tier = self.overall_tier.value
        return (
            f"Engineering velocity tier is {tier}. Deployment frequency is {self.deployment_frequency_per_day:.1f} per day, "
            f"with an average lead time of {self.lead_time_for_changes_hours:.1f} hours and "
            f"change failure rate at {self.change_failure_rate_percentage:.1f}%."
        )
