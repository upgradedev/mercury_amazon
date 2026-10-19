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

Model calls are off by default
------------------------------
The brief routes are public, so a model is called only when the server sets
``MERCURY_AGENT_MODEL=on``, and at most ``MERCURY_AGENT_MODEL_MAX_CALLS`` times
(default 100) per process. Otherwise every brief is deterministic and says why
(``fallback_reason`` ``model_off_by_default`` or ``model_call_cap_reached``).
Re-attaching the Bedrock policy to the role is not enough on its own.

Each brief names its provenance field by field: ``model_fields`` lists what a
model wrote, ``template_fields`` what the deterministic template filled in.
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
#: Room for the model to think and still write the brief. Adaptive thinking is on by
#: default for Claude Sonnet 5 on Bedrock and is billed against the same ceiling. At
#: 1200, one of five local calls on 2026-10-19 stopped at max_tokens with a thinking
#: block and no text, and the live verification press after the ddccb3e deploy failed
#: the same way (ValueError, 16.2 s). Volcan uses 16000 for the same reason.
MODEL_MAX_TOKENS = 16000
CREDENTIAL_CACHE_SECONDS = 300.0
MAX_CACHE_ENTRIES = 256

CAPABILITY_READY = "ready_to_attempt"
CAPABILITY_NO_SDK = "unavailable_sdk_not_installed"
CAPABILITY_NO_CREDENTIALS = "unavailable_no_credentials"
CAPABILITY_NEITHER = "unavailable_no_sdk_and_no_credentials"
#: What /health and the brief routes report when the deployed adapter will not call a
#: model whatever the credentials say: the server has not set MERCURY_AGENT_MODEL=on,
#: or this process has used its MERCURY_AGENT_MODEL_MAX_CALLS. "ready_to_attempt"
#: there read as model readiness while every brief was deterministic.
CAPABILITY_OFF = "disabled_by_flag"
CAPABILITY_CAPPED = "disabled_call_cap_reached"

SDK_MODULE = "anthropic"

_ARN_MODEL_RE = re.compile(r"[:/]([a-z0-9-]+(?:\.[a-z0-9-]+)+)$", re.IGNORECASE)


#: Words a model reply may not use about this board. The data is a fixture and
#: dispatch is record-only, so a reply that says a rollback is staged or executed, or
#: that names a cause, is wrong whatever else it says. This is a keyword guard, not a
#: proof: it catches the phrasings seen on the live deck, and the card still labels
#: any model text as an advisory draft.
FORBIDDEN_CLAIMS = re.compile(
    r"\b(?:is|was|has been|been|now|already)\s+staged\b"
    # "awaiting authorization", "awaiting authorized staging", AWAITING_AUTHORIZED_STAGING
    r"|\bawaiting[\s_]+(?:authori|confirmation|approval)"
    r"|\bready\s+to\s+(?:stage|roll\s*back|revert)\b"
    r"|\b(?:was|has been|been|is)\s+(?:executed|rolled back|reverted|performed|dispatched)\b"
    r"|\brollback\s+(?:succeeded|completed|is complete)\b"
    r"|\bcaused\s+by\b|\broot cause (?:is|was)\b|\bthe cause (?:is|was)\b"
    r"|\bintroduced\s+the\s+(?:regression|errors?|incident|bug|spike|outage|failure)\b"
    # "Errors rose after a4ec9aa shrank the pool": a cause told as a sequence.
    r"|\bafter\s+(?:commit\s+)?[0-9a-f]{7,40}\b",
    re.IGNORECASE,
)

#: The fields of the recommended action a prompt may carry. Its status
#: (AWAITING_AUTHORIZED_STAGING), lease and note describe staging, which nothing
#: has done, so a model is never shown them.
PROMPT_RECOMMENDED_FIELDS = ("type", "target_commit_sha", "target_service", "environment")
BRIEF_FIELDS = ("incident_severity", "commander_brief_10ft", "root_cause_hypothesis", "responder_handoff_draft")
DEFAULT_MAX_MODEL_CALLS = 100


def model_calls_enabled() -> bool:
    """A model is called only when the server opts in with MERCURY_AGENT_MODEL=on."""
    return (os.getenv("MERCURY_AGENT_MODEL") or "off").strip().lower() == "on"


def max_model_calls() -> int:
    try:
        return max(0, int(os.getenv("MERCURY_AGENT_MODEL_MAX_CALLS") or DEFAULT_MAX_MODEL_CALLS))
    except ValueError:
        return DEFAULT_MAX_MODEL_CALLS


def forbidden_claim(text: str) -> bool:
    """True when model text claims a cause or a staged or executed rollback."""
    return forbidden_claim_match(text) is not None


def forbidden_claim_match(text: str) -> str | None:
    """The first phrase in model text that the guard rejects, or None."""
    match = FORBIDDEN_CLAIMS.search(text or "")
    return match.group(0) if match else None


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
        self._model_calls = 0
        self._model_calls_lock = threading.Lock()

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

    def reported_capability(self, refresh: bool = False) -> str:
        """The capability a reader is shown: what a brief would actually do.

        resolved_capability answers "could an attempt reach Bedrock?" from credentials
        and the SDK. The deployed adapter also needs MERCURY_AGENT_MODEL=on and calls
        left under the cap, so without them no brief is a model brief and this says so.
        An injected client (tests) is its own opt-in, as in _can_attempt_live_call.
        """
        if self._client_factory is None:
            if not model_calls_enabled():
                return CAPABILITY_OFF
            with self._model_calls_lock:
                if self._model_calls >= max_model_calls():
                    return CAPABILITY_CAPPED
        return self.resolved_capability(refresh=refresh)

    def health_summary(self) -> dict[str, Any]:
        return {
            "model_id": public_model_label(self.model_id),
            "region": self.region_name,
            "resolved_capability": self.reported_capability(),
            "model_calls_enabled": model_calls_enabled(),
        }

    def model_path_capability(self, refresh: bool = False) -> dict[str, Any]:
        creds = self.credentials_present(refresh=refresh)
        sdk = self.sdk_present()
        return {
            "resolved_capability": self.reported_capability(refresh=False),
            "model_calls_enabled": model_calls_enabled(),
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
        if self._client_factory is None:
            # The deployed adapter. An injected client (tests) is its own opt-in.
            if not model_calls_enabled():
                self.last_fallback_reason = "model_off_by_default"
                return False
            if os.getenv("PYTEST_CURRENT_TEST") and os.getenv("MERCURY_ALLOW_BEDROCK_IN_PYTEST") != "1":
                self.last_fallback_reason = "pytest_offline_guard"
                return False
            if self.resolved_capability() != CAPABILITY_READY:
                self.last_fallback_reason = self.resolved_capability()
                return False
        with self._model_calls_lock:
            if self._model_calls >= max_model_calls():
                self.last_fallback_reason = "model_call_cap_reached"
                return False
            self._model_calls += 1
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
        data_label: str = "OFFLINE FIXTURE",
        rollback_dispatch: str = "record-only",
    ) -> dict[str, Any]:
        """Produce an advisory brief for a `what_changed` correlation.

        ``data_label`` and ``rollback_dispatch`` are what the board stamps on the same
        answer. The model is told both, and a reply that claims a cause or a staged or
        executed rollback is discarded for the deterministic brief.
        """
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
                "d": data_label,
                "x": rollback_dispatch,
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
            deployment=what_changed_payload.get("deployment_evidence"),
        )

        if verdict == "INSUFFICIENT_DATA":
            # There is no reading to explain, so there is nothing to ask a model.
            deterministic["latency_ms"] = round((time.perf_counter() - started) * 1000.0, 2)
            deterministic["fallback_reason"] = "insufficient_data"
            return deterministic

        if not self._can_attempt_live_call(prefer_bedrock):
            deterministic["latency_ms"] = round((time.perf_counter() - started) * 1000.0, 2)
            deterministic["fallback_reason"] = self.last_fallback_reason
            return deterministic

        causality = attribution.get("causality_statement") or (
            "Temporal proximity does not prove a change caused the anomaly."
        )
        prompt_recommended = (
            {k: recommended.get(k) for k in PROMPT_RECOMMENDED_FIELDS}
            if isinstance(recommended, dict) else None
        )
        prompt = (
            "You are drafting an advisory note for Mercury's Fire TV incident board.\n"
            f"The data below is labelled {data_label}. Say so if you describe it: it is not a reading of a real service.\n"
            f"Rollback dispatch is {rollback_dispatch}: Stage and Confirm record a decision and contact no pipeline.\n"
            "Rules:\n"
            "- Do not claim a cause. A named commit is only a temporal candidate. " + causality + "\n"
            "- Do not say a rollback is staged, awaiting authorization, executed or completed, and do not mention"
            " rollback status at all, not even to deny it: the board shows that status itself.\n"
            "- Never use these phrasings, which the board rejects even in a negative sentence: 'caused by',"
            " 'root cause is', 'the cause is', 'the cause was', 'introduced the regression', 'after <commit>', 'is staged',"
            " 'has been staged', 'awaiting', 'ready to stage', 'ready to roll back', 'was executed', 'rolled back',"
            " 'reverted', 'dispatched'. Write 'the only runtime commit in the window was <commit>' or"
            " 'a temporal candidate' instead.\n"
            "- Do not invent facts that are not in the data below.\n"
            "Return ONLY a valid JSON object (1-2 concise sentences per field) with these exact keys:\n"
            '  "incident_severity": one of ["SEV-1_ROLLBACK_READY", "SEV-2_ATTRIBUTION_REFUSED", "NOMINAL_NO_ANOMALY"],\n'
            '  "commander_brief_10ft": 2 concise sentences for a 10-foot TV screen,\n'
            '  "root_cause_hypothesis": what the reading and the candidate commits do and do not show,\n'
            '  "responder_handoff_draft": {"current_action": "...", "confirmed_facts": ["..."], "next_step": "..."}\n\n'
            f"Service: {service}\n"
            f"Verdict: {verdict}\n"
            f"Metric: {json.dumps(metric)}\n"
            f"Attribution details: commits_in_window={attribution.get('commits_in_window')}, set_aside={attribution.get('commits_set_aside')}, refusal={attribution.get('refusal_statement')}\n"
            f"Offending commit candidate: {json.dumps(offending)}\n"
            f"Rollback target if a person stages one: {json.dumps(prompt_recommended)}\n"
        )
        try:
            client = self._build_client()
            response = client.messages.create(
                model=self.model_id,
                max_tokens=MODEL_MAX_TOKENS,
                messages=[{"role": "user", "content": prompt}],
                timeout=MODEL_CALL_TIMEOUT_SEC,
            )
            raw_text = self._extract_first_text(response)
            parsed, model_fields = self._parse_json_or_wrap(raw_text, deterministic)
            rejected_phrase = forbidden_claim_match(json.dumps({f: parsed[f] for f in model_fields}))
            if rejected_phrase is not None:
                # A model answered and its reply was discarded: say exactly that, and which phrase.
                self.last_fallback_reason = "model_claim_rejected"
                deterministic["rejected_phrase"] = rejected_phrase
                deterministic["latency_ms"] = round((time.perf_counter() - started) * 1000.0, 2)
                deterministic["fallback_reason"] = self.last_fallback_reason
                deterministic["model_call_attempted"] = True
                return deterministic
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
                "model_call_attempted": True,
                "model_fields": model_fields,
                "template_fields": [f for f in BRIEF_FIELDS if f not in model_fields],
                "cache_key_sha256": cache_key,
            }
            while len(self._cache) >= MAX_CACHE_ENTRIES:
                self._cache.pop(next(iter(self._cache)), None)
            self._cache[cache_key] = dict(result)
            return result
        except Exception as exc:  # noqa: BLE001
            self.last_fallback_reason = f"{type(exc).__name__}"
            deterministic["latency_ms"] = round((time.perf_counter() - started) * 1000.0, 2)
            deterministic["fallback_reason"] = self.last_fallback_reason
            deterministic["model_call_attempted"] = True
            return deterministic

    @staticmethod
    def _parse_json_or_wrap(raw_text: str, baseline: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
        """The brief fields, and the names of the fields the model itself wrote.

        A field the reply leaves out or leaves empty keeps the deterministic text and
        is not listed, so the deck shows it as the template's, not the model's.
        """
        cleaned = raw_text.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.DOTALL).strip()
        start_idx = cleaned.find("{")
        end_idx = cleaned.rfind("}")
        if start_idx != -1 and end_idx > start_idx:
            try:
                data = json.loads(cleaned[start_idx : end_idx + 1])
                if isinstance(data, dict):
                    fields: dict[str, Any] = {}
                    by_model: list[str] = []
                    for name in BRIEF_FIELDS:
                        value = data.get(name)
                        usable = isinstance(value, dict) if name == "responder_handoff_draft" else (
                            isinstance(value, str) and bool(value.strip())
                        )
                        if usable:
                            fields[name] = value
                            by_model.append(name)
                        else:
                            fields[name] = baseline[name]
                    return fields, by_model
            except ValueError:
                pass
        return (
            {
                "incident_severity": baseline["incident_severity"],
                "commander_brief_10ft": cleaned[:400],
                "root_cause_hypothesis": baseline["root_cause_hypothesis"],
                "responder_handoff_draft": baseline["responder_handoff_draft"],
            },
            ["commander_brief_10ft"],
        )

    def _deterministic_brief(
        self,
        *,
        service: str,
        verdict: str,
        metric: dict[str, Any],
        attribution: dict[str, Any],
        offending: dict[str, Any] | None,
        recommended: dict[str, Any] | None,
        deployment: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Write the brief from the correlator's own verdict, never from a guess.

        Every branch keys on ``verdict``, the field the board itself shows. A named
        commit is described as a temporal candidate with the correlator's measured
        held-out precision. Nothing here says a rollback is staged: on this board Stage
        and Confirm are record-only, and nothing is staged until a viewer presses Stage.
        """
        m_name = metric.get("name", "ErrorCount")
        baseline = metric.get("baseline", 0.0)
        current = metric.get("current", 0.0)
        factor = metric.get("anomaly_factor", 1.0)
        accuracy = attribution.get("measured_accuracy") or {}
        precision = accuracy.get("precision_when_it_names_a_commit")
        precision_clause = (
            f" When Mercury names a commit, it was the cause in {round(float(precision) * 100)} percent "
            "of cases on a synthetic held-out split."
            if isinstance(precision, (int, float)) else ""
        )
        causality = attribution.get("causality_statement") or (
            "Temporal proximity does not prove it caused the anomaly."
        )

        if verdict == "INSUFFICIENT_DATA":
            severity = "INSUFFICIENT_DATA"
            stmt = attribution.get("refusal_statement") or (
                f"Mercury has no readings of {m_name} for {service}."
            )
            brief = (
                f"{service} has no readings of {m_name}, so there is nothing to explain. "
                "Mercury refuses to guess: this is missing data, not a finding about any deploy."
            )
            hypothesis = stmt
            draft = {
                "current_action": f"No action on {service}: there are no readings to act on.",
                "confirmed_facts": [stmt],
                "next_step": f"Connect a real metric source for {service} before asking again.",
            }
        elif verdict == "ANOMALY_ATTRIBUTED" and recommended and offending:
            severity = "SEV-1_ROLLBACK_READY"
            sha = str(offending.get("sha", ""))[:7]
            target_sha = str(recommended.get("target_commit_sha", ""))[:7]
            brief = (
                f"{service} {m_name} rose {factor}x ({baseline} to {current}), and {sha} is the "
                f"only runtime commit in the window: a temporal candidate, not proof of cause."
                f"{precision_clause}"
            )
            hypothesis = (
                f"Commit {sha} ('{offending.get('message', '')}') is the sole runtime candidate "
                f"before the onset. {causality}"
            )
            draft = {
                "current_action": (
                    f"Decide whether to stage a record-only rollback of {service} from {sha} "
                    f"to {target_sha}. Stage has not been pressed."
                ),
                "confirmed_facts": [
                    f"{m_name} rose from baseline {baseline} to {current} ({factor}x).",
                    f"The sole runtime candidate commit in the window is {sha}.",
                ],
                "next_step": (
                    "Check the candidate's diff against the symptom before pressing Stage; "
                    "Confirm records the decision and contacts no pipeline."
                ),
            }
        elif verdict == "ANOMALY_ATTRIBUTED" and offending:
            # A candidate is named, but no authenticated marker pair proves a target,
            # so there is nothing to roll back to. Reachable on non-fixture data.
            severity = "SEV-2_NO_ROLLBACK_TARGET"
            sha = str(offending.get("sha", ""))[:7]
            blocked = (deployment or {}).get("blocked_reason") or (
                "No verified rollback target is recorded for this candidate."
            )
            brief = (
                f"{service} {m_name} rose {factor}x ({baseline} to {current}), and {sha} is the "
                f"only runtime commit in the window: a temporal candidate, not proof of cause."
                f"{precision_clause} No rollback target is verified, so Stage stays locked."
            )
            hypothesis = (
                f"Commit {sha} ('{offending.get('message', '')}') is the sole runtime candidate "
                f"before the onset. {causality} {blocked}"
            )
            draft = {
                "current_action": f"Investigate {service}; the candidate is {sha} and no rollback target is verified.",
                "confirmed_facts": [
                    f"{m_name} rose from baseline {baseline} to {current} ({factor}x).",
                    f"The sole runtime candidate commit in the window is {sha}.",
                    blocked,
                ],
                "next_step": (
                    "Record an authenticated deployment marker and health readback for the healthy "
                    "revision before any rollback can be staged."
                ),
            }
        elif verdict == "NO_ANOMALY" or attribution.get("nothing_to_revert"):
            severity = "NOMINAL_NO_ANOMALY"
            brief = (
                f"{service} {m_name} reads {current} against a baseline of {baseline} ({factor}x), "
                "under the anomaly threshold. Nothing to revert."
            )
            hypothesis = "The reading does not cross the anomaly threshold, so no commit was evaluated."
            draft = {
                "current_action": f"Monitor {service}; no active incident.",
                "confirmed_facts": [
                    f"{m_name} reading {current} is under the anomaly threshold (baseline {baseline})."
                ],
                "next_step": "Continue standard wallboard observation.",
            }
        else:
            severity = "SEV-2_ATTRIBUTION_REFUSED"
            refusal = attribution.get("refusal_reason") or verdict
            stmt = attribution.get("refusal_statement") or "Attribution refused by correlator."
            brief = (
                f"{service} {m_name} rose {factor}x ({baseline} to {current}), but Mercury refused "
                f"to name a commit ({refusal}). Rollback staging stays locked."
            )
            hypothesis = f"{stmt} Commits in window: {attribution.get('commits_in_window', 0)}."
            draft = {
                "current_action": f"Investigate {service} by hand; Mercury refused to name a commit ({refusal}).",
                "confirmed_facts": [
                    f"{m_name} rose {factor}x ({baseline} to {current}).",
                    str(attribution.get("handoff_fact") or stmt),
                ],
                "next_step": (
                    "Inspect service logs and recent config or dependency changes before any manual mitigation."
                ),
            }

        return {
            "synthesis_mode": "deterministic",
            "model_answered": None,
            # No model wrote this brief, so it names none. agent_status reports the
            # capability; a model brief overwrites both fields.
            "model_id": None,
            "region": None,
            "cached": False,
            "model_call_attempted": False,
            "model_fields": [],
            "template_fields": list(BRIEF_FIELDS),
            "incident_severity": severity,
            "commander_brief_10ft": brief,
            "root_cause_hypothesis": hypothesis,
            "responder_handoff_draft": draft,
            "guardrail_attestation": (
                "Agent synthesis is advisory; temporal correlation refusal rules, authenticated "
                "DeploymentMarker verification, and single-use SHA-256 governance tokens remain authoritative."
            ),
        }
