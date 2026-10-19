"""Infrastructure Adapter: AWS Cost Explorer spend telemetry.

Calls ``ce:GetCostAndUsage`` through boto3 when AWS credentials are resolvable,
and serves a recorded offline fixture otherwise. The report carries a
:class:`~src.domain.provenance.Provenance` stamp saying which happened, and the
cockpit renders that stamp on screen.

Known limitation, stated because it changes what the numbers mean: AWS Cost
Explorer aggregates at daily granularity with a reporting lag of up to 24 hours.
A spend spike in the last hour will not appear here. Sub-hour spend alerting
needs CloudWatch metric alarms, which Mercury does not implement.
"""
from __future__ import annotations

import calendar
import json
import logging
import os
import time
from datetime import date, datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

from src.domain.cloud_cost import CloudCostReport, CostAnomaly
from src.domain.provenance import DataSource, Provenance
from src.infrastructure.offline_mode import OFFLINE_REASON, offline_mode_enabled
from src.infrastructure.safe_errors import describe_exception

FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "aws_cost_fixture.json"
ANOMALY_THRESHOLD_PCT = 50.0
CACHE_TTL_SECONDS = 900.0

logger = logging.getLogger(__name__)


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class AWSCostAdapter:
    """Reads month-to-date AWS spend per service from Cost Explorer.

    Args:
        client: injected boto3 ``ce`` client. When omitted the adapter builds one
            lazily and only if credentials resolve.
        region: Cost Explorer endpoint region. Cost Explorer is a global service
            fronted by ``us-east-1``.
        anomaly_threshold_pct: day-over-average increase that counts as an anomaly.
    """

    def __init__(
        self,
        client: Any = None,
        region: str | None = None,
        anomaly_threshold_pct: float = ANOMALY_THRESHOLD_PCT,
    ) -> None:
        self._client = client
        self.region = region or os.environ.get("AWS_COST_EXPLORER_REGION", "us-east-1")
        self.anomaly_threshold_pct = anomaly_threshold_pct
        self._resolution_cached = False
        self._resolved_client: Any = None
        self._cache: tuple[float, CloudCostReport] | None = None

    def _cached_report(self) -> CloudCostReport | None:
        """Return the cached live report while it is still within its TTL."""
        if self._cache is None:
            return None
        cached_at, report = self._cache
        if time.time() - cached_at > CACHE_TTL_SECONDS:
            self._cache = None
            return None
        return report

    def invalidate_cache(self) -> None:
        """Drop the cached report so the next call goes back to Cost Explorer."""
        self._cache = None

    # -------------------------------------------------------------- Fixtures

    @staticmethod
    @lru_cache(maxsize=1)
    def _load_fixture() -> dict[str, Any]:
        """Read the recorded fixture. Cached, so editing it needs a restart."""
        with open(FIXTURE_PATH, "r", encoding="utf-8") as handle:
            return json.load(handle)

    def _fixture_report(self, reason: str) -> CloudCostReport:
        fixture = self._load_fixture()
        return CloudCostReport(
            total_month_to_date_usd=fixture["total_month_to_date_usd"],
            projected_end_of_month_usd=fixture["projected_end_of_month_usd"],
            anomalies=[
                CostAnomaly(
                    service_name=item["service_name"],
                    previous_daily_avg_usd=item["previous_daily_avg_usd"],
                    current_daily_usd=item["current_daily_usd"],
                    percentage_increase=item["percentage_increase"],
                    root_cause_explanation=item["root_cause_explanation"],
                )
                for item in fixture["anomalies"]
            ],
            provenance=Provenance(
                source=DataSource.OFFLINE_FIXTURE,
                detail=f"{reason} Serving {FIXTURE_PATH.name}: {fixture['note']}",
                observed_at_utc=fixture["recorded_at_utc"],
            ),
        )

    # ------------------------------------------------------------------ boto3

    def _resolve_client(self) -> Any:
        """Return a Cost Explorer client, or None when credentials do not resolve.

        The outcome is cached, including the None outcome. Resolving credentials
        walks the whole boto3 provider chain, which on a machine with no
        credentials includes an instance-metadata probe that must time out; doing
        that per request added over a second to every cost call.
        """
        if self._client is not None:
            return self._client
        if self._resolution_cached:
            return self._resolved_client

        self._resolution_cached = True
        try:
            import boto3  # imported lazily so the package stays importable without boto3

            session = boto3.session.Session()
            if session.get_credentials() is None:
                self._resolved_client = None
            else:
                self._resolved_client = session.client("ce", region_name=self.region)
        except Exception:
            self._resolved_client = None
        return self._resolved_client

    def reset_credential_cache(self) -> None:
        """Force the next call to resolve credentials again."""
        self._resolution_cached = False
        self._resolved_client = None

    # ------------------------------------------------------------ Computation

    @staticmethod
    def month_to_date_window(today: date | None = None) -> tuple[str, str, int]:
        """Return the ``(start, end, elapsed_days)`` Cost Explorer window.

        Cost Explorer treats ``End`` as exclusive, so the window runs from the
        first of the month to today.
        """
        today = today or datetime.now(timezone.utc).date()
        start = today.replace(day=1)
        elapsed_days = max((today - start).days, 1)
        return start.isoformat(), today.isoformat(), elapsed_days

    @classmethod
    def summarize(
        cls,
        results_by_time: list[dict[str, Any]],
        elapsed_days: int,
        days_in_month: int,
        anomaly_threshold_pct: float = ANOMALY_THRESHOLD_PCT,
    ) -> tuple[float, float, list[CostAnomaly]]:
        """Reduce a Cost Explorer ``ResultsByTime`` payload to a cockpit summary.

        Pure function, separated from the network call so the whole reduction is
        unit tested against recorded API shapes.
        """
        per_service_daily: dict[str, list[float]] = {}
        total = 0.0
        for bucket in results_by_time:
            for group in bucket.get("Groups", []):
                keys = group.get("Keys") or ["Unknown"]
                service = keys[0]
                amount_str = (group.get("Metrics", {}).get("UnblendedCost", {}) or {}).get("Amount", "0")
                try:
                    amount = float(amount_str)
                except (TypeError, ValueError):
                    amount = 0.0
                per_service_daily.setdefault(service, []).append(amount)
                total += amount

        projected = (total / elapsed_days) * days_in_month if elapsed_days else total

        anomalies: list[CostAnomaly] = []
        for service, daily in per_service_daily.items():
            if len(daily) < 2:
                continue
            latest = daily[-1]
            baseline_values = daily[:-1]
            baseline = sum(baseline_values) / len(baseline_values)
            if baseline <= 0 or latest <= baseline:
                continue
            increase_pct = (latest - baseline) / baseline * 100.0
            if increase_pct < anomaly_threshold_pct:
                continue
            anomalies.append(
                CostAnomaly(
                    service_name=service,
                    previous_daily_avg_usd=round(baseline, 2),
                    current_daily_usd=round(latest, 2),
                    percentage_increase=round(increase_pct, 1),
                    root_cause_explanation=(
                        f"Latest daily spend exceeded the {len(baseline_values)}-day month-to-date "
                        "average for this service. Cost Explorer does not report a cause; "
                        "inspect the service's usage records."
                    ),
                )
            )

        anomalies.sort(key=lambda a: a.percentage_increase, reverse=True)
        return round(total, 2), round(projected, 2), anomalies

    # ------------------------------------------------------------- Public API

    def fetch_cost_report(self) -> CloudCostReport:
        """Return month-to-date spend, live from Cost Explorer when possible.

        Successful results are cached for :data:`CACHE_TTL_SECONDS`. Two reasons,
        both real: AWS bills roughly one cent per Cost Explorer request, and the
        underlying data only refreshes daily, so polling it per wallboard refresh
        would spend money to receive the same answer.
        """
        if offline_mode_enabled():
            return self._fixture_report(OFFLINE_REASON)

        cached = self._cached_report()
        if cached is not None:
            return cached

        client = self._resolve_client()
        if client is None:
            return self._fixture_report(
                "No AWS credentials resolved, so no Cost Explorer call was attempted."
            )

        try:
            start, end, elapsed_days = self.month_to_date_window()
            today = datetime.now(timezone.utc).date()
            days_in_month = calendar.monthrange(today.year, today.month)[1]

            response = client.get_cost_and_usage(
                TimePeriod={"Start": start, "End": end},
                Granularity="DAILY",
                Metrics=["UnblendedCost"],
                GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}],
            )
            total, projected, anomalies = self.summarize(
                response.get("ResultsByTime", []),
                elapsed_days,
                days_in_month,
                self.anomaly_threshold_pct,
            )
            report = CloudCostReport(
                total_month_to_date_usd=total,
                projected_end_of_month_usd=projected,
                anomalies=anomalies,
                provenance=Provenance(
                    source=DataSource.AWS_COST_EXPLORER,
                    detail=(
                        f"AWS Cost Explorer GetCostAndUsage, DAILY granularity grouped by SERVICE, "
                        f"{start} to {end} ({elapsed_days} elapsed days). Cost Explorer lags by up "
                        f"to 24 hours, so the newest day may be partial. Cached for "
                        f"{CACHE_TTL_SECONDS:.0f}s because AWS bills per Cost Explorer request."
                    ),
                    observed_at_utc=_iso_now(),
                ),
            )
        except Exception as exc:
            # Broad on purpose: any botocore error must degrade to the labelled
            # fixture rather than take the wallboard down. Logged so a real
            # failure is diagnosable instead of silently looking like fixture mode.
            reason = describe_exception(exc)
            logger.warning("Cost Explorer call failed: %s", reason)
            return self._fixture_report(f"Cost Explorer call failed ({reason}).")

        self._cache = (time.time(), report)
        return report
