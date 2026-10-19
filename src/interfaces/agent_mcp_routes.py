"""Interfaces Layer: MCP 2025-11-25 Streamable HTTP & Bedrock SRE Agent routes for Mercury.

Implements:
1. JSON-RPC 2.0 Model Context Protocol (revision 2025-11-25) Streamable HTTP at
   `POST /mcp` and `GET /mcp` (`initialize`, `notifications/initialized`, `ping`,
   `tools/list`, `tools/call` across 10 Mercury SRE war-room tools).
2. `POST /mcp/tools/agent_incident_brief` and `GET /mcp/tools/agent_status`.
   The brief is advisory. It is written deterministically from Mercury's own
   correlation unless a model on Amazon Bedrock (`anthropic.claude-sonnet-5` via
   `AnthropicBedrockMantle`) actually answers, and the response says which.
3. `GET /mcp/agent-deck.js`, the deck script in `agent_deck.py`, which the cockpit
   page always carries. It makes no call until a viewer presses one of its buttons.
"""
from __future__ import annotations

import json
import secrets
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from src.infrastructure.bedrock_incident_agent import BedrockIncidentAgentAdapter
from src.interfaces.agent_deck import AGENT_DECK_JS
from src.interfaces.live_rows import data_sources_sentence

PROTOCOL_VERSION = "2025-11-25"
SUPPORTED_PROTOCOL_VERSIONS = (PROTOCOL_VERSION, "2025-06-18")
SERVER_NAME = "mercury-firetv-cockpit"
SERVER_VERSION = "0.2.0"

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602

bedrock_agent = BedrockIncidentAgentAdapter()


class AgentIncidentBriefRequest(BaseModel):
    service_name: str = Field(default="checkout-api", min_length=1, max_length=128)
    environment: str = Field(default="production", min_length=1, max_length=64)
    time_window_minutes: int = Field(default=60, ge=5, le=1440)
    prefer_bedrock: bool = Field(
        default=True,
        description=(
            "Attempt an Amazon Bedrock model call when the SDK, credentials and IAM permission "
            "allow it; the brief is deterministic otherwise and says so."
        ),
    )


def _mcp_tool_catalog() -> list[dict[str, Any]]:
    return [
        {
            "name": "agent_incident_brief",
            "title": "Advisory Incident Brief",
            "description": (
                "Run what_changed for a service and draft an advisory brief and responder handoff. "
                "Deterministic unless a model on Amazon Bedrock answers; the response names the engine, "
                "the data label and the rollback dispatch mode. A named commit is a temporal candidate, "
                "not a cause."
            ),
            "inputSchema": AgentIncidentBriefRequest.model_json_schema(),
        },
        {
            "name": "agent_status",
            "title": "Agent & MCP 2025-11-25 Status",
            "description": "Report whether a Bedrock model call can be attempted, the MCP transport, and request telemetry.",
            "inputSchema": {"type": "object", "properties": {"refresh": {"type": "boolean"}}},
        },
        {
            "name": "what_changed",
            "title": "Temporal Anomaly & Runtime Commit Correlator",
            "description": "Correlate a CloudWatch error spike against runtime-filtered commits and verified deployment markers.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "service_name": {"type": "string", "default": "checkout-api"},
                    "environment": {"type": "string", "default": "production"},
                    "time_window_minutes": {"type": "integer", "default": 60},
                },
            },
        },
        {
            "name": "get_dora_velocity_report",
            "title": "DORA Engineering Velocity Report",
            "description": "Calculate deployment frequency, lead time, change failure rate, and MTTR with data provenance.",
            "inputSchema": {"type": "object", "properties": {}},
        },
        {
            "name": "get_pr_bottlenecks",
            "title": "Stale Pull Request Bottleneck Radar",
            "description": "List open pull requests exceeding the 36-hour review SLA.",
            "inputSchema": {"type": "object", "properties": {}},
        },
        {
            "name": "get_aws_cost_anomalies",
            "title": "AWS Cost Explorer Spend & Anomaly Report",
            "description": "Report month-to-date AWS spend, end-of-month projection, and daily service cost spikes.",
            "inputSchema": {"type": "object", "properties": {}},
        },
        {
            "name": "audit_observability",
            "title": "Service Telemetry Completeness Audit",
            "description": "Check which required telemetry signals are present or missing for a target service.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "service_name": {"type": "string", "default": "checkout-api"},
                    "received_signals": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        {
            "name": "deployment_timeline",
            "title": "Authenticated Deployment Marker Timeline",
            "description": "Return verified deployment markers and post-deploy health readbacks for a service.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "service": {"type": "string", "default": "checkout-api"},
                    "environment": {"type": "string", "default": "production"},
                },
            },
        },
        {
            "name": "demo_stage_rollback",
            "title": "Stage Record-Only Demo Rollback",
            "description": "Mint a content-bound single-use HMAC-SHA256 governance token for the offline fixture target.",
            "inputSchema": {"type": "object", "properties": {"action_id": {"type": "string"}}},
        },
        {
            "name": "demo_update_handoff",
            "title": "Publish Record-Only Responder Handoff",
            "description": "Publish the shared responder handoff with optimistic concurrency revision checking.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "service_name": {"type": "string", "default": "checkout-api"},
                    "expected_revision": {"type": "integer"},
                },
            },
        },
    ]


def register_agent_mcp_routes(app: FastAPI) -> None:
    """Register Bedrock SRE Agent routes and MCP 2025-11-25 Streamable HTTP on `app`."""

    @app.get("/mcp/tools/agent_status")
    async def agent_status(refresh: bool = False) -> dict[str, Any]:
        return {
            "bedrock_model_path": bedrock_agent.model_path_capability(refresh=refresh),
            "mcp_protocol": {
                "version": PROTOCOL_VERSION,
                "supported_versions": list(SUPPORTED_PROTOCOL_VERSIONS),
                "transport": "Streamable HTTP (POST /mcp)",
                "tools_published": len(_mcp_tool_catalog()),
            },
            "observability": {
                "format": "AWS CloudWatch Embedded Metric Format (EMF)",
                "header": "X-Mercury-Request-Id",
                # The request audit log masks PII (observability_harness.mask_pii), and this
                # says so only when that masking works on a probe. Nothing redacts what the
                # agent sends to a model, so that flag is False.
                "audit_log_pii_masking": _audit_masking_works(),
                "agent_prompt_pii_redaction": False,
            },
        }

    @app.post("/mcp/tools/agent_incident_brief")
    async def agent_incident_brief(
        req: AgentIncidentBriefRequest = AgentIncidentBriefRequest(),
    ) -> dict[str, Any]:
        from src.interfaces import mcp_server

        correlation_payload = await mcp_server.what_changed(
            mcp_server.WhatChangedRequest(
                service_name=req.service_name,
                environment=req.environment,
                time_window_minutes=req.time_window_minutes,
            )
        )
        data_label = str(
            (correlation_payload.get("metric_provenance") or {}).get("display_label") or "UNLABELLED DATA"
        )
        rollback_dispatch = mcp_server._dispatch_mode()
        synthesis = bedrock_agent.synthesize_incident_brief(
            what_changed_payload=correlation_payload,
            prefer_bedrock=req.prefer_bedrock,
            data_label=data_label,
            rollback_dispatch=rollback_dispatch,
        )
        response = {
            **correlation_payload,
            "data_label": data_label,
            "rollback_dispatch": rollback_dispatch,
            "agent_synthesis": synthesis,
        }
        # A deterministic brief names no model and no region anywhere in the
        # response; agent_status reports the capability.
        if synthesis.get("synthesis_mode") == "bedrock":
            response["bedrock_model_path"] = bedrock_agent.model_path_capability()
        return response

    @app.get("/mcp")
    async def mcp_streamable_http_get() -> Response:
        return Response(
            status_code=405,
            headers={"Allow": "POST"},
            content=json.dumps(
                {
                    "protocolVersion": PROTOCOL_VERSION,
                    "server": SERVER_NAME,
                    "detail": "Send JSON-RPC 2.0 requests via POST /mcp.",
                }
            ),
            media_type="application/json",
        )

    @app.post("/mcp")
    async def mcp_streamable_http_post(request: Request) -> Response:
        raw = await request.body()
        try:
            message = json.loads(raw.decode("utf-8"))
        except Exception:
            return JSONResponse(
                status_code=200,
                content={"jsonrpc": "2.0", "id": None, "error": {"code": PARSE_ERROR, "message": "Invalid JSON"}},
            )

        if isinstance(message, list) or not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            return JSONResponse(
                status_code=200,
                content={
                    "jsonrpc": "2.0",
                    "id": message.get("id") if isinstance(message, dict) else None,
                    "error": {"code": INVALID_REQUEST, "message": "Expected a single JSON-RPC 2.0 object."},
                },
            )

        method = message.get("method")
        params = message.get("params") or {}
        if not isinstance(method, str) or not method:
            return JSONResponse(
                status_code=200,
                content={"jsonrpc": "2.0", "id": message.get("id"), "error": {"code": INVALID_REQUEST, "message": "Missing method"}},
            )
        if not isinstance(params, dict):
            return JSONResponse(
                status_code=200,
                content={"jsonrpc": "2.0", "id": message.get("id"), "error": {"code": INVALID_PARAMS, "message": "params must be an object"}},
            )

        if "id" not in message:
            if method.startswith("notifications/"):
                return Response(status_code=202)
            return JSONResponse(
                status_code=200,
                content={"jsonrpc": "2.0", "id": None, "error": {"code": INVALID_REQUEST, "message": "Request requires id"}},
            )

        req_id = message["id"]
        if method == "initialize":
            requested = params.get("protocolVersion")
            negotiated = requested if requested in SUPPORTED_PROTOCOL_VERSIONS else PROTOCOL_VERSION
            session_id = secrets.token_urlsafe(24)
            return JSONResponse(
                status_code=200,
                headers={"MCP-Session-Id": session_id, "MCP-Protocol-Version": negotiated},
                content={
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "protocolVersion": negotiated,
                        "capabilities": {"tools": {"listChanged": False}},
                        "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                        "instructions": (
                            "Mercury 10-Foot Fire TV Incident War Room (MCP 2025-11-25). "
                            "Use what_changed for deterministic runtime-scoped attribution, and "
                            "agent_incident_brief for an advisory brief over it. "
                            + data_sources_sentence()
                        ),
                    },
                },
            )

        if method == "ping":
            return JSONResponse(status_code=200, content={"jsonrpc": "2.0", "id": req_id, "result": {}})

        if method == "tools/list":
            return JSONResponse(
                status_code=200,
                content={"jsonrpc": "2.0", "id": req_id, "result": {"tools": _mcp_tool_catalog()}},
            )

        if method == "tools/call":
            name = params.get("name")
            arguments = params.get("arguments") or {}
            if not isinstance(name, str) or not isinstance(arguments, dict):
                return JSONResponse(
                    status_code=200,
                    content={"jsonrpc": "2.0", "id": req_id, "error": {"code": INVALID_PARAMS, "message": "Invalid tool call params"}},
                )
            return await _dispatch_mcp_tool(req_id, name, arguments)

        return JSONResponse(
            status_code=200,
            content={"jsonrpc": "2.0", "id": req_id, "error": {"code": METHOD_NOT_FOUND, "message": f"Method '{method}' not found"}},
        )

    async def _dispatch_mcp_tool(
        req_id: Any, name: str, arguments: dict[str, Any]
    ) -> JSONResponse:
        from src.interfaces import mcp_server

        try:
            if name == "agent_incident_brief":
                payload = await agent_incident_brief(AgentIncidentBriefRequest(**arguments))
            elif name == "agent_status":
                payload = await agent_status(refresh=bool(arguments.get("refresh", False)))
            elif name == "what_changed":
                payload = await mcp_server.what_changed(mcp_server.WhatChangedRequest(**arguments))
            elif name == "get_dora_velocity_report":
                payload = await mcp_server.get_dora_velocity_report()
            elif name == "get_pr_bottlenecks":
                payload = await mcp_server.get_pr_bottlenecks()
            elif name == "get_aws_cost_anomalies":
                payload = await mcp_server.get_aws_cost_anomalies()
            elif name == "audit_observability":
                payload = await mcp_server.audit_observability(
                    mcp_server.ObservabilityAuditRequest(**arguments)
                )
            elif name == "deployment_timeline":
                payload = await mcp_server.deployment_timeline(
                    service=str(arguments.get("service", "checkout-api")),
                    environment=str(arguments.get("environment", "production")),
                )
            elif name == "demo_stage_rollback":
                payload = await mcp_server.demo_stage_rollback(
                    mcp_server.StageRollbackRequest(**arguments)
                )
            elif name == "demo_update_handoff":
                from src.interfaces.handoff_routes import DEMO_ACTION_ID, DEMO_STAMP

                mcp_server._validate_record_only_demo(DEMO_ACTION_ID)
                service_name = str(arguments.get("service_name", "checkout-api"))
                demo_data = mcp_server.recorded_demo_handoff(
                    mcp_server.incident_use_case, mcp_server.deployment_evidence, service_name
                )
                item = mcp_server.incident_handoffs.update(
                    **demo_data, expected_revision=arguments.get("expected_revision")
                )
                payload = {**item.to_dict(), **DEMO_STAMP}
            else:
                return JSONResponse(
                    status_code=200,
                    content={
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "error": {"code": INVALID_PARAMS, "message": f"Unknown tool '{name}'"},
                    },
                )
        except Exception as exc:  # noqa: BLE001
            from src.infrastructure.safe_errors import describe_exception

            return JSONResponse(
                status_code=200,
                content={
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": f"Tool '{name}' failed ({describe_exception(exc)})."}],
                        "isError": True,
                    },
                },
            )

        return JSONResponse(
            status_code=200,
            content={
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": json.dumps(payload, indent=2, sort_keys=True)}],
                    "structuredContent": payload,
                    "isError": False,
                },
            },
        )

    @app.get("/mcp/agent-deck.js")
    async def serve_agent_deck_js() -> Response:
        """Serve the agent deck script. It makes no call until a viewer presses a button."""
        return Response(content=AGENT_DECK_JS, media_type="application/javascript; charset=utf-8")


def _audit_masking_works() -> bool:
    """True when the request audit log's PII masking removes a probe address."""
    from src.infrastructure.observability_harness import PrivateObservabilityHarness

    probe = "contact probe.user@example.com"
    return "probe.user@example.com" not in PrivateObservabilityHarness().mask_pii(probe)


def render_cockpit_response(index_path: Path, request: Request) -> Response:
    """Serve docs/index.html with /mcp/agent-deck.js injected, everywhere.

    The deck used to be left out under pytest and under MERCURY_OFFLINE=1, so every
    browser and D-pad test ran against a page judges never see. The deck makes no
    call until a viewer presses one of its buttons, so there is no reason left to
    serve two pages.
    """
    if index_path.exists():
        html = index_path.read_text(encoding="utf-8")
        injected = html.replace(
            "</body>",
            '  <script src="/mcp/agent-deck.js" defer></script>\n</body>',
            1,
        )
        return Response(content=injected, media_type="text/html; charset=utf-8")
    return JSONResponse({"message": "Mercury API is running. The cockpit page was not found in docs/."})
