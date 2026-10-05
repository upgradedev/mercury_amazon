"""The display-only deploy feed the public board falls back to.

The public Lambda has no git checkout and no GitHub token. It used to quote the
trial's own commit recording, so the board read one of this repository's commit
messages as the deploy behind a checkout-api spike. It now serves an invented,
labelled deploy feed, and these tests pin three things: every demo row still reaches
its verdict on it, the board names the feed's stand-in deploy, and nothing that
feeds a published figure reads it.
"""
import json
from pathlib import Path

import pytest

from src.application.diagnose_incident_use_case import DiagnoseIncidentUseCase
from src.domain.change_scope import MERCURY_SERVICE_SCOPE
from src.domain.deployment_evidence import DeploymentEvidenceLedger
from src.domain.incident_correlation import (
    AttributionRefusal,
    CorrelationVerdict,
    IncidentCorrelator,
)
from src.domain.provenance import DataSource
from src.infrastructure.cloudwatch_adapter import CloudWatchMetricAdapter
from src.infrastructure.demo_evidence import recorded_demo_handoff, seed_recorded_demo_evidence
from src.infrastructure.deploy_feed_fixture import DEFAULT_FEED, DeployFeedFixtureProvider

REPO_ROOT = Path(__file__).resolve().parents[2]
FEED = json.loads(DEFAULT_FEED.read_text(encoding="utf-8"))


class Nothing:
    """GitHub without a token, or a Lambda zip without .git."""

    def list_recent_commits(self, limit=10):
        return []


@pytest.fixture
def lambda_use_case(monkeypatch):
    """The server's wiring as the public Lambda runs it."""
    monkeypatch.setenv("MERCURY_OFFLINE", "1")
    adapter = CloudWatchMetricAdapter()
    adapter._resolve_client = lambda: None
    return DiagnoseIncidentUseCase(
        adapter, Nothing(), Nothing(), DeployFeedFixtureProvider(),
        correlator=IncidentCorrelator(service_scope=MERCURY_SERVICE_SCOPE),
    )


def test_the_feed_says_it_is_invented_and_display_only():
    note = FEED["note"]
    assert note.startswith("DISPLAY-ONLY STAND-IN, INVENTED.")
    assert "not commits from this or any repository" in note
    assert "OFFLINE FIXTURE" in note
    assert "commit_stream_fixture.json, which this file does not change" in note
    detail = DeployFeedFixtureProvider().detail
    assert "written by hand" in detail and "not used by any published figure" in detail


def test_the_server_falls_back_to_the_feed_not_to_the_trial_recording():
    from src.interfaces import mcp_server

    assert isinstance(mcp_server.recorded_commit_provider, DeployFeedFixtureProvider)


def test_no_stand_in_deploy_reuses_a_real_recorded_commit():
    """An invented record must never be mistaken for one of the trial's real commits."""
    recorded = json.loads(
        (REPO_ROOT / "src/infrastructure/fixtures/commit_stream_fixture.json").read_text(encoding="utf-8"))
    real = {commit["sha"] for commit in recorded["commits"]}
    stand_ins = {deploy["sha"] for deploy in FEED["deploys"]}
    assert not stand_ins & real


def test_nothing_that_produces_a_published_figure_reads_the_feed():
    for script in sorted((REPO_ROOT / "scripts").glob("*.py")):
        if script.name == "build_lambda_package.py":
            continue  # it ships the file; it computes nothing from it
        assert "deploy_feed_fixture" not in script.read_text(encoding="utf-8"), script.name


@pytest.mark.parametrize("service, verdict, refusal", [
    ("checkout-api", CorrelationVerdict.ANOMALY_ATTRIBUTED, None),
    ("payments-worker", CorrelationVerdict.NO_ANOMALY, None),
    ("search-indexer", CorrelationVerdict.ANOMALY_WITHOUT_ATTRIBUTION,
     AttributionRefusal.NO_CANDIDATE_IN_WINDOW),
    ("release-train", CorrelationVerdict.ANOMALY_WITHOUT_ATTRIBUTION,
     AttributionRefusal.WINDOW_TOO_CROWDED),
    ("quiet-service", CorrelationVerdict.INSUFFICIENT_DATA, None),
])
def test_every_demo_row_reaches_its_verdict_on_the_feed(lambda_use_case, service, verdict, refusal):
    answer = lambda_use_case.execute(service, 60)
    assert answer.verdict is verdict
    assert answer.attribution_refusal is refusal
    assert answer.commit_provenance.source is DataSource.OFFLINE_FIXTURE
    assert "written by hand" in answer.commit_provenance.detail


def test_the_board_names_the_stand_in_deploy_and_offers_the_one_before_it(lambda_use_case):
    answer = lambda_use_case.execute("checkout-api", 60)
    lone, previous = FEED["deploys"][0], FEED["deploys"][1]
    assert answer.offending_commit.sha == lone["sha"]
    assert answer.offending_commit.message == lone["message"]
    assert answer.offending_commit.author == lone["author"]
    assert answer.rollback_target.sha == previous["sha"]
    crowded = lambda_use_case.execute("release-train", 60)
    assert crowded.commits_in_window == 5


def test_the_demo_handoff_on_the_feed_speaks_candidate_not_cause(lambda_use_case):
    ledger = DeploymentEvidenceLedger()
    seed_recorded_demo_evidence(lambda_use_case, ledger)
    handoff = recorded_demo_handoff(lambda_use_case, ledger)
    assert handoff is not None, "the feed no longer gives the demo a rollback pair"
    lone = FEED["deploys"][0]
    assert handoff["confirmed_facts"][1].startswith(
        f"Temporal candidate, not proof of cause: commit {lone['sha']} by {lone['author']}")
    assert not any("ANOMALY_ATTRIBUTED" in fact for fact in handoff["confirmed_facts"])
