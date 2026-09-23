"""
Private Observability Harness for Mercury (AWS Serverless eu-west-1).
Emits structured JSON logs adhering to AWS CloudWatch Embedded Metric Format (EMF).
Guarantees $0.00 idle cost, zero 3rd-party telemetry leaks, and client-side PII masking.
"""

import json
import logging
import re
import time
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger("mercury-10foot-warroom")
logger.setLevel(logging.INFO)

class PrivateObservabilityHarness:
    """
    Zero-dependency, privacy-first telemetry harness.
    Outputs CloudWatch EMF compliant metrics directly to stdout.
    """

    NAMESPACE = "Mercury/DevOpsCockpit"
    SERVICE_NAME = "mercury-10foot-warroom"

    PII_REGEXES = [
        re.compile(r"[\w\.-]+@[\w\.-]+", re.IGNORECASE),
        re.compile(r"ghp_[a-zA-Z0-9]{36}", re.IGNORECASE),
        re.compile(r"AWS_SECRET_ACCESS_KEY=[^\s]+", re.IGNORECASE)
    ]

    def __init__(self, request_id: Optional[str] = None):
        self.request_id = request_id or str(uuid.uuid4())
        self.start_time = time.perf_counter()
        self.metrics: Dict[str, float] = {}
        self.dimensions: Dict[str, str] = {
            "ServiceName": self.SERVICE_NAME,
            "Environment": "production-eu-west-1"
        }
        self.audit_events: List[Dict[str, Any]] = []

    def mask_pii(self, text: str) -> str:
        """Sanitizes sensitive user information before telemetry emission."""
        if not isinstance(text, str):
            text = str(text)
        sanitized = text
        for rx in self.PII_REGEXES:
            sanitized = rx.sub("[REDACTED_PII]", sanitized)
        return sanitized

    def record_metric(self, metric_name: str, value: float, unit: str = "Milliseconds") -> "PrivateObservabilityHarness":
        """Records a custom metric value."""
        self.metrics[metric_name] = float(value)
        return self

    def add_audit_event(self, actor: str, action: str, details: Dict[str, Any]) -> "PrivateObservabilityHarness":
        """Logs a private compliance/security audit record with PII masking."""
        safe_details = {k: self.mask_pii(str(v)) for k, v in details.items()}
        self.audit_events.append({
            "timestamp": time.time(),
            "actor": self.mask_pii(actor),
            "action": action,
            "details": safe_details
        })
        return self

    def build_emf_payload(self) -> Dict[str, Any]:
        """Constructs an AWS CloudWatch Embedded Metric Format (EMF) compliant JSON object."""
        elapsed_ms = (time.perf_counter() - self.start_time) * 1000.0
        
        emf = {
            "_aws": {
                "Timestamp": int(time.time() * 1000),
                "CloudWatchMetrics": [
                    {
                        "Namespace": self.NAMESPACE,
                        "Dimensions": [list(self.dimensions.keys())],
                        "Metrics": [{ "Name": k, "Unit": "Milliseconds" if "Ms" in k or "Duration" in k or "Latency" in k else "Count" } for k in self.metrics.keys()]
                    }
                ]
            },
            "RequestId": self.request_id,
            "TotalExecutionLatencyMs": round(elapsed_ms, 2),
            **self.dimensions,
            **self.metrics,
            "AuditEvents": self.audit_events
        }
        return emf

    def flush(self) -> str:
        """Serializes and logs the EMF payload to stdout for CloudWatch ingestion."""
        payload = self.build_emf_payload()
        serialized = json.dumps(payload)
        logger.info(serialized)
        return serialized
