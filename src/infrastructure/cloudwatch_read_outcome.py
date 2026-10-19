"""How a live CloudWatch read of a production function ended, and how long to trust it.

A read of one of the allow-listed production functions
(``src/infrastructure/cloudwatch_adapter.py``) ends in one of four ways, and the board
stamps each one differently:

* CloudWatch answered with a reading: LIVE, remembered 60 s.
* CloudWatch answered with nothing, or refused (AccessDenied): "No live data",
  remembered 60 s, because asking again soon gets the same answer.
* CloudWatch gave no answer (a deadline, a botocore timeout, a connection dropped
  before any answer): "Not read", remembered 30 s, then asked again.
* CloudWatch was never asked, because no AWS credentials resolved (a local run): also
  "Not read", never remembered.

The two "Not read" kinds are told apart from an answer by the first words of their
reason, which every surface (the row stamp, the agent brief) reads.
"""
from __future__ import annotations

from src.domain.incident_correlation import MetricSeries
from src.domain.provenance import DataSource

#: How long a read that did not answer is remembered as not read, so a slow CloudWatch
#: is not asked again by every page view while it is slow. Every kind of "did not
#: answer" uses it: a deadline (``mark_unread``), a botocore connect or read timeout
#: that ends the read itself, and a connection dropped before any answer.
UNREAD_CACHE_SECONDS = 30.0
#: The first words of a row that got no answer from CloudWatch. The board stamps such a
#: row "Not read" rather than "No live data", which means CloudWatch answered with
#: nothing or refused.
UNREAD_REASON_PREFIX = "CloudWatch did not answer"
#: The first words of a row CloudWatch was never asked about, because no AWS
#: credentials resolved (a local run). Also stamped "Not read", and never cached.
NOT_CALLED_REASON_PREFIX = "CloudWatch was not called"
#: botocore's defaults are a 60 s connect timeout, a 60 s read timeout and legacy
#: retries, which can outlive the Lambda's 30 s timeout. botocore reads ``max_attempts``
#: as retries, so 1 is the first try plus at most one retry: at worst 2 x (2 s + 3 s) per
#: call. The page's own deadline (src/interfaces/live_rows.py) is what bounds "/".
CLIENT_CONNECT_TIMEOUT_SECONDS = 2
CLIENT_READ_TIMEOUT_SECONDS = 3
CLIENT_MAX_ATTEMPTS = 1

#: botocore's timeout-class failures: CloudWatch did not answer in time, as opposed to
#: answering with a refusal (AccessDenied) or with nothing.
_TIMEOUT_ERROR_NAMES = frozenset({
    "ReadTimeoutError", "ConnectTimeoutError", "ConnectTimeout", "ReadTimeout",
    "EndpointConnectionError",
})
#: botocore's transport failures that are not a timeout: the connection was dropped or
#: never made, so CloudWatch gave no answer either.
_NO_ANSWER_ERROR_NAMES = frozenset({
    "ConnectionClosedError", "ProxyConnectionError", "HTTPClientError",
})


def is_timeout(exc: BaseException) -> bool:
    """True when a CloudWatch call failed because nothing answered in time."""
    try:
        from botocore.exceptions import (
            ConnectTimeoutError,
            EndpointConnectionError,
            ReadTimeoutError,
        )

        if isinstance(exc, (ReadTimeoutError, ConnectTimeoutError, EndpointConnectionError)):
            return True
    except ImportError:  # pragma: no cover - botocore ships with boto3
        pass
    return isinstance(exc, TimeoutError) or type(exc).__name__ in _TIMEOUT_ERROR_NAMES


def got_no_answer(exc: BaseException) -> bool:
    """True when a CloudWatch call failed with no answer at all: a timeout or a transport failure.

    A dropped connection (``ConnectionClosedError``) is not CloudWatch answering with
    nothing or refusing, so it must not be stamped "No live data".
    """
    if is_timeout(exc):
        return True
    try:
        from botocore.exceptions import ConnectionError as BotocoreConnectionError
        from botocore.exceptions import HTTPClientError

        if isinstance(exc, (BotocoreConnectionError, HTTPClientError)):
            return True
    except ImportError:  # pragma: no cover - botocore ships with boto3
        pass
    return isinstance(exc, ConnectionError) or type(exc).__name__ in _NO_ANSWER_ERROR_NAMES


def is_unread(series: MetricSeries) -> bool:
    """True for a production row that got no answer (a deadline, a timeout, a dropped connection)."""
    return (
        series.provenance.source is DataSource.NO_LIVE_DATA
        and series.provenance.detail.startswith(UNREAD_REASON_PREFIX)
    )


def not_called(series: MetricSeries) -> bool:
    """True for a production row CloudWatch was never asked about (no credentials resolved)."""
    return (
        series.provenance.source is DataSource.NO_LIVE_DATA
        and series.provenance.detail.startswith(NOT_CALLED_REASON_PREFIX)
    )
