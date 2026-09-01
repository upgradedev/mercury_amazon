"""Domain model for AWS Cloud Cost Radar & Anomaly Alerts."""
from dataclasses import dataclass


@dataclass(frozen=True)
class CostAnomaly:
    service_name: str
    previous_daily_avg_usd: float
    current_daily_usd: float
    percentage_increase: float
    root_cause_explanation: str


@dataclass(frozen=True)
class CloudCostReport:
    total_month_to_date_usd: float
    projected_end_of_month_usd: float
    anomalies: list[CostAnomaly]

    def to_voice_summary(self) -> str:
        base = f"Total cloud spend month-to-date is ${self.total_month_to_date_usd:,.2f}, projected to reach ${self.projected_end_of_month_usd:,.2f}."
        if self.anomalies:
            top = self.anomalies[0]
            base += f" Alert: {top.service_name} spend surged by {top.percentage_increase:.0f}%. Root cause: {top.root_cause_explanation}."
        return base
