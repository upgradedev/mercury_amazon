"""Unit tests for the GitHub REST telemetry adapter.

Drives the adapter through ``httpx.MockTransport``, so the real request building,
paging, header and JSON handling all execute; only the socket is replaced. Also
covers the fallback path and asserts the fallback is labelled as such.
"""
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from src.domain.provenance import DataSource
from src.infrastructure.github_adapter import FIXTURE_PATH, GitHubTelemetryAdapter

REPO = "acme/widgets"


def _iso(minutes_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def make_client(routes: dict[str, object], recorder: list | None = None) -> httpx.Client:
    """Build a client whose transport answers from ``routes`` keyed by path."""

    def handler(request: httpx.Request) -> httpx.Response:
        if recorder is not None:
            recorder.append(request)
        payload = routes.get(request.url.path)
        if payload is None:
            return httpx.Response(404, json={"message": "Not Found"})
        if callable(payload):
            return payload(request)
        return httpx.Response(200, json=payload)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_computation_is_pure_and_matches_the_documented_definitions():
    runs = [
        {"status": "completed", "conclusion": "success", "created_at": _iso(600)},
        {"status": "completed", "conclusion": "failure", "created_at": _iso(500)},
        {"status": "completed", "conclusion": "success", "created_at": _iso(440)},
        {"status": "in_progress", "conclusion": None, "created_at": _iso(10)},
    ]
    prs = [
        {"created_at": _iso(1000), "merged_at": _iso(880)},   # 2 hours
        {"created_at": _iso(1000), "merged_at": _iso(760)},   # 4 hours
    ]
    metrics, sample = GitHubTelemetryAdapter.compute_dora_from_runs_and_prs(runs, prs, window_days=30)

    assert metrics["deployment_frequency_per_day"] == pytest.approx(2 / 30, abs=1e-3)
    assert metrics["change_failure_rate_percentage"] == pytest.approx(100 / 3, abs=0.01)
    assert metrics["lead_time_for_changes_hours"] == pytest.approx(3.0, abs=0.05)
    assert metrics["mean_time_to_recovery_hours"] == pytest.approx(1.0, abs=0.05)
    assert sample == 5  # three completed runs plus two merged pull requests


def test_in_progress_runs_are_excluded_from_the_failure_rate():
    runs = [{"status": "in_progress", "conclusion": None, "created_at": _iso(5)}]
    metrics, sample = GitHubTelemetryAdapter.compute_dora_from_runs_and_prs(runs, [], 30)
    assert metrics["change_failure_rate_percentage"] == 0.0
    assert sample == 0


def test_a_failure_with_no_following_success_yields_no_recovery_time():
    runs = [
        {"status": "completed", "conclusion": "success", "created_at": _iso(500)},
        {"status": "completed", "conclusion": "failure", "created_at": _iso(100)},
    ]
    metrics, _ = GitHubTelemetryAdapter.compute_dora_from_runs_and_prs(runs, [], 30)
    assert metrics["mean_time_to_recovery_hours"] == 0.0


def test_live_call_produces_a_live_provenance_stamp():
    routes = {
        f"/repos/{REPO}": {"default_branch": "main"},
        f"/repos/{REPO}/actions/runs": {
            "workflow_runs": [
                {"status": "completed", "conclusion": "success", "created_at": _iso(60)},
                {"status": "completed", "conclusion": "success", "created_at": _iso(120)},
            ]
        },
        f"/repos/{REPO}/pulls": [
            {"created_at": _iso(300), "merged_at": _iso(180), "updated_at": _iso(180)},
        ],
    }
    recorder: list[httpx.Request] = []
    adapter = GitHubTelemetryAdapter(token="ghp_test", repository=REPO, client=make_client(routes, recorder))
    report = adapter.get_metrics_raw()

    assert report.provenance.source is DataSource.GITHUB_API
    assert report.provenance.is_live is True
    assert report.provenance.display_label == "LIVE"
    assert REPO in report.provenance.detail
    assert report.sample_size == 3
    assert report.deployment_frequency_per_day == pytest.approx(2 / 30, abs=1e-3)
    # The Authorization header must actually be sent.
    assert recorder[0].headers["Authorization"] == "Bearer ghp_test"


def test_repository_with_no_workflow_runs_says_so_rather_than_estimating():
    routes = {
        f"/repos/{REPO}": {"default_branch": "main"},
        f"/repos/{REPO}/actions/runs": {"workflow_runs": []},
        f"/repos/{REPO}/pulls": [],
    }
    adapter = GitHubTelemetryAdapter(token="ghp_test", repository=REPO, client=make_client(routes))
    report = adapter.get_metrics_raw()
    assert report.deployment_frequency_per_day == 0.0
    assert "no workflow runs in the window" in report.provenance.detail
    assert "rather than estimated" in report.provenance.detail


def test_http_failure_falls_back_to_the_fixture_and_names_the_error():
    def boom(request):
        return httpx.Response(500, json={"message": "server error"})

    adapter = GitHubTelemetryAdapter(
        token="ghp_test", repository=REPO,
        client=make_client({f"/repos/{REPO}": boom}),
    )
    report = adapter.get_metrics_raw()
    assert report.provenance.source is DataSource.OFFLINE_FIXTURE
    assert report.provenance.is_live is False
    assert report.provenance.display_label == "OFFLINE FIXTURE"
    assert "Live GitHub call failed" in report.provenance.detail


def test_no_token_serves_the_fixture_without_calling_out():
    adapter = GitHubTelemetryAdapter(token="", repository=REPO)
    assert adapter.can_call_live is False
    report = adapter.get_metrics_raw()
    assert report.provenance.source is DataSource.OFFLINE_FIXTURE
    assert "GITHUB_TOKEN is not set" in report.provenance.detail


def test_pr_radar_only_reports_pull_requests_past_the_sla():
    routes = {
        f"/repos/{REPO}/pulls": [
            {"number": 1, "title": "fresh", "created_at": _iso(60), "user": {"login": "a"}},
            {"number": 2, "title": "stale", "created_at": _iso(60 * 50), "user": {"login": "b"}},
        ]
    }
    adapter = GitHubTelemetryAdapter(token="ghp_test", repository=REPO, client=make_client(routes))
    radar = adapter.get_pr_radar()

    assert radar.total_open_prs == 2
    assert len(radar.stale_prs_over_36h) == 1
    assert radar.stale_prs_over_36h[0].pr_id == 2
    assert radar.stale_prs_over_36h[0].is_stale is True
    assert radar.provenance.is_live is True


def test_recent_commits_are_empty_rather_than_invented_without_a_token():
    adapter = GitHubTelemetryAdapter(token="", repository=REPO)
    assert adapter.list_recent_commits() == []


def test_recent_commits_are_flattened_from_the_api_shape():
    routes = {
        f"/repos/{REPO}": {"default_branch": "main"},
        f"/repos/{REPO}/commits": [
            {
                "sha": "abcdef1234567890",
                "commit": {
                    "message": "Fix the thing\n\nlonger body",
                    "author": {"name": "Dana", "date": _iso(15)},
                },
            }
        ],
    }
    adapter = GitHubTelemetryAdapter(token="ghp_test", repository=REPO, client=make_client(routes))
    commits = adapter.list_recent_commits(limit=5)
    assert commits[0]["sha"] == "abcdef1"
    assert commits[0]["message"] == "Fix the thing"
    assert commits[0]["author"] == "Dana"


def test_the_committed_fixture_declares_where_it_came_from():
    """The fixture must be a recording with provenance, not hand-written numbers."""
    with open(FIXTURE_PATH, "r", encoding="utf-8") as handle:
        fixture = json.load(handle)

    assert fixture["recorded_from_repository"]
    assert fixture["recorded_at_utc"]
    assert fixture["recorded_by_command"].startswith("python scripts/record_github_fixture.py")
    assert set(fixture["dora"]) >= {
        "deployment_frequency_per_day", "lead_time_for_changes_hours",
        "change_failure_rate_percentage", "mean_time_to_recovery_hours",
        "sample_size", "window_days",
    }
def test_recent_commits_carry_their_file_lists_from_a_per_commit_read():
    routes = {
        f"/repos/{REPO}": {"default_branch": "main"},
        f"/repos/{REPO}/commits": [
            {"sha": "aaa111", "commit": {"message": "ship it", "author": {"name": "D", "date": _iso(15)}}},
            {"sha": "bbb222", "commit": {"message": "docs", "author": {"name": "D", "date": _iso(25)}}},
        ],
        f"/repos/{REPO}/commits/aaa111": {"files": [{"filename": "src/app.py"}, {"filename": "README.md"}]},
        f"/repos/{REPO}/commits/bbb222": {"files": [{"filename": "README.md"}]},
    }
    adapter = GitHubTelemetryAdapter(token="ghp_test", repository=REPO, client=make_client(routes))
    commits = adapter.list_recent_commits(limit=5)
    assert commits[0]["paths"] == ["src/app.py", "README.md"]
    assert commits[1]["paths"] == ["README.md"]


def test_a_failed_per_commit_read_leaves_the_file_list_unknown():
    """A commit whose files cannot be read stays a candidate: missing data
    never sets a change aside."""
    routes = {
        f"/repos/{REPO}": {"default_branch": "main"},
        f"/repos/{REPO}/commits": [
            {"sha": "aaa111", "commit": {"message": "ship it", "author": {"name": "D", "date": _iso(15)}}},
        ],
    }
    adapter = GitHubTelemetryAdapter(token="ghp_test", repository=REPO, client=make_client(routes))
    assert adapter.list_recent_commits(limit=5)[0]["paths"] is None


def test_a_capped_file_list_stays_unknown():
    """The single-commit endpoint caps its file list; a full page may hide a
    runtime file, so it is unknown, not a clean bill."""
    routes = {
        f"/repos/{REPO}": {"default_branch": "main"},
        f"/repos/{REPO}/commits": [
            {"sha": "aaa111", "commit": {"message": "mega merge", "author": {"name": "D", "date": _iso(15)}}},
        ],
        f"/repos/{REPO}/commits/aaa111": {"files": [{"filename": f"f{i}.txt"} for i in range(300)]},
    }
    adapter = GitHubTelemetryAdapter(token="ghp_test", repository=REPO, client=make_client(routes))
    assert adapter.list_recent_commits(limit=5)[0]["paths"] is None
