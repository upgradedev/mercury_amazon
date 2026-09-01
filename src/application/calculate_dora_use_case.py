"""Use Case: Calculate DORA Velocity Metrics."""
from typing import Protocol
from src.domain.dora_metrics import DORAMetricsReport


class TelemetryDataProvider(Protocol):
    def get_metrics_raw(self) -> DORAMetricsReport:
        ...


class CalculateDORAUseCase:
    def __init__(self, provider: TelemetryDataProvider):
        self._provider = provider

    def execute(self) -> DORAMetricsReport:
        return self._provider.get_metrics_raw()
