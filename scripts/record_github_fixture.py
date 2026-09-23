"""Record the offline GitHub telemetry fixture from a real GitHub API call.

The fixture that ``GitHubTelemetryAdapter`` serves when no ``GITHUB_TOKEN`` is
present is not hand-written. It is a recording of one real run of the adapter
against a real public repository, produced by this script, and it carries the
repository, timestamp and command that produced it.

Usage::

    python scripts/record_github_fixture.py                 # default source repo
    python scripts/record_github_fixture.py encode/httpx    # any public repo
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.infrastructure.github_adapter import FIXTURE_PATH, GitHubTelemetryAdapter  # noqa: E402

DEFAULT_SOURCE_REPO = "encode/httpx"


def main() -> int:
    source_repo = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SOURCE_REPO
    token = os.environ.get("GITHUB_TOKEN", "")

    adapter = GitHubTelemetryAdapter(
        token=token,
        repository=source_repo,
        allow_unauthenticated=True,
    )

    dora = adapter.get_metrics_raw()
    radar = adapter.get_pr_radar()

    if not dora.provenance.is_live or not radar.provenance.is_live:
        print("Refusing to write the fixture: the live call did not succeed.", file=sys.stderr)
        print(f"  DORA provenance : {dora.provenance.detail}", file=sys.stderr)
        print(f"  Radar provenance: {radar.provenance.detail}", file=sys.stderr)
        return 1

    command = f"python scripts/record_github_fixture.py {source_repo}"
    fixture = {
        "schema": "mercury.github_fixture/1",
        "note": (
            "Recorded output of one real GitHub REST API read. Mercury serves this when "
            "GITHUB_TOKEN is absent, and labels it 'offline-fixture' on screen."
        ),
        "recorded_from_repository": source_repo,
        "recorded_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "recorded_by_command": command,
        "authenticated": bool(token),
        "live_provenance_detail": dora.provenance.detail,
        "dora": {
            "deployment_frequency_per_day": dora.deployment_frequency_per_day,
            "lead_time_for_changes_hours": dora.lead_time_for_changes_hours,
            "change_failure_rate_percentage": dora.change_failure_rate_percentage,
            "mean_time_to_recovery_hours": dora.mean_time_to_recovery_hours,
            "sample_size": dora.sample_size,
            "window_days": dora.window_days,
        },
        "pull_requests": {
            "total_open_prs": radar.total_open_prs,
            "stale_prs_over_36h": [
                {
                    "pr_id": pull.pr_id,
                    "repository": pull.repository,
                    "title": pull.title,
                    "author": pull.author,
                    "hours_open": pull.hours_open,
                    "is_blocked": pull.is_blocked,
                }
                for pull in radar.stale_prs_over_36h
            ],
        },
    }

    FIXTURE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(FIXTURE_PATH, "w", encoding="utf-8") as handle:
        json.dump(fixture, handle, indent=2)
        handle.write("\n")

    print(json.dumps(fixture, indent=2))
    print(f"\nWrote {FIXTURE_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
