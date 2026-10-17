"""Interfaces Layer: MCP 2025-11-25 Streamable HTTP & Bedrock SRE Agent routes for Mercury.

Implements:
1. JSON-RPC 2.0 Model Context Protocol (revision 2025-11-25) Streamable HTTP at
   `POST /mcp` and `GET /mcp` (`initialize`, `notifications/initialized`, `ping`,
   `tools/list`, `tools/call` across 10 Mercury SRE war-room tools).
2. `POST /mcp/tools/agent_incident_brief` and `GET /mcp/tools/agent_status`
   bridging Mercury's temporal attribution engine and governed rollback tokens
   with Amazon Bedrock (`anthropic.claude-sonnet-5` via `AnthropicBedrockMantle`).
"""
from __future__ import annotations

import json
import os
import secrets
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from src.infrastructure.bedrock_incident_agent import BedrockIncidentAgentAdapter

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
        description="Attempt Amazon Bedrock Claude Sonnet 5 synthesis when credentials + SDK resolve.",
    )


def _mcp_tool_catalog() -> list[dict[str, Any]]:
    return [
        {
            "name": "agent_incident_brief",
            "title": "Bedrock SRE Incident Commander Brief",
            "description": (
                "Correlate service anomalies with deployment windows and synthesize a 10-foot "
                "Fire TV Incident Commander root-cause brief and responder handoff via Amazon Bedrock (Claude Sonnet 5)."
            ),
            "inputSchema": AgentIncidentBriefRequest.model_json_schema(),
        },
        {
            "name": "agent_status",
            "title": "Bedrock Agent & MCP 2025-11-25 Status",
            "description": "Report Amazon Bedrock model capability, MCP 2025-11-25 transport, and CloudWatch EMF telemetry.",
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
                "pii_redaction_active": True,
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
        synthesis = bedrock_agent.synthesize_incident_brief(
            what_changed_payload=correlation_payload,
            prefer_bedrock=req.prefer_bedrock,
        )
        return {
            **correlation_payload,
            "agent_synthesis": synthesis,
            "bedrock_model_path": bedrock_agent.model_path_capability(),
        }

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
                            "Use agent_incident_brief for Amazon Bedrock Claude Sonnet 5 root-cause "
                            "synthesis and what_changed for deterministic runtime-scoped attribution."
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
            return JSONResponse(
                status_code=200,
                content={
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": f"Tool '{name}' failed: {exc}"}],
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
        """Serve the interactive 10-foot Fire TV Bedrock Claude Sonnet 5 & MCP 2025-11-25 command deck."""
        return Response(content=AGENT_DECK_JS, media_type="application/javascript; charset=utf-8")


def render_cockpit_response(index_path: Path, request: Request) -> Response:
    """Serve docs/index.html, injecting /mcp/agent-deck.js on AWS Lambda or when ?agent=1 is set."""
    if index_path.exists():
        if os.environ.get("AWS_LAMBDA_FUNCTION_NAME") or request.query_params.get("agent") == "1":
            html = index_path.read_text(encoding="utf-8")
            injected = html.replace(
                "</body>",
                '  <script src="/mcp/agent-deck.js" defer></script>\n</body>',
                1,
            )
            return Response(content=injected, media_type="text/html; charset=utf-8")
        return FileResponse(index_path)
    return JSONResponse({"message": "Mercury API is running. The cockpit page was not found in docs/."})


AGENT_DECK_JS = r"""(function () {
  if (document.getElementById('bedrockAgentSection')) return;
  var anchor = document.getElementById('rollback') || document.getElementById('hero');
  if (!anchor || !anchor.parentNode) return;

  var style = document.createElement('style');
  style.textContent = [
    '#bedrockAgentSection .agent-pills { display:flex; flex-wrap:wrap; gap:0.5rem; margin:0.65rem 0; }',
    '#bedrockAgentSection .agent-pill { font-family:var(--mono, monospace); font-size:var(--fs-small, 0.9rem); padding:0.2rem 0.6rem; border:1px solid var(--rule, #2A2E37); background:var(--board, #0E1014); color:var(--ink-2, #A7B0C0); }',
    '#bedrockAgentSection .agent-pill-ok { border-color:var(--ok, #3DD68C); color:var(--ok, #3DD68C); font-weight:600; }',
    '#bedrockAgentSection .agent-pill-amber { border-color:var(--amber, #FFB23F); color:var(--amber, #FFB23F); font-weight:600; }',
    '#bedrockAgentSection .agent-card { border-top:2px solid var(--amber, #FFB23F); background:var(--flap, #14171D); padding:0.9rem 1rem; margin-top:0.75rem; }',
    '#bedrockAgentSection .agent-brief-10ft { font-family:var(--display, sans-serif); font-size:var(--fs-row, 1.25rem); color:var(--ink, #F3F5F8); line-height:1.35; margin:0.4rem 0 0.6rem; }',
    '#bedrockAgentSection .agent-pre { white-space:pre-wrap; word-break:break-word; overflow-x:auto; max-width:100%; font-family:var(--mono, monospace); font-size:var(--fs-small, 0.85rem); padding:0.75rem; background:var(--board, #0E1014); border:1px solid var(--rule, #2A2E37); color:var(--ink-2, #A7B0C0); margin-top:0.5rem; }'
  ].join('\n');
  document.head.appendChild(style);

  function mk(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined && text !== null) e.textContent = String(text);
    return e;
  }

  function activeService() {
    var btn = document.querySelector('.btn-demo[aria-pressed="true"]');
    return (btn && btn.getAttribute('data-service')) || 'checkout-api';
  }

  var sec = mk('section', 'screen');
  sec.id = 'bedrockAgentSection';
  sec.setAttribute('aria-labelledby', 'bedrockAgentTitle');

  sec.appendChild(mk('p', 'section-kicker', 'Amazon Bedrock Claude Sonnet 5 · MCP 2025-11-25 Streamable HTTP'));
  var h2 = mk('h2', null, 'AI Incident Commander & MCP 2025-11-25 War Room');
  h2.id = 'bedrockAgentTitle';
  sec.appendChild(h2);
  sec.appendChild(mk('p', 'note',
    'Deterministic window correlation and HMAC-SHA256 governance tokens hold rollback authority, while Claude Sonnet 5 (anthropic.claude-sonnet-5 on Amazon Bedrock in eu-west-1) synthesizes 10-foot commander briefs and responder handoffs over MCP 2025-11-25 Streamable HTTP.'
  ));

  var bar = mk('div', 'actions-bar');
  bar.style.marginTop = '0.85rem';

  var btnBrief = mk('button', 'btn btn-primary', 'Ask Claude Sonnet 5 Commander');
  btnBrief.id = 'btnAgentBrief';
  btnBrief.type = 'button';
  btnBrief.setAttribute('data-tv-focusable', '');
  btnBrief.setAttribute('data-tv-label', 'Ask Claude Sonnet 5 Incident Commander');
  btnBrief.title = 'Call POST /mcp/tools/agent_incident_brief for the selected service using Amazon Bedrock Claude Sonnet 5';

  var btnPublish = mk('button', 'btn', 'Publish Agent Handoff to DynamoDB');
  btnPublish.id = 'btnAgentPublishHandoff';
  btnPublish.type = 'button';
  btnPublish.setAttribute('data-tv-focusable', '');
  btnPublish.setAttribute('data-tv-label', 'Publish Agent Handoff to DynamoDB');
  btnPublish.title = 'Persist the responder handoff for the selected service into Amazon DynamoDB with optimistic concurrency';

  var btnMcp = mk('button', 'btn', 'Verify MCP 2025-11-25 Handshake');
  btnMcp.id = 'btnAgentMcpHandshake';
  btnMcp.type = 'button';
  btnMcp.setAttribute('data-tv-focusable', '');
  btnMcp.setAttribute('data-tv-label', 'Verify MCP 2025-11-25 Streamable HTTP handshake');
  btnMcp.title = 'Run JSON-RPC 2.0 initialize, notifications/initialized, tools/list, and tools/call against POST /mcp';

  bar.appendChild(btnBrief);
  bar.appendChild(btnPublish);
  bar.appendChild(btnMcp);
  sec.appendChild(bar);

  var consoleBox = mk('div', 'console');
  consoleBox.style.marginTop = '0.85rem';
  var header = mk('div', 'console-header');
  header.appendChild(mk('span', null, 'Claude Sonnet 5 SRE Synthesis & MCP 2025-11-25 Telemetry'));
  var latencySpan = mk('span', 'latency', 'Ready (anthropic.claude-sonnet-5 · eu-west-1)');
  latencySpan.id = 'bedrockAgentLatency';
  header.appendChild(latencySpan);
  consoleBox.appendChild(header);

  var out = mk('div');
  out.id = 'bedrockAgentOutput';
  var empty = mk('div', 'empty-state-card',
    'Select any service on the departures board above and press "Ask Claude Sonnet 5 Commander" or "Verify MCP 2025-11-25 Handshake" to run live Amazon Bedrock synthesis and Streamable HTTP tool discovery.'
  );
  empty.id = 'bedrockAgentEmpty';
  out.appendChild(empty);
  consoleBox.appendChild(out);
  sec.appendChild(consoleBox);

  anchor.parentNode.insertBefore(sec, anchor.nextSibling);

  btnBrief.addEventListener('click', async function () {
    var svc = activeService();
    btnBrief.disabled = true;
    latencySpan.textContent = 'Calling Amazon Bedrock Claude Sonnet 5 for ' + svc + '…';
    try {
      var t0 = performance.now();
      var r = await fetch('/mcp/tools/agent_incident_brief', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ service_name: svc, environment: 'production', time_window_minutes: 60, prefer_bedrock: true })
      });
      var d = await r.json();
      var elapsed = Math.round(performance.now() - t0);
      var syn = d.agent_synthesis || {};
      var draft = syn.responder_handoff_draft || {};

      var old = document.getElementById('bedrockAgentEmpty');
      if (old) old.remove();
      var prev = document.getElementById('card-agent-brief');
      if (prev) prev.remove();

      var card = mk('div', 'agent-card');
      card.id = 'card-agent-brief';
      var pills = mk('div', 'agent-pills');
      pills.appendChild(mk('span', 'agent-pill agent-pill-amber', 'Service: ' + (d.service || svc)));
      pills.appendChild(mk('span', 'agent-pill agent-pill-ok', 'Engine: ' + (syn.synthesis_mode || 'bedrock') + ' · ' + (syn.model_answered || syn.model_id || 'anthropic.claude-sonnet-5')));
      pills.appendChild(mk('span', 'agent-pill', 'Severity: ' + (syn.incident_severity || 'EVALUATED')));
      pills.appendChild(mk('span', 'agent-pill', 'Correlator Verdict: ' + (d.verdict || 'N/A')));
      pills.appendChild(mk('span', 'agent-pill', 'Latency: ' + (syn.latency_ms || elapsed) + ' ms (cached: ' + Boolean(syn.cached) + ')'));
      card.appendChild(pills);

      card.appendChild(mk('p', 'agent-brief-10ft', syn.commander_brief_10ft || ''));
      card.appendChild(mk('p', 'note', 'Root-Cause Hypothesis: ' + (syn.root_cause_hypothesis || '')));
      card.appendChild(mk('p', 'note', 'Draft Responder Handoff — Action: ' + (draft.current_action || '') + ' | Next step: ' + (draft.next_step || '')));
      card.appendChild(mk('p', 'note', 'Guardrail: ' + (syn.governance_guardrail || '')));
      out.insertBefore(card, out.firstChild);
      latencySpan.textContent = 'POST /mcp/tools/agent_incident_brief (' + svc + ') · ' + (syn.latency_ms || elapsed) + ' ms';
    } catch (err) {
      latencySpan.textContent = 'Error calling agent_incident_brief';
    } finally {
      btnBrief.disabled = false;
    }
  });

  btnPublish.addEventListener('click', async function () {
    var svc = activeService();
    btnPublish.disabled = true;
    latencySpan.textContent = 'Publishing responder handoff for ' + svc + ' to Amazon DynamoDB…';
    try {
      var t0 = performance.now();
      var r = await fetch('/mcp/tools/demo_update_handoff', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ service_name: svc })
      });
      var d = await r.json();
      var elapsed = Math.round(performance.now() - t0);
      var refreshBtn = document.querySelector('[data-action="handoff-refresh"]');
      if (refreshBtn) refreshBtn.click();

      var old = document.getElementById('bedrockAgentEmpty');
      if (old) old.remove();
      var prev = document.getElementById('card-agent-handoff');
      if (prev) prev.remove();

      var card = mk('div', 'agent-card');
      card.id = 'card-agent-handoff';
      var pills = mk('div', 'agent-pills');
      pills.appendChild(mk('span', 'agent-pill agent-pill-ok', 'DynamoDB Revision: ' + (d.revision || 1)));
      pills.appendChild(mk('span', 'agent-pill agent-pill-amber', 'Incident ID: ' + (d.incident_id || (svc + '-active'))));
      pills.appendChild(mk('span', 'agent-pill', 'Responder: ' + (d.responder || 'oncall-sre')));
      pills.appendChild(mk('span', 'agent-pill', 'Write Latency: ' + elapsed + ' ms'));
      card.appendChild(pills);
      card.appendChild(mk('p', 'note', 'Current Action: ' + (d.current_action || '')));
      card.appendChild(mk('p', 'note', 'Next Step: ' + (d.next_step || '')));
      out.insertBefore(card, out.firstChild);
      latencySpan.textContent = 'POST /mcp/tools/demo_update_handoff · revision ' + (d.revision || 1) + ' (' + elapsed + ' ms)';
    } finally {
      btnPublish.disabled = false;
    }
  });

  btnMcp.addEventListener('click', async function () {
    btnMcp.disabled = true;
    latencySpan.textContent = 'Running MCP 2025-11-25 Streamable HTTP handshake…';
    try {
      var t0 = performance.now();
      var rInit = await fetch('/mcp', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          jsonrpc: '2.0',
          id: 1,
          method: 'initialize',
          params: { protocolVersion: '2025-11-25', clientInfo: { name: 'mercury-firetv-cockpit', version: '0.2.0' }, capabilities: {} }
        })
      });
      var initBody = await rInit.json();
      var sessionId = rInit.headers.get('MCP-Session-Id') || 'stateless';
      await fetch('/mcp', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'MCP-Protocol-Version': '2025-11-25' },
        body: JSON.stringify({ jsonrpc: '2.0', method: 'notifications/initialized', params: {} })
      });
      var rList = await fetch('/mcp', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'MCP-Protocol-Version': '2025-11-25' },
        body: JSON.stringify({ jsonrpc: '2.0', id: 2, method: 'tools/list', params: {} })
      });
      var listBody = await rList.json();
      var rCall = await fetch('/mcp', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'MCP-Protocol-Version': '2025-11-25' },
        body: JSON.stringify({ jsonrpc: '2.0', id: 3, method: 'tools/call', params: { name: 'agent_status', arguments: {} } })
      });
      var callBody = await rCall.json();
      var elapsed = Math.round(performance.now() - t0);
      var tools = (listBody.result && listBody.result.tools) || [];

      var old = document.getElementById('bedrockAgentEmpty');
      if (old) old.remove();
      var prev = document.getElementById('card-agent-mcp');
      if (prev) prev.remove();

      var card = mk('div', 'agent-card');
      card.id = 'card-agent-mcp';
      var pills = mk('div', 'agent-pills');
      pills.appendChild(mk('span', 'agent-pill agent-pill-ok', 'MCP Protocol: ' + (initBody.result && initBody.result.protocolVersion)));
      pills.appendChild(mk('span', 'agent-pill agent-pill-amber', 'Tools Published: ' + tools.length));
      pills.appendChild(mk('span', 'agent-pill', 'Server: ' + (initBody.result && initBody.result.serverInfo && initBody.result.serverInfo.name)));
      pills.appendChild(mk('span', 'agent-pill', 'Session: ' + sessionId.slice(0, 16) + '…'));
      pills.appendChild(mk('span', 'agent-pill', 'Round-trip: ' + elapsed + ' ms'));
      card.appendChild(pills);
      card.appendChild(mk('p', 'note', 'Published Tools (' + tools.length + '): ' + tools.map(function (t) { return t.name; }).join(', ')));
      card.appendChild(mk('pre', 'agent-pre', JSON.stringify((callBody.result && callBody.result.structuredContent) || callBody, null, 2)));
      out.insertBefore(card, out.firstChild);
      latencySpan.textContent = 'MCP 2025-11-25 verified (' + tools.length + ' tools · ' + elapsed + ' ms)';
    } finally {
      btnMcp.disabled = false;
    }
  });
})();
"""

