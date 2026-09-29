"""Read-only commit evidence bundled with the offline demonstration.

Lambda zip deployments do not contain a ``.git`` directory.  Without a GitHub
token that used to leave the public cockpit with no commit evidence at all, even
though the repository already ships the exact recorded commit stream used by the
published correlation trial.  This adapter reads that recording.  Its caller
labels the provenance ``offline-fixture`` so a recorded repository commit is
never presented as a live deployment of the service being monitored.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_RECORDING = REPO_ROOT / "src" / "infrastructure" / "fixtures" / "commit_stream_fixture.json"
#: The file list of every recorded commit, from ``python scripts/record_commit_paths.py``.
DEFAULT_PATHS = REPO_ROOT / "src" / "infrastructure" / "fixtures" / "commit_paths_fixture.json"


def _load_paths(path: Path) -> dict[str, list[str]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    by_sha = payload.get("paths_by_sha") if isinstance(payload, dict) else None
    return {str(k): list(v) for k, v in by_sha.items() if isinstance(v, list)} if isinstance(by_sha, dict) else {}


class RecordedCommitProvider:
    """Return commits from the checked-in, reproducible ``git log`` recording."""

    def __init__(self, path: Path | str = DEFAULT_RECORDING, paths_path: Path | str = DEFAULT_PATHS) -> None:
        self.path = Path(path)
        self.paths_path = Path(paths_path)
        self.recorded_at_head = ""
        self.recorded_at_utc = ""

    def list_recent_commits(self, limit: int = 20) -> list[dict[str, Any]]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        if not isinstance(payload, dict) or not isinstance(payload.get("commits"), list):
            return []
        self.recorded_at_head = str(payload.get("recorded_at_head") or "")
        self.recorded_at_utc = str(payload.get("recorded_at_utc") or "")
        bounded = max(1, min(int(limit), 100))
        paths = _load_paths(self.paths_path)
        commits = []
        for item in payload["commits"][:bounded]:
            if not isinstance(item, dict):
                continue
            entry = dict(item)
            # A recorded commit with no recorded file list stays unknown, and so a candidate.
            entry["paths"] = paths.get(str(entry.get("sha", ""))) or None
            commits.append(entry)
        return commits

    @property
    def detail(self) -> str:
        return (
            "{count} commits read from the checked-in git-log recording at "
            f"{self.recorded_at_head or 'an unknown revision'} ({self.recorded_at_utc or 'time unknown'}). "
            "They are real Mercury repository commits recorded for the reproducible trial, "
            "not live commits or deployments of the monitored service."
        )
