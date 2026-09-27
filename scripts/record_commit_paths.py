#!/usr/bin/env python3
"""Record which files each commit in the recorded stream changed.

The commit stream the correlation trial scores against
(``src/infrastructure/fixtures/commit_stream_fixture.json``) was recorded from ``git log``
with a sha, a message, an author and a time. ``git`` also knows which files each of those
commits changed, and that is the signal the attribution engine uses to set aside a commit
that changed nothing the running service is built from. This script reads it once, with
``git show --name-only --no-renames``, and writes it to a separate file so the recorded
stream stays byte-identical and every corpus built from it is unchanged.

Run::

    python scripts/record_commit_paths.py            # record
    python scripts/record_commit_paths.py --check    # compare the recording to git
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
STREAM_PATH = REPO_ROOT / "src" / "infrastructure" / "fixtures" / "commit_stream_fixture.json"
PATHS_PATH = REPO_ROOT / "src" / "infrastructure" / "fixtures" / "commit_paths_fixture.json"


def changed_paths(sha: str, repo_root: Path = REPO_ROOT) -> list[str] | None:
    """Files the commit changed, both sides of a rename. None when git cannot say."""
    try:
        result = subprocess.run(
            ["git", "show", "--no-renames", "--name-only", "--format=", sha],
            capture_output=True, text=True, cwd=str(repo_root), timeout=20,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    return sorted({line.strip() for line in result.stdout.splitlines() if line.strip()})


def record() -> dict:
    stream = json.loads(STREAM_PATH.read_text(encoding="utf-8"))
    paths = {}
    for entry in stream["commits"]:
        found = changed_paths(entry["sha"])
        if found is None:
            raise SystemExit(f"git could not read the files changed by {entry['sha']}")
        paths[entry["sha"]] = found
    return {
        "recorded_by_command": "python scripts/record_commit_paths.py",
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": (
            "git show --no-renames --name-only for each commit in commit_stream_fixture.json. "
            "Real file lists of real development commits of this repository; nothing edited."
        ),
        "stream_recorded_at_head": stream.get("recorded_at_head"),
        "commit_count": len(paths),
        "paths_by_sha": paths,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    fresh = record()
    if args.check:
        recorded = json.loads(PATHS_PATH.read_text(encoding="utf-8"))
        if recorded.get("paths_by_sha") != fresh["paths_by_sha"]:
            print("commit_paths_fixture.json no longer matches git show for the recorded stream")
            return 1
        print(f"commit_paths_fixture.json matches git for all {fresh['commit_count']} commits")
        return 0
    PATHS_PATH.write_text(json.dumps(fresh, indent=2) + "\n", encoding="utf-8")
    print(f"recorded the changed files of {fresh['commit_count']} commits into "
          f"{PATHS_PATH.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
