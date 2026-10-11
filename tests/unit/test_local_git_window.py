"""New commits must not move the local demo's verdicts.

CI run 37579019212 failed six tests on a branch that changed only footage and
receipts: ``git log -20`` at HEAD filled with commits the runtime filter sets aside,
the burst behind ``release-train`` left the window, and the crowded refusal turned
into an attribution. The server now serves a recorded window pinned at one merge
(``src/infrastructure/local_git_window.py``). These tests stack new commits on a
checkout and show the verdicts stay where the README's table puts them.
"""
from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

import pytest

from src.application.diagnose_incident_use_case import DiagnoseIncidentUseCase
from src.domain.change_scope import MERCURY_SERVICE_SCOPE
from src.domain.incident_correlation import IncidentCorrelator
from src.infrastructure.cloudwatch_adapter import CloudWatchMetricAdapter
from src.infrastructure.deploy_feed_fixture import DeployFeedFixtureProvider
from src.infrastructure.local_git_adapter import LocalGitCommitProvider
from src.infrastructure.local_git_window import PinnedGitWindowProvider

#: The README's demo table (README.md "Five verdicts"), service by service.
README_TABLE = {
    "checkout-api": ("ANOMALY_ATTRIBUTED", None),
    "release-train": ("ANOMALY_WITHOUT_ATTRIBUTION", "WINDOW_TOO_CROWDED"),
    "search-indexer": ("ANOMALY_WITHOUT_ATTRIBUTION", "NO_CANDIDATE_IN_WINDOW"),
    "payments-worker": ("NO_ANOMALY", None),
    "quiet-service": ("INSUFFICIENT_DATA", None),
}


class _NoGitHub:
    def list_recent_commits(self, limit: int = 20):
        return []


def _verdicts(local_provider) -> dict[str, tuple[str, str | None]]:
    use_case = DiagnoseIncidentUseCase(
        CloudWatchMetricAdapter(), _NoGitHub(), local_provider, DeployFeedFixtureProvider(),
        correlator=IncidentCorrelator(service_scope=MERCURY_SERVICE_SCOPE),
    )
    found = {}
    for service in README_TABLE:
        result = use_case.execute(service, 60)
        refusal = result.attribution_refusal
        found[service] = (result.verdict.value, getattr(refusal, "value", refusal))
    return found


def _stack_lone_runtime_commits(root, count: int) -> None:
    """A checkout whose newest commits each touch src/ and sit two hours apart.

    That is the shape that broke CI: plenty of commits, none with company in its
    75 minute window, so an unpinned demo has no crowded window to refuse.
    """
    git = ["git", "-c", "user.name=Mercury Test", "-c", "user.email=test@example.invalid",
           "-c", "commit.gpgsign=false", "-c", "init.defaultBranch=main"]
    subprocess.run([*git, "init", "-q", str(root)], check=True, capture_output=True)
    start = datetime(2026, 10, 20, 0, 0, tzinfo=timezone.utc)
    for index in range(count):
        target = root / "src" / f"module_{index}.py"
        target.parent.mkdir(exist_ok=True)
        target.write_text(f"VALUE = {index}\n", encoding="utf-8")
        stamp = (start + timedelta(hours=2 * index)).isoformat()
        env = {**os.environ, "GIT_AUTHOR_DATE": stamp, "GIT_COMMITTER_DATE": stamp}
        subprocess.run([*git, "add", "-A"], cwd=root, check=True, capture_output=True)
        subprocess.run([*git, "commit", "-q", "-m", f"Change module {index}"], cwd=root,
                       env=env, check=True, capture_output=True)


def test_new_commits_cannot_change_the_release_train_verdict(tmp_path):
    _stack_lone_runtime_commits(tmp_path, 25)
    assert MERCURY_SERVICE_SCOPE.touches(("src/module_0.py",)) is True

    # Control: reading git log at HEAD of that checkout reproduces the CI failure,
    # so the stacked commits really are the shape that flips the verdict.
    unpinned = _verdicts(LocalGitCommitProvider(repo_root=tmp_path))
    assert unpinned["release-train"] == ("ANOMALY_ATTRIBUTED", None)

    # The pinned window ignores whatever HEAD holds and keeps all five rows.
    pinned = PinnedGitWindowProvider(repo_root=tmp_path)
    assert pinned.is_available
    assert _verdicts(pinned) == README_TABLE

    # And the server is wired to the pinned window, not to git log at HEAD.
    from src.interfaces import mcp_server
    assert isinstance(mcp_server.incident_use_case._local_commits, PinnedGitWindowProvider)
    assert mcp_server.incident_use_case._local_commits.window_path == pinned.window_path

    # Outside a checkout it stays silent, so the public Lambda keeps its deploy feed.
    assert PinnedGitWindowProvider(repo_root=tmp_path / "no-checkout").list_recent_commits() == []


def test_the_recorded_window_is_this_repositorys_real_git_log():
    if not LocalGitCommitProvider().is_available:
        pytest.skip("not a git checkout")
    result = subprocess.run(
        [sys.executable, "scripts/record_local_git_window.py", "--check"],
        cwd=PinnedGitWindowProvider().repo_root, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    window = PinnedGitWindowProvider().list_recent_commits()
    assert len(window) == 20
    # Every recorded commit can name its parent, so the rollback target never falls
    # off the edge of the window.
    for entry in window:
        parent = PinnedGitWindowProvider().parent_of(entry["sha"])
        assert parent is not None and parent["sha"] != entry["sha"]
