"""Unit tests for Mercury DORA velocity calculations."""
from src.application.calculate_dora_use_case import CalculateDORAUseCase
from src.domain.dora_metrics import DORAMetricsReport, PerformanceTier


class MockEliteTelemetry:
    def get_metrics_raw(self) -> DORAMetricsReport:
        return DORAMetricsReport(
            deployment_frequency_per_day=3.5,
            lead_time_for_changes_hours=8.0,
            change_failure_rate_percentage=2.0,
            mean_time_to_recovery_hours=0.5
        )


class MockMediumTelemetry:
    def get_metrics_raw(self) -> DORAMetricsReport:
        return DORAMetricsReport(
            deployment_frequency_per_day=0.1,
            lead_time_for_changes_hours=96.0,
            change_failure_rate_percentage=22.0,
            mean_time_to_recovery_hours=8.0
        )


def test_dora_elite_tier():
    use_case = CalculateDORAUseCase(MockEliteTelemetry())
    report = use_case.execute()
    assert report.overall_tier == PerformanceTier.ELITE
    assert "velocity tier is ELITE" in report.to_voice_summary()


def test_dora_medium_tier():
    use_case = CalculateDORAUseCase(MockMediumTelemetry())
    report = use_case.execute()
    assert report.overall_tier == PerformanceTier.MEDIUM
    assert "velocity tier is MEDIUM" in report.to_voice_summary()
