"""A staged recommendation's bounded validity, based on operator-supplied data.

This module does not fetch CloudWatch. Recovery and TTL expiry are terminal
for a registration; only explicitly staging again creates a fresh registration.
"""
import math
import time
from dataclasses import dataclass
from typing import Any, Dict


@dataclass
class EvidenceContract:
    metric_name: str
    safe_threshold: float
    comparison: str
    ttl_seconds: float = 60.0


class DynamicRecommendationEngine:
    def __init__(self):
        self._recommendations: Dict[str, Dict[str, Any]] = {}

    def register_recommendation(self, rec_id: str, action: str, evidence: EvidenceContract) -> None:
        if evidence.comparison not in {"less_than", "greater_than"}:
            raise ValueError("Unsupported evidence comparison.")
        if not math.isfinite(evidence.safe_threshold) or not math.isfinite(evidence.ttl_seconds) or evidence.ttl_seconds <= 0:
            raise ValueError("Evidence threshold and positive TTL must be finite.")
        self._recommendations[rec_id] = {
            "action": action, "evidence": evidence, "created_at": time.time(), "status": "ACTIVE",
        }

    def status(self, rec_id: str) -> Dict[str, Any]:
        rec = self._recommendations.get(rec_id)
        if rec is None:
            return {"recommendation_id": rec_id, "status": "UNKNOWN_RECOMMENDATION"}
        evidence = rec["evidence"]
        if rec["status"] == "ACTIVE" and time.time() >= rec["created_at"] + evidence.ttl_seconds:
            rec["status"] = "STALE"
            rec["reason"] = "The recommendation evidence lease expired; stage and review again."
        result = {
            "recommendation_id": rec_id, "status": rec["status"], "action": rec["action"],
            "source": "OPERATOR_SUPPLIED_METRIC_NO_LIVE_REFRESH",
        }
        for key in ("reason", "withdrawn_at", "current_metric_value"):
            if key in rec:
                result[key] = rec[key]
        return result

    def evaluate_liveness(self, rec_id: str, current_metric_value: float) -> Dict[str, Any]:
        if not math.isfinite(current_metric_value):
            raise ValueError("Metric value must be finite.")
        current = self.status(rec_id)
        if current["status"] != "ACTIVE":
            return current
        rec = self._recommendations[rec_id]
        evidence: EvidenceContract = rec["evidence"]
        is_safe = (
            current_metric_value < evidence.safe_threshold
            if evidence.comparison == "less_than"
            else current_metric_value > evidence.safe_threshold
        )
        rec["current_metric_value"] = current_metric_value
        if is_safe:
            rec["status"] = "WITHDRAWN"
            rec["reason"] = (
                f"Telemetry self-resolved according to the operator-supplied reading: "
                f"{evidence.metric_name} reached safe level ({current_metric_value})."
            )
            rec["withdrawn_at"] = time.time()
        return self.status(rec_id)
