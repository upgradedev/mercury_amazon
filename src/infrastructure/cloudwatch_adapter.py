"""Infrastructure Adapter: CloudWatch metric series for the incident correlator.

Calls ``cloudwatch:GetMetricStatistics`` through boto3 when AWS credentials are
resolvable. When they are not, it returns a deterministic simulated series whose
provenance says, in the payload the cockpit renders, that the numbers were
generated locally and were never read from CloudWatch.

The simulated series is not a disguise for a live reading. It exists so the
correlator, the rollback governance path and the Fire TV interaction can be
demonstrated end to end without an AWS account, and every surface that shows it
is labelled ``offline-fixture``.

The simulation used to be one pair of module constants, which meant every service
name produced the same spike. A reviewer typing an invented service name got the
same 34x factor as the real demo service, and no input anyone could supply ever
reached the correlator's two refusal verdicts. That is fixed here in two moves:

1. :data:`SIMULATED_SERVICES` names the services this fixture knows and what each
   one is there to show, one per verdict the correlator can reach. The numbers
   are derived from the service name with SHA-256, so they differ per service and
   are identical on every machine and every restart. Nothing is hand-picked.
2. A service the fixture does not know is refused. The adapter returns a series
   with no points and says why, rather than inventing a spike for a name it has
   never heard of.
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from src.domain.incident_correlation import (
    DEFAULT_ATTRIBUTION_WINDOW_MINUTES,
    MetricPoint,
    MetricSeries,
)
from src.domain.provenance import DataSource, Provenance
from src.infrastructure.offline_mode import OFFLINE_REASON, offline_mode_enabled

DEFAULT_NAMESPACE = "AWS/ApplicationELB"
DEFAULT_METRIC = "HTTPCode_Target_5XX_Count"
SERIES_POINTS = 6

# Where the newest simulated reading is placed relative to the newest known
# commit. The unattributed offset is a multiple of the correlator's own
# attribution window, so widening that window cannot silently turn the
# no-attribution demo into an attributed one.
ANCHOR_OFFSET_MINUTES = 4
UNATTRIBUTED_ANCHOR_OFFSET_MINUTES = DEFAULT_ATTRIBUTION_WINDOW_MINUTES * 4

SHAPE_ATTRIBUTED = "spike_after_a_commit"
SHAPE_UNATTRIBUTED = "spike_far_from_any_commit"
SHAPE_INSIDE_BASELINE = "inside_its_own_baseline"
SHAPE_FLAT = "flat_and_healthy"


@dataclass(frozen=True)
class SimulatedService:
    """One named service in the offline fixture, and the verdict it demonstrates."""

    shape: str
    demonstrates: str


# One entry per verdict a judge can reach from the cockpit. The fourth verdict,
# INSUFFICIENT_DATA, is what any name absent from this mapping produces.
SIMULATED_SERVICES: dict[str, SimulatedService] = {
    "checkout-api": SimulatedService(
        SHAPE_ATTRIBUTED,
        "an error spike a few minutes after a real commit, which the correlator attributes "
        "and offers a rollback for",
    ),
    "payments-worker": SimulatedService(
        SHAPE_INSIDE_BASELINE,
        "a reading above its baseline but under the anomaly threshold, which the correlator "
        "refuses to call an incident",
    ),
    "search-indexer": SimulatedService(
        SHAPE_UNATTRIBUTED,
        "an error spike hours away from any commit, which the correlator calls an anomaly and "
        "then declines to blame anything for",
    ),
}


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _digest(service_name: str) -> bytes:
    """SHA-256 of the service name.

    Deliberately not the builtin ``hash``: Python randomises string hashing per
    process, so that would give the same service different numbers on every
    restart, which is the opposite of what this fixture is for.
    """
    return hashlib.sha256(service_name.encode("utf-8")).digest()


def simulated_baseline_for(service_name: str) -> float:
    """The baseline error count this fixture uses for one service, 1.00 to 9.99."""
    digest = _digest(service_name)
    return round(1.0 + (((digest[0] << 8) | digest[1]) % 900) / 100.0, 2)


def simulated_multiplier_for(service_name: str, shape: str) -> float:
    """How far the newest reading sits above the baseline, by shape.

    An ``inside_its_own_baseline`` service lands between 1.20x and 1.89x: the
    reading visibly moves, so the screen is not showing a flat line, and it stays
    under the correlator's 3.0x threshold by a margin no rounding can close. A
    spiking service lands between 6.00x and 12.99x, which clears the threshold by
    the same kind of margin. Both bands are asserted by tests, so a future edit
    that lets them meet fails the build.
    """
    digest = _digest(service_name)
    if shape == SHAPE_FLAT:
        return 1.0
    if shape == SHAPE_INSIDE_BASELINE:
        return round(1.2 + (digest[2] % 70) / 100.0, 2)
    return round(6.0 + (((digest[2] << 8) | digest[3]) % 700) / 100.0, 2)


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
        self._resolution_cached = False
        self._resolved_client: Any = None

    def _resolve_client(self) -> Any:
        """Return a CloudWatch client, or None when credentials do not resolve.

        Cached for the same reason as the Cost Explorer adapter: walking the
        boto3 credential chain on a machine without credentials waits on an
        instance-metadata probe, and doing it per request made every incident
        query take most of a second.
        """
        if self._client is not None:
            return self._client
        if self._resolution_cached:
            return self._resolved_client

        self._resolution_cached = True
        try:
            import boto3

            session = boto3.session.Session()
            if session.get_credentials() is None:
                self._resolved_client = None
            else:
                self._resolved_client = session.client("cloudwatch", region_name=self.region)
        except Exception:
            self._resolved_client = None
        return self._resolved_client

    def reset_credential_cache(self) -> None:
        """Force the next call to resolve credentials again."""
        self._resolution_cached = False
        self._resolved_client = None

    # ------------------------------------------------------------ Simulation

    def _shape_for(self, service_name: str) -> str | None:
        """The fixture shape for this service, or None when it is not known.

        ``MERCURY_SIMULATE_INCIDENT=0`` flattens every known service, which is
        what that switch has always meant. It cannot make an unknown service
        known: refusing a name this fixture has never heard of is not a shape.
        """
        known = SIMULATED_SERVICES.get(service_name)
        if known is None:
            return None
        return known.shape if self.simulate_incident else SHAPE_FLAT

    def _refused_series(self, service_name: str, reason: str) -> MetricSeries:
        """Return no data for a service this fixture does not know.

        The alternative was to invent a spike for any string a caller supplied,
        which is what made the old simulation service-independent. A series with
        no points reaches the correlator as INSUFFICIENT_DATA, so the cockpit
        renders a refusal rather than a fabricated incident.
        """
        return MetricSeries(
            metric_name=DEFAULT_METRIC,
            namespace=DEFAULT_NAMESPACE,
            points=[],
            provenance=Provenance(
                source=DataSource.OFFLINE_FIXTURE,
                detail=(
                    f"{reason} No metric series was generated for '{service_name}': it is not one "
                    f"of the services the offline fixture knows "
                    f"({', '.join(sorted(SIMULATED_SERVICES))}), and this adapter does not invent "
                    "a reading for a name it has never seen. Connect AWS credentials to read this "
                    "service from CloudWatch."
                ),
                observed_at_utc=_iso_now(),
            ),
        )

    def _simulated_series(
        self,
        service_name: str,
        reason: str,
        window_minutes: int,
        anchor_at: datetime | None = None,
    ) -> MetricSeries:
        """Build a deterministic local series for one named service.

        The values come from :func:`simulated_baseline_for` and
        :func:`simulated_multiplier_for`, both of which are SHA-256 over the
        service name, so two services never share a reading and the same service
        reads the same on every machine.

        When ``anchor_at`` is given, the final reading is placed relative to it.
        The caller passes the newest known commit time, so the attributed demo is
        coherent, and the unattributed demo is deliberately placed far enough away
        that no commit falls inside the attribution window. This only ever moves
        simulated points; a live CloudWatch reading never reaches this method.
        """
        shape = self._shape_for(service_name)
        if shape is None:
            return self._refused_series(service_name, reason)

        offset = UNATTRIBUTED_ANCHOR_OFFSET_MINUTES if shape == SHAPE_UNATTRIBUTED else ANCHOR_OFFSET_MINUTES
        end = (anchor_at + timedelta(minutes=offset)) if anchor_at else datetime.now(timezone.utc)
        step = max(window_minutes // SERIES_POINTS, 1)

        baseline = simulated_baseline_for(service_name)
        latest = round(baseline * simulated_multiplier_for(service_name, shape), 2)
        points = [
            MetricPoint(
                at=end - timedelta(minutes=step * (SERIES_POINTS - 1 - index)),
                value=baseline,
            )
            for index in range(SERIES_POINTS)
        ]
        points[-1] = MetricPoint(at=points[-1].at, value=latest)

        if anchor_at is None:
            anchoring = ""
        elif shape == SHAPE_UNATTRIBUTED:
            anchoring = (
                f" The final reading is placed {offset} minutes after the newest known commit, "
                f"which is deliberately outside the {DEFAULT_ATTRIBUTION_WINDOW_MINUTES} minute "
                "attribution window, so the correlator has an anomaly and nothing to blame for it; "
                "the commits are real, this metric is not."
            )
        else:
            anchoring = (
                f" The final reading is placed {offset} minutes after the newest known commit so "
                "the correlation is demonstrable; the commits are real, this metric is not."
            )

        return MetricSeries(
            metric_name=DEFAULT_METRIC,
            namespace=DEFAULT_NAMESPACE,
            points=points,
            provenance=Provenance(
                source=DataSource.OFFLINE_FIXTURE,
                detail=(
                    f"{reason} These {len(points)} data points for {service_name} were generated "
                    f"locally by CloudWatchMetricAdapter (shape '{shape}', baseline {baseline} "
                    f"rising to {latest}, both derived from the SHA-256 of the service name) and "
                    "were never read from CloudWatch."
                    + anchoring
                    + " Set MERCURY_SIMULATE_INCIDENT=0 for a flat and healthy series."
                ),
                observed_at_utc=_iso_now(),
            ),
        )

    # ------------------------------------------------------------- Public API

    def get_error_series(
        self,
        service_name: str,
        window_minutes: int = 60,
        anchor_at: datetime | None = None,
        namespace: str = DEFAULT_NAMESPACE,
        metric_name: str = DEFAULT_METRIC,
        dimension_name: str = "LoadBalancer",
    ) -> MetricSeries:
        """Return the error metric series for a service over the recent window."""
        if offline_mode_enabled():
            return self._simulated_series(service_name, OFFLINE_REASON, window_minutes, anchor_at)

        client = self._resolve_client()
        if client is None:
            return self._simulated_series(
                service_name,
                "No AWS credentials resolved, so no CloudWatch call was attempted.",
                window_minutes,
                anchor_at,
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
                    anchor_at,
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
                anchor_at,
            )
