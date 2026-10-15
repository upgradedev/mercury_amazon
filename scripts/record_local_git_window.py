#!/usr/bin/env python3
"""Record the git log window the local demo board is anchored to.

``src/infrastructure/local_git_window.py`` serves this recording instead of reading
``git log -20`` at HEAD, so a new commit cannot change the demo's verdicts. This
script writes it from ``git log -20`` at the pinned commit, with each commit's file
list (``--name-only --no-renames``) and its first parent, so the correlator can name
a rollback target for the oldest commit too.

Run::

    python scripts/record_local_git_window.py            # record at the current pin
    python scripts/record_local_git_window.py --pin SHA  # move the pin, then re-run the tests
    python scripts/record_local_git_window.py --check    # compare the recording to git
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WINDOW_PATH = REPO_ROOT / "src" / "infrastructure" / "fixtures" / "local_git_window.json"
LIMIT = 20
# Full SHA plus the fields LocalGitCommitProvider reads, one record per commit.
LOG_FORMAT = "%x1e%H%x1f%an%x1f%aI%x1f%s"


def _git_log(*args: str) -> list[dict]:
    result = subprocess.run(
        ["git", "-c", "core.quotePath=false", "log", "--name-only", "--no-renames",
         f"--pretty=format:{LOG_FORMAT}", *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=str(REPO_ROOT), timeout=30,
    )
    if result.returncode != 0:
        raise SystemExit(f"git log {' '.join(args)} failed: {result.stderr.strip()}")
    entries = []
    for record in result.stdout.split("\x1e"):
        lines = [line for line in record.splitlines() if line.strip()]
        if not lines:
            continue
        full_sha, author, committed_at, subject = lines[0].split("\x1f")
        paths = [line.strip() for line in lines[1:]]
        entries.append({
            # Seven characters, fixed, so the recording does not change when git
            # would print a longer abbreviation in a larger repository.
            "sha": full_sha[:7],
            "full_sha": full_sha,
            "message": subject,
            "author": author,
            "committed_at": committed_at,
            "paths": paths or None,
        })
    return entries


def record(pin: str) -> dict:
    commits = _git_log(f"-{LIMIT}", pin)
    if len(commits) != LIMIT:
        raise SystemExit(f"git log -{LIMIT} {pin} returned {len(commits)} commits")
    parents = {}
    for commit in commits:
        found = _git_log("-1", f"{commit['full_sha']}^")
        if found:
            parents[commit["sha"]] = found[0]
    return {
        "schema": "mercury.local_git_window/1",
        "note": (
            "The window LocalGitCommitProvider would read with git log -20 at the pinned "
            "commit, recorded so new commits cannot change the local demo's verdicts. Real "
            "commits of this repository, nothing edited. Served only where a git checkout "
            "exists; the public Lambda has none and serves the invented deploy feed instead."
        ),
        "recorded_by_command": "python scripts/record_local_git_window.py",
        "source_command": f"git log -{LIMIT} --name-only --no-renames {pin}",
        "pinned_at_sha": commits[0]["full_sha"],
        "limit": LIMIT,
        "commits": commits,
        "parents": parents,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="compare the recording to git")
    parser.add_argument("--pin", help="commit to record the window at (default: the current pin)")
    args = parser.parse_args()

    current = json.loads(WINDOW_PATH.read_text(encoding="utf-8")) if WINDOW_PATH.exists() else {}
    pin = args.pin or current.get("pinned_at_sha")
    if not pin:
        raise SystemExit("no pin recorded yet: pass --pin SHA")
    fresh = record(pin)

    if args.check:
        if fresh != current:
            print(f"{WINDOW_PATH.name} does not match git log at {pin[:7]}", file=sys.stderr)
            return 1
        print(f"{WINDOW_PATH.name} matches git log -{LIMIT} at {pin[:7]}")
        return 0

    WINDOW_PATH.write_text(json.dumps(fresh, indent=2, ensure_ascii=False) + "\n",
                           encoding="utf-8", newline="\n")
    print(f"recorded {len(fresh['commits'])} commits and {len(fresh['parents'])} parents "
          f"at {pin[:7]} to {WINDOW_PATH.relative_to(REPO_ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
