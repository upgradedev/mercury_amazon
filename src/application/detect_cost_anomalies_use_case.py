"""Use Case: Detect Cloud Spend Anomalies."""
from typing import Protocol

from src.domain.cloud_cost import CloudCostReport


class CostDataProvider(Protocol):
    def fetch_cost_report(self) -> CloudCostReport:
        ...


class DetectCostAnomaliesUseCase:
    def __init__(self, provider: CostDataProvider):
        self._provider = provider

    def execute(self) -> CloudCostReport:
        return self._provider.fetch_cost_report()
