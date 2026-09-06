#!/usr/bin/env python3
"""Record a coverage measurement so the README's numbers can be checked cheaply.

The README quotes a coverage percentage and a statement count. Both were prose
that nothing verified, which is the same defect class as the stale assertion and
check counts elsewhere in this repository: correct the day they were typed, free
to drift on every commit afterwards.

Measuring coverage inside a test is not an option here, because that re-runs the
whole suite and turns a fast check into a multi-minute one. So the measurement is
recorded once by this script, exactly as benchmarks_summary.json is, and the
documentation test compares the README against this file in milliseconds. CI runs
this script, so a drifted number fails the build rather than waiting for a reader.

Usage:
    python scripts/record_coverage_summary.py            # measure and write
    python scripts/record_coverage_summary.py --check    # measure and compare only
"""
from __future__ import annotations

import json
import os
import platform
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SUMMARY_PATH = REPO_ROOT / "coverage_summary.json"
COMMAND = ["-m", "pytest", "tests/", "-q", "--cov=src", "--cov-report=term"]


def measure() -> dict[str, object]:
    result = subprocess.run(
        [sys.executable, *COMMAND],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        env=dict(os.environ, MERCURY_OFFLINE="1"),
    )
    total = re.search(r"^TOTAL\s+(\d+)\s+(\d+)\s+(\d+)%", result.stdout, re.MULTILINE)
    if not total:
        sys.stderr.write(result.stdout[-4000:])
        raise SystemExit("pytest-cov printed no TOTAL line; coverage was not measured")

    statements, missed, percent = (int(total.group(i)) for i in (1, 2, 3))
    return {
        "schema": "mercury.coverage/1",
        "note": (
            "Line coverage of src/ measured by pytest-cov over the committed test "
            "suite. The CI floor is 85 percent; this is the value that run produced."
        ),
        "measured_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "measured_by_command": "python scripts/record_coverage_summary.py",
        "equivalent_command": "python -m pytest tests/ -q --cov=src --cov-report=term",
        "python_version": platform.python_version(),
        "platform": sys.platform,
        "statements": statements,
        "missed": missed,
        "percent": percent,
    }


def main() -> int:
    checking = "--check" in sys.argv
    measured = measure()

    if checking:
        if not SUMMARY_PATH.exists():
            print("coverage_summary.json is missing; run this script without --check")
            return 1
        recorded = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
        drifted = [
            f"{field}: recorded {recorded.get(field)}, measured {measured[field]}"
            for field in ("statements", "percent")
            if recorded.get(field) != measured[field]
        ]
        if drifted:
            print("coverage summary has drifted:\n  " + "\n  ".join(drifted))
            return 1
        print(f"coverage summary agrees: {measured['percent']}% of {measured['statements']} statements")
        return 0

    SUMMARY_PATH.write_text(json.dumps(measured, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {SUMMARY_PATH.name}: {measured['percent']}% of {measured['statements']} statements")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
