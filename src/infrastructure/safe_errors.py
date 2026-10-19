"""Turn an exception into text that is safe to put on a public page.

Every adapter used to put ``f"{type(exc).__name__}: {exc}"`` into the provenance the
cockpit renders. An ``AccessDenied`` from AWS carries the caller's role ARN, and the
ARN carries the AWS account id, so a missing IAM grant would have printed the account
id on the public board. This module is the one place an exception becomes text:

* a botocore ``ClientError`` keeps its error code (``AccessDenied``,
  ``ThrottlingException``) and a short generic reason, and drops AWS's message;
* an ``httpx.HTTPStatusError`` keeps its status code and a short generic reason;
* anything else keeps a scrubbed, truncated message.

Whatever survives is scrubbed again: ARNs, 12-digit account ids, access key ids,
request ids, GitHub tokens and email addresses are replaced with placeholders. The
exception class name is always kept, so a failure stays diagnosable.
"""
from __future__ import annotations

import re

MAX_REASON_CHARS = 160

_SCRUBBERS: tuple[tuple[re.Pattern[str], str], ...] = (
    # Any ARN, whatever the partition or service, up to the next separator.
    (re.compile(r"arn:aws[a-z-]*:[^\s\"'<>,;)]*", re.IGNORECASE), "[arn redacted]"),
    # AWS access key ids (long-term AKIA, temporary ASIA, and the other id prefixes).
    (re.compile(r"\b(?:AKIA|ASIA|AIDA|AROA|AGPA|ANPA|ANVA|APKA|ABIA|ACCA|AIPA)[A-Z0-9]{16}\b"),
     "[key id redacted]"),
    # Request ids: "RequestId: x", "Request ID: x", "x-amz-request-id: x".
    (re.compile(r"(?i)\b(?:x-amz-)?request[ _-]?id\b\s*[:=]?\s*[A-Za-z0-9-]+"), "request id [redacted]"),
    # UUIDs, which is the shape most AWS request ids take.
    (re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"),
     "[id redacted]"),
    # GitHub tokens.
    (re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b"), "[token redacted]"),
    # Email addresses.
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "[email redacted]"),
    # Any run of exactly twelve digits: the shape of an AWS account id.
    (re.compile(r"(?<!\d)\d{12}(?!\d)"), "[account redacted]"),
)

#: Short, generic reasons for the AWS error codes a read-only adapter can meet.
_AWS_CODE_REASONS = {
    "AccessDenied": "the deployment's role is not allowed to make this read",
    "AccessDeniedException": "the deployment's role is not allowed to make this read",
    "UnauthorizedOperation": "the deployment's role is not allowed to make this read",
    "ExpiredToken": "the deployment's credentials have expired",
    "ExpiredTokenException": "the deployment's credentials have expired",
    "InvalidClientTokenId": "the deployment's credentials were not recognised",
    "UnrecognizedClientException": "the deployment's credentials were not recognised",
    "Throttling": "AWS throttled the request",
    "ThrottlingException": "AWS throttled the request",
    "LimitExceededException": "AWS throttled the request",
    "InvalidParameterValue": "AWS rejected a request parameter",
    "InvalidParameterCombination": "AWS rejected a request parameter",
}

_HTTP_REASONS = {
    401: "the request was not authenticated",
    403: "forbidden, or the anonymous rate limit was reached",
    404: "not found, or not public",
    429: "rate limited",
}


def scrub(text: str, limit: int = MAX_REASON_CHARS) -> str:
    """Remove identifiers from free text and cap its length."""
    cleaned = str(text)
    for pattern, replacement in _SCRUBBERS:
        cleaned = pattern.sub(replacement, cleaned)
    cleaned = " ".join(cleaned.split())
    if len(cleaned) > limit:
        cleaned = cleaned[: limit - 3].rstrip() + "..."
    return cleaned


def _aws_error_code(exc: BaseException) -> str | None:
    response = getattr(exc, "response", None)
    if not isinstance(response, dict):
        return None
    error = response.get("Error")
    if not isinstance(error, dict):
        return None
    code = error.get("Code")
    return str(code) if code else None


def _http_status(exc: BaseException) -> int | None:
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    return status if isinstance(status, int) else None


def describe_exception(exc: BaseException) -> str:
    """``ClassName: short reason``, with nothing in it that identifies the account."""
    name = type(exc).__name__
    code = _aws_error_code(exc)
    if code is not None:
        reason = _AWS_CODE_REASONS.get(code, "AWS refused the request")
        return scrub(f"{name}: {code}, {reason}")
    status = _http_status(exc)
    if status is not None:
        if status >= 500:
            reason = "the server failed"
        else:
            reason = _HTTP_REASONS.get(status, "the request was refused")
        return scrub(f"{name}: HTTP {status}, {reason}")
    message = scrub(str(exc))
    return f"{name}: {message}" if message else name
