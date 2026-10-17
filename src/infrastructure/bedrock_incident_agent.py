"""Infrastructure Layer: Amazon Bedrock SRE Incident Commander Agent for Mercury.

Bridges Mercury's 10-foot Fire TV incident attribution and governed rollback engine
with Amazon Bedrock (`anthropic.claude-sonnet-5` via `AnthropicBedrockMantle`).

Neuro-Symbolic Boundary
-----------------------
1. **Symbolic / Cryptographic Guardrail (Authoritative):**
   - Temporal anomaly detection, runtime-file change filtering (`MERCURY_SERVICE_SCOPE`),
     explicit attribution refusals (`MULTIPLE_CANDIDATES`, `NO_COMMITS_IN_WINDOW`),
     authenticated `DeploymentMarker` pair verification, and single-use HMAC-SHA256
     governance tokens (`GovernedRollbackUseCase`) remain 100% deterministic.
2. **Neural / Agentic Layer (Amazon Bedrock Claude Sonnet 5):**
   - Synthesizes 10-foot Fire TV Incident Commander briefs explaining metric anomalies,
     runtime file diffs, and attribution refusals.
   - Drafts structured responder handoffs (`current_action`, `confirmed_facts`, `next_step`)
     for DynamoDB-backed multi-responder handoff coordination.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import threading
import time
from typing import Any, Callable

DEFAULT_MODEL_ID = "anthropic.claude-sonnet-5"
DEFAULT_REGION = "eu-west-1"
MODEL_CALL_TIMEOUT_SEC = 25.0
CREDENTIAL_CACHE_SECONDS = 300.0

CAPABILITY_READY = "ready_to_attempt"
CAPABILITY_NO_SDK = "unavailable_sdk_not_installed"
CAPABILITY_NO_CREDENTIALS = "unavailable_no_credentials"
CAPABILITY_NEITHER = "unavailable_no_sdk_and_no_credentials"

SDK_MODULE = "anthropic"

_ARN_MODEL_RE = re.compile(r"[:/]([a-z0-9-]+(?:\.[a-z0-9-]+)+)$", re.IGNORECASE)


def public_model_label(model_id: str) -> str:
    """Return a clean model identifier without exposing an AWS account number."""
    if not model_id.startswith("arn:"):
        return model_id
    match = _ARN_MODEL_RE.search(model_id)
    return match.group(1) if match else "custom-bedrock-profile"


class BedrockIncidentAgentAdapter:
    """Amazon Bedrock (`Claude Sonnet 5`) SRE Incident Commander Agent."""

    def __init__(
        self,
        region_name: str = DEFAULT_REGION,
        model_id: str = DEFAULT_MODEL_ID,
        client_factory: Callable[[str], Any] | None = None,
    ) -> None:
        self.region_name = os.getenv("AWS_REGION", region_name)
        self.model_id = os.getenv("AWS_BEDROCK_MODEL_ID", model_id)
        self._client_factory = client_factory
        self.last_fallback_reason: str | None = None
        self._credentials_cache: tuple[bool, float] | None = None
        self._credentials_lock = threading.Lock()
        self._cache: dict[str, dict[str, Any]] = {}

    @staticmethod
    def sdk_present() -> bool:
        try:
            return importlib.util.find_spec(SDK_MODULE) is not None
        except (ImportError, ValueError):
            return False

    def credentials_present(self, refresh: bool = False) -> bool:
        with self._credentials_lock:
            if self._credentials_cache is not None and not refresh:
                answer, ts = self._credentials_cache
                if time.monotonic() - ts < CREDENTIAL_CACHE_SECONDS:
                    return answer
            answer = self._resolve_credentials()
            self._credentials_cache = (answer, time.monotonic())
            return answer

    @staticmethod
    def _resolve_credentials() -> bool:
        if os.getenv("AWS_ACCESS_KEY_ID") or os.getenv("AWS_SESSION_TOKEN"):
            return True
        try:
            import boto3

            return boto3.Session().get_credentials() is not None
        except Exception:
            return False

    def resolved_capability(self, refresh: bool = False) -> str:
        creds = self.credentials_present(refresh=refresh)
        sdk = self.sdk_present()
        if creds and sdk:
            return CAPABILITY_READY
        if creds:
            return CAPABILITY_NO_SDK
        if sdk:
            return CAPABILITY_NO_CREDENTIALS
        return CAPABILITY_NEITHER

    def health_summary(self) -> dict[str, Any]:
        return {
            "model_id": public_model_label(self.model_id),
            "region": self.region_name,
            "resolved_capability": self.resolved_capability(),
        }

    def model_path_capability(self, refresh: bool = False) -> dict[str, Any]:
        creds = self.credentials_present(refresh=refresh)
        sdk = self.sdk_present()
        return {
            "resolved_capability": self.resolved_capability(refresh=False),
            "credentials_present": creds,
            "sdk_installed": sdk,
            "model_id": public_model_label(self.model_id),
            "region": self.region_name,
            "cache_entries": len(self._cache),
        }

    def _build_client(self) -> Any:
        if self._client_factory is not None:
            return self._client_factory(self.region_name)
        from anthropic import AnthropicBedrockMantle

        return AnthropicBedrockMantle(aws_region=self.region_name, max_retries=0)

    def _can_attempt_live_call(self, prefer_bedrock: bool) -> bool:
        if not prefer_bedrock:
            self.last_fallback_reason = "prefer_bedrock_false"
            return False
        if self._client_factory is not None:
            return True
        if os.getenv("PYTEST_CURRENT_TEST") and os.getenv("MERCURY_ALLOW_BEDROCK_IN_PYTEST") != "1":
            self.last_fallback_reason = "pytest_offline_guard"
            return False
        if self.resolved_capability() != CAPABILITY_READY:
            self.last_fallback_reason = self.resolved_capability()
            return False
        return True

    @staticmethod
    def _extract_first_text(message: Any) -> str:
        blocks = message.get("content") if isinstance(message, dict) else getattr(message, "content", None)
        for block in blocks or []:
            btype = block.get("type") if isinstance(block, dict) else getattr(block, "type", None)
            text = block.get("text") if isinstance(block, dict) else getattr(block, "text", None)
            if btype == "text" and isinstance(text, str) and text.strip():
                return text.strip()
        raise ValueError("Empty response content from Bedrock model")

    def synthesize_incident_brief(
        self,
        *,
        what_changed_payload: dict[str, Any],
        prefer_bedrock: bool = True,
    ) -> dict[str, Any]:
        """Produce a 10-foot SRE Incident Commander brief for a `what_changed` correlation."""
        service = str(what_changed_payload.get("service", "checkout-api"))
        verdict = str(what_changed_payload.get("verdict", "UNKNOWN"))
        metric = what_changed_payload.get("metric") or {}
        attribution = what_changed_payload.get("attribution") or {}
        offending = what_changed_payload.get("offending_commit")
        recommended = what_changed_payload.get("recommended_action")

        cache_seed = json.dumps(
            {
                "s": service,
                "v": verdict,
                "m": metric,
                "o": offending.get("sha") if isinstance(offending, dict) else None,
                "r": recommended.get("target_commit_sha") if isinstance(recommended, dict) else None,
                "model": public_model_label(self.model_id),
            },
            sort_keys=True,
        )
        cache_key = hashlib.sha256(cache_seed.encode("utf-8")).hexdigest()
        if prefer_bedrock and cache_key in self._cache:
            cached_copy = dict(self._cache[cache_key])
            cached_copy["cached"] = True
            return cached_copy

        started = time.perf_counter()
        deterministic = self._deterministic_brief(
            service=service,
            verdict=verdict,
            metric=metric,
            attribution=attribution,
            offending=offending,
            recommended=recommended,
        )

        if not self._can_attempt_live_call(prefer_bedrock):
            deterministic["latency_ms"] = round((time.perf_counter() - started) * 1000.0, 2)
            deterministic["fallback_reason"] = self.last_fallback_reason
            return deterministic

        prompt = (
            "You are Mercury's 10-Foot Fire TV SRE Incident Commander Agent on Amazon Bedrock.\n"
            "Synthesize an incident diagnosis and responder handoff brief from the telemetry correlation.\n"
            "Return ONLY a valid JSON object (1-2 concise sentences per field) with these exact keys:\n"
            '  "incident_severity": one of ["SEV-1_ROLLBACK_READY", "SEV-2_ATTRIBUTION_REFUSED", "NOMINAL_NO_ANOMALY"],\n'
            '  "commander_brief_10ft": 2 concise sentences suitable for a 10-foot TV war-room screen,\n'
            '  "root_cause_hypothesis": technical explanation of the metric reading vs candidate commits,\n'
            '  "responder_handoff_draft": {"current_action": "...", "confirmed_facts": ["..."], "next_step": "..."}\n\n'
            f"Service: {service}\n"
            f"Verdict: {verdict}\n"
            f"Metric: {json.dumps(metric)}\n"
            f"Attribution details: commits_in_window={attribution.get('commits_in_window')}, set_aside={attribution.get('commits_set_aside')}, refusal={attribution.get('refusal_statement')}\n"
            f"Offending commit candidate: {json.dumps(offending)}\n"
            f"Recommended governed action: {json.dumps(recommended)}\n"
        )
        try:
            client = self._build_client()
            response = client.messages.create(
                model=self.model_id,
                max_tokens=1200,
                messages=[{"role": "user", "content": prompt}],
                timeout=MODEL_CALL_TIMEOUT_SEC,
            )
            raw_text = self._extract_first_text(response)
            parsed = self._parse_json_or_wrap(raw_text, deterministic)
            latency_ms = round((time.perf_counter() - started) * 1000.0, 2)
            result = {
                **deterministic,
                **parsed,
                "synthesis_mode": "bedrock",
                "model_answered": public_model_label(self.model_id),
                "model_id": public_model_label(self.model_id),
                "region": self.region_name,
                "cached": False,
                "latency_ms": latency_ms,
                "fallback_reason": None,
                "cache_key_sha256": cache_key,
            }
            self._cache[cache_key] = dict(result)
            return result
        except Exception as exc:  # noqa: BLE001
            self.last_fallback_reason = f"{type(exc).__name__}"
            deterministic["latency_ms"] = round((time.perf_counter() - started) * 1000.0, 2)
            deterministic["fallback_reason"] = self.last_fallback_reason
            return deterministic

    @staticmethod
    def _parse_json_or_wrap(raw_text: str, baseline: dict[str, Any]) -> dict[str, Any]:
        cleaned = raw_text.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.DOTALL).strip()
        start_idx = cleaned.find("{")
        end_idx = cleaned.rfind("}")
        if start_idx != -1 and end_idx > start_idx:
            try:
                data = json.loads(cleaned[start_idx : end_idx + 1])
                if isinstance(data, dict):
                    draft = data.get("responder_handoff_draft")
                    if not isinstance(draft, dict):
                        draft = baseline["responder_handoff_draft"]
                    return {
                        "incident_severity": str(
                            data.get("incident_severity") or baseline["incident_severity"]
                        ),
                        "commander_brief_10ft": str(
                            data.get("commander_brief_10ft") or baseline["commander_brief_10ft"]
                        ),
                        "root_cause_hypothesis": str(
                            data.get("root_cause_hypothesis") or baseline["root_cause_hypothesis"]
                        ),
                        "responder_handoff_draft": draft,
                    }
            except ValueError:
                pass
        return {
            "incident_severity": baseline["incident_severity"],
            "commander_brief_10ft": cleaned[:400],
            "root_cause_hypothesis": baseline["root_cause_hypothesis"],
            "responder_handoff_draft": baseline["responder_handoff_draft"],
        }

    def _deterministic_brief(
        self,
        *,
        service: str,
        verdict: str,
        metric: dict[str, Any],
        attribution: dict[str, Any],
        offending: dict[str, Any] | None,
        recommended: dict[str, Any] | None,
    ) -> dict[str, Any]:
        m_name = metric.get("name", "ErrorCount")
        baseline = metric.get("baseline", 0.0)
        current = metric.get("current", 0.0)
        factor = metric.get("anomaly_factor", 1.0)

        if recommended and offending:
            severity = "SEV-1_ROLLBACK_READY"
            sha = offending.get("sha", "")[:7]
            target_sha = str(recommended.get("target_commit_sha", ""))[:7]
            files = offending.get("runtime_files") or []
            brief = (
                f"{service} {m_name} spiked {factor}x ({baseline} -> {current}) after sole runtime deploy {sha}. "
                f"Governed rollback to verified artifact {target_sha} is ready for two-step D-pad confirmation."
            )
            hypothesis = (
                f"Commit {sha} ('{offending.get('message', '')}') modified runtime files {files} inside the "
                "60-minute window prior to anomaly onset."
            )
            draft = {
                "current_action": f"Stage and confirm governed rollback of {service} from {sha} to {target_sha}.",
                "confirmed_facts": [
                    f"{m_name} rose from baseline {baseline} to {current} ({factor}x).",
                    f"Sole runtime candidate commit in window is {sha}.",
                ],
                "next_step": f"Verify post-rollback health readback for {service} at revision {target_sha}.",
            }
        elif attribution.get("nothing_to_revert"):
            severity = "NOMINAL_NO_ANOMALY"
            brief = f"{service} {m_name} is within normal baseline ({current} vs {baseline}). Nothing to revert."
            hypothesis = "Telemetry reading does not exceed anomaly thresholds; no rollback candidate evaluated."
            draft = {
                "current_action": f"Monitor {service}; no active incident.",
                "confirmed_facts": [f"{m_name} reading {current} is within baseline {baseline}."],
                "next_step": "Continue standard wallboard observation.",
            }
        else:
            severity = "SEV-2_ATTRIBUTION_REFUSED"
            refusal = attribution.get("refusal_reason") or verdict
            stmt = attribution.get("refusal_statement") or "Attribution refused by correlator."
            brief = (
                f"{service} {m_name} is elevated ({current} vs {baseline}, {factor}x), but Mercury refused "
                f"single-commit attribution ({refusal}). Automated rollback staging stays locked."
            )
            hypothesis = f"{stmt} Commits in window: {attribution.get('commits_in_window', 0)}."
            draft = {
                "current_action": f"Investigate {service} manually; single-commit attribution refused ({refusal}).",
                "confirmed_facts": [
                    f"{m_name} spiked {factor}x ({baseline} -> {current}).",
                    str(attribution.get("handoff_fact") or stmt),
                ],
                "next_step": "Inspect service logs and recent config/dependency changes before manual mitigation.",
            }

        return {
            "synthesis_mode": "deterministic",
            "model_answered": None,
            "model_id": public_model_label(self.model_id),
            "region": self.region_name,
            "cached": False,
            "incident_severity": severity,
            "commander_brief_10ft": brief,
            "root_cause_hypothesis": hypothesis,
            "responder_handoff_draft": draft,
            "guardrail_attestation": (
                "Agent synthesis is advisory; temporal correlation refusal rules, authenticated "
                "DeploymentMarker verification, and single-use SHA-256 governance tokens remain authoritative."
            ),
        }
