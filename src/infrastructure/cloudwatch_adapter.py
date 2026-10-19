"""Infrastructure Adapter: CloudWatch metric series for the incident correlator.

Calls ``cloudwatch:GetMetricStatistics`` through boto3 when AWS credentials are
resolvable. When they are not, it returns a deterministic simulated series whose
provenance says, in the payload the cockpit renders, that the numbers were
generated locally and were never read from CloudWatch. When a live read is
attempted and comes back empty or fails, it returns no points and the label
NO LIVE DATA; it never substitutes the simulated series for a live read.

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

The hybrid board adds a third kind of row: the hackathon's own production Lambda
functions, :data:`LIVE_PRODUCTION_FUNCTIONS`, read from CloudWatch for real
(``AWS/Lambda`` ``Errors``, with ``Invocations`` beside it). Only those exact names
are ever sent to CloudWatch this way, so a caller cannot use the public
``what_changed`` route to probe other functions. They are read live whenever a live
CloudWatch read is allowed: ``MERCURY_OFFLINE`` unset, or ``MERCURY_LIVE_CLOUDWATCH=1``
on top of it. The four simulated services keep their fixture series either way.
"""
from __future__ import annotations

import hashlib
import itertools
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import wait as wait_for
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from src.domain.incident_correlation import (
    DEFAULT_ATTRIBUTION_WINDOW_MINUTES,
    MetricPoint,
    MetricSeries,
)
from src.domain.provenance import DataSource, Provenance
from src.infrastructure import cloudwatch_read_outcome as outcome
from src.infrastructure.cloudwatch_read_outcome import (  # importable from here too
    NOT_CALLED_REASON_PREFIX,
    UNREAD_CACHE_SECONDS,
    UNREAD_REASON_PREFIX,
)
from src.infrastructure.offline_mode import (
    OFFLINE_REASON,
    live_cloudwatch_enabled,
    offline_mode_enabled,
)
from src.infrastructure.safe_errors import describe_exception

DEFAULT_NAMESPACE = "AWS/ApplicationELB"
DEFAULT_METRIC = "HTTPCode_Target_5XX_Count"
SERIES_POINTS = 6

#: The hackathon's own production functions, the only names read live from
#: ``AWS/Lambda``. Fixed in code on purpose: an allow-list a request cannot extend.
LIVE_PRODUCTION_FUNCTIONS: tuple[str, ...] = (
    "mercury-wallboard-euw1-prod",
    "volcan-mcp-euw1-prod",
    "aletheia-provenance-euw1-prod",
)
LIVE_LAMBDA_NAMESPACE = "AWS/Lambda"
LIVE_LAMBDA_METRIC = "Errors"
LIVE_LAMBDA_CONTEXT_METRIC = "Invocations"
LIVE_LAMBDA_DIMENSION = "FunctionName"
#: These functions are invoked a few times an hour, so a 60 minute window is mostly
#: empty buckets. A live row always reads the last 24 hours at one hour per point.
LIVE_LAMBDA_WINDOW_MINUTES = 24 * 60
LIVE_LAMBDA_PERIOD_SECONDS = 3600
#: How long one live read is reused. A public page asks every row on load, so
#: without this each page view would be two CloudWatch calls per function.
LIVE_CACHE_ENV = "MERCURY_CLOUDWATCH_CACHE_SECONDS"
DEFAULT_LIVE_CACHE_SECONDS = 60.0
#: How a read ended, its 30 s "not read" memory and the client timeouts: cloudwatch_read_outcome.py.
#: The longest a board question (``what_changed``, ``agent_incident_brief``) waits for a
#: production row it has to read, as the page waits for its rows
#: (``src/interfaces/live_rows.py``). The agent's model call (25 s) comes after it, and
#: the function's own timeout is 30 s.
ROUTE_READ_DEADLINE_SECONDS = 3.0

# Where the newest simulated reading is placed relative to the newest known
# commit. The unattributed offset is a multiple of the correlator's own
# attribution window, so widening that window cannot silently turn the
# no-attribution demo into an attributed one.
ANCHOR_OFFSET_MINUTES = 4
UNATTRIBUTED_ANCHOR_OFFSET_MINUTES = DEFAULT_ATTRIBUTION_WINDOW_MINUTES * 4

SHAPE_ATTRIBUTED = "spike_after_a_lone_commit"
SHAPE_CROWDED = "spike_after_a_burst_of_commits"
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
        "then cannot attribute to anything, without saying no deploy was involved",
    ),
    "release-train": SimulatedService(
        SHAPE_CROWDED,
        "an error spike after a burst of changes, which the correlator calls an anomaly and then "
        "refuses to name any one of them for, because nothing in the metric says which did it",
    ),
}


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def commits_in_window_before(reading_at: datetime, commit_times: list[datetime]) -> int:
    """How many of ``commit_times`` fall in the attribution window ending at a reading."""
    start = reading_at - timedelta(minutes=DEFAULT_ATTRIBUTION_WINDOW_MINUTES)
    return sum(1 for at in commit_times if start <= at <= reading_at)


def choose_anchor(shape: str, newest: datetime | None, commit_times: list[datetime] | None) -> datetime | None:
    """Pick the commit a simulated reading is placed after, so a demo does not drift.

    Anchoring every shape at the newest commit was fine while the correlator named the
    closest change whatever else was in the window. It stopped being fine when the
    correlator started refusing a crowded window: whether ``checkout-api`` attributed or
    refused then depended on how many times somebody had committed in the hour before
    HEAD, so the same checkout demonstrated different verdicts on different days.

    This picks deterministically from the real log instead:

    * an attributing shape is placed after the newest commit that is **alone** in its
      own attribution window, so the attribution path is reachable;
    * the crowded shape is placed after the commit with the **most** company in its
      window, so the refusal path is reachable.

    Both are choices made to make a path demonstrable, which is what a demo is, and the
    provenance the screen renders says so in the same words. The evidence for how often
    the correlator is right is the labelled corpus in ``scripts/correlation_trial.py``,
    never these four buttons.
    """
    if not commit_times:
        return newest
    ordered = sorted(commit_times)
    if shape == SHAPE_ATTRIBUTED:
        alone = [
            at for at in ordered
            if commits_in_window_before(at + timedelta(minutes=ANCHOR_OFFSET_MINUTES), ordered) == 1
        ]
        return alone[-1] if alone else newest
    if shape == SHAPE_CROWDED:
        return max(
            ordered,
            key=lambda at: (
                commits_in_window_before(at + timedelta(minutes=ANCHOR_OFFSET_MINUTES), ordered), at,
            ),
        )
    return newest


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
        # function -> (written at, ttl, series, the sequence number of the read that wrote
        # it). The number is taken when a read begins, so a read that began later always
        # has a larger one, even inside one tick of a coarse clock.
        self._live_cache: dict[str, tuple[float, float, MetricSeries, float]] = {}
        self._live_lock = threading.Lock()
        self._read_seq = itertools.count(1)
        # The page reads the production rows in parallel; without this a second thread
        # could see the resolution flagged as done before the client exists.
        self._client_lock = threading.Lock()

    def _resolve_client(self) -> Any:
        """Return a CloudWatch client, or None when credentials do not resolve.

        Cached for the same reason as the Cost Explorer adapter: walking the
        boto3 credential chain on a machine without credentials waits on an
        instance-metadata probe, and doing it per request made every incident
        query take most of a second.
        """
        if self._client is not None:
            return self._client
        with self._client_lock:
            if self._resolution_cached:
                return self._resolved_client
            try:
                import boto3

                session = boto3.session.Session()
                if session.get_credentials() is None:
                    self._resolved_client = None
                else:
                    from botocore.config import Config

                    self._resolved_client = session.client(
                        "cloudwatch",
                        region_name=self.region,
                        config=Config(
                            connect_timeout=outcome.CLIENT_CONNECT_TIMEOUT_SECONDS,
                            read_timeout=outcome.CLIENT_READ_TIMEOUT_SECONDS,
                            retries={"max_attempts": outcome.CLIENT_MAX_ATTEMPTS},
                        ),
                    )
            except Exception:
                self._resolved_client = None
            self._resolution_cached = True
            return self._resolved_client

    def reset_credential_cache(self) -> None:
        """Force the next call to resolve credentials again."""
        with self._client_lock:
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

    def _no_live_data(
        self, service_name: str, reason: str, namespace: str, metric_name: str
    ) -> MetricSeries:
        """Fail closed after a live read that produced nothing usable.

        A CloudWatch call was made and came back empty or failed. This used to fall
        back to the simulated series, placed just after a real commit, so a
        misconfigured alarm during a real incident could show a generated spike lined
        up behind a real change. Now the answer is no points at all, stamped NO LIVE
        DATA with the reason, which the correlator reports as INSUFFICIENT_DATA and
        never as a candidate. The simulated series is only for the paths where no live
        read was attempted (MERCURY_OFFLINE, or no credentials), and it says so.
        """
        return MetricSeries(
            metric_name=metric_name,
            namespace=namespace,
            points=[],
            provenance=Provenance(
                source=DataSource.NO_LIVE_DATA,
                detail=(
                    f"{reason} No metric series is shown for {service_name}: a failed or empty "
                    "live read is not replaced with generated data, so nothing can be "
                    "attributed from it."
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
        commit_times: list[datetime] | None = None,
    ) -> MetricSeries:
        """Build a deterministic local series for one named service.

        The values come from :func:`simulated_baseline_for` and
        :func:`simulated_multiplier_for`, both of which are SHA-256 over the
        service name, so two services never share a reading and the same service
        reads the same on every machine.

        When ``anchor_at`` is given, the final reading is placed relative to it.
        The caller passes the newest known commit time, and ``commit_times`` when it has
        the whole log, which lets :func:`choose_anchor` place the attributing shape after
        a commit that is alone in its window and the crowded shape after a burst. Without
        that the demonstrated verdict moved with the last hour of somebody's commit
        history. The unattributed demo is deliberately placed far enough away that no
        commit falls inside the attribution window. This only ever moves simulated points;
        a live CloudWatch reading never reaches this method.
        """
        shape = self._shape_for(service_name)
        if shape is None:
            return self._refused_series(service_name, reason)

        offset = UNATTRIBUTED_ANCHOR_OFFSET_MINUTES if shape == SHAPE_UNATTRIBUTED else ANCHOR_OFFSET_MINUTES
        anchor_at = choose_anchor(shape, anchor_at, commit_times)
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
                "attribution window, so the correlator has an anomaly and an empty window, which it "
                "reports as cannot-attribute rather than as no-deploy; the commits are whatever the "
                "commit stamp beside this answer says they are, and this metric is generated."
            )
        elif shape == SHAPE_CROWDED:
            anchoring = (
                f" The final reading is placed {offset} minutes after the commit with the most "
                f"company inside the {DEFAULT_ATTRIBUTION_WINDOW_MINUTES} minute attribution "
                "window, chosen from the commit log so the crowded-window refusal is reachable from "
                "this screen; the commits are whatever the commit stamp beside this answer says "
                "they are, and this metric is generated."
            )
        elif shape == SHAPE_ATTRIBUTED:
            anchoring = (
                f" The final reading is placed {offset} minutes after the newest commit that is "
                f"alone in its {DEFAULT_ATTRIBUTION_WINDOW_MINUTES} minute attribution window, "
                "chosen from the commit log so the attribution is demonstrable and does not change "
                "with the last hour of somebody's commit history; the commits are whatever the "
                "commit stamp beside this answer says they are, and this metric is generated."
            )
        else:
            anchoring = (
                f" The final reading is placed {offset} minutes after the newest known commit so "
                "the correlation is demonstrable; the commits are whatever the commit stamp beside "
                "this answer says they are, and this metric is generated."
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

    # ------------------------------------------------- Live production rows

    @staticmethod
    def live_read_allowed() -> bool:
        """True when a live CloudWatch read may be made at all.

        ``MERCURY_OFFLINE`` unset allows it, as it always has. With it set, only
        ``MERCURY_LIVE_CLOUDWATCH=1`` does, and then only for the production rows.
        """
        return live_cloudwatch_enabled() or not offline_mode_enabled()

    @classmethod
    def is_live_production_row(cls, service_name: str) -> bool:
        """True for one of the allow-listed production functions, when it may be read live."""
        return service_name in LIVE_PRODUCTION_FUNCTIONS and cls.live_read_allowed()

    @staticmethod
    def _live_cache_seconds() -> float:
        try:
            return max(float(os.environ.get(LIVE_CACHE_ENV, DEFAULT_LIVE_CACHE_SECONDS)), 0.0)
        except ValueError:
            return DEFAULT_LIVE_CACHE_SECONDS

    def invalidate_live_cache(self) -> None:
        """Drop every cached live read, so the next request goes back to CloudWatch."""
        with self._live_lock:
            self._live_cache.clear()

    def cached_live_series(self, function_name: str) -> MetricSeries | None:
        """The cached live read for one function while it is fresh, without calling AWS."""
        with self._live_lock:
            entry = self._live_cache.get(function_name)
        if entry is None:
            return None
        read_at, ttl, series = entry[:3]
        if time.monotonic() - read_at > ttl:
            return None
        return series

    def mark_unread(self, function_name: str, waited_seconds: float) -> MetricSeries:
        """Record that a production read did not answer in time, and return that row.

        The row is NO LIVE DATA with a reason that names the wait and nothing else, and
        it is remembered for :data:`UNREAD_CACHE_SECONDS`. A read still running in the
        background replaces it with its real answer when it finishes. A read that
        answered between the page giving up and this mark already left a fresh answer
        in the cache (the read began with none, or it would not have been slow), and
        that answer is kept and returned rather than hidden for 30 s.
        """
        series = self._no_live_data(
            function_name,
            (
                f"{UNREAD_REASON_PREFIX} within {waited_seconds:g} s, so this row was not read "
                "this time."
            ),
            LIVE_LAMBDA_NAMESPACE,
            LIVE_LAMBDA_METRIC,
        )
        with self._live_lock:
            entry = self._live_cache.get(function_name)
            if entry is not None:
                read_at, ttl, answered = entry[:3]
                fresh = time.monotonic() - read_at <= ttl
                if fresh and not outcome.is_unread(answered):
                    return answered
            # Sequence 0, older than any read: whichever read answers next, however late,
            # replaces it.
            self._live_cache[function_name] = (
                time.monotonic(), UNREAD_CACHE_SECONDS, series, 0)
        return series

    def _sum_series(
        self, client: Any, metric_name: str, function_name: str, start: datetime, end: datetime
    ) -> list[dict[str, Any]]:
        response = client.get_metric_statistics(
            Namespace=LIVE_LAMBDA_NAMESPACE,
            MetricName=metric_name,
            Dimensions=[{"Name": LIVE_LAMBDA_DIMENSION, "Value": function_name}],
            StartTime=start,
            EndTime=end,
            Period=LIVE_LAMBDA_PERIOD_SECONDS,
            Statistics=["Sum"],
        )
        return sorted(response.get("Datapoints", []), key=lambda d: d["Timestamp"])

    def _no_credentials_for_production_row(self, function_name: str) -> MetricSeries:
        """A production row CloudWatch was never asked about: no AWS credentials resolved.

        It is NO LIVE DATA, never OFFLINE FIXTURE: there is no fixture for a real
        function, and the deck and the agent stamp the answer with this label. The board
        draws it "Not read". It only happens on a local run; the deployed function always
        has its role's credentials.
        """
        return MetricSeries(
            metric_name=LIVE_LAMBDA_METRIC,
            namespace=LIVE_LAMBDA_NAMESPACE,
            points=[],
            provenance=Provenance(
                source=DataSource.NO_LIVE_DATA,
                detail=(
                    f"{NOT_CALLED_REASON_PREFIX} for the production function {function_name}: no "
                    "AWS credentials resolved where this server runs, so this row was not read and "
                    "no reading is invented for it."
                ),
                observed_at_utc=_iso_now(),
            ),
        )

    def _read_production_function(self, function_name: str) -> MetricSeries:
        """Read ``Errors`` and ``Invocations`` for one production function, uncached."""
        client = self._resolve_client()
        if client is None:
            return self._no_credentials_for_production_row(function_name)
        window_hours = LIVE_LAMBDA_WINDOW_MINUTES // 60
        try:
            end = datetime.now(timezone.utc)
            start = end - timedelta(minutes=LIVE_LAMBDA_WINDOW_MINUTES)
            errors = self._sum_series(client, LIVE_LAMBDA_METRIC, function_name, start, end)
            invocations = self._sum_series(client, LIVE_LAMBDA_CONTEXT_METRIC, function_name, start, end)
        except Exception as exc:
            if outcome.got_no_answer(exc):
                # CloudWatch did not answer (a timeout, or a connection dropped first):
                # that is a row not read, not an answer with nothing in it, so it is
                # stamped and remembered like the page's own deadline (30 s), not like a
                # read that answered (60 s).
                in_time = " in time" if outcome.is_timeout(exc) else ""
                return self._no_live_data(
                    function_name,
                    f"{UNREAD_REASON_PREFIX}{in_time} ({describe_exception(exc)}), so this row was not read.",
                    LIVE_LAMBDA_NAMESPACE,
                    LIVE_LAMBDA_METRIC,
                )
            return self._no_live_data(
                function_name,
                f"CloudWatch call failed ({describe_exception(exc)}).",
                LIVE_LAMBDA_NAMESPACE,
                LIVE_LAMBDA_METRIC,
            )

        read_at = _iso_now()
        total_invocations = int(sum(float(d.get("Sum", 0.0)) for d in invocations))
        points = [MetricPoint(at=d["Timestamp"], value=float(d.get("Sum", 0.0))) for d in errors]
        if not points:
            series = self._no_live_data(
                function_name,
                (
                    f"CloudWatch returned no {LIVE_LAMBDA_METRIC} datapoints for the production "
                    f"function {function_name} in the last {window_hours} hours "
                    f"({total_invocations} invocations)."
                ),
                LIVE_LAMBDA_NAMESPACE,
                LIVE_LAMBDA_METRIC,
            )
            return series
        total_errors = int(sum(p.value for p in points))
        return MetricSeries(
            metric_name=LIVE_LAMBDA_METRIC,
            namespace=LIVE_LAMBDA_NAMESPACE,
            points=points,
            provenance=Provenance(
                source=DataSource.AWS_CLOUDWATCH,
                detail=(
                    f"Live production reading, not a simulated service: CloudWatch "
                    f"GetMetricStatistics for {LIVE_LAMBDA_NAMESPACE}/{LIVE_LAMBDA_METRIC} with "
                    f"{LIVE_LAMBDA_CONTEXT_METRIC} beside it, dimension "
                    f"{LIVE_LAMBDA_DIMENSION}={function_name}, Sum per "
                    f"{LIVE_LAMBDA_PERIOD_SECONDS}s over the last {window_hours} hours: "
                    f"{total_errors} errors in {total_invocations} invocations across "
                    f"{len(points)} hourly datapoints, read at {read_at}. This is one of the "
                    "hackathon's own Lambda functions. No deploy feed for it is connected, so "
                    "Mercury does not attribute its errors to any commit."
                ),
                observed_at_utc=read_at,
            ),
        )

    def get_production_series(self, function_name: str) -> MetricSeries:
        """Return the live series for one allow-listed production function.

        A fresh cached read is returned unchanged, ``observed_at_utc`` included, so the
        read time on the board is the time CloudWatch was actually asked. Failures are
        cached too: a missing IAM grant must not turn every page view into a call.
        """
        if function_name not in LIVE_PRODUCTION_FUNCTIONS:
            raise ValueError(f"{function_name!r} is not an allow-listed production function")
        cached = self.cached_live_series(function_name)
        if cached is not None:
            return cached
        with self._live_lock:
            started = next(self._read_seq)
        series = self._read_production_function(function_name)
        if outcome.not_called(series):
            # No credentials: nothing was read, so nothing is remembered either.
            return series
        ttl = UNREAD_CACHE_SECONDS if outcome.is_unread(series) else self._live_cache_seconds()
        with self._live_lock:
            entry = self._live_cache.get(function_name)
            if (
                entry is not None
                and entry[3] > started
                and (not outcome.is_unread(entry[2]) or outcome.is_unread(series))
            ):
                # A read that began after this one has already written its answer (two
                # requests missed the cache together, or this read outlived a deadline).
                # That answer is newer, so this late one must not overwrite it; the
                # caller gets the newer answer while it is fresh. A newer read that got
                # no answer (a timeout) is not an answer, so a late real answer replaces
                # it, and a not-read mark carries sequence 0 for the same reason.
                read_at, newer_ttl, newer = entry[:3]
                return newer if time.monotonic() - read_at <= newer_ttl else series
            self._live_cache[function_name] = (time.monotonic(), ttl, series, started)
        return series

    def get_production_series_within(self, function_name: str, deadline_seconds: float) -> MetricSeries:
        """:meth:`get_production_series`, waiting at most ``deadline_seconds`` for it.

        A read that has not answered by then is recorded as not read (``mark_unread``)
        and carries on in the background, where its answer replaces that mark. The
        worker is not joined, so a slow CloudWatch cannot hold the request.
        """
        if function_name not in LIVE_PRODUCTION_FUNCTIONS:
            raise ValueError(f"{function_name!r} is not an allow-listed production function")
        cached = self.cached_live_series(function_name)
        if cached is not None:
            return cached
        pool = ThreadPoolExecutor(max_workers=1)
        try:
            future = pool.submit(self.get_production_series, function_name)
            wait_for([future], timeout=deadline_seconds)
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
        if future.done() and not future.cancelled():
            return future.result()
        return self.mark_unread(function_name, deadline_seconds)

    # ------------------------------------------------------------- Public API

    def get_error_series(
        self,
        service_name: str,
        window_minutes: int = 60,
        anchor_at: datetime | None = None,
        namespace: str = DEFAULT_NAMESPACE,
        metric_name: str = DEFAULT_METRIC,
        dimension_name: str = "LoadBalancer",
        commit_times: list[datetime] | None = None,
    ) -> MetricSeries:
        """Return the error metric series for a service over the recent window.

        An allow-listed production function is read from ``AWS/Lambda`` whenever a
        live read is allowed (see :meth:`is_live_production_row`), over its own fixed
        24 hour window. Every other name follows the original path: the fixture under
        ``MERCURY_OFFLINE``, whatever ``MERCURY_LIVE_CLOUDWATCH`` says.
        """
        if self.is_live_production_row(service_name):
            # A board question waits for the row no longer than the page does.
            return self.get_production_series_within(service_name, ROUTE_READ_DEADLINE_SECONDS)
        if offline_mode_enabled():
            return self._simulated_series(
                service_name, OFFLINE_REASON, window_minutes, anchor_at, commit_times
            )

        client = self._resolve_client()
        if client is None:
            return self._simulated_series(
                service_name,
                "No AWS credentials resolved, so no CloudWatch call was attempted.",
                window_minutes,
                anchor_at,
                commit_times,
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
                return self._no_live_data(
                    service_name,
                    (
                        f"CloudWatch returned no datapoints for {metric_name} on {service_name} "
                        f"in the last {window_minutes} minutes."
                    ),
                    namespace,
                    metric_name,
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
            return self._no_live_data(
                service_name,
                f"CloudWatch call failed ({describe_exception(exc)}).",
                namespace,
                metric_name,
            )
