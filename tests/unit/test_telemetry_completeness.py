"""
Unit tests for TelemetryAbsenceDetector (Mercury).
"""

from src.domain.telemetry_completeness import TelemetryAbsenceDetector


def test_telemetry_detector_flags_missing_emf_logs_and_p95():
    detector = TelemetryAbsenceDetector()
    received = {"error_rate", "throttling_count", "memory_utilization"}
    
    report = detector.audit_service_observability("OrderProcessingLambda", received)
    assert report.is_fully_observable is False
    assert "emf_logs" in report.missing_signals
    assert "p95_latency" in report.missing_signals
    assert report.observability_gap_score == 0.40
