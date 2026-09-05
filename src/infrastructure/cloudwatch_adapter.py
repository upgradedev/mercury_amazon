"""Infrastructure Adapter: CloudWatch metric series for the incident correlator.

Calls ``cloudwatch:GetMetricStatistics`` through boto3 when AWS credentials are
resolvable. When they are not, it returns a deterministic simulated series whose
provenance says, in the payload the cockpit renders, that the numbers were
generated locally and were never read from CloudWatch.

The simulated series is not a disguise for a live reading. It exists so the
correlator, the rollback governance path and the Fire TV interaction can be
demonstrated end to end without an AWS account, and every surface that shows it
is labelled ``offline-fixture``.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

from src.domain.incident_correlation import MetricPoint, MetricSeries
from src.domain.provenance import DataSource, Provenance

DEFAULT_NAMESPACE = "AWS/ApplicationELB"
DEFAULT_METRIC = "HTTPCode_Target_5XX_Count"
SIMULATED_BASELINE = 2.0
SIMULATED_SPIKE = 68.0


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class CloudWatchMetricAdapter:
    """Reads an error metric series for one service.

    Args:
        client: injected boto3 ``cloudwatch`` client. Built lazily when omitted,
            and only if credentials resolve.
        region: AWS region. Defaults to ``AWS_REGION``.
        simulate_incident: shape of the offline series. ``True`` produces a
            series that ends in a spike, ``False`` a flat healthy series. Read
            from ``MERCURY_SIMULATE_INCIDENT`` when not passed.
    """

    def __init__(
        self,
        client: Any = None,
        region: str | None = None,
        simulate_incident: bool | None = None,
    ) -> None:
        self._client = client
        self.region = region or os.environ.get("AWS_REGION", "eu-west-1")
        if simulate_incident is None:
            simulate_incident = os.environ.get("MERCURY_SIMULATE_INCIDENT", "1") not in ("0", "false", "False")
        self.simulate_incident = simulate_incident

    def _resolve_client(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            import boto3

            session = boto3.session.Session()
            if session.get_credentials() is None:
                return None
            return session.client("cloudwatch", region_name=self.region)
        except Exception:
            return None

    # ------------------------------------------------------------ Simulation

    def _simulated_series(self, service_name: str, reason: str, window_minutes: int) -> MetricSeries:
        """Build a deterministic local series, labelled as generated rather than read."""
        now = datetime.now(timezone.utc)
        step = max(window_minutes // 6, 1)
        points = [
            MetricPoint(at=now - timedelta(minutes=step * (6 - index)), value=SIMULATED_BASELINE)
            for index in range(6)
        ]
        if self.simulate_incident:
            points[-1] = MetricPoint(at=points[-1].at, value=SIMULATED_SPIKE)

        shape = "ending in a spike" if self.simulate_incident else "flat and healthy"
        return MetricSeries(
            metric_name=DEFAULT_METRIC,
            namespace=DEFAULT_NAMESPACE,
            points=points,
            provenance=Provenance(
                source=DataSource.OFFLINE_FIXTURE,
                detail=(
                    f"{reason} These {len(points)} data points for {service_name} were generated "
                    f"locally by CloudWatchMetricAdapter ({shape}) and were never read from "
                    "CloudWatch. Set MERCURY_SIMULATE_INCIDENT=0 for a healthy series."
                ),
                observed_at_utc=_iso_now(),
            ),
        )

    # ------------------------------------------------------------- Public API

    def get_error_series(
        self,
        service_name: str,
        window_minutes: int = 60,
        namespace: str = DEFAULT_NAMESPACE,
        metric_name: str = DEFAULT_METRIC,
        dimension_name: str = "LoadBalancer",
    ) -> MetricSeries:
        """Return the error metric series for a service over the recent window."""
        client = self._resolve_client()
        if client is None:
            return self._simulated_series(
                service_name,
                "No AWS credentials resolved, so no CloudWatch call was attempted.",
                window_minutes,
            )

        try:
            end = datetime.now(timezone.utc)
            start = end - timedelta(minutes=window_minutes)
            period = max((window_minutes // 6) * 60, 60)
            response = client.get_metric_statistics(
                Namespace=namespace,
                MetricName=metric_name,
                Dimensions=[{"Name": dimension_name, "Value": service_name}],
                StartTime=start,
                EndTime=end,
                Period=period,
                Statistics=["Sum"],
            )
            datapoints = sorted(
                response.get("Datapoints", []),
                key=lambda d: d["Timestamp"],
            )
            points = [
                MetricPoint(at=entry["Timestamp"], value=float(entry.get("Sum", 0.0)))
                for entry in datapoints
            ]
            if not points:
                return self._simulated_series(
                    service_name,
                    (
                        f"CloudWatch returned no datapoints for {metric_name} on {service_name} "
                        f"in the last {window_minutes} minutes."
                    ),
                    window_minutes,
                )
            return MetricSeries(
                metric_name=metric_name,
                namespace=namespace,
                points=points,
                provenance=Provenance(
                    source=DataSource.AWS_CLOUDWATCH,
                    detail=(
                        f"CloudWatch GetMetricStatistics for {namespace}/{metric_name}, dimension "
                        f"{dimension_name}={service_name}, {len(points)} datapoints at {period}s "
                        f"resolution over the last {window_minutes} minutes."
                    ),
                    observed_at_utc=_iso_now(),
                ),
            )
        except Exception as exc:
            return self._simulated_series(
                service_name,
                f"CloudWatch call failed ({type(exc).__name__}: {exc}).",
                window_minutes,
            )
