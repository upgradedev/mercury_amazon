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


class RecordedCommitProvider:
    """Return commits from the checked-in, reproducible ``git log`` recording."""

    def __init__(self, path: Path | str = DEFAULT_RECORDING) -> None:
        self.path = Path(path)
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
        return [dict(item) for item in payload["commits"][:bounded] if isinstance(item, dict)]

    @property
    def detail(self) -> str:
        return (
            "{count} commits read from the checked-in git-log recording at "
            f"{self.recorded_at_head or 'an unknown revision'} ({self.recorded_at_utc or 'time unknown'}). "
            "They are real Mercury repository commits recorded for the reproducible trial, "
            "not live commits or deployments of the monitored service."
        )
