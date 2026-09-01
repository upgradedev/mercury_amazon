"""Infrastructure Adapter: GitHub / GitLab API Client."""
from src.domain.dora_metrics import DORAMetricsReport
from src.domain.git_radar import PRRadarReport, PullRequestDigest


class GitHubTelemetryAdapter:
    def get_metrics_raw(self) -> DORAMetricsReport:
        return DORAMetricsReport(
            deployment_frequency_per_day=2.4,
            lead_time_for_changes_hours=14.5,
            change_failure_rate_percentage=3.2,
            mean_time_to_recovery_hours=0.8
        )

    def get_pr_radar(self) -> PRRadarReport:
        return PRRadarReport(
            total_open_prs=18,
            stale_prs_over_36h=[
                PullRequestDigest(
                    pr_id=342,
                    repository="backend-payments",
                    title="Implement Stripe Webhook Retry Logic",
                    author="dev_alex",
                    hours_open=48.0,
                    is_blocked=True
                )
            ]
        )
