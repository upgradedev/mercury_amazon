"""Multi-Source DevOps Event Ingestion Adapter for Mercury War Room Cockpit."""
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from typing import Any, Dict


@dataclass
class DevOpsTelemetryEvent:
    event_id: str
    source: str        # "GitHub_Actions", "AWS_CloudWatch", "Datadog"
    status: str        # "SUCCESS", "FAILURE", "INCIDENT_CRITICAL"
    summary: str
    timestamp: str


class DevOpsTelemetryIngestAdapter:
    """Aggregates CI/CD and CloudWatch alarms for 10-foot Fire TV display."""

    @classmethod
    def ingest_github_webhook(cls, repo_name: str, workflow_name: str, conclusion: str) -> DevOpsTelemetryEvent:
        e_id = f"devops_{hashlib.md5(f'{repo_name}:{workflow_name}'.encode()).hexdigest()[:8]}"
        status = "SUCCESS" if conclusion == "success" else "FAILURE"
        summary = f"Workflow '{workflow_name}' on '{repo_name}' ended with status: {conclusion.upper()}"

        return DevOpsTelemetryEvent(
            event_id=e_id,
            source="GitHub_Actions",
            status=status,
            summary=summary,
            timestamp=datetime.now(timezone.utc).isoformat()
        )
