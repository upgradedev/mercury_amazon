"""Interfaces Layer: FastMCP-style HTTP server for the Mercury Fire TV cockpit.

Every telemetry response carries the provenance of its data, so the Fire TV
wallboard can label a live reading differently from a recorded fixture without
the viewer having to trust the server.

The two rollback endpoints are the only state-changing ones and both require the
deployment secret as a bearer token. Confirmation additionally requires a
single-use, content-bound governance token minted at staging time.
"""
from __future__ import annotations

import logging
import os
import secrets
import subprocess
import time
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from src.application.calculate_dora_use_case import CalculateDORAUseCase
from src.application.detect_cost_anomalies_use_case import DetectCostAnomaliesUseCase
from src.application.diagnose_incident_use_case import DiagnoseIncidentUseCase
from src.application.governed_rollback_use_case import GovernedRollbackUseCase
from src.application.inspect_pr_bottlenecks_use_case import InspectPRBottlenecksUseCase
from src.domain.governed_rollback import GovernanceTokenError, RollbackDenialReason
from src.domain.recommendation_invalidator import DynamicRecommendationEngine, EvidenceContract
from src.domain.telemetry_completeness import TelemetryAbsenceDetector
from src.infrastructure.aws_cost_adapter import AWSCostAdapter
from src.infrastructure.cloudwatch_adapter import CloudWatchMetricAdapter
from src.infrastructure.cloudwatch_github_ingest import DevOpsTelemetryIngestAdapter
from src.infrastructure.github_actions_dispatcher import (
    GitHubActionsRollbackDispatcher,
    RollbackDispatchError,
)
from src.infrastructure.github_adapter import GitHubTelemetryAdapter
from src.infrastructure.local_git_adapter import LocalGitCommitProvider
from src.infrastructure.observability_harness import PrivateObservabilityHarness
from src.infrastructure.trial_summary import naming_accuracy

logger = logging.getLogger("mercury.mcp")

WEB_DIR = Path(__file__).resolve().parent.parent.parent / "docs"
MAX_STALE_PRS_ON_SCREEN = 6

# The only file types the cockpit route will serve out of docs/. Markdown is
# deliberately absent: docs/ also holds the project's written documentation and
# the API server has no business handing it out.
COCKPIT_ASSET_TYPES = {
    ".js": "application/javascript",
    ".json": "application/json",
    ".css": "text/css",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
}

app = FastAPI(
    title="Mercury Fire TV Incident Commander",
    description=(
        "HTTP tool server for the Mercury 10-foot engineering war room on Fire TV. "
        "Telemetry responses declare whether they are live or a recorded fixture."
    ),
    version="0.2.0",
)


# --------------------------------------------------------------------- Config

def _resolve_rollback_secret() -> tuple[str, bool]:
    """Return the rollback signing secret and whether it was generated here.

    A generated secret is ephemeral: it changes on every restart and is written
    to the server log so an operator can paste it into the cockpit. Set
    ``MERCURY_ROLLBACK_SECRET`` for anything beyond a local demo.
    """
    configured = os.environ.get("MERCURY_ROLLBACK_SECRET", "")
    if configured:
        return configured, False
    generated = secrets.token_urlsafe(24)
    logger.warning(
        "MERCURY_ROLLBACK_SECRET is not set. Generated an ephemeral rollback secret for this "
        "process only: %s  -- paste it into the cockpit's Governance secret field. "
        "It changes on every restart.",
        generated,
    )
    return generated, True


def _build_sha() -> str:
    """Report the commit this process was built from, for deployment verification."""
    explicit = os.environ.get("MERCURY_BUILD_SHA", "")
    if explicit:
        return explicit
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=10,
            cwd=str(Path(__file__).resolve().parent.parent.parent),
        )
        return result.stdout.strip()
    except Exception:
        return ""


ROLLBACK_SECRET, ROLLBACK_SECRET_IS_EPHEMERAL = _resolve_rollback_secret()
BUILD_SHA = _build_sha()

github_adapter = GitHubTelemetryAdapter()
aws_adapter = AWSCostAdapter()
cloudwatch_adapter = CloudWatchMetricAdapter()

dora_use_case = CalculateDORAUseCase(github_adapter)
cost_use_case = DetectCostAnomaliesUseCase(aws_adapter)
pr_use_case = InspectPRBottlenecksUseCase(github_adapter)
local_git_provider = LocalGitCommitProvider()
incident_use_case = DiagnoseIncidentUseCase(cloudwatch_adapter, github_adapter, local_git_provider)

# Selected by MERCURY_ROLLBACK_DISPATCH. None unless a deployment asks for it, in
# which case the use case keeps its record-only default and nothing is contacted.
rollback_dispatcher = GitHubActionsRollbackDispatcher.from_env()
if rollback_dispatcher is not None:
    logger.warning(
        "Rollback dispatch mode is github_actions against %s/%s@%s. Armed: %s. %s",
        rollback_dispatcher.repository or "<no repository configured>",
        rollback_dispatcher.workflow,
        rollback_dispatcher.ref,
        rollback_dispatcher.armed,
        rollback_dispatcher.disarm_reason,
    )
rollback_use_case = GovernedRollbackUseCase(ROLLBACK_SECRET, rollback_dispatcher)
recommendation_engine = DynamicRecommendationEngine()
telemetry_detector = TelemetryAbsenceDetector()
devops_events: list[dict[str, Any]] = []


# ---------------------------------------------------------------------- Auth

def require_operator(authorization: str | None = Header(default=None)) -> str:
    """Authorize a state-changing call with the deployment's shared secret.

    Refuses with 401 unless the caller presents ``Authorization: Bearer <secret>``.
    The comparison is constant time.
    """
    import hmac

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Rollback endpoints require an Authorization: Bearer <MERCURY_ROLLBACK_SECRET> header.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    presented = authorization[len("Bearer "):].strip()
    if not hmac.compare_digest(presented, ROLLBACK_SECRET):
        raise HTTPException(
            status_code=401,
            detail="The presented bearer secret does not match this deployment's rollback secret.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return presented


DENIAL_STATUS = {
    RollbackDenialReason.UNKNOWN_ACTION: 404,
    RollbackDenialReason.NOT_PENDING: 409,
    RollbackDenialReason.LEASE_EXPIRED: 410,
    RollbackDenialReason.MALFORMED_TOKEN: 400,
    RollbackDenialReason.TOKEN_ACTION_MISMATCH: 403,
    RollbackDenialReason.TOKEN_CONTENT_MISMATCH: 403,
    RollbackDenialReason.BAD_SIGNATURE: 403,
    RollbackDenialReason.TOKEN_ALREADY_USED: 409,
}


# -------------------------------------------------------------------- Schemas

class StageRollbackRequest(BaseModel):
    action_id: str = Field(min_length=1, max_length=128)
    target_service: str = Field(min_length=1, max_length=128)
    target_commit_sha: str = Field(min_length=1, max_length=64)
    reason: str = Field(min_length=1, max_length=500)
    lease_sec: float = Field(default=300.0, gt=0, le=3600)


class ConfirmRollbackRequest(BaseModel):
    action_id: str = Field(min_length=1, max_length=128)
    governance_token: str = Field(min_length=1, max_length=512)


class WhatChangedRequest(BaseModel):
    service_name: str = Field(default="checkout-api", min_length=1, max_length=128)
    time_window_minutes: int = Field(default=60, ge=5, le=1440)


class ObservabilityAuditRequest(BaseModel):
    service_name: str = Field(default="checkout-api", min_length=1, max_length=128)
    received_signals: list[str] = Field(default_factory=list)


class WorkflowRunEvent(BaseModel):
    repository: str = Field(min_length=1, max_length=200)
    workflow_name: str = Field(min_length=1, max_length=200)
    conclusion: str = Field(min_length=1, max_length=40)


# ------------------------------------------------------------- Observability

@app.middleware("http")
async def emit_request_metrics(request: Request, call_next):
    """Emit one CloudWatch EMF record per request, with PII masked."""
    harness = PrivateObservabilityHarness()
    started = time.perf_counter()
    response = await call_next(request)
    harness.record_metric("RequestLatencyMs", round((time.perf_counter() - started) * 1000.0, 2))
    harness.record_metric("ResponseStatus", float(response.status_code), unit="Count")
    harness.add_audit_event(
        actor=request.client.host if request.client else "unknown",
        action=f"{request.method} {request.url.path}",
        details={"status": response.status_code},
    )
    harness.flush()
    response.headers["X-Mercury-Request-Id"] = harness.request_id
    return response


# ------------------------------------------------------------------ Read APIs

@app.get("/health")
async def health_check() -> dict[str, Any]:
    """Liveness plus the commit this process was built from.

    ``build_sha`` is what ``scripts/probe_deployment.py`` reads to decide whether
    a deployment matches the submitted commit. It is an empty string when the
    process cannot determine its own commit.
    """
    return {
        "status": "ok",
        "service": "mercury-firetv-cockpit",
        "version": app.version,
        "build_sha": BUILD_SHA,
        "rollback_secret_is_ephemeral": ROLLBACK_SECRET_IS_EPHEMERAL,
        "github_live": github_adapter.can_call_live,
        "rollback_dispatch": _dispatch_mode(),
    }


def _dispatch_mode() -> str:
    """Say which dispatcher a confirmed rollback would reach, without guessing.

    Three states, and the difference between the last two is the whole point of
    the env gate: configured is not armed.
    """
    if rollback_dispatcher is None:
        return "record-only"
    if rollback_dispatcher.armed:
        return "github-actions-armed"
    return "github-actions-dry-run"


@app.post("/mcp/tools/get_dora_velocity_report")
async def get_dora_velocity_report() -> dict[str, Any]:
    """DORA velocity metrics with the provenance of the data behind them."""
    report = dora_use_case.execute()
    return {
        "voice_summary": report.to_voice_summary(),
        "tier": report.overall_tier.value,
        "metrics": {
            "deployment_frequency_per_day": report.deployment_frequency_per_day,
            "lead_time_hours": report.lead_time_for_changes_hours,
            "change_failure_rate_pct": report.change_failure_rate_percentage,
            "mttr_hours": report.mean_time_to_recovery_hours,
        },
        "sample_size": report.sample_size,
        "window_days": report.window_days,
        "provenance": report.provenance.to_dict(),
    }


@app.post("/mcp/tools/get_pr_bottlenecks")
async def get_pr_bottlenecks() -> dict[str, Any]:
    """Open pull requests past the 36 hour review SLA."""
    radar = pr_use_case.execute()
    return {
        "voice_summary": radar.to_voice_summary(),
        "total_open": radar.total_open_prs,
        "stale_count": len(radar.stale_prs_over_36h),
        "stale_prs": [
            {
                "id": pull.pr_id,
                "repo": pull.repository,
                "title": pull.title,
                "author": pull.author,
                "hours_open": pull.hours_open,
            }
            for pull in radar.stale_prs_over_36h[:MAX_STALE_PRS_ON_SCREEN]
        ],
        "truncated_for_display": len(radar.stale_prs_over_36h) > MAX_STALE_PRS_ON_SCREEN,
        "provenance": radar.provenance.to_dict(),
    }


@app.post("/mcp/tools/get_aws_cost_anomalies")
async def get_aws_cost_anomalies() -> dict[str, Any]:
    """Month-to-date AWS spend and day-over-average anomalies."""
    report = cost_use_case.execute()
    return {
        "voice_summary": report.to_voice_summary(),
        "month_to_date_usd": report.total_month_to_date_usd,
        "projected_usd": report.projected_end_of_month_usd,
        "anomalies": [
            {
                "service": anomaly.service_name,
                "increase_pct": anomaly.percentage_increase,
                "previous_daily_avg_usd": anomaly.previous_daily_avg_usd,
                "current_daily_usd": anomaly.current_daily_usd,
                "root_cause": anomaly.root_cause_explanation,
            }
            for anomaly in report.anomalies
        ],
        "provenance": report.provenance.to_dict(),
    }


@app.post("/mcp/tools/what_changed")
async def what_changed(req: WhatChangedRequest = WhatChangedRequest()) -> dict[str, Any]:
    """Correlate an error metric anomaly with the deployment that preceded it.

    Returns the correlator's verdict as-is, including the verdicts where it
    cannot attribute the anomaly to any commit.
    """
    correlation = incident_use_case.execute(req.service_name, req.time_window_minutes)

    payload: dict[str, Any] = {
        "service": correlation.service_name,
        "verdict": correlation.verdict.value,
        "incident_detected": correlation.incident_detected,
        "voice_summary": correlation.to_voice_summary(),
        "explanation": correlation.explanation,
        "metric": {
            "name": correlation.metric_name,
            "baseline": correlation.baseline_value,
            "current": correlation.current_value,
            "anomaly_factor": correlation.anomaly_factor,
            "sample_size": correlation.sample_size,
        },
        "metric_provenance": correlation.metric_provenance.to_dict(),
        "commit_provenance": correlation.commit_provenance.to_dict(),
        # How many changes were candidates, why nothing was named when nothing was,
        # and what naming a commit is measured to be worth. The accuracy travels with
        # the answer because the moment it matters is the moment somebody is deciding
        # whether to revert, not the moment they read the README.
        "attribution": {
            "commits_in_window": correlation.commits_in_window,
            "is_ambiguous": correlation.attribution_is_ambiguous,
            "refusal_reason": (
                correlation.attribution_refusal.value if correlation.attribution_refusal else None
            ),
            "onset_at": correlation.onset_at.isoformat() if correlation.onset_at else None,
            "baseline_points": correlation.baseline_points,
            "measured_accuracy": naming_accuracy(),
        },
        "offending_commit": None,
        "recommended_action": None,
    }

    if correlation.offending_commit is not None:
        commit = correlation.offending_commit
        payload["offending_commit"] = {
            "sha": commit.sha,
            "author": commit.author,
            "message": commit.message,
            "committed_at": commit.committed_at.isoformat(),
        }

    if correlation.rollback_is_available and correlation.rollback_target is not None:
        target = correlation.rollback_target
        payload["recommended_action"] = {
            "type": "GOVERNED_ROLLBACK",
            "target_commit_sha": target.sha,
            "target_service": correlation.service_name,
            "lease_seconds": 300,
            "status": "AWAITING_AUTHORIZED_STAGING",
            "note": (
                "Staging this rollback requires the deployment's bearer secret. "
                "Confirming it requires the single-use governance token that staging returns."
            ),
        }

    return payload


@app.post("/mcp/tools/audit_observability")
async def audit_observability(req: ObservabilityAuditRequest) -> dict[str, Any]:
    """Report which standard telemetry signals are missing for a service."""
    report = telemetry_detector.audit_service_observability(req.service_name, set(req.received_signals))
    return {
        "service": report.service_name,
        "expected_signals": sorted(report.expected_signals),
        "received_signals": sorted(report.received_signals),
        "missing_signals": report.missing_signals,
        "is_fully_observable": report.is_fully_observable,
        "observability_gap_score": round(report.observability_gap_score, 3),
    }


@app.get("/mcp/events/devops")
async def list_devops_events() -> dict[str, Any]:
    """Return the CI events this server has received, newest first."""
    return {"events": list(reversed(devops_events))[:20], "total": len(devops_events)}


@app.post("/webhooks/github/workflow_run", dependencies=[Depends(require_operator)])
async def ingest_workflow_run(event: WorkflowRunEvent) -> dict[str, Any]:
    """Ingest a GitHub Actions workflow_run event onto the war room timeline."""
    telemetry = DevOpsTelemetryIngestAdapter.ingest_github_webhook(
        event.repository, event.workflow_name, event.conclusion
    )
    record = {
        "event_id": telemetry.event_id,
        "source": telemetry.source,
        "status": telemetry.status,
        "summary": telemetry.summary,
        "timestamp": telemetry.timestamp,
    }
    devops_events.append(record)
    return record


# ------------------------------------------------------------- Governed write

@app.post("/mcp/tools/stage_rollback", dependencies=[Depends(require_operator)])
async def stage_rollback(req: StageRollbackRequest) -> dict[str, Any]:
    """Stage a rollback and mint the single-use token that can confirm it.

    Requires the deployment bearer secret. The returned governance token is bound
    to this action id and to the SHA-256 hash of this exact payload.
    """
    action, token = rollback_use_case.stage_rollback(
        req.action_id, req.target_service, req.target_commit_sha, req.reason, req.lease_sec
    )
    recommendation_engine.register_recommendation(
        rec_id=action.action_id,
        action=f"Roll back {action.target_service} to {action.target_commit_sha}",
        evidence=EvidenceContract(
            metric_name="HTTPCode_Target_5XX_Count",
            safe_threshold=5.0,
            comparison="less_than",
            ttl_seconds=action.lease_sec,
        ),
    )
    return {
        "action_id": action.action_id,
        "target_service": action.target_service,
        "target_commit_sha": action.target_commit_sha,
        "state": action.state.value,
        "payload_hash": action.payload_hash,
        "governance_token": token,
        "lease_seconds_remaining": round(action.seconds_remaining(), 1),
        "confirmation_prompt": (
            f"Rollback of {action.target_service} is staged. Confirm on the Fire TV remote within "
            f"{action.lease_sec:.0f} seconds. The token is valid once and only for this exact change."
        ),
    }


@app.post("/mcp/tools/confirm_rollback", dependencies=[Depends(require_operator)])
async def confirm_rollback(req: ConfirmRollbackRequest) -> dict[str, Any]:
    """Confirm a staged rollback with its single-use governance token."""
    try:
        action, output = rollback_use_case.confirm_and_execute(req.action_id, req.governance_token)
    except GovernanceTokenError as exc:
        raise HTTPException(
            status_code=DENIAL_STATUS.get(exc.reason, 403),
            detail={"denial_reason": exc.reason.value, "message": str(exc)},
        ) from exc
    except RollbackDispatchError as exc:
        # Governance passed and the nonce is spent, so this action can never be
        # confirmed again. Say that, rather than implying a retry will work.
        raise HTTPException(
            status_code=502,
            detail={
                "denial_reason": "DISPATCH_FAILED",
                "message": (
                    f"{exc} The governance token for '{req.action_id}' has been spent, so this "
                    "action cannot be confirmed again. Stage the rollback afresh."
                ),
            },
        ) from exc

    return {
        "status": action.state.value,
        "action_id": action.action_id,
        "target_service": action.target_service,
        "target_commit_sha": action.target_commit_sha,
        "output": output,
    }


@app.post("/mcp/tools/recommendation_liveness")
async def recommendation_liveness(action_id: str, current_metric_value: float) -> dict[str, Any]:
    """Withdraw a staged rollback recommendation when the metric self-resolves."""
    return recommendation_engine.evaluate_liveness(action_id, current_metric_value)


# -------------------------------------------------------------- Cockpit files

@app.get("/")
async def serve_cockpit():
    """Serve the same cockpit page that GitHub Pages publishes from docs/."""
    index_path = WEB_DIR / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return JSONResponse({"message": "Mercury API is running. The cockpit page was not found in docs/."})


# There is deliberately no StaticFiles mount over docs/. A blanket mount serves
# every file in that directory, including the written documentation, which is
# exactly what the allowlist in serve_cockpit_asset below exists to prevent. The
# cockpit links its assets relatively, so that one route is sufficient.


@app.get("/{asset_name}")
async def serve_cockpit_asset(asset_name: str):
    """Serve the cockpit's sibling assets at the paths the page requests them from.

    The page is written once and served from both GitHub Pages and this server, so
    it links its script, manifest and service worker relatively. This route makes
    those relative links resolve here too.

    Only the extensions in :data:`COCKPIT_ASSET_TYPES` are served, and only files
    that resolve to a direct child of ``docs/``, so this cannot be walked out of
    the directory into the rest of the repository.
    """
    suffix = Path(asset_name).suffix.lower()
    media_type = COCKPIT_ASSET_TYPES.get(suffix)
    if media_type is None:
        raise HTTPException(status_code=404, detail="Not found")

    candidate = (WEB_DIR / asset_name).resolve()
    if candidate.parent != WEB_DIR.resolve() or not candidate.is_file():
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(candidate, media_type=media_type)


if __name__ == "__main__":
    import uvicorn

    logging.basicConfig(level=logging.INFO)
    uvicorn.run(app, host="127.0.0.1", port=8002)
