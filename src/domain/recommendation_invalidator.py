"""
Dynamic Recommendation Invalidator with Live Telemetry TTL Contracts.
Automatically withdraws incident remediation advice when underlying telemetry self-resolves.
"""

from typing import Dict, Any, List, Optional
import time
from dataclasses import dataclass, field

@dataclass
class EvidenceContract:
    metric_name: str
    safe_threshold: float
    comparison: str  # 'less_than', 'greater_than'
    ttl_seconds: float = 60.0

class DynamicRecommendationEngine:
    """
    Evaluates recommendation freshness against real-time CloudWatch EMF telemetry.
    If system returns to normal envelope, the recommendation is automatically retracted.
    """
    def __init__(self):
        self._recommendations: Dict[str, Dict[str, Any]] = {}

    def register_recommendation(
        self,
        rec_id: str,
        action: str,
        evidence: EvidenceContract
    ) -> None:
        self._recommendations[rec_id] = {
            "action": action,
            "evidence": evidence,
            "created_at": time.time(),
            "status": "ACTIVE"
        }

    def evaluate_liveness(self, rec_id: str, current_metric_value: float) -> Dict[str, Any]:
        if rec_id not in self._recommendations:
            return {"status": "UNKNOWN_RECOMMENDATION"}

        rec = self._recommendations[rec_id]
        evidence: EvidenceContract = rec["evidence"]

        # Check self-resolution
        is_safe = False
        if evidence.comparison == "less_than":
            is_safe = current_metric_value < evidence.safe_threshold
        elif evidence.comparison == "greater_than":
            is_safe = current_metric_value > evidence.safe_threshold

        if is_safe:
            rec["status"] = "WITHDRAWN"
            return {
                "recommendation_id": rec_id,
                "status": "WITHDRAWN",
                "action": rec["action"],
                "reason": f"Telemetry self-resolved: {evidence.metric_name} reached safe level ({current_metric_value}).",
                "withdrawn_at": time.time()
            }

        return {
            "recommendation_id": rec_id,
            "status": "ACTIVE",
            "action": rec["action"],
            "current_metric_value": current_metric_value
        }
