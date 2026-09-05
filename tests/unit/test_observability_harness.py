"""
Unit tests for Private Observability Harness in mercury_amazon.
Verifies CloudWatch EMF formatting, PII sanitization, and zero-leak compliance.
"""

import json

from src.infrastructure.observability_harness import PrivateObservabilityHarness


def test_harness_initialization_and_emf_structure():
    harness = PrivateObservabilityHarness(request_id="test-req-123")
    harness.record_metric("DORALeadTimeHours", 42.5)
    
    payload = harness.build_emf_payload()
    assert payload["RequestId"] == "test-req-123"
    assert "DORALeadTimeHours" in payload
    assert payload["DORALeadTimeHours"] == 42.5
    assert "_aws" in payload
    assert payload["_aws"]["CloudWatchMetrics"][0]["Namespace"] == "Mercury/DevOpsCockpit"

def test_pii_sanitization():
    harness = PrivateObservabilityHarness()
    raw_text = "User test@example.com executed action with secret token 1234"
    masked = harness.mask_pii(raw_text)
    assert "test@example.com" not in masked
    assert "[REDACTED_PII]" in masked

def test_audit_event_logging():
    harness = PrivateObservabilityHarness()
    harness.add_audit_event("user@domain.com", "EXECUTE_ACTION", {"target": "resource-1", "email": "admin@domain.com"})
    harness.record_metric("ChangeFailureRatePercent", 1.0, "Count")
    
    output = harness.flush()
    parsed = json.loads(output)
    assert len(parsed["AuditEvents"]) == 1
    assert parsed["AuditEvents"][0]["action"] == "EXECUTE_ACTION"
    assert parsed["AuditEvents"][0]["actor"] == "[REDACTED_PII]"
