"""Unit tests for Mercury DevOps Ingestion."""
import pytest
from src.infrastructure.cloudwatch_github_ingest import DevOpsTelemetryIngestAdapter


def test_github_webhook_ingest():
    evt = DevOpsTelemetryIngestAdapter.ingest_github_webhook("upgradedev/volcan_amazon", "ci.yml", "success")
    assert evt.source == "GitHub_Actions"
    assert evt.status == "SUCCESS"
    assert "volcan_amazon" in evt.summary
