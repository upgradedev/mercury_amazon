"""
Telemetry Absence Detector for Mercury (CE Pattern).
Flags missing log streams, absent health metrics, and unobserved dependencies during incidents.
"""

from dataclasses import dataclass
from typing import List, Set


@dataclass
class TelemetryCoverageReport:
    service_name: str
    expected_signals: Set[str]
    received_signals: Set[str]
    missing_signals: List[str]
    is_fully_observable: bool
    observability_gap_score: float  # 0.0 (perfect) to 1.0 (blind)

class TelemetryAbsenceDetector:
    """
    Detects unmonitored blindspots during cloud production incidents.
    """
    
    STANDARD_SIGNALS = {"p95_latency", "error_rate", "throttling_count", "memory_utilization", "emf_logs"}

    def audit_service_observability(self, service_name: str, received_signals: Set[str]) -> TelemetryCoverageReport:
        missing = sorted(list(self.STANDARD_SIGNALS - received_signals))
        gap_score = len(missing) / len(self.STANDARD_SIGNALS)
        
        return TelemetryCoverageReport(
            service_name=service_name,
            expected_signals=self.STANDARD_SIGNALS,
            received_signals=received_signals,
            missing_signals=missing,
            is_fully_observable=len(missing) == 0,
            observability_gap_score=gap_score
        )
