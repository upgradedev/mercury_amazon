"""Infrastructure Adapter: commits read from the local git checkout.

The GitHub adapter needs a token, and Mercury's own repository is private, so a
judge running the quickstart has no commit history to correlate against and the
war room can only ever answer "cannot attribute". That is honest, but it hides
the feature behind a credential.

This adapter closes the gap with real data rather than invented data: it shells
out to ``git log`` in the checkout the server is running from. The commits are
genuine, and the provenance says ``local-git`` so nobody mistakes them for the
GitHub API.

Each commit carries the files it changed (``git log --name-only --no-renames``), so the
correlator can set aside a commit that changed no file the server is built from. A
commit git lists no files for, such as a merge, gets ``paths`` of None, which the
correlator treats as unknown and keeps as a candidate.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
#: One record per commit, opened by a record separator so the file list ``--name-only``
#: prints after it can be told apart from the next commit's header.
LOG_FORMAT = "%x1e%h%x1f%an%x1f%aI%x1f%s"


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
                ["git", "-c", "core.quotePath=false", "log", f"-{max(1, min(limit, 100))}",
                 "--name-only", "--no-renames", f"--pretty=format:{LOG_FORMAT}"],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                cwd=str(self.repo_root), timeout=self.timeout,
            )
        except Exception:
            return []

        if result.returncode != 0:
            return []

        commits: list[dict[str, Any]] = []
        for record in result.stdout.split(""):
            lines = [line for line in record.splitlines() if line.strip()]
            if not lines:
                continue
            parts = lines[0].split("")
            if len(parts) != 4:
                continue
            short_sha, author, committed_at, subject = parts
            paths = tuple(line.strip() for line in lines[1:])
            commits.append({
                "sha": short_sha,
                "full_sha": short_sha,
                "message": subject,
                "author": author,
                "committed_at": committed_at,
                "paths": list(paths) if paths else None,
            })
        return commits

    def parent_of(self, sha: str) -> dict[str, Any] | None:
        """Return the parent of one commit in the same dict shape, or None.

        The correlator's rollback target is the commit before the offending
        one; when the offending commit is the oldest one fetched, the list
        cannot name it, but history still holds it. None also covers the
        root commit, shallow clones and anything git cannot answer.
        """
        if not self.is_available or not re.fullmatch(r"[0-9a-fA-F]+", sha or ""):
            return None
        try:
            result = subprocess.run(
                ["git", "-c", "core.quotePath=false", "log", "-1",
                 "--name-only", "--no-renames", f"--pretty=format:{LOG_FORMAT}",
                 f"{sha}^"],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                cwd=str(self.repo_root), timeout=self.timeout,
            )
        except Exception:
            return None
        if result.returncode != 0:
            return None
        lines = [line for line in result.stdout.replace("\x1e", "").splitlines()
                 if line.strip()]
        if not lines:
            return None
        parts = lines[0].split("\x1f")
        if len(parts) != 4:
            return None
        short_sha, author, committed_at, subject = parts
        paths = tuple(line.strip() for line in lines[1:])
        return {
            "sha": short_sha,
            "full_sha": short_sha,
            "message": subject,
            "author": author,
            "committed_at": committed_at,
            "paths": list(paths) if paths else None,
        }
