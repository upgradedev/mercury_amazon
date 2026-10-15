"""Infrastructure Adapter: a recorded window of this repository's own git log.

``LocalGitCommitProvider`` reads ``git log -20`` at HEAD, and the demo board's five
verdicts were placed against whatever those 20 commits were. The window is taken
before the runtime filter, so a stack of docs, video and receipt commits on top of
HEAD pushed the runtime commits out of the 20, the crowded window behind
``release-train`` emptied, and the refusal turned into an attribution. CI run
37579019212 failed six tests that way on a branch whose only changes were footage
and receipts.

This provider serves the same 20 commits every time: the window ``git log -20``
returned at the pinned merge, recorded with each commit's file list and first
parent in ``fixtures/local_git_window.json`` by ``scripts/record_local_git_window.py``
(which also has a ``--check`` mode). The commits are still real commits of this
repository and the provenance still says ``local-git``; what changes is that a new
commit can no longer move which of them the demo is anchored to.

It answers only where a git checkout exists, exactly like ``LocalGitCommitProvider``.
The public Lambda zip has no ``.git``, so it keeps serving the invented deploy feed
(``deploy_feed_fixture.py``) and never quotes this repository's commit messages.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.infrastructure.local_git_adapter import REPO_ROOT, LocalGitCommitProvider

DEFAULT_WINDOW = REPO_ROOT / "src" / "infrastructure" / "fixtures" / "local_git_window.json"


def _copy(entry: Any) -> dict[str, Any] | None:
    if not isinstance(entry, dict):
        return None
    paths = entry.get("paths")
    return {
        "sha": entry.get("sha"),
        "full_sha": entry.get("full_sha") or entry.get("sha"),
        "message": entry.get("message"),
        "author": entry.get("author"),
        "committed_at": entry.get("committed_at"),
        "paths": list(paths) if isinstance(paths, list) and paths else None,
    }


class PinnedGitWindowProvider(LocalGitCommitProvider):
    """Serves the recorded ``git log -20`` window instead of reading git log at HEAD.

    It keeps LocalGitCommitProvider's ``is_available`` gate (a ``.git`` beside the
    code), so where there is no checkout it returns nothing, as that provider does.
    """

    def __init__(self, repo_root: Path | str | None = None,
                 window_path: Path | str = DEFAULT_WINDOW) -> None:
        super().__init__(repo_root)
        self.window_path = Path(window_path)

    def _load(self) -> dict[str, Any]:
        try:
            payload = json.loads(self.window_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return payload if isinstance(payload, dict) else {}

    @property
    def pinned_at(self) -> str:
        return str(self._load().get("pinned_at_sha") or "")

    def list_recent_commits(self, limit: int = 20) -> list[dict[str, Any]]:
        if not self.is_available:
            return []
        commits = self._load().get("commits")
        if not isinstance(commits, list):
            return []
        bounded = max(1, min(int(limit), 100))
        copied = (_copy(entry) for entry in commits[:bounded])
        return [entry for entry in copied if entry is not None]

    def parent_of(self, sha: str) -> dict[str, Any] | None:
        """The recorded first parent of one commit in the window, or None."""
        if not self.is_available or not sha:
            return None
        parents = self._load().get("parents")
        if not isinstance(parents, dict):
            return None
        return _copy(parents.get(sha))

    @property
    def detail(self) -> str:
        return (
            "{count} commits from this repository's own git log, read once with git log at "
            f"{self.pinned_at[:7] or 'the pinned commit'} and recorded in "
            "src/infrastructure/fixtures/local_git_window.json, because no GitHub token is "
            "configured. These are real commits from this repository, not the service being "
            "monitored. The window is pinned so a later commit cannot change which demo "
            "verdict the board reaches."
        )
