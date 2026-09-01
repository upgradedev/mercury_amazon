"""Unit tests for Mercury AWS Cost Radar."""
from src.application.detect_cost_anomalies_use_case import DetectCostAnomaliesUseCase
from src.domain.cloud_cost import CloudCostReport, CostAnomaly


class MockCostProvider:
    def fetch_cost_report(self) -> CloudCostReport:
        return CloudCostReport(
            total_month_to_date_usd=1250.00,
            projected_end_of_month_usd=1800.00,
            anomalies=[
                CostAnomaly(
                    service_name="Amazon Bedrock",
                    previous_daily_avg_usd=10.0,
                    current_daily_usd=80.0,
                    percentage_increase=700.0,
                    root_cause_explanation="Autonomous agent loop load testing"
                )
            ]
        )


def test_cost_anomaly_reporting():
    use_case = DetectCostAnomaliesUseCase(MockCostProvider())
    report = use_case.execute()
    assert report.total_month_to_date_usd == 1250.00
    assert len(report.anomalies) == 1
    assert "surged by 700%" in report.to_voice_summary()
