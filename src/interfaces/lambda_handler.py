"""AWS Lambda API Gateway HTTP API v2 bridge for the FastAPI application."""
from __future__ import annotations

import asyncio
import base64
from typing import Any, Iterable
from urllib.parse import urlencode

from src.interfaces.mcp_server import app

_TEXT_CONTENT_PREFIXES = ("text/", "application/json", "application/javascript", "application/xml")


def _decode_body(event: dict[str, Any]) -> bytes:
    body = event.get("body")
    if body is None:
        return b""
    if event.get("isBase64Encoded"):
        return base64.b64decode(body)
    return body.encode("utf-8")


def _scope(event: dict[str, Any]) -> dict[str, Any]:
    request_context = event.get("requestContext") or {}
    http = request_context.get("http") or {}
    path = event.get("rawPath") or http.get("path") or "/"
    raw_query = event.get("rawQueryString")
    if raw_query is None:
        raw_query = urlencode(event.get("queryStringParameters") or {})
    headers = [
        (str(key).lower().encode("latin-1"), str(value).encode("latin-1"))
        for key, value in (event.get("headers") or {}).items()
    ]
    return {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.1"},
        "http_version": "1.1",
        "method": (http.get("method") or "GET").upper(),
        "scheme": "https",
        "path": path,
        "raw_path": path.encode("utf-8"),
        "root_path": "",
        "query_string": raw_query.encode("utf-8"),
        "headers": headers,
        "client": (http.get("sourceIp") or "0.0.0.0", 0),
        "server": (request_context.get("domainName") or "lambda", 443),
    }


async def _invoke(scope: dict[str, Any], body: bytes) -> dict[str, Any]:
    messages: list[dict[str, Any]] = []
    sent = False

    async def receive() -> dict[str, Any]:
        nonlocal sent
        if sent:
            return await asyncio.Event().wait()
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        messages.append(message)

    await app(scope, receive, send)
    status = 500
    raw_headers: Iterable[tuple[bytes, bytes]] = []
    chunks: list[bytes] = []
    for message in messages:
        if message["type"] == "http.response.start":
            status = message["status"]
            raw_headers = message.get("headers") or []
        elif message["type"] == "http.response.body":
            chunks.append(message.get("body", b""))
    headers = {
        key.decode("latin-1").lower(): value.decode("latin-1")
        for key, value in raw_headers
    }
    payload = b"".join(chunks)
    is_text = any(
        headers.get("content-type", "").startswith(prefix)
        for prefix in _TEXT_CONTENT_PREFIXES
    )
    return {
        "statusCode": status,
        "headers": headers,
        "body": (
            payload.decode("utf-8", errors="replace")
            if is_text
            else base64.b64encode(payload).decode("ascii")
        ),
        "isBase64Encoded": not is_text,
    }


def handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    """Translate one API Gateway v2 or Lambda Function URL event to one ASGI request."""
    return asyncio.run(_invoke(_scope(event), _decode_body(event)))

