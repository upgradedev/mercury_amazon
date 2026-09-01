"""Use Case: Inspect Pull Request Review Bottlenecks."""
from typing import Protocol
from src.domain.git_radar import PRRadarReport


class PRRadarDataProvider(Protocol):
    def get_pr_radar(self) -> PRRadarReport:
        ...


class InspectPRBottlenecksUseCase:
    def __init__(self, provider: PRRadarDataProvider):
        self._provider = provider

    def execute(self) -> PRRadarReport:
        return self._provider.get_pr_radar()
