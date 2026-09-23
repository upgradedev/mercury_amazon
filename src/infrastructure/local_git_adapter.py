"""Infrastructure Adapter: commits read from the local git checkout.

The GitHub adapter needs a token, and Mercury's own repository is private, so a
judge running the quickstart has no commit history to correlate against and the
war room can only ever answer "cannot attribute". That is honest, but it hides
the feature behind a credential.

This adapter closes the gap with real data rather than invented data: it shells
out to ``git log`` in the checkout the server is running from. The commits are
genuine, and the provenance says ``local-git`` so nobody mistakes them for the
GitHub API.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
LOG_FORMAT = "%h%x1f%an%x1f%aI%x1f%s"


class LocalGitCommitProvider:
    """Reads recent commits from the git checkout this process is running in."""

    def __init__(self, repo_root: Path | str | None = None, timeout: float = 10.0) -> None:
        self.repo_root = Path(repo_root) if repo_root else REPO_ROOT
        self.timeout = timeout

    @property
    def is_available(self) -> bool:
        return (self.repo_root / ".git").exists()

    def list_recent_commits(self, limit: int = 20) -> list[dict[str, Any]]:
        """Return up to ``limit`` recent commits, or an empty list if git cannot run.

        Returns the same shape as ``GitHubTelemetryAdapter.list_recent_commits``,
        so the two are interchangeable behind the use case's protocol.
        """
        if not self.is_available:
            return []
        try:
            result = subprocess.run(
                ["git", "log", f"-{max(1, min(limit, 100))}", f"--pretty=format:{LOG_FORMAT}"],
                capture_output=True, text=True, cwd=str(self.repo_root), timeout=self.timeout,
            )
        except Exception:
            return []

        if result.returncode != 0:
            return []

        commits: list[dict[str, Any]] = []
        for line in result.stdout.splitlines():
            parts = line.split("\x1f")
            if len(parts) != 4:
                continue
            short_sha, author, committed_at, subject = parts
            commits.append({
                "sha": short_sha,
                "full_sha": short_sha,
                "message": subject,
                "author": author,
                "committed_at": committed_at,
            })
        return commits
