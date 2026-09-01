"""Infrastructure Adapter: AWS Cost Explorer & CloudWatch Telemetry."""
from src.domain.cloud_cost import CloudCostReport, CostAnomaly


class AWSCostAdapter:
    def fetch_cost_report(self) -> CloudCostReport:
        return CloudCostReport(
            total_month_to_date_usd=4850.20,
            projected_end_of_month_usd=6200.00,
            anomalies=[
                CostAnomaly(
                    service_name="Amazon Bedrock & ECS Staging",
                    previous_daily_avg_usd=45.00,
                    current_daily_usd=185.00,
                    percentage_increase=311.0,
                    root_cause_explanation="Unclosed load test tasks in staging cluster"
                )
            ]
        )
