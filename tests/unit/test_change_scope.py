"""The service scope is derived from what ships, and a commit's file list is real.

``src/domain/change_scope.py`` decides whether a commit touched a file the server is built
from. That set is not a tuning knob: it has to cover everything the ``Dockerfile`` copies
and everything ``scripts/build_lambda_package.py`` packs, and the file lists it is read
against have to be what ``git`` says those commits changed.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

import build_lambda_package  # noqa: E402

from src.domain.change_scope import MERCURY_SERVICE_SCOPE, ServiceScope  # noqa: E402
from src.domain.incident_correlation import (  # noqa: E402
    REFUSAL_MUST_NOT_CLAIM,
    AttributionRefusal,
    CommitRef,
    CorrelationVerdict,
    IncidentCorrelator,
    MetricPoint,
    MetricSeries,
)

PATHS_FIXTURE = REPO_ROOT / "src" / "infrastructure" / "fixtures" / "commit_paths_fixture.json"
NOW = datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc)


def _dockerfile_sources() -> list[str]:
    sources = []
    for line in (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8").splitlines():
        match = re.match(r"\s*COPY\s+(?!--from)(.+)$", line)
        if not match:
            continue
        parts = match.group(1).split()
        sources += parts[:-1]
    return sources


def test_every_file_the_image_copies_is_inside_the_scope():
    sources = _dockerfile_sources()
    assert "src/" in sources and "docs/index.html" in sources
    for source in sources:
        if source.endswith("/"):
            probe = source + "any_module.py"
        else:
            probe = source.replace("*", "example")
        assert MERCURY_SERVICE_SCOPE.covers(probe), f"the Dockerfile ships {source}, the scope misses it"


def test_every_file_the_lambda_zip_packs_is_inside_the_scope():
    for path in build_lambda_package.package_manifest():
        assert MERCURY_SERVICE_SCOPE.covers(path), f"the Lambda zip ships {path}, the scope misses it"
    assert MERCURY_SERVICE_SCOPE.covers("src/interfaces/mcp_server.py")


@pytest.mark.parametrize("path", [
    "README.md", "docs/EVIDENCE.md", "tests/unit/test_x.py", "video/narration.json",
    "ci/readiness.py", "app/build.gradle.kts", ".github/workflows/ci.yml",
])
def test_files_the_server_is_not_built_from_are_outside_the_scope(path):
    assert not MERCURY_SERVICE_SCOPE.covers(path)


def test_an_unknown_file_list_is_neither_inside_nor_outside():
    assert MERCURY_SERVICE_SCOPE.touches(None) is None
    assert MERCURY_SERVICE_SCOPE.touches(()) is None
    assert MERCURY_SERVICE_SCOPE.touches(("README.md", "src/a.py")) is True
    assert MERCURY_SERVICE_SCOPE.touches(("README.md",)) is False


def _git_can_read(sha: str) -> bool:
    result = subprocess.run(["git", "cat-file", "-t", sha], capture_output=True, text=True,
                            cwd=str(REPO_ROOT), timeout=10)
    return result.returncode == 0 and result.stdout.strip() == "commit"


def test_the_recorded_file_lists_are_what_git_says_those_commits_changed():
    recorded = json.loads(PATHS_FIXTURE.read_text(encoding="utf-8"))
    assert recorded["recorded_by_command"] == "python scripts/record_commit_paths.py"
    stream = json.loads((PATHS_FIXTURE.parent / "commit_stream_fixture.json").read_text(encoding="utf-8"))
    assert set(recorded["paths_by_sha"]) == {c["sha"] for c in stream["commits"]}
    sample = sorted(recorded["paths_by_sha"])[:8]
    if not all(_git_can_read(sha) for sha in sample):
        pytest.skip("this clone does not carry the history the recording was made from")
    import record_commit_paths
    for sha in sample:
        assert record_commit_paths.changed_paths(sha) == recorded["paths_by_sha"][sha]


# ------------------------------------------------ The correlator with a scope


def _spike() -> MetricSeries:
    points = [MetricPoint(at=NOW - timedelta(minutes=10 * (5 - i)), value=v)
              for i, v in enumerate([10, 11, 9, 10, 10, 60])]
    return MetricSeries(metric_name="5xx", namespace="test", points=points)


def _commit(sha: str, minutes_before: int, paths) -> CommitRef:
    return CommitRef(sha=sha, message=sha, author="a", committed_at=NOW - timedelta(minutes=minutes_before),
                     paths=paths)


def test_a_commit_outside_the_scope_is_set_aside_and_said_so():
    commits = [_commit("aaa", 30, ("src/app.py",)), _commit("bbb", 10, ("README.md",))]
    scoped = IncidentCorrelator(service_scope=MERCURY_SERVICE_SCOPE).correlate("svc", _spike(), commits)
    assert scoped.verdict is CorrelationVerdict.ANOMALY_ATTRIBUTED
    assert scoped.offending_commit.sha == "aaa"
    assert scoped.commits_in_window == 1 and scoped.commits_set_aside == 1
    assert "not a finding that they are harmless" in scoped.explanation

    unscoped = IncidentCorrelator().correlate("svc", _spike(), commits)
    assert unscoped.attribution_refusal is AttributionRefusal.WINDOW_TOO_CROWDED
    assert unscoped.commits_set_aside == 0


def test_a_commit_with_no_file_list_is_always_a_candidate():
    commits = [_commit("aaa", 30, ("src/app.py",)), _commit("bbb", 10, None)]
    answer = IncidentCorrelator(service_scope=MERCURY_SERVICE_SCOPE).correlate("svc", _spike(), commits)
    assert answer.attribution_refusal is AttributionRefusal.WINDOW_TOO_CROWDED
    assert answer.commits_set_aside == 0


def test_a_window_holding_only_set_aside_commits_is_a_refusal_not_a_clearance():
    commits = [_commit("bbb", 10, ("README.md",))]
    answer = IncidentCorrelator(service_scope=MERCURY_SERVICE_SCOPE).correlate("svc", _spike(), commits)
    assert answer.attribution_refusal is AttributionRefusal.NO_CANDIDATE_IN_WINDOW
    assert answer.nothing_to_revert is False
    statement = answer.refusal_statement
    assert "not a finding that those changes are harmless" in statement
    for text in (statement, answer.explanation, answer.to_voice_summary()):
        for pattern in REFUSAL_MUST_NOT_CLAIM:
            assert not re.search(pattern, text, re.IGNORECASE), (pattern, text)


def test_a_scope_is_a_plain_value_another_service_can_declare():
    web = ServiceScope(name="web", patterns=("web/*",))
    assert web.touches(("web/index.ts",)) is True
    assert web.touches(("src/app.py",)) is False


# ------------------------------------------- The server counts only runtime commits


class _Entries:
    def __init__(self, entries):
        self.entries = entries

    def list_recent_commits(self, limit=20):
        return self.entries[:limit]


class _Empty:
    def list_recent_commits(self, limit=20):
        return []


def test_a_readme_only_commit_is_never_named_for_the_demo_spike():
    """The 2026-09-27 review saw the board blame a README edit for a 5XX spike.

    The newest commit edits only prose. The use case must place the simulated reading
    after the runtime commit, and the correlator must name that one and report the prose
    commit as set aside, never as the deploy.
    """
    from src.application.diagnose_incident_use_case import DiagnoseIncidentUseCase
    from src.infrastructure.cloudwatch_adapter import CloudWatchMetricAdapter

    entries = [
        {"sha": "docs001", "message": "Frame the README", "author": "D",
         "committed_at": (NOW - timedelta(minutes=5)).isoformat(),
         "paths": ["README.md", "docs/DEVPOST_SUBMISSION.md", "docs/EVIDENCE.md"]},
        {"sha": "code001", "message": "Change the server", "author": "D",
         "committed_at": (NOW - timedelta(minutes=40)).isoformat(),
         "paths": ["src/interfaces/mcp_server.py"]},
        {"sha": "base001", "message": "Older change", "author": "D",
         "committed_at": (NOW - timedelta(hours=6)).isoformat(),
         "paths": ["src/domain/change_scope.py"]},
    ]
    use_case = DiagnoseIncidentUseCase(
        CloudWatchMetricAdapter(), _Empty(), _Entries(entries),
        correlator=IncidentCorrelator(service_scope=MERCURY_SERVICE_SCOPE),
    )
    answer = use_case.execute("checkout-api")
    assert answer.verdict is CorrelationVerdict.ANOMALY_ATTRIBUTED
    assert answer.offending_commit.sha == "code001"
    assert answer.offending_commit.paths == ("src/interfaces/mcp_server.py",)


def test_the_server_names_no_prose_only_commit_and_says_how_many_it_set_aside(monkeypatch):
    from fastapi.testclient import TestClient

    from src.interfaces import mcp_server

    entries = [
        {"sha": "docs002", "message": "Edit the README", "author": "D",
         "committed_at": (NOW - timedelta(minutes=70)).isoformat(), "paths": ["README.md"]},
        {"sha": "code002", "message": "Change the board", "author": "D",
         "committed_at": (NOW - timedelta(minutes=72)).isoformat(), "paths": ["docs/index.html"]},
        {"sha": "base002", "message": "Older", "author": "D",
         "committed_at": (NOW - timedelta(hours=9)).isoformat(), "paths": ["src/a.py"]},
    ]
    monkeypatch.setattr(mcp_server.incident_use_case, "_commits", _Empty())
    monkeypatch.setattr(mcp_server.incident_use_case, "_local_commits", _Entries(entries))
    payload = TestClient(mcp_server.app).post(
        "/mcp/tools/what_changed", json={"service_name": "checkout-api"}).json()
    assert payload["verdict"] == "ANOMALY_ATTRIBUTED"
    assert payload["offending_commit"]["sha"] == "code002"
    assert payload["offending_commit"]["runtime_files"] == ["docs/index.html"]
    assert payload["attribution"]["commits_set_aside"] == 1
    assert payload["attribution"]["commits_in_window"] == 1
    rule = payload["attribution"]["candidate_filter"]
    assert rule["defined_in"] == "src/domain/change_scope.py"
    assert rule["runtime_paths"] == list(MERCURY_SERVICE_SCOPE.patterns)


def test_local_git_carries_file_lists():
    # The trial reads the recording's file lists itself (scripts/correlation_trial.py,
    # load_commit_paths); the server no longer has a recording adapter to check here.
    from src.infrastructure.local_git_adapter import LocalGitCommitProvider

    local = LocalGitCommitProvider()
    if not local.is_available:
        pytest.skip("not a git checkout")
    commits = local.list_recent_commits(limit=5)
    assert commits
    for entry in commits:
        assert entry["paths"] is None or all(isinstance(p, str) and p for p in entry["paths"])


def test_local_git_parent_of_names_the_commit_before():
    from src.infrastructure.local_git_adapter import LocalGitCommitProvider

    local = LocalGitCommitProvider()
    if not local.is_available:
        pytest.skip("not a git checkout")
    head = local.list_recent_commits(limit=1)
    assert head
    parent = local.parent_of(head[0]["sha"])
    if parent is None:
        pytest.skip("checkout root has no parent")
    assert parent["sha"] != head[0]["sha"]
    assert parent["sha"] and all(c in "0123456789abcdef" for c in parent["sha"])
    assert parent["committed_at"]
    assert local.parent_of("not-a-sha!!!") is None
    assert local.parent_of("") is None
