"""A display-only, invented deploy feed for the public demo board.

The public cockpit runs from a Lambda zip with no ``.git`` directory and no GitHub
token. It used to fall back to ``commit_stream_fixture.json``, the recording the
published trial is scored on, so the board quoted one of this repository's own
commit messages against checkout-api. That read as the team talking about its own
work, not as an incident.

This provider serves ``fixtures/deploy_feed_fixture.json`` instead: a handful of
hand-written deploy records whose messages look like a deploy feed. They are
invented, the provenance the board renders says so, and nothing that produces a
published figure reads them. ``commit_stream_fixture.json`` is unchanged and the
trial scripts read it directly, so the trial, the held-out split and every number
derived from them stay where they are. The server-side adapter that used to read
the recording had no caller left once this feed replaced it, so it was removed.

The records carry no file lists, so every one stays a deploy candidate, exactly as
an unknown file list does on the GitHub path.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_FEED = REPO_ROOT / "src" / "infrastructure" / "fixtures" / "deploy_feed_fixture.json"


class DeployFeedFixtureProvider:
    """Return the invented stand-in deploys, newest first, in the commit provider shape."""

    def __init__(self, path: Path | str = DEFAULT_FEED) -> None:
        self.path = Path(path)

    def list_recent_commits(self, limit: int = 20) -> list[dict[str, Any]]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        deploys = payload.get("deploys") if isinstance(payload, dict) else None
        if not isinstance(deploys, list):
            return []
        bounded = max(1, min(int(limit), 100))
        entries = []
        for item in deploys[:bounded]:
            if not isinstance(item, dict):
                continue
            entry = {key: item.get(key) for key in ("sha", "message", "author", "committed_at")}
            entry["paths"] = None
            entries.append(entry)
        return entries

    @property
    def detail(self) -> str:
        return (
            "{count} stand-in deploys from the display-only fixture "
            "src/infrastructure/fixtures/deploy_feed_fixture.json. They were written by hand "
            "for this demo: not real commits, not deployments of any service, and not used "
            "by any published figure. They carry no file lists, so each one counts as a "
            "deploy candidate; the runtime filter has nothing to read."
        )
